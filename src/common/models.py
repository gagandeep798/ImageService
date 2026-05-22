"""Pydantic models for request validation and response serialisation.

All user-facing models intentionally exclude internal DynamoDB fields (PK, SK,
GSI keys) so that storage implementation details are never leaked through the
API.  The ``ImageRecord`` model is the canonical in-memory representation of a
DynamoDB item; ``ImageResponse`` is its public-facing subset.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})

ImageStatus = str  # PENDING | PENDING_FINALIZE | SCANNING | ACTIVE | QUARANTINE | DELETED | ABORTED


class UploadInitiateRequest(BaseModel):
    """Request body for POST /images — step 1 of the chunked upload flow."""

    user_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    total_size_bytes: int = Field(gt=0)
    title: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2048)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Reject any MIME type that is not an accepted image format."""
        if v not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"content_type must be one of {sorted(ALLOWED_CONTENT_TYPES)}")
        return v


class UploadPartRequest(BaseModel):
    """Request body for POST /images/{id}/parts — asks for a presigned URL for one chunk."""

    upload_id: str
    part_number: int = Field(ge=1, le=10000)
    size_bytes: int = Field(gt=0)


class UploadCompleteRequest(BaseModel):
    """Request body for POST /images/{id}/complete — finalises the S3 multipart upload."""

    upload_id: str
    parts: list[PartRecord]


class PartRecord(BaseModel):
    """A single completed S3 multipart part identified by its number and ETag."""

    part_number: int
    etag: str


UploadCompleteRequest.model_rebuild()


class ImageRecord(BaseModel):
    """Full DynamoDB item representation — includes internal fields like s3_key and upload_id.

    Never serialised directly to API responses; use ``ImageResponse`` instead.
    """

    image_id: str
    user_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    status: ImageStatus
    s3_key: str
    upload_id: Optional[str] = None
    size_bytes: Optional[int] = None
    content_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail_keys: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None


class ImageResponse(BaseModel):
    """Public-facing image representation — excludes internal storage details."""

    image_id: str
    user_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    status: ImageStatus
    size_bytes: Optional[int] = None
    content_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail_keys: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ListImagesResponse(BaseModel):
    """Paginated list response returned by GET /images."""

    items: list[ImageResponse]
    next_cursor: Optional[str] = None
    count: int


class UserRecord(BaseModel):
    """DynamoDB user profile record.

    Email is stored only as a hashed value (``email_hash`` + ``email_salt``) —
    the plaintext address is never persisted.
    """

    user_id: str
    display_name: str
    email_hash: str
    email_salt: str
    status: str
    storage_used_bytes: int = 0
    storage_quota_bytes: int = 10 * 1024 * 1024 * 1024
    image_count: int = 0
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    gdpr_erased_at: Optional[str] = None
