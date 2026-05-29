"""
Integration test fixtures — requires LocalStack running via docker-compose.
Run with: pytest -m integration (after make localstack-up)
"""
import os

import boto3
import pytest

LOCALSTACK_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:4566")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "http://localhost:4566")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_BOTO_KWARGS = dict(
    endpoint_url=LOCALSTACK_ENDPOINT,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

_S3_KWARGS = dict(
    endpoint_url=S3_ENDPOINT,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)


@pytest.fixture(scope="session")
def localstack_dynamo():
    return boto3.resource("dynamodb", **_BOTO_KWARGS)


@pytest.fixture(scope="session")
def localstack_s3():
    return boto3.client("s3", **_S3_KWARGS)


@pytest.fixture(scope="session")
def integration_settings():
    """Settings pointing at LocalStack."""
    from src.common.config import Settings
    return Settings(
        images_table_name=os.environ.get("IMAGES_TABLE_NAME", "image-service-images"),
        users_table_name=os.environ.get("USERS_TABLE_NAME", "image-service-users"),
        migrations_table_name=os.environ.get("MIGRATIONS_TABLE_NAME", "image-service-migrations"),
        secret_hashes_table_name=os.environ.get("SECRET_HASHES_TABLE_NAME", "image-service-secret-hashes"),
        dynamodb_endpoint_url=LOCALSTACK_ENDPOINT,
        aws_region=REGION,
        originals_bucket=os.environ.get("ORIGINALS_BUCKET", "image-service-originals-000000000000-us-east-1"),
        thumbnails_bucket=os.environ.get("THUMBNAILS_BUCKET", "image-service-thumbnails-000000000000-us-east-1"),
        quarantine_bucket=os.environ.get("QUARANTINE_BUCKET", "image-service-quarantine-000000000000-us-east-1"),
        logs_bucket=os.environ.get("LOGS_BUCKET", "image-service-logs-000000000000-us-east-1"),
        s3_endpoint_url=S3_ENDPOINT,
        max_image_size_bytes=20 * 1024 * 1024,
        chunk_size_bytes=5 * 1024 * 1024,
        upload_url_ttl_seconds=900,
        download_url_ttl_seconds=3600,
        # Role ARNs empty for LocalStack — IAM is not enforced locally
        dynamo_read_role_arn=os.environ.get("DYNAMO_READ_ROLE_ARN") or None,
        dynamo_write_role_arn=os.environ.get("DYNAMO_WRITE_ROLE_ARN") or None,
        dynamo_delete_role_arn=os.environ.get("DYNAMO_DELETE_ROLE_ARN") or None,
        gsi2_shard_count=int(os.environ.get("DYNAMO_GSI2_SHARD_COUNT", "8")),
        pii_pepper=os.environ.get("PII_PEPPER", "integration-test-pepper"),
        cloudfront_private_key_pem="LOCAL_DEV_NO_CLOUDFRONT",
        cloudfront_key_pair_id="LOCAL_DEV",
        slack_webhook_url="",
        env="local",
    )
