"""GET /images/{image_id}/download — Return a time-limited download URL.

Returns a JSON envelope with either a CloudFront signed URL (production) or a
plain S3 presigned GET URL (local dev).  The image binary is served directly
from storage — it never flows through Lambda.
"""
from datetime import UTC, datetime, timedelta

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ForbiddenError, ImageServiceError, NotFoundError
from src.common.middleware import get_caller_user_id, get_request_id, is_admin
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for GET /images/{image_id}/download.

    Returns 200 with ``download_url`` set to the presigned/CloudFront URL.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        image_id = event["pathParameters"]["image_id"]
        caller_id = get_caller_user_id(event)
        image = img_repo.get_by_id(settings, image_id)

        if image.user_id != caller_id and not is_admin(event):
            raise ForbiddenError("Access denied")

        if image.status != "ACTIVE":
            raise NotFoundError(f"Image {image_id} not available")

        url = store_repo.get_download_url(settings, image.s3_key)
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.download_url_ttl_seconds)
        return resp.ok(
            {"download_url": url, "expires_at": expires_at.isoformat()},
            request_id,
        )

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in download")
        return resp.error(exc, request_id)
