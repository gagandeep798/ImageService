"""DELETE /images/{image_id}/upload — Abort an in-progress multipart upload and clean up.

Cancels the S3 multipart session (releasing any staged parts), restores the
user's reserved quota if the size was already known, and marks the image record
as ABORTED so it is excluded from future queries.
"""
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common.config import get_settings
from src.common.exceptions import ForbiddenError, ImageServiceError
from src.common.middleware import get_caller_user_id, get_request_id
from src.common import response as resp
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo
from src.repositories import user_repository as user_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for DELETE /images/{image_id}/upload.

    Returns 200 with ``{image_id, status: "ABORTED"}``.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        caller_id = get_caller_user_id(event)
        image_id = event["pathParameters"]["image_id"]

        image = img_repo.get_by_id(settings, image_id, consistent=True)
        if image.user_id != caller_id:
            raise ForbiddenError("Access denied")

        if image.status == "PENDING" and image.upload_id and image.s3_key:
            store_repo.cancel_upload(settings, image.s3_key, image.upload_id)
            if image.size_bytes:
                user_repo.release_quota(settings, caller_id, image.size_bytes)

        img_repo.set_status(settings, image_id, "ABORTED")

        return resp.ok({"image_id": image_id, "status": "ABORTED"}, request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in upload_abort")
        return resp.error(exc, request_id)
