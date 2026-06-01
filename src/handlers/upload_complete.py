"""POST /images/{image_id}/complete — Step 3: assemble all uploaded parts into the final S3 object.

After calling ``complete_multipart_upload`` on S3, the image record is
transitioned to PENDING_FINALIZE.  An S3 ObjectCreated event then fires and
queues a message for the ``finalize_upload`` Lambda to extract dimensions and
advance the record through the scan pipeline.
"""
import json

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common import response as resp
from src.common.config import get_settings
from src.common.exceptions import ForbiddenError, ImageServiceError
from src.common.middleware import get_caller_user_id, get_request_id
from src.common.models import UploadCompleteRequest
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for POST /images/{image_id}/complete.

    Returns 200 with ``{image_id, status: "PROCESSING"}``.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        caller_id = get_caller_user_id(event)
        image_id = event["pathParameters"]["image_id"]
        body = json.loads(event.get("body") or "{}")
        req = UploadCompleteRequest(**body)

        image = img_repo.get_by_id(settings, image_id, consistent=True)
        if image.user_id != caller_id:
            raise ForbiddenError("Access denied")
        if image.status != "PENDING":
            raise ImageServiceError(f"Upload not in PENDING state (current: {image.status})")

        store_repo.finalize_upload(
            settings,
            image.s3_key,
            req.upload_id,
            [p.model_dump() for p in req.parts],
        )

        img_repo.set_status(settings, image_id, "PENDING_FINALIZE")

        metrics.add_metric(name="upload.completed", unit=MetricUnit.Count, value=1)
        logger.info("upload_completed", image_id=image_id, user_id=caller_id)

        return resp.ok({"image_id": image_id, "status": "PROCESSING"}, request_id)

    except ImageServiceError as exc:
        metrics.add_metric(name="upload.failed", unit=MetricUnit.Count, value=1)
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in upload_complete")
        metrics.add_metric(name="upload.failed", unit=MetricUnit.Count, value=1)
        return resp.error(exc, request_id)
