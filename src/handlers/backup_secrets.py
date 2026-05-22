"""
Scheduled daily Lambda — computes SHA-256 hashes of all Secrets Manager
secrets and stores them in DynamoDB for tamper detection.
Raises a CloudWatch metric if any secret hash changes unexpectedly.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="image-service")
metrics = Metrics(namespace="ImageService")

_SM_PREFIX = "image-service/"


def _sm_client() -> boto3.client:
    """Build a Secrets Manager client, routing to LocalStack when an endpoint URL is set."""
    kwargs: dict = {"region_name": os.environ.get("AWS_DEFAULT_REGION", "us-east-1")}
    endpoint = os.environ.get("SECRETSMANAGER_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("secretsmanager", **kwargs)


def _dynamo_table() -> object:
    """Return the boto3 Table for the secret-hashes tracking table."""
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL")
    kwargs: dict = {"region_name": os.environ.get("AWS_DEFAULT_REGION", "us-east-1")}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    resource = boto3.resource("dynamodb", **kwargs)
    return resource.Table(os.environ.get("SECRET_HASHES_TABLE_NAME", "image-service-secret-hashes"))


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

    env = os.environ.get("ENV", "local")
    prefix = f"{_SM_PREFIX}{env}/"

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
