"""POST /images — Step 1 of the chunked multipart upload flow.

Validates the upload request, reserves storage quota, creates an S3 multipart
upload session, writes a PENDING metadata record to DynamoDB, and returns a
presigned PUT URL the client uses to upload the first (or only) chunk.
"""
import json

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from ulid import ULID

from src.common.config import get_settings
from src.common.exceptions import ImageServiceError, ValidationError
from src.common.middleware import get_caller_user_id, get_request_id
from src.common.models import UploadInitiateRequest
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
    """Lambda entry point for POST /images.

    Returns 202 Accepted with ``{image_id, upload_id, s3_key, chunk_size_bytes}``.
    The client uses ``upload_id`` and ``s3_key`` for subsequent part upload requests.
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        caller_id = get_caller_user_id(event)
        body = json.loads(event.get("body") or "{}")
        req = UploadInitiateRequest(**body)

        if req.user_id != caller_id:
            from src.common.exceptions import ForbiddenError
            raise ForbiddenError("Cannot upload on behalf of another user")

        if req.total_size_bytes > settings.max_image_size_bytes:
            raise ValidationError(f"File exceeds max size of {settings.max_image_size_bytes} bytes")

        user_repo.check_and_reserve_quota(settings, caller_id, req.total_size_bytes)

        image_id = f"img_{ULID()}"
        upload_id, s3_key = store_repo.initiate_upload(
            settings, caller_id, image_id, req.filename, req.content_type
        )

        img_repo.create_pending(
            settings,
            image_id=image_id,
            user_id=caller_id,
            s3_key=s3_key,
            upload_id=upload_id,
            content_type=req.content_type,
            title=req.title,
            description=req.description,
            tags=req.tags,
        )

        metrics.add_metric(name="upload.initiated", unit=MetricUnit.Count, value=1)
        logger.info("upload_initiated", image_id=image_id, user_id=caller_id)

        return resp.accepted(
            {
                "image_id": image_id,
                "upload_id": upload_id,
                "s3_key": s3_key,
                "chunk_size_bytes": settings.chunk_size_bytes,
                "status": "PENDING",
            },
            request_id,
        )

    except ImageServiceError as exc:
        metrics.add_metric(name="upload.failed", unit=MetricUnit.Count, value=1)
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in upload_initiate")
        metrics.add_metric(name="upload.failed", unit=MetricUnit.Count, value=1)
        return resp.error(exc, request_id)
