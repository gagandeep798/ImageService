"""Direct-invocation handler for AV scan results — drives the SCANNING → ACTIVE or QUARANTINE transition.

Invoked asynchronously by FinalizeUploadFunction with payload ``{image_id, result}``
where ``result`` is ``CLEAN`` or ``THREAT``.  Threat images are moved to the
quarantine bucket and marked QUARANTINE.  Clean images become ACTIVE and
GenerateThumbnailsFunction is invoked asynchronously.
"""
import json

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common.config import get_settings
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point — processes a single scan result."""
    settings = get_settings()
    image_id: str = event.get("image_id", "")
    scan_result: str = event.get("result", "CLEAN")  # CLEAN | THREAT

    if not image_id:
        return {"ok": False, "error": "missing image_id"}

    try:
        if scan_result == "THREAT":
            image = img_repo.get_by_id(settings, image_id, consistent=True)
            store_repo.move_to_quarantine(settings, image.s3_key)
            img_repo.set_status(settings, image_id, "QUARANTINE")
            metrics.add_metric(name="scan.threat_detected", unit=MetricUnit.Count, value=1)
            logger.warning("image_quarantined", image_id=image_id)
        else:
            img_repo.set_status(settings, image_id, "ACTIVE")
            metrics.add_metric(name="scan.clean", unit=MetricUnit.Count, value=1)
            logger.info("image_activated", image_id=image_id)

            boto3.client("lambda", region_name=settings.aws_region).invoke(
                FunctionName=settings.generate_thumbnails_function_arn,
                InvocationType="Event",
                Payload=json.dumps({"image_id": image_id}).encode(),
            )

    except Exception:
        logger.exception("Failed to process scan result", image_id=image_id)
        raise

    return {"ok": True}
