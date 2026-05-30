"""Application configuration loaded from environment variables at cold-start.

``get_settings()`` is decorated with ``lru_cache`` so env vars are read
exactly once per Lambda container lifetime.  All downstream modules import this
function rather than reading environment variables directly.
"""
import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class Settings:
    # DynamoDB
    images_table_name: str
    users_table_name: str
    migrations_table_name: str
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
    dynamo_read_role_arn: Optional[str]
    dynamo_write_role_arn: Optional[str]
    dynamo_delete_role_arn: Optional[str]

    # DynamoDB sharding
    gsi2_shard_count: int

    # PII
    pii_pepper: str

    # CloudFront
    cloudfront_private_key_pem: str
    cloudfront_key_pair_id: str

    # Alerts
    slack_webhook_url: str

    # JWT
    jwt_secret: str
    jwt_access_token_ttl: int
    jwt_refresh_token_ttl: int

    # Env
    env: str
    service_version: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.environ.get("ENV", "local")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    _aws_endpoint = os.environ.get("AWS_ENDPOINT_URL") or None
    dynamo_endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL") or _aws_endpoint
    s3_endpoint = os.environ.get("S3_ENDPOINT_URL") or _aws_endpoint

    cf_b64 = os.environ.get("CLOUDFRONT_PRIVATE_KEY_B64", "")
    cf_private_key = base64.b64decode(cf_b64).decode() if cf_b64 else ""

    settings = Settings(
        images_table_name=os.environ.get("IMAGES_TABLE_NAME", "image-service-images"),
        users_table_name=os.environ.get("USERS_TABLE_NAME", "image-service-users"),
        migrations_table_name=os.environ.get("MIGRATIONS_TABLE_NAME", "image-service-migrations"),
        dynamodb_endpoint_url=dynamo_endpoint,
        aws_region=region,
        originals_bucket=os.environ.get("ORIGINALS_BUCKET", ""),
        thumbnails_bucket=os.environ.get("THUMBNAILS_BUCKET", ""),
        quarantine_bucket=os.environ.get("QUARANTINE_BUCKET", ""),
        logs_bucket=os.environ.get("LOGS_BUCKET", ""),
        s3_endpoint_url=s3_endpoint,
        max_image_size_bytes=int(os.environ.get("MAX_IMAGE_SIZE_BYTES", str(20 * 1024 * 1024))),
        chunk_size_bytes=int(os.environ.get("CHUNK_SIZE_BYTES", str(5 * 1024 * 1024))),
        upload_url_ttl_seconds=int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900")),
        download_url_ttl_seconds=int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "3600")),
        dynamo_read_role_arn=os.environ.get("DYNAMO_READ_ROLE_ARN") or None,
        dynamo_write_role_arn=os.environ.get("DYNAMO_WRITE_ROLE_ARN") or None,
        dynamo_delete_role_arn=os.environ.get("DYNAMO_DELETE_ROLE_ARN") or None,
        gsi2_shard_count=int(os.environ.get("DYNAMO_GSI2_SHARD_COUNT", "8")),
        pii_pepper=os.environ["PII_PEPPER"],
        cloudfront_private_key_pem=cf_private_key,
        cloudfront_key_pair_id=os.environ.get("CLOUDFRONT_KEY_PAIR_ID", ""),
        slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
        jwt_secret=os.environ["JWT_SECRET"],
        jwt_access_token_ttl=int(os.environ.get("JWT_ACCESS_TOKEN_TTL", "3600")),
        jwt_refresh_token_ttl=int(os.environ.get("JWT_REFRESH_TOKEN_TTL", "2592000")),
        env=env,
        service_version=os.environ.get("SERVICE_VERSION", "0.1.0"),
    )

    return settings


# Alias for CLI tools, migrations, and integration tests that need Settings without
# calling Secrets Manager. Since get_settings() is already env-var only, this is
# identical — the alias exists to signal intent at the call site.
get_env_settings = get_settings


def get_env(key: str, default: str = "") -> str:
    """Read a single env var. All os.environ access is centralised in config.py."""
    return os.environ.get(key, default)
