"""Shared pytest fixtures for unit tests (moto-based, no external deps).

``TEST_SETTINGS`` is the single source of truth for all test configuration.
It is a direct ``Settings`` dataclass construction — no environment variables
are read here.  Every fixture and test reads values from ``mock_settings``
rather than from ``os.environ`` or hardcoded strings.

AWS credentials are handled automatically by the ``@mock_aws`` decorator /
``mock_aws()`` context manager; no manual credential setup is required.
"""
import boto3
import pytest
from moto import mock_aws

from src.common.config import Settings

# ── Single source of truth for all test configuration ────────────────────────
# Direct dataclass construction — no os.environ reads, no Secrets Manager calls.
TEST_SETTINGS = Settings(
    images_table_name="test-images",
    users_table_name="test-users",
    migrations_table_name="test-migrations",
    secret_hashes_table_name="test-secret-hashes",
    dynamodb_endpoint_url=None,
    aws_region="us-east-1",
    originals_bucket="test-originals",
    thumbnails_bucket="test-thumbnails",
    quarantine_bucket="test-quarantine",
    logs_bucket="test-logs",
    s3_endpoint_url=None,
    max_image_size_bytes=20 * 1024 * 1024,
    chunk_size_bytes=5 * 1024 * 1024,
    upload_url_ttl_seconds=900,
    download_url_ttl_seconds=3600,
    dynamo_read_role_arn=None,
    dynamo_write_role_arn=None,
    dynamo_delete_role_arn=None,
    gsi2_shard_count=2,
    pii_pepper="test-pepper-for-unit-tests-only",
    cloudfront_private_key_pem="LOCAL_DEV_NO_CLOUDFRONT",
    cloudfront_key_pair_id="LOCAL_DEV",
    slack_webhook_url="",
    env="test",
    service_version="0.1.0",
    secretsmanager_endpoint_url=None,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def mock_settings() -> Settings:
    """Return the canonical test Settings instance.

    The single source of truth for all table names, bucket names, limits,
    and other configuration values used in tests.
    """
    return TEST_SETTINGS


@pytest.fixture(scope="function")
def dynamodb_tables(mock_settings: Settings):
    """Create the images and users DynamoDB tables in moto.

    All names are read from ``mock_settings``.  ``mock_aws`` provides its own
    credential mocking — no ``os.environ`` manipulation needed.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name=mock_settings.aws_region)

        client.create_table(
            TableName=mock_settings.images_table_name,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "UserImagesIndex",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "StatusIndex",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )

        client.create_table(
            TableName=mock_settings.users_table_name,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "EmailHashIndex_PK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[{
                "IndexName": "EmailHashIndex",
                "KeySchema": [{"AttributeName": "EmailHashIndex_PK", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }],
        )

        yield boto3.resource("dynamodb", region_name=mock_settings.aws_region)


@pytest.fixture(scope="function")
def s3_buckets(mock_settings: Settings):
    """Create all S3 buckets in moto.

    All names are read from ``mock_settings``.
    """
    with mock_aws():
        s3 = boto3.client("s3", region_name=mock_settings.aws_region)
        for bucket in (
            mock_settings.originals_bucket,
            mock_settings.thumbnails_bucket,
            mock_settings.quarantine_bucket,
            mock_settings.logs_bucket,
        ):
            s3.create_bucket(Bucket=bucket)
        yield s3
