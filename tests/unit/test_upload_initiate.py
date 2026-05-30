"""Unit tests for upload_initiate handler."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings

pytestmark = pytest.mark.unit


def _make_event(body: dict, user_id: str = "usr_abc") -> dict:
    return {
        "body": json.dumps(body),
        "requestContext": {
            "requestId": "test-req-id",
            "authorizer": {"user_id": user_id},
        },
        "pathParameters": {},
        "queryStringParameters": {},
    }


@mock_aws
def test_upload_initiate_returns_202(dynamodb_tables, s3_buckets, mock_settings: Settings):
    with patch("src.handlers.upload_initiate.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.initiate_upload",
               return_value=("upload-id-123", "originals/usr_abc/2026/05/img_xxx/photo.jpg")), \
         patch("src.repositories.user_repository.check_and_reserve_quota"):

        from src.handlers.upload_initiate import handler
        event = _make_event({
            "user_id": "usr_abc",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "total_size_bytes": mock_settings.chunk_size_bytes,
            "title": "My Photo",
        })

        resp = handler(event, MagicMock())
        assert resp["statusCode"] == 202
        data = json.loads(resp["body"])["data"]
        assert data["status"] == "PENDING"
        assert "upload_id" in data
        assert "image_id" in data
        assert data["chunk_size_bytes"] == mock_settings.chunk_size_bytes


@mock_aws
def test_upload_initiate_rejects_unsupported_content_type(dynamodb_tables, s3_buckets, mock_settings: Settings):
    with patch("src.handlers.upload_initiate.get_settings", return_value=mock_settings):
        from src.handlers.upload_initiate import handler
        event = _make_event({
            "user_id": "usr_abc",
            "filename": "script.exe",
            "content_type": "application/octet-stream",
            "total_size_bytes": 100,
        })
        resp = handler(event, MagicMock())
        assert resp["statusCode"] == 400


@mock_aws
def test_upload_initiate_rejects_file_exceeding_max_size(dynamodb_tables, s3_buckets, mock_settings: Settings):
    with patch("src.handlers.upload_initiate.get_settings", return_value=mock_settings):
        from src.handlers.upload_initiate import handler
        event = _make_event({
            "user_id": "usr_abc",
            "filename": "huge.jpg",
            "content_type": "image/jpeg",
            "total_size_bytes": mock_settings.max_image_size_bytes + 1,
        })
        resp = handler(event, MagicMock())
        assert resp["statusCode"] == 400


@mock_aws
def test_upload_initiate_rejects_wrong_user(dynamodb_tables, s3_buckets, mock_settings: Settings):
    with patch("src.handlers.upload_initiate.get_settings", return_value=mock_settings):
        from src.handlers.upload_initiate import handler
        event = _make_event({
            "user_id": "usr_OTHER",  # does not match JWT sub
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "total_size_bytes": 1024,
        }, user_id="usr_abc")
        resp = handler(event, MagicMock())
        assert resp["statusCode"] == 403
