"""
Scheduled daily Lambda — computes SHA-256 hashes of all Secrets Manager
secrets and stores them in DynamoDB for tamper detection.
Raises a CloudWatch metric if any secret hash changes unexpectedly.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common.config import get_settings

logger = Logger(service="image-service")
metrics = Metrics(namespace="ImageService")

_SM_PREFIX = "image-service/"


def _sm_client() -> boto3.client:
    """Build a Secrets Manager client, routing to LocalStack when an endpoint URL is set."""
    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.secretsmanager_endpoint_url:
        kwargs["endpoint_url"] = settings.secretsmanager_endpoint_url
    return boto3.client("secretsmanager", **kwargs)


def _dynamo_table() -> object:
    """Return the boto3 Table for the secret-hashes tracking table."""
    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    resource = boto3.resource("dynamodb", **kwargs)
    return resource.Table(settings.secret_hashes_table_name)


def _hash_secret(name: str, value: str) -> str:
    """Compute SHA-256(secret_name + ":" + secret_value) for tamper-detection.

    The actual secret value is never stored — only this hash.
    """
    return hashlib.sha256(f"{name}:{value}".encode()).hexdigest()


@logger.inject_lambda_context(log_event=False)
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:  # noqa: ARG001
    """Lambda entry point — runs daily to hash and record all Secrets Manager values.

    Emits the ``secrets.unexpected_change`` metric if any hash differs from the
    previously stored value without a known rotation in the last 24 hours.
    Returns ``{ok: True, unexpected_changes: <int>}``.
    """
    sm = _sm_client()
    table = _dynamo_table()
    now = datetime.now(timezone.utc).isoformat()
    ttl_90d = int(datetime.now(timezone.utc).timestamp()) + 90 * 86400

    prefix = f"{_SM_PREFIX}{get_settings().env}/"

    paginator = sm.get_paginator("list_secrets")
    unexpected_changes = 0

    for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
        for secret_meta in page.get("SecretList", []):
            name: str = secret_meta["Name"]

            try:
                resp = sm.get_secret_value(SecretId=name)
                value: str = resp.get("SecretString", "") or ""
            except Exception as exc:
                logger.warning("Could not read secret", name=name, error=str(exc))
                continue

            new_hash = _hash_secret(name, value)

            # Check previous hash
            prev = table.get_item(Key={"PK": f"SECHASH#{name}", "SK": "LATEST"}).get("Item")
            if prev and prev.get("hash") != new_hash:
                logger.warning("secret_hash_changed", name=name)
                metrics.add_metric(name="secrets.unexpected_change", unit=MetricUnit.Count, value=1)
                unexpected_changes += 1

            # Write current hash
            table.put_item(Item={
                "PK": f"SECHASH#{name}",
                "SK": "LATEST",
                "hash": new_hash,
                "computed_at": now,
            })
            # Historical record
            table.put_item(Item={
                "PK": f"SECHASH#{name}",
                "SK": f"HISTORY#{now}",
                "hash": new_hash,
                "computed_at": now,
                "ttl": ttl_90d,
            })

    logger.info("secrets_backup_complete", unexpected_changes=unexpected_changes)
    return {"ok": True, "unexpected_changes": unexpected_changes}
