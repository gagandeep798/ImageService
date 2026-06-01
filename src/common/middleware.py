"""Shared Lambda middleware utilities."""
import base64
import json

from src.common.exceptions import ForbiddenError


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without signature verification (API GW already validated it)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.b64decode(payload_b64))
    except Exception:
        return {}


def _claims_from_auth_header(event: dict) -> dict:
    """Extract Cognito claims from Authorization Bearer token when authorizer context is absent.

    SAM local skips the Cognito authorizer, so requestContext.authorizer.claims is empty.
    Decoding the JWT here lets the frontend work with real tokens locally without needing
    the ?_dev_user_id bypass.  In production API Gateway populates authorizer.claims, so
    this path is never reached.
    """
    headers = event.get("headers") or {}
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if not auth.startswith("Bearer "):
        return {}
    return _decode_jwt_payload(auth[7:])


def get_caller_user_id(event: dict) -> str:
    """Extract user_id from Cognito authorizer claims, JWT Bearer token, or dev bypass param."""
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    user_id: str = claims.get("custom:user_id", "")

    if not user_id:
        # SAM local skips the Cognito authorizer — decode the Bearer token directly
        jwt_claims = _claims_from_auth_header(event)
        user_id = jwt_claims.get("custom:user_id", "")

    if not user_id:
        # Last resort: ?_dev_user_id query param for curl-based local testing
        user_id = (event.get("queryStringParameters") or {}).get("_dev_user_id", "")

    if not user_id:
        raise ForbiddenError("Missing authentication")
    return user_id


def is_admin(event: dict) -> bool:
    """Return True if the caller is in the Cognito 'admins' group."""
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    groups = claims.get("cognito:groups", "") or ""
    if not groups:
        jwt_claims = _claims_from_auth_header(event)
        groups = jwt_claims.get("cognito:groups", "") or ""
    return "admins" in groups


def get_request_id(event: dict) -> str:
    """Extract the API Gateway request ID for logging and response envelopes."""
    return (
        event.get("requestContext", {}).get("requestId", "")
        or event.get("requestContext", {}).get("extendedRequestId", "")
    )
