"""POST /images/{image_id}/parts — Step 2: issue a presigned URL for a single chunk.

The client calls this once per chunk.  The handler verifies ownership and that
the upload is still in PENDING status, then returns a short-lived presigned
``upload_part`` URL the client uses to PUT the chunk directly to S3.
"""
import json

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ForbiddenError, ImageServiceError
from src.common.middleware import get_caller_user_id, get_request_id
from src.common.models import UploadPartRequest
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for POST /images/{image_id}/parts.

    Returns 200 with ``{presigned_part_url, part_number}``.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        caller_id = get_caller_user_id(event)
        image_id = event["pathParameters"]["image_id"]
        body = json.loads(event.get("body") or "{}")
        req = UploadPartRequest(**body)

        image = img_repo.get_by_id(settings, image_id, consistent=True)
        if image.user_id != caller_id:
            raise ForbiddenError("Access denied")
        if image.status not in ("PENDING",):
            raise ImageServiceError(f"Upload is not in PENDING state (current: {image.status})")

        presigned_url = store_repo.get_part_upload_url(
            settings, image.s3_key, req.upload_id, req.part_number
        )

        return resp.ok(
            {"presigned_part_url": presigned_url, "part_number": req.part_number},
            request_id,
        )

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in upload_part")
        return resp.error(exc, request_id)
