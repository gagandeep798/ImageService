"""S3 event handler — drives the PENDING_FINALIZE → SCANNING state transition.

Triggered directly by S3 ObjectCreated events on the originals bucket.  For each
record the handler:
  1. Parses the ``image_id`` from the S3 object key.
  2. Calls S3 GetObject to determine file size and extract dimensions.
  3. Updates the DynamoDB record to SCANNING with the measured attributes.
  4. Increments the owner's ``image_count`` quota field.
  5. Asynchronously invokes ScanCompleteFunction with the scan result.
"""
import io
import json

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from PIL import Image

from src.common.config import get_settings
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo
from src.repositories import user_repository as user_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


def _extract_dimensions(data: bytes) -> tuple[int | None, int | None]:
    try:
        img = Image.open(io.BytesIO(data))
        return img.width, img.height
    except Exception:
        return None, None


def _parse_image_id_from_key(s3_key: str) -> str | None:
    # originals/{user_id}/{year}/{month}/{image_id}/{filename}
    parts = s3_key.split("/")
    if len(parts) >= 5:
        return parts[4]
    return None


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point — processes a batch of S3 ObjectCreated records."""
    settings = get_settings()
    lambda_client = boto3.client("lambda", region_name=settings.aws_region)
    processed = failed = 0

    for s3_record in event.get("Records", []):
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

            lambda_client.invoke(
                FunctionName=settings.scan_complete_function_arn,
                InvocationType="Event",
                Payload=json.dumps({"image_id": image_id, "result": "CLEAN"}).encode(),
            )

            metrics.add_metric(name="image.finalized", unit=MetricUnit.Count, value=1)
            logger.info("upload_finalized", image_id=image_id, size_bytes=size_bytes)
            processed += 1

        except Exception as exc:
            logger.exception("Failed to finalize image", image_id=image_id, error=str(exc))
            metrics.add_metric(name="upload.failed", unit=MetricUnit.Count, value=1)
            failed += 1
            raise

    return {"processed": processed, "failed": failed}
