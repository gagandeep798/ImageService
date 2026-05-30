"""POST /auth/refresh — exchange a Cognito refresh token for a new ID token."""
from __future__ import annotations

import base64
import json as _json

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ImageServiceError, ValidationError
from src.common.middleware import get_request_id
from src.common.models import RefreshRequest

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")


def _cognito(settings):
    kwargs = dict(region_name=settings.aws_region)
    if settings.cognito_endpoint_url:
        kwargs["endpoint_url"] = settings.cognito_endpoint_url
    return boto3.client("cognito-idp", **kwargs)


def _decode_id_token_claims(id_token: str) -> dict:
    payload_b64 = id_token.split(".")[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    return _json.loads(base64.b64decode(payload_b64))


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        body = _json.loads(event.get("body") or "{}")
        req = RefreshRequest(**body)
    except Exception as exc:
        return resp.error(ValidationError(str(exc)), request_id)

    try:
        cognito = _cognito(settings)

        try:
            auth_result = cognito.initiate_auth(
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": req.refresh_token},
                ClientId=settings.cognito_client_id,
            )["AuthenticationResult"]
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NotAuthorizedException", "TokenExpiredException"):
                return resp.error(ValidationError("Refresh token expired or invalid"), request_id)
            raise

        id_token = auth_result["IdToken"]
        claims = _decode_id_token_claims(id_token)
        user_id = claims.get("custom:user_id", "")

        return resp.ok({
            "access_token": id_token,
            "token_type": "Bearer",
            "expires_in": auth_result["ExpiresIn"],
            "user_id": user_id,
        }, request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unexpected error during token refresh")
        return resp.error(ImageServiceError(str(exc)), request_id)
