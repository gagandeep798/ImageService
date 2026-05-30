"""POST /auth/login — authenticate and return tokens."""
from __future__ import annotations

import json

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import jwt_utils
from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ImageServiceError, NotFoundError, ValidationError
from src.common.middleware import get_request_id
from src.common.models import LoginRequest, TokenResponse
from src.repositories import user_repository as user_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")

_INVALID_MSG = "Invalid email or password"


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        body = json.loads(event.get("body") or "{}")
        req = LoginRequest(**body)
    except Exception as exc:
        return resp.error(ValidationError(str(exc)), request_id)

    try:
        try:
            user = user_repo.get_user_by_email(settings, req.email)
        except NotFoundError:
            return resp.error(ValidationError(_INVALID_MSG), request_id)

        if not user_repo.verify_password(req.password, user.password_hash):
            return resp.error(ValidationError(_INVALID_MSG), request_id)

        access_token = jwt_utils.issue_access_token(settings, user.user_id)
        refresh_token = jwt_utils.issue_refresh_token(settings, user.user_id)

        token_resp = TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_token_ttl,
            user_id=user.user_id,
        )
        return resp.ok(token_resp.model_dump(), request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unexpected error during login")
        return resp.error(ImageServiceError(str(exc)), request_id)
