"""Unit tests for download handler — GET /images/{id}/download."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _event(image_id: str, user_id: str = "usr_abc") -> dict:
    return {
        "pathParameters": {"image_id": image_id},
        "requestContext": {
            "requestId": "req-dl",
            "authorizer": {"claims": {"custom:user_id": user_id}},
        },
        "queryStringParameters": {},
    }


@mock_aws
def test_returns_download_url_for_active_image(
    dynamodb_tables: object,
    s3_buckets: object,
    mock_settings: Settings,
) -> None:
    img_repo.create_pending(
        mock_settings, "img_dl1", "usr_abc",
        "originals/usr_abc/img_dl1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )
    img_repo.set_status(mock_settings, "img_dl1", "ACTIVE")

    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_dl1"), MagicMock())

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])["data"]
    assert data["download_url"]
    assert data["expires_at"]


@mock_aws
def test_returns_403_for_other_users_image(
    dynamodb_tables: object,
    mock_settings: Settings,
) -> None:
    img_repo.create_pending(
        mock_settings, "img_dl_other", "usr_owner",
        "originals/usr_owner/img_dl_other/f.jpg", "up-1", "image/jpeg", None, None, [],
    )
    img_repo.set_status(mock_settings, "img_dl_other", "ACTIVE")

    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_dl_other", user_id="usr_other"), MagicMock())

    assert resp["statusCode"] == 403


@mock_aws
def test_returns_404_for_non_active_image(
    dynamodb_tables: object,
    mock_settings: Settings,
) -> None:
    img_repo.create_pending(
        mock_settings, "img_dl2", "usr_abc",
        "originals/usr_abc/img_dl2/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_dl2"), MagicMock())

    assert resp["statusCode"] == 404


@mock_aws
def test_returns_404_for_missing_image(dynamodb_tables: object, mock_settings: Settings) -> None:
    with patch("src.handlers.download.get_settings", return_value=mock_settings):
        from src.handlers.download import handler
        resp = handler(_event("img_missing"), MagicMock())

    assert resp["statusCode"] == 404
