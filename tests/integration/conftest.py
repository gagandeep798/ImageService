"""
Integration test fixtures — requires LocalStack running via docker-compose.
Run with: pytest -m integration (after make localstack-up)
"""
import boto3
import pytest

from src.common.config import get_env_settings

_settings = get_env_settings()

LOCALSTACK_ENDPOINT = _settings.dynamodb_endpoint_url or "http://localhost:4566"
S3_ENDPOINT = _settings.s3_endpoint_url or "http://localhost:4566"
REGION = _settings.aws_region

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
    """Settings pointing at LocalStack, populated from .env.local."""
    return get_env_settings()
