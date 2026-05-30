"""Unit tests for upload_part handler — POST /images/{id}/parts."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _event(image_id: str, body: dict, user_id: str = "usr_abc") -> dict:
    return {
        "pathParameters": {"image_id": image_id},
        "body": json.dumps(body),
        "requestContext": {
            "requestId": "req-part",
            "authorizer": {"claims": {"custom:user_id": user_id}},
        },
        "queryStringParameters": {},
    }


@mock_aws
def test_returns_presigned_url(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_part1", "usr_abc",
        "originals/usr_abc/img_part1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.upload_part.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.get_part_upload_url",
               return_value="https://s3.example.com/presigned"):
        from src.handlers.upload_part import handler
        resp = handler(_event("img_part1", {"upload_id": "up-1", "part_number": 1}), MagicMock())

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])["data"]
    assert data["presigned_part_url"] == "https://s3.example.com/presigned"
    assert data["part_number"] == 1


@mock_aws
def test_returns_403_for_wrong_owner(dynamodb_tables, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_part2", "usr_owner",
        "originals/usr_owner/img_part2/f.jpg", "up-2", "image/jpeg", None, None, [],
    )

    with patch("src.handlers.upload_part.get_settings", return_value=mock_settings):
        from src.handlers.upload_part import handler
        resp = handler(_event("img_part2", {"upload_id": "up-2", "part_number": 1}, user_id="usr_attacker"), MagicMock())

    assert resp["statusCode"] == 403


@mock_aws
def test_returns_404_for_missing_image(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.upload_part.get_settings", return_value=mock_settings):
        from src.handlers.upload_part import handler
        resp = handler(_event("img_missing", {"upload_id": "up-x", "part_number": 1}), MagicMock())

    assert resp["statusCode"] == 404
