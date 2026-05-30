"""Unit tests for list_images handler — GET /images."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _event(qs: dict = None) -> dict:
    return {
        "pathParameters": {},
        "requestContext": {"requestId": "req-list", "authorizer": {"user_id": "usr_abc"}},
        "queryStringParameters": qs or {},
    }


@mock_aws
def test_lists_active_images_for_user(dynamodb_tables, mock_settings: Settings):
    for i in range(3):
        img_repo.create_pending(
            mock_settings, f"img_list{i}", "usr_list",
            f"originals/usr_list/img_list{i}/f.jpg", f"up-{i}", "image/jpeg", None, None, [],
        )
        img_repo.set_status(mock_settings, f"img_list{i}", "ACTIVE")

    with patch("src.handlers.list_images.get_settings", return_value=mock_settings):
        from src.handlers.list_images import handler
        resp = handler(_event({"user_id": "usr_list", "limit": "10"}), MagicMock())

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])["data"]
    assert data["count"] == 3
    assert all(item["status"] == "ACTIVE" for item in data["items"])


@mock_aws
def test_respects_limit_parameter(dynamodb_tables, mock_settings: Settings):
    for i in range(5):
        img_repo.create_pending(
            mock_settings, f"img_lim{i}", "usr_lim",
            f"originals/usr_lim/f{i}.jpg", f"up-{i}", "image/jpeg", None, None, [],
        )
        img_repo.set_status(mock_settings, f"img_lim{i}", "ACTIVE")

    with patch("src.handlers.list_images.get_settings", return_value=mock_settings):
        from src.handlers.list_images import handler
        resp = handler(_event({"user_id": "usr_lim", "limit": "2"}), MagicMock())

    data = json.loads(resp["body"])["data"]
    assert data["count"] == 2


@mock_aws
def test_returns_empty_list_for_unknown_user(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.list_images.get_settings", return_value=mock_settings):
        from src.handlers.list_images import handler
        resp = handler(_event({"user_id": "usr_nobody"}), MagicMock())

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["data"]["count"] == 0
