"""Unit tests for finalize_upload handler — direct S3 event trigger."""
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _s3_event(s3_key: str, size: int = 1024) -> dict:
    return {"Records": [{"s3": {"object": {"key": s3_key, "size": size}}}]}


@mock_aws
def test_transitions_to_scanning(dynamodb_tables, s3_buckets, mock_settings: Settings):
    img_repo.create_pending(
        mock_settings, "img_fin1", "usr_abc",
        "originals/usr_abc/2026/05/img_fin1/photo.jpg", "up-1", "image/jpeg", None, None, [],
    )

    mock_lambda = MagicMock()
    with patch("src.handlers.finalize_upload.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.get_object_bytes", return_value=b"\xff\xd8\xff"), \
         patch("src.handlers.finalize_upload._extract_dimensions", return_value=(1920, 1080)), \
         patch("src.repositories.user_repository.finalize_quota"), \
         patch("boto3.client", return_value=mock_lambda):
        from src.handlers.finalize_upload import handler
        result = handler(_s3_event("originals/usr_abc/2026/05/img_fin1/photo.jpg"), MagicMock())

    assert result["processed"] == 1
    image = img_repo.get_by_id(mock_settings, "img_fin1")
    assert image.status == "SCANNING"


@mock_aws
def test_skips_non_originals_keys(dynamodb_tables, mock_settings: Settings):
    with patch("src.handlers.finalize_upload.get_settings", return_value=mock_settings):
        from src.handlers.finalize_upload import handler
        result = handler(_s3_event("thumbnails/img/128.jpg"), MagicMock())

    assert result["processed"] == 0
