"""Shared Lambda middleware utilities."""
from src.common.exceptions import ForbiddenError


def get_caller_user_id(event: dict) -> str:
    """Extract user_id from Cognito authorizer claims or dev bypass query param."""
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    user_id: str = claims.get("custom:user_id", "")
    if not user_id:
        # sam local bypasses the Cognito authorizer; support ?_dev_user_id for local API testing
        user_id = (event.get("queryStringParameters") or {}).get("_dev_user_id", "")
    if not user_id:
        raise ForbiddenError("Missing authentication")
    return user_id


def is_admin(event: dict) -> bool:
    """Return True if the caller is in the Cognito 'admins' group."""
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    groups = claims.get("cognito:groups", "") or ""
    return "admins" in groups


def get_request_id(event: dict) -> str:
    """Extract the API Gateway request ID for logging and response envelopes."""
    return (
        event.get("requestContext", {}).get("requestId", "")
        or event.get("requestContext", {}).get("extendedRequestId", "")
    )
