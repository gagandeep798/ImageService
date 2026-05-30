"""Unit tests for S3 storage repository."""

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import storage_repository as store_repo

pytestmark = pytest.mark.unit


@mock_aws
def test_get_download_url_falls_back_to_s3_presigned(s3_buckets, mock_settings: Settings):
    """When CloudFront is not configured (LOCAL_DEV), a presigned S3 URL is returned."""
    url = store_repo.get_download_url(mock_settings, "originals/usr_abc/2026/05/img_1/f.jpg")
    assert "test-originals" in url or "s3" in url.lower()


@mock_aws
def test_initiate_upload_returns_upload_id_and_key(s3_buckets, mock_settings: Settings):
    upload_id, s3_key = store_repo.initiate_upload(
        mock_settings, "usr_abc", "img_001", "photo.jpg", "image/jpeg"
    )
    assert upload_id
    assert "usr_abc" in s3_key
    assert "img_001" in s3_key
    assert s3_key.endswith("photo.jpg")


@mock_aws
def test_cancel_upload_is_idempotent(s3_buckets, mock_settings: Settings):
    """Aborting a non-existent or already-aborted upload should not raise."""
    store_repo.cancel_upload(mock_settings, "originals/usr/img/f.jpg", "nonexistent-upload-id")


@mock_aws
def test_put_thumbnail_uploads_to_thumbnails_bucket(s3_buckets, mock_settings: Settings):
    import boto3
    key = store_repo.put_thumbnail(
        mock_settings, "img_001", "128.jpg", b"\xff\xd8\xff", "image/jpeg"
    )
    assert key == "thumbnails/img_001/128.jpg"
    s3 = boto3.client("s3", region_name=mock_settings.aws_region)
    resp = s3.head_object(Bucket=mock_settings.thumbnails_bucket, Key=key)
    assert resp["ContentType"] == "image/jpeg"
    assert resp["CacheControl"] == "public, max-age=86400"
