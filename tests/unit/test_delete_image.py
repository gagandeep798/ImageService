"""Unit tests for delete_image handler."""
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
            "requestId": "req-del",
            "authorizer": {"jwt": {"claims": {"sub": user_id}}},
        },
        "queryStringParameters": {},
    }


def _seed_image(settings: Settings, image_id: str, user_id: str) -> None:
    img_repo.create_pending(
        settings, image_id, user_id,
        f"originals/{user_id}/{image_id}/f.jpg",
        f"up-{image_id}", "image/jpeg", None, None, [],
    )


@mock_aws
def test_delete_own_image(dynamodb_tables, mock_settings: Settings):
    _seed_image(mock_settings, "img_del1", "usr_abc")
    img_repo.set_status(mock_settings, "img_del1", "ACTIVE")

    with patch("src.handlers.delete_image.get_settings", return_value=mock_settings):
        from src.handlers.delete_image import handler
        resp = handler(_event("img_del1", "usr_abc"), MagicMock())

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])["data"]
    assert data["status"] == "DELETED"
    assert data["image_id"] == "img_del1"


@mock_aws
def test_delete_other_users_image_returns_403(dynamodb_tables, mock_settings: Settings):
    _seed_image(mock_settings, "img_del2", "usr_owner")

    with patch("src.handlers.delete_image.get_settings", return_value=mock_settings):
        from src.handlers.delete_image import handler
        resp = handler(_event("img_del2", "usr_attacker"), MagicMock())

    assert resp["statusCode"] == 403


@mock_aws
def test_delete_already_deleted_returns_404(dynamodb_tables, mock_settings: Settings):
    _seed_image(mock_settings, "img_del3", "usr_abc")
    img_repo.soft_delete(mock_settings, "img_del3")

    with patch("src.handlers.delete_image.get_settings", return_value=mock_settings):
        from src.handlers.delete_image import handler
        resp = handler(_event("img_del3", "usr_abc"), MagicMock())

    assert resp["statusCode"] == 404


@mock_aws
def test_delete_nonexistent_image_returns_404(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.delete_image.get_settings", return_value=mock_settings):
        from src.handlers.delete_image import handler
        resp = handler(_event("img_does_not_exist", "usr_abc"), MagicMock())

    assert resp["statusCode"] == 404
