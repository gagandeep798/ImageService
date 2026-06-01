"""Unit tests for Pydantic models — validation, field constraints, and serialisation."""
import pytest
from pydantic import ValidationError

from src.common.models import (
    ImageResponse,
    PartRecord,
    UploadCompleteRequest,
    UploadInitiateRequest,
    UserRecord,
)

pytestmark = pytest.mark.unit


class TestUploadInitiateRequest:
    def test_valid_request(self):
        req = UploadInitiateRequest(
            filename="photo.jpg",
            content_type="image/jpeg",
            total_size_bytes=1024,
        )
        assert req.content_type == "image/jpeg"
        assert req.tags == []

    def test_rejects_invalid_content_type(self):
        with pytest.raises(ValidationError):
            UploadInitiateRequest(
                filename="script.exe",
                content_type="application/octet-stream",
                total_size_bytes=100,
            )

    def test_accepts_all_allowed_content_types(self):
        for ct in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            req = UploadInitiateRequest(filename="f", content_type=ct, total_size_bytes=1)
            assert req.content_type == ct

    def test_rejects_zero_size(self):
        with pytest.raises(ValidationError):
            UploadInitiateRequest(
                filename="photo.jpg",
                content_type="image/jpeg",
                total_size_bytes=0,
            )


class TestUploadCompleteRequest:
    def test_valid_with_parts(self):
        req = UploadCompleteRequest(
            upload_id="up-123",
            parts=[PartRecord(part_number=1, etag='"abc"'), PartRecord(part_number=2, etag='"def"')],
        )
        assert len(req.parts) == 2
        assert req.parts[0].part_number == 1


class TestImageResponse:
    def test_excludes_internal_fields(self):
        fields = set(ImageResponse.model_fields.keys())
        assert "s3_key" not in fields
        assert "upload_id" not in fields
        assert "deleted_at" not in fields
        assert "image_id" in fields
        assert "status" in fields


class TestUserRecord:
    def test_credentials_not_in_fields(self):
        # Credentials are owned by Cognito — profile record has no email/password fields
        fields = set(UserRecord.model_fields.keys())
        assert "email" not in fields
        assert "email_hash" not in fields
        assert "password_hash" not in fields
        assert "display_name" in fields
        assert "storage_quota_bytes" in fields
