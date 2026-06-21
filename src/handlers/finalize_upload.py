"""SQS consumer that drives the PENDING_FINALIZE → SCANNING state transition.

Triggered by an SQS message that wraps the S3 ObjectCreated event.  For each
message the handler:
  1. Parses the ``image_id`` from the S3 object key.
  2. Calls S3 HeadObject/GetObject to determine file size and extract dimensions.
  3. Updates the DynamoDB record to SCANNING with the measured attributes.
  4. Increments the owner's ``image_count`` quota field.

Re-raises exceptions so the SQS trigger retries failed records (up to
``maxReceiveCount`` before routing to the DLQ).
"""
import io
import json
from typing import Optional

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from PIL import Image

from src.common.config import get_settings
from src.common import response as resp
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo
from src.repositories import user_repository as user_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


def _extract_dimensions(data: bytes) -> tuple[Optional[int], Optional[int]]:
    """Extract (width, height) from raw image bytes using Pillow.  Returns (None, None) on failure."""
    try:
        img = Image.open(io.BytesIO(data))
        return img.width, img.height
    except Exception:
        return None, None


def _parse_image_id_from_key(s3_key: str) -> Optional[str]:
    """Extract the image_id segment from the canonical S3 key pattern.

    Key pattern: ``originals/{user_id}/{year}/{month}/{image_id}/{filename}``
    """
    # originals/{user_id}/{year}/{month}/{image_id}/{filename}
    parts = s3_key.split("/")
    if len(parts) >= 5:
        return parts[4]
    return None


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point — processes a batch of SQS records wrapping S3 ObjectCreated events."""
    settings = get_settings()
    processed = failed = 0

    for record in event.get("Records", []):
        body = json.loads(record.get("body", "{}"))
        # SQS wraps the S3 event
        s3_records = body.get("Records", [body]) if "Records" in body else [body]

        for s3_record in s3_records:
            s3_info = s3_record.get("s3", {})
            s3_key = s3_info.get("object", {}).get("key", "")
            size_bytes = s3_info.get("object", {}).get("size", 0)

            if not s3_key.startswith("originals/"):
                continue

            image_id = _parse_image_id_from_key(s3_key)
            if not image_id:
                logger.warning("Could not parse image_id from key", s3_key=s3_key)
                failed += 1
                continue

            try:
                raw = store_repo.get_object_bytes(settings, s3_key)
                width, height = _extract_dimensions(raw)

                img_repo.update_after_finalize(settings, image_id, size_bytes, width, height)

                image = img_repo.get_by_id(settings, image_id, consistent=True)
                user_repo.finalize_quota(settings, image.user_id, size_bytes)

                metrics.add_metric(name="image.finalized", unit=MetricUnit.Count, value=1)
                logger.info("upload_finalized", image_id=image_id, size_bytes=size_bytes)
                processed += 1

            except Exception as exc:
                logger.exception("Failed to finalize image", image_id=image_id, error=str(exc))
                metrics.add_metric(name="upload.failed", unit=MetricUnit.Count, value=1)
                failed += 1
                raise  # Re-raise so SQS retries (DLQ after max attempts)

    return {"processed": processed, "failed": failed}
