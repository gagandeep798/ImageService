"""Unit tests for gdpr_delete_user handler — DELETE /users/{id}."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo
from src.repositories import user_repository as user_repo

pytestmark = pytest.mark.unit


def _event(user_id: str, caller_id: str) -> dict:
    return {
        "pathParameters": {"user_id": user_id},
        "requestContext": {"requestId": "req-gdpr", "authorizer": {"claims": {"custom:user_id": caller_id}}},
        "queryStringParameters": {},
    }


@mock_aws
def test_self_erasure_marks_user_deleted(dynamodb_tables, mock_settings: Settings):
    user_repo.create_user(mock_settings, "usr_erase1", "Erase Me")

    with patch("src.handlers.gdpr_delete_user.get_settings", return_value=mock_settings):
        from src.handlers.gdpr_delete_user import handler
        resp = handler(_event("usr_erase1", "usr_erase1"), MagicMock())

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])["data"]
    assert data["user_id"] == "usr_erase1"
    assert "erased_at" in data


@mock_aws
def test_returns_403_when_wrong_caller(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.gdpr_delete_user.get_settings", return_value=mock_settings):
        from src.handlers.gdpr_delete_user import handler
        resp = handler(_event("usr_victim", "usr_attacker"), MagicMock())

    assert resp["statusCode"] == 403


@mock_aws
def test_also_soft_deletes_user_images(dynamodb_tables, mock_settings: Settings):
    user_repo.create_user(mock_settings, "usr_erase2", "With Images")
    img_repo.create_pending(
        mock_settings, "img_e1", "usr_erase2",
        "originals/usr_erase2/img_e1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )
    img_repo.set_status(mock_settings, "img_e1", "ACTIVE")

    with patch("src.handlers.gdpr_delete_user.get_settings", return_value=mock_settings):
        from src.handlers.gdpr_delete_user import handler
        resp = handler(_event("usr_erase2", "usr_erase2"), MagicMock())

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["data"]["images_deleted"] == 1
    from src.common.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        img_repo.get_by_id(mock_settings, "img_e1")
