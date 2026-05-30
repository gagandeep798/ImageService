"""Unit tests for download handler — GET /images/{id}/download."""
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _event(image_id: str) -> dict:
    return {
        "pathParameters": {"image_id": image_id},
        "requestContext": {"requestId": "req-dl", "authorizer": {"user_id": "usr_abc"}},
        "queryStringParameters": {},
    }


@mock_aws
def test_returns_302_redirect_for_active_image(dynamodb_tables, s3_buckets, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_dl1", "usr_abc",
        "originals/usr_abc/img_dl1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )
    img_repo.set_status(mock_settings, "img_dl1", "ACTIVE")

    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_dl1"), MagicMock())

    assert resp["statusCode"] == 302
    assert "Location" in resp["headers"]
    assert resp["headers"]["Location"]


@mock_aws
def test_returns_404_for_non_active_image(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_dl2", "usr_abc",
        "originals/usr_abc/img_dl2/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_dl2"), MagicMock())

    assert resp["statusCode"] == 404


@mock_aws
def test_returns_404_for_missing_image(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_missing"), MagicMock())

    assert resp["statusCode"] == 404
