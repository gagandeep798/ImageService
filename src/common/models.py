"""Pydantic models for request validation and response serialisation.

All user-facing models intentionally exclude internal DynamoDB fields (PK, SK,
GSI keys) so that storage implementation details are never leaked through the
API.  The ``ImageRecord`` model is the canonical in-memory representation of a
DynamoDB item; ``ImageResponse`` is its public-facing subset.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})

ImageStatus = str  # PENDING | PENDING_FINALIZE | SCANNING | ACTIVE | QUARANTINE | DELETED | ABORTED


class UploadInitiateRequest(BaseModel):
    """Request body for POST /images — step 1 of the chunked upload flow."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    total_size_bytes: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
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
    filename: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: ImageStatus
    s3_key: str
    upload_id: str | None = None
    size_bytes: int | None = None
    content_type: str
    width: int | None = None
    height: int | None = None
    thumbnail_keys: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class ImageResponse(BaseModel):
    """Public-facing image representation — excludes internal storage details."""

    image_id: str
    user_id: str
    filename: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: ImageStatus
    size_bytes: int | None = None
    content_type: str
    width: int | None = None
    height: int | None = None
    thumbnail_keys: dict[str, str] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    created_at: str
    updated_at: str


class ListImagesResponse(BaseModel):
    """Paginated list response returned by GET /images."""

    items: list[ImageResponse]
    next_cursor: str | None = None
    count: int


class UserRecord(BaseModel):
    """DynamoDB user profile record. Credentials are owned by Cognito."""

    user_id: str
    display_name: str
    status: str
    storage_used_bytes: int = 0
    storage_quota_bytes: int = 10 * 1024 * 1024 * 1024
    image_count: int = 0
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    gdpr_erased_at: str | None = None


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user_id: str
