"""GET /images — Paginated list with optional filters.

When ``user_id`` is provided the query hits the UserImagesIndex GSI for an
efficient per-user scan.  Without ``user_id`` a scatter-gather across all
StatusIndex shards is performed and results are merged in-memory.

Supported query params: ``user_id``, ``tag``, ``status`` (default ACTIVE),
``limit`` (default 20, max 100), ``cursor`` (base64 LastEvaluatedKey).
"""
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common.config import get_settings
from src.common.exceptions import ImageServiceError
from src.common.middleware import get_request_id
from src.common import response as resp
from src.repositories import image_repository as img_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for GET /images.

    Returns 200 with a ``ListImagesResponse`` containing ``items`` and an
    optional ``next_cursor`` for the next page.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        qs = event.get("queryStringParameters") or {}
        user_id = qs.get("user_id")
        tag = qs.get("tag")
        status = qs.get("status", "ACTIVE")
        limit = min(int(qs.get("limit", "20")), 100)
        cursor = qs.get("cursor")

        if user_id:
            result = img_repo.list_by_user(settings, user_id, status, tag, limit, cursor)
        else:
            result = img_repo.list_global(settings, status, tag, limit, cursor)

        return resp.ok(result.model_dump(), request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in list_images")
        return resp.error(exc, request_id)
