"""GET /images/{image_id} — Return the public metadata for a single image.

Uses a strongly-consistent read so callers that poll immediately after upload
completion see the latest status without waiting for replication.
"""
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ImageServiceError
from src.common.middleware import get_request_id
from src.repositories import image_repository as img_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for GET /images/{image_id}.

    Returns 200 with the image's public ``ImageResponse`` fields.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        image_id = event["pathParameters"]["image_id"]
        image = img_repo.get_by_id(settings, image_id, consistent=True)

        return resp.ok(img_repo.to_response(settings, image).model_dump(), request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in get_image")
        return resp.error(exc, request_id)
