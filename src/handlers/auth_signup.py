"""POST /auth/signup — create a new account and return tokens."""
from __future__ import annotations

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from ulid import ULID

from src.common import jwt_utils, response as resp
from src.common.config import get_settings
from src.common.exceptions import ConflictError, ImageServiceError, ValidationError
from src.common.middleware import get_request_id
from src.common.models import SignupRequest, TokenResponse
from src.repositories import user_repository as user_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        import json
        body = json.loads(event.get("body") or "{}")
        req = SignupRequest(**body)
    except Exception as exc:
        return resp.error(ValidationError(str(exc)), request_id)

    try:
        # Check if email already registered
        try:
            user_repo.get_user_by_email(settings, req.email)
            return resp.error(ConflictError("Email already registered"), request_id)
        except Exception as lookup_exc:
            from src.common.exceptions import NotFoundError
            if not isinstance(lookup_exc, NotFoundError):
                raise

        user_id = f"usr_{ULID().str.lower()}"
        user_repo.create_user(settings, user_id, req.display_name, req.email, req.password)

        access_token = jwt_utils.issue_access_token(settings, user_id)
        refresh_token = jwt_utils.issue_refresh_token(settings, user_id)

        token_resp = TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_token_ttl,
            user_id=user_id,
        )
        return resp.created(token_resp.model_dump(), request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unexpected error during signup")
        return resp.error(ImageServiceError(str(exc)), request_id)
