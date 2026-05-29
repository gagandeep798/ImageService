"""Application configuration loaded from AWS Secrets Manager at cold-start.

``get_settings()`` is decorated with ``lru_cache`` so Secrets Manager is called
exactly once per Lambda container lifetime.  All downstream modules import this
function rather than reading environment variables directly, keeping credential
handling in a single place.
"""
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class Settings:
    """Immutable configuration bundle populated from Secrets Manager + env vars.

    Frozen so it can safely be cached as a module-level singleton and shared
    across concurrent Lambda invocations without mutation risk.
    """
    # DynamoDB
    images_table_name: str
    users_table_name: str
    migrations_table_name: str
    secret_hashes_table_name: str
    dynamodb_endpoint_url: Optional[str]
    aws_region: str

    # S3
    originals_bucket: str
    thumbnails_bucket: str
    quarantine_bucket: str
    logs_bucket: str
    s3_endpoint_url: Optional[str]

    # Upload
    max_image_size_bytes: int
    chunk_size_bytes: int
    upload_url_ttl_seconds: int
    download_url_ttl_seconds: int

    # DynamoDB IAM role ARNs (optional — falls back to Lambda execution role when empty)
    # Each role has a separate IAM policy scoped to its access tier.
    dynamo_read_role_arn: Optional[str]    # GetItem, Query, Scan only
    dynamo_write_role_arn: Optional[str]   # PutItem, UpdateItem (non-delete) only
    dynamo_delete_role_arn: Optional[str]  # UpdateItem restricted to soft-delete fields only

    # DynamoDB sharding
    gsi2_shard_count: int

    # PII
    pii_pepper: str

    # CloudFront
    cloudfront_private_key_pem: str
    cloudfront_key_pair_id: str

    # Alerts
    slack_webhook_url: str

    # Env
    env: str


def _sm_client(endpoint_url: Optional[str], region: str) -> boto3.client:
    """Build a Secrets Manager boto3 client, optionally pointing at LocalStack."""
    kwargs: dict = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("secretsmanager", **kwargs)


def _get_secret(client: boto3.client, secret_id: str) -> dict:
    """Fetch and JSON-decode a Secrets Manager secret by ID.

    Raises:
        RuntimeError: if the secret cannot be retrieved (missing, permission denied, etc.).
    """
    try:
        resp = client.get_secret_value(SecretId=secret_id)
        return json.loads(resp["SecretString"])
    except ClientError as exc:
        raise RuntimeError(f"Failed to fetch secret {secret_id}: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings.

    Called once per Lambda container.  Reads five Secrets Manager paths and
    merges them with environment variable fallbacks for local development.
    """
    env = os.environ.get("ENV", "local")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    dynamo_endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL") or None
    s3_endpoint = os.environ.get("S3_ENDPOINT_URL") or None
    sm_endpoint = os.environ.get("SECRETSMANAGER_ENDPOINT_URL") or None

    sm = _sm_client(sm_endpoint, region)

    dynamo_cfg = _get_secret(sm, f"image-service/{env}/dynamodb")
    s3_cfg = _get_secret(sm, f"image-service/{env}/s3")
    pii_cfg = _get_secret(sm, f"image-service/{env}/pii_pepper")
    cf_cfg = _get_secret(sm, f"image-service/{env}/cloudfront")
    alerts_cfg = _get_secret(sm, f"image-service/{env}/alerts")

    return Settings(
        images_table_name=dynamo_cfg.get("images_table", os.environ.get("IMAGES_TABLE_NAME", "image-service-images")),
        users_table_name=dynamo_cfg.get("users_table", os.environ.get("USERS_TABLE_NAME", "image-service-users")),
        migrations_table_name=dynamo_cfg.get("migrations_table", os.environ.get("MIGRATIONS_TABLE_NAME", "image-service-migrations")),
        secret_hashes_table_name=dynamo_cfg.get("secret_hashes_table", os.environ.get("SECRET_HASHES_TABLE_NAME", "image-service-secret-hashes")),
        dynamodb_endpoint_url=dynamo_endpoint,
        aws_region=region,
        originals_bucket=s3_cfg.get("originals_bucket", os.environ.get("ORIGINALS_BUCKET", "")),
        thumbnails_bucket=s3_cfg.get("thumbnails_bucket", os.environ.get("THUMBNAILS_BUCKET", "")),
        quarantine_bucket=s3_cfg.get("quarantine_bucket", os.environ.get("QUARANTINE_BUCKET", "")),
        logs_bucket=s3_cfg.get("logs_bucket", os.environ.get("LOGS_BUCKET", "")),
        s3_endpoint_url=s3_endpoint,
        max_image_size_bytes=int(os.environ.get("MAX_IMAGE_SIZE_BYTES", str(20 * 1024 * 1024))),
        chunk_size_bytes=int(os.environ.get("CHUNK_SIZE_BYTES", str(5 * 1024 * 1024))),
        upload_url_ttl_seconds=int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900")),
        download_url_ttl_seconds=int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "3600")),
        dynamo_read_role_arn=dynamo_cfg.get("read_role_arn") or os.environ.get("DYNAMO_READ_ROLE_ARN") or None,
        dynamo_write_role_arn=dynamo_cfg.get("write_role_arn") or os.environ.get("DYNAMO_WRITE_ROLE_ARN") or None,
        dynamo_delete_role_arn=dynamo_cfg.get("delete_role_arn") or os.environ.get("DYNAMO_DELETE_ROLE_ARN") or None,
        gsi2_shard_count=int(os.environ.get("DYNAMO_GSI2_SHARD_COUNT", "8")),
        pii_pepper=pii_cfg["pepper"],
        cloudfront_private_key_pem=cf_cfg.get("private_key_pem", ""),
        cloudfront_key_pair_id=cf_cfg.get("key_pair_id", ""),
        slack_webhook_url=alerts_cfg.get("slack_webhook", ""),
        env=env,
    )
