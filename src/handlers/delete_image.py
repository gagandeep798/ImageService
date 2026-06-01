"""DELETE /images/{image_id} — Soft-delete an image.

Sets ``status=DELETED``, records ``deleted_at``, and sets a 7-day DynamoDB TTL.
The S3 object is removed asynchronously by a DynamoDB Streams cleanup Lambda
after TTL expiry.  Returns 403 if the caller does not own the image (admins
may bypass ownership).
"""
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ForbiddenError, ImageServiceError, NotFoundError
from src.common.middleware import get_caller_user_id, get_request_id, is_admin
from src.repositories import image_repository as img_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for DELETE /images/{image_id}.

    Returns 200 with ``{image_id, status: "DELETED"}``.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        caller_id = get_caller_user_id(event)
        image_id = event["pathParameters"]["image_id"]

        image = img_repo.get_by_id(settings, image_id, consistent=True)

        if image.user_id != caller_id and not is_admin(event):
            raise ForbiddenError("Access denied")

        if image.status == "DELETED":
            raise NotFoundError(f"Image {image_id} not found")

        img_repo.soft_delete(settings, image_id)

        metrics.add_metric(name="image.deleted", unit=MetricUnit.Count, value=1)
        logger.info("image_deleted", image_id=image_id, user_id=caller_id)

        return resp.ok({"image_id": image_id, "status": "DELETED"}, request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in delete_image")
        return resp.error(exc, request_id)
