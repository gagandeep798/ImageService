"""Unit tests for get_image handler — GET /images/{id}."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _event(image_id: str) -> dict:
    return {
        "pathParameters": {"image_id": image_id},
        "requestContext": {"requestId": "req-get", "authorizer": {"claims": {"custom:user_id": "usr_abc"}}},
        "queryStringParameters": {},
    }


@mock_aws
def test_returns_image_metadata(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_get1", "usr_abc",
        "originals/usr_abc/img_get1/f.jpg", "up-1", "image/jpeg", "Title", None, ["nature"],
    )
    img_repo.set_status(mock_settings, "img_get1", "ACTIVE")

    with patch("src.handlers.get_image.get_settings", return_value=mock_settings):
        from src.handlers.get_image import handler
        resp = handler(_event("img_get1"), MagicMock())

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])["data"]
    assert data["image_id"] == "img_get1"
    assert data["title"] == "Title"
    assert "s3_key" not in data
    assert "upload_id" not in data


@mock_aws
def test_returns_404_for_missing_image(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.get_image.get_settings", return_value=mock_settings):
        from src.handlers.get_image import handler
        resp = handler(_event("img_missing"), MagicMock())

    assert resp["statusCode"] == 404


@mock_aws
def test_returns_404_for_deleted_image(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_get2", "usr_abc",
        "originals/usr_abc/img_get2/f.jpg", "up-1", "image/jpeg", None, None, [],
    )
    img_repo.soft_delete(mock_settings, "img_get2")

    with patch("src.handlers.get_image.get_settings", return_value=mock_settings):
        from src.handlers.get_image import handler
        resp = handler(_event("img_get2"), MagicMock())

    assert resp["statusCode"] == 404
