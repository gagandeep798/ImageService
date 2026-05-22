"""Unit tests for generate_thumbnails handler — SQS trigger."""
import json
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _sqs_event(image_id: str) -> dict:
    return {"Records": [{"body": json.dumps({"image_id": image_id})}]}


def _minimal_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\xff\xc0\x00\x0b\x08\x00\x08\x00\x08\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf8\xff\xd9"
    )


@mock_aws
def test_generates_thumbnails_and_updates_record(dynamodb_tables, s3_buckets, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_thm1", "usr_abc",
        "originals/usr_abc/2026/05/img_thm1/f.jpg", "up-1", "image/jpeg", None, None, [],
    )
    img_repo.set_status(mock_settings, "img_thm1", "ACTIVE")

    with patch("src.handlers.generate_thumbnails.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.get_object_bytes", return_value=_minimal_jpeg()):
        from src.handlers.generate_thumbnails import handler
        handler(_sqs_event("img_thm1"), MagicMock())

    image = img_repo.get_by_id(mock_settings, "img_thm1")
    assert "128.jpg" in image.thumbnail_keys
    assert "400.jpg" in image.thumbnail_keys
    assert "1200.jpg" in image.thumbnail_keys
