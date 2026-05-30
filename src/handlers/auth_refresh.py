"""POST /auth/refresh — exchange a refresh token for a new access token."""
from __future__ import annotations

import json

import jwt as pyjwt
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import jwt_utils, response as resp
from src.common.config import get_settings
from src.common.exceptions import ImageServiceError, ValidationError
from src.common.middleware import get_request_id
from src.common.models import RefreshRequest

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        body = json.loads(event.get("body") or "{}")
        req = RefreshRequest(**body)
    except Exception as exc:
        return resp.error(ValidationError(str(exc)), request_id)

    try:
        payload = jwt_utils.decode_token(settings, req.refresh_token, "refresh")
        user_id = payload["sub"]
        access_token = jwt_utils.issue_access_token(settings, user_id)

        return resp.ok({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": settings.jwt_access_token_ttl,
            "user_id": user_id,
        }, request_id)

    except pyjwt.ExpiredSignatureError:
        return resp.error(ValidationError("Refresh token expired"), request_id)
    except pyjwt.InvalidTokenError:
        return resp.error(ValidationError("Invalid refresh token"), request_id)
    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unexpected error during token refresh")
        return resp.error(ImageServiceError(str(exc)), request_id)
