"""Unit tests for upload_complete handler — POST /images/{id}/complete."""
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
        "body": json.dumps({"upload_id": "up-1", "parts": [{"part_number": 1, "etag": '"abc"'}]}),
        "requestContext": {"requestId": "req-cmp", "authorizer": {"claims": {"custom:user_id": user_id}}},
        "queryStringParameters": {},
    }


@mock_aws
def test_returns_processing_status(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_cmp1", "usr_abc",
        "originals/usr_abc/img_cmp1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.upload_complete.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.finalize_upload"):
        from src.handlers.upload_complete import handler
        resp = handler(_event("img_cmp1"), MagicMock())

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["data"]["status"] == "PROCESSING"


@mock_aws
def test_returns_403_for_wrong_owner(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_cmp2", "usr_owner",
        "originals/usr_owner/img_cmp2/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.upload_complete.get_settings", return_value=mock_settings):
        from src.handlers.upload_complete import handler
        resp = handler(_event("img_cmp2", user_id="usr_other"), MagicMock())

    assert resp["statusCode"] == 403
