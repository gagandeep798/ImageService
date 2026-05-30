"""POST /auth/signup — create a Cognito account + DynamoDB profile and return tokens."""
from __future__ import annotations

import base64
import json as _json

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError
from ulid import ULID

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ConflictError, ImageServiceError, ValidationError
from src.common.middleware import get_request_id
from src.common.models import SignupRequest, TokenResponse
from src.repositories import user_repository as user_repo

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
        req = SignupRequest(**body)
    except Exception as exc:
        return resp.error(ValidationError(str(exc)), request_id)

    try:
        cognito = _cognito(settings)
        user_id = f"usr_{ULID().str.lower()}"

        try:
            cognito.sign_up(
                ClientId=settings.cognito_client_id,
                Username=req.email,
                Password=req.password,
                UserAttributes=[
                    {"Name": "custom:user_id", "Value": user_id},
                ],
            )
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "UsernameExistsException":
                return resp.error(ConflictError("Email already registered"), request_id)
            raise

        cognito.admin_confirm_sign_up(
            UserPoolId=settings.cognito_user_pool_id,
            Username=req.email,
        )

        auth_result = cognito.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": req.email, "PASSWORD": req.password},
            ClientId=settings.cognito_client_id,
        )["AuthenticationResult"]

        user_repo.create_user(settings, user_id, req.display_name)

        token_resp = TokenResponse(
            access_token=auth_result["IdToken"],
            refresh_token=auth_result["RefreshToken"],
            expires_in=auth_result["ExpiresIn"],
            user_id=user_id,
        )
        return resp.created(token_resp.model_dump(), request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unexpected error during signup")
        return resp.error(ImageServiceError(str(exc)), request_id)
