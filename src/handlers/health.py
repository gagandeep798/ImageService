"""GET /health — Liveness check for DynamoDB and S3.

This endpoint is unauthenticated (JWT authorizer is bypassed in template.yaml)
and rate-limited by WAF to prevent abuse.  It is polled by the CloudWatch
Synthetics canary from multiple regions and used as the Route 53 health check
target for automatic DNS failover.

Returns 200 when all checks pass; 503 with a ``degraded`` status when any check fails.
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common.config import get_settings
from src.common.dynamo import get_read_resource
from src.common.s3 import get_s3_client

logger = Logger(service="image-service")


def _check_dynamodb(settings) -> str:
    """Verify DynamoDB reachability by describing the images table.  Returns ``"ok"`` or an error string."""
    try:
        resource = get_read_resource(settings)
        resource.meta.client.describe_table(TableName=settings.images_table_name)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _check_s3(settings) -> str:
    """Verify S3 reachability by heading the originals bucket.  Returns ``"ok"`` or an error string."""
    try:
        client = get_s3_client(settings)
        client.head_bucket(Bucket=settings.originals_bucket)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point for GET /health.  Runs all checks within a 2-second budget."""
    settings = get_settings()

    checks = {
        "dynamodb_images": _check_dynamodb(settings),
        "s3_originals": _check_s3(settings),
    }

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    import json
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "status": "healthy" if all_ok else "degraded",
            "checks": checks,
            "version": settings.service_version,
            "env": settings.env,
        }),
    }
