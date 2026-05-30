"""SQS consumer for AV scan results — drives the SCANNING → ACTIVE or QUARANTINE transition.

Each SQS message contains ``{image_id, result}`` where ``result`` is either
``CLEAN`` or ``THREAT``.  Threat images are moved to the quarantine S3 bucket
and their metadata status is set to QUARANTINE.  Clean images are flipped to
ACTIVE, making them visible via the API.
"""
import json

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
    """Lambda entry point — processes scan result messages from the ScanQueue."""
    settings = get_settings()

    for record in event.get("Records", []):
        body = json.loads(record.get("body", "{}"))
        image_id: str = body.get("image_id", "")
        scan_result: str = body.get("result", "CLEAN")  # CLEAN | THREAT

        if not image_id:
            continue

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

        except Exception:
            logger.exception("Failed to process scan result", image_id=image_id)
            raise  # SQS retries

    return {"ok": True}
