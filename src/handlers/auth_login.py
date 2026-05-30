"""POST /auth/login — authenticate with Cognito and return tokens."""
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
from src.common.models import LoginRequest, TokenResponse

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")

_INVALID_MSG = "Invalid email or password"


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
        req = LoginRequest(**body)
    except Exception as exc:
        return resp.error(ValidationError(str(exc)), request_id)

    try:
        cognito = _cognito(settings)

        try:
            auth_result = cognito.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": req.email, "PASSWORD": req.password},
                ClientId=settings.cognito_client_id,
            )["AuthenticationResult"]
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NotAuthorizedException", "UserNotFoundException"):
                return resp.error(ValidationError(_INVALID_MSG), request_id)
            raise

        id_token = auth_result["IdToken"]
        claims = _decode_id_token_claims(id_token)
        user_id = claims.get("custom:user_id", "")

        token_resp = TokenResponse(
            access_token=id_token,
            refresh_token=auth_result["RefreshToken"],
            expires_in=auth_result.get("ExpiresIn", 3600),
            user_id=user_id,
        )
        return resp.ok(token_resp.model_dump(), request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unexpected error during login")
        return resp.error(ImageServiceError(str(exc)), request_id)
