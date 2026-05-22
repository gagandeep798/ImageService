"""Unit tests for health handler."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings

pytestmark = pytest.mark.unit


@mock_aws
def test_health_returns_200_when_healthy(dynamodb_tables, s3_buckets, mock_settings: Settings):
    with patch("src.handlers.health.get_settings", return_value=mock_settings):
        from src.handlers.health import handler
        resp = handler({}, MagicMock())

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "healthy"
    assert body["checks"]["dynamodb_images"] == "ok"
    assert body["checks"]["s3_originals"] == "ok"
    assert body["env"] == mock_settings.env


@mock_aws
def test_health_returns_503_on_missing_table(mock_settings: Settings):
    """No tables are created — DynamoDB check should report an error."""
    with patch("src.handlers.health.get_settings", return_value=mock_settings):
        from src.handlers.health import handler
        resp = handler({}, MagicMock())

    assert resp["statusCode"] == 503
    body = json.loads(resp["body"])
    assert body["status"] == "degraded"
    assert body["checks"]["dynamodb_images"] != "ok"
