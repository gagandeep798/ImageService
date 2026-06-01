"""DynamoDB client factory with connection pooling, health monitoring, and sharding helpers.

Three access tiers are maintained as module-level singletons, reused across warm
Lambda containers (equivalent to a connection pool):

- ``get_read_resource``   — eventual consistency; ``GetItem``, ``Query``, ``Scan`` only
- ``get_write_resource``  — strong consistency;   ``PutItem``, ``UpdateItem`` (non-delete)
- ``get_delete_resource`` — strong consistency;   ``UpdateItem`` scoped to soft-delete only

When ``dynamo_<tier>_role_arn`` is configured in Settings (loaded from Secrets Manager),
each factory assumes that IAM role via STS before building the boto3 resource.  This
enforces least-privilege at the AWS level: the delete role's IAM policy restricts
``UpdateItem`` to setting ``status = DELETED`` only.  Falls back to the Lambda
execution role when no role ARN is configured (local dev, unit tests).

Sharding:
``gsi2_pk`` spreads StatusIndex writes across ``shard_count`` partitions using the
MD5 of the image ULID, preventing hot-partition throttling.
"""
import hashlib
import time
from collections.abc import Generator
from contextlib import contextmanager

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from boto3.resources.base import ServiceResource
from botocore.exceptions import ClientError

from src.common.config import Settings

logger = Logger(service="image-service")
metrics = Metrics(namespace="ImageService")

# Module-level singletons — one per access tier, reused across warm invocations
_read_resource: ServiceResource | None = None
_write_resource: ServiceResource | None = None
_delete_resource: ServiceResource | None = None


def _assume_role(role_arn: str, session_name: str, region: str) -> dict:
    """Assume an IAM role via STS and return temporary credentials.

    The caller is responsible for caching the returned credentials for the
    lifetime of the Lambda container (they are valid for 1 hour).
    """
    sts = boto3.client("sts", region_name=region)
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
    return resp["Credentials"]


def _build_resource(
    settings: Settings,
    role_arn: str | None = None,
    session_name: str = "image-service",
) -> ServiceResource:
    """Instantiate a DynamoDB resource, optionally using STS-assumed credentials.

    When ``role_arn`` is provided the factory assumes that role before creating
    the resource, enforcing the IAM permission boundary for that access tier.
    Falls back to the Lambda execution role when ``role_arn`` is None.
    """
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

    if role_arn:
        creds = _assume_role(role_arn, session_name, settings.aws_region)
        kwargs["aws_access_key_id"] = creds["AccessKeyId"]
        kwargs["aws_secret_access_key"] = creds["SecretAccessKey"]
        kwargs["aws_session_token"] = creds["SessionToken"]

    return boto3.resource("dynamodb", **kwargs)


def get_read_resource(settings: Settings) -> ServiceResource:
    """Return the read-tier DynamoDB resource (eventual consistency).

    Uses the ``dynamo_read_role_arn`` IAM role when configured.
    Permitted DynamoDB actions: ``GetItem``, ``Query``, ``Scan``,
    ``DescribeTable``, ``BatchGetItem``.
    """
    global _read_resource
    if _read_resource is None:
        _read_resource = _build_resource(
            settings,
            role_arn=settings.dynamo_read_role_arn or None,
            session_name="image-service-read",
        )
    return _read_resource


def get_write_resource(settings: Settings) -> ServiceResource:
    """Return the write-tier DynamoDB resource (strong consistency).

    Uses the ``dynamo_write_role_arn`` IAM role when configured.
    Permitted DynamoDB actions: ``PutItem``, ``UpdateItem`` (non-delete
    attributes), ``BatchWriteItem``.  Soft-delete operations must use
    ``get_delete_resource`` instead.
    """
    global _write_resource
    if _write_resource is None:
        _write_resource = _build_resource(
            settings,
            role_arn=settings.dynamo_write_role_arn or None,
            session_name="image-service-write",
        )
    return _write_resource


def get_delete_resource(settings: Settings) -> ServiceResource:
    """Return the delete-tier DynamoDB resource (strong consistency).

    Uses the ``dynamo_delete_role_arn`` IAM role when configured.
    Permitted DynamoDB actions: ``UpdateItem`` restricted by an IAM condition
    that allows only setting ``status = DELETED``, ``deleted_at``, and ``ttl``.
    This role cannot create items, read arbitrary attributes, or modify any
    field other than the soft-delete fields.
    """
    global _delete_resource
    if _delete_resource is None:
        _delete_resource = _build_resource(
            settings,
            role_arn=settings.dynamo_delete_role_arn or None,
            session_name="image-service-delete",
        )
    return _delete_resource


@contextmanager
def monitor(operation: str) -> Generator[None, None, None]:
    """Wrap a DynamoDB call, recording latency and errors as CloudWatch metrics."""
    start = time.monotonic()
    try:
        yield
    except ClientError as exc:
        metrics.add_metric(name="dynamodb.connection_errors", unit=MetricUnit.Count, value=1)
        logger.error("DynamoDB error", operation=operation, error=str(exc))
        raise
    finally:
        duration_ms = (time.monotonic() - start) * 1000
        metrics.add_metric(name="dynamodb.call_latency_ms", unit=MetricUnit.Milliseconds, value=duration_ms)


def gsi2_pk(status: str, image_id: str, shard_count: int) -> str:
    """Compute the sharded GSI2 partition key for a given status and image ID.

    Uses MD5 of the image ID (not for security — ``usedforsecurity=False``) to
    distribute writes evenly across ``shard_count`` logical partitions and prevent
    hot-partition throttling on the StatusIndex GSI.
    """
    shard = int(hashlib.md5(image_id.encode(), usedforsecurity=False).hexdigest(), 16) % shard_count
    return f"STATUS#{status}#{shard}"


def gsi2_pk_all_shards(status: str, shard_count: int) -> list[str]:
    """Return all shard keys for a status, used in scatter-gather global list queries."""
    return [f"STATUS#{status}#{i}" for i in range(shard_count)]
