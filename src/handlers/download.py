"""GET /images/{image_id}/download — Redirect to a time-limited download URL.

Returns 302 with a ``Location`` header pointing to either a CloudFront signed
URL (production) or a plain S3 presigned GET URL (local dev).  The image binary
is served directly from storage — it never flows through Lambda.
"""
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ImageServiceError, NotFoundError
from src.common.middleware import get_request_id
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

    Returns 302 with ``Location`` set to the presigned/CloudFront URL.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        image_id = event["pathParameters"]["image_id"]
        image = img_repo.get_by_id(settings, image_id)

        if image.status != "ACTIVE":
            raise NotFoundError(f"Image {image_id} not available")

        url = store_repo.get_download_url(settings, image.s3_key)
        return resp.redirect(url)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in download")
        return resp.error(exc, request_id)
