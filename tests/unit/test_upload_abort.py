"""Unit tests for upload_abort handler — DELETE /images/{id}/upload."""
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
        "body": None,
        "requestContext": {"requestId": "req-abt", "authorizer": {"jwt": {"claims": {"sub": user_id}}}},
        "queryStringParameters": {},
    }


@mock_aws
def test_abort_sets_status_aborted(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_abt1", "usr_abc",
        "originals/usr_abc/img_abt1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.upload_abort.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.cancel_upload"):
        from src.handlers.upload_abort import handler
        resp = handler(_event("img_abt1"), MagicMock())

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["data"]["status"] == "ABORTED"


@mock_aws
def test_abort_returns_403_for_wrong_owner(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_abt2", "usr_owner",
        "originals/usr_owner/img_abt2/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.upload_abort.get_settings", return_value=mock_settings):
        from src.handlers.upload_abort import handler
        resp = handler(_event("img_abt2", user_id="usr_other"), MagicMock())

    assert resp["statusCode"] == 403
