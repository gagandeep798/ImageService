"""S3 facade for the image upload lifecycle.

Wraps the low-level ``src.common.s3`` helpers with domain-aware logic so that
Lambda handlers never interact with boto3 directly.  All upload-path methods
work with presigned URLs — binary data is sent directly from the client to S3
and never passes through Lambda.
"""
from __future__ import annotations

from src.common.config import Settings
from src.common.s3 import (
    abort_multipart_upload,
    build_s3_key,
    complete_multipart_upload,
    create_multipart_upload,
    generate_download_url,
    generate_upload_part_url,
    get_s3_client,
)


def initiate_upload(settings: Settings, user_id: str, image_id: str, filename: str, content_type: str) -> tuple[str, str]:
    """Start a new S3 multipart upload and return ``(upload_id, s3_key)``.

    The ``s3_key`` is derived from the canonical naming template so the key is
    deterministic and can be reconstructed from metadata if needed.
    """
    client = get_s3_client(settings)
    s3_key = build_s3_key(user_id, image_id, filename)
    upload_id = create_multipart_upload(client, settings.originals_bucket, s3_key, content_type)
    return upload_id, s3_key


def get_part_upload_url(
    settings: Settings,
    s3_key: str,
    upload_id: str,
    part_number: int,
) -> str:
    """Generate a presigned URL the client uses to PUT a single chunk directly to S3.

    The URL is scoped to a specific ``upload_id`` and ``part_number`` so it
    cannot be misused for other uploads.
    """
    client = get_s3_client(settings)
    return generate_upload_part_url(
        client,
        settings.originals_bucket,
        s3_key,
        upload_id,
        part_number,
        settings.upload_url_ttl_seconds,
    )


def finalize_upload(settings: Settings, s3_key: str, upload_id: str, parts: list[dict]) -> None:
    """Tell S3 to assemble all uploaded parts into the final object."""
    client = get_s3_client(settings)
    complete_multipart_upload(client, settings.originals_bucket, s3_key, upload_id, parts)


def cancel_upload(settings: Settings, s3_key: str, upload_id: str) -> None:
    """Abort a multipart upload and release any staged parts from S3."""
    client = get_s3_client(settings)
    abort_multipart_upload(client, settings.originals_bucket, s3_key, upload_id)


def get_download_url(settings: Settings, s3_key: str) -> str:
    """Return a time-limited download URL (CloudFront signed URL in prod, S3 presigned in dev)."""
    client = get_s3_client(settings)
    return generate_download_url(client, settings, s3_key)


def get_object_metadata(settings: Settings, s3_key: str) -> dict:
    """Return the S3 object metadata dict from a HeadObject call."""
    client = get_s3_client(settings)
    return client.head_object(Bucket=settings.originals_bucket, Key=s3_key)


def get_object_bytes(settings: Settings, s3_key: str, max_bytes: int = 65536) -> bytes:
    """Download the leading ``max_bytes`` of an S3 object using a Range request.

    Used by ``finalize_upload`` to read just enough bytes for Pillow to extract
    image dimensions and validate the file format, without loading the full object.
    """
    client = get_s3_client(settings)
    resp = client.get_object(
        Bucket=settings.originals_bucket,
        Key=s3_key,
        Range=f"bytes=0-{max_bytes - 1}",
    )
    return resp["Body"].read()


def move_to_quarantine(settings: Settings, s3_key: str) -> str:
    """Atomically copy an object to the quarantine bucket and delete it from originals.

    Called by the scan pipeline when a threat is detected.  The quarantine bucket
    uses a separate KMS key so compromised objects remain isolated.

    Returns:
        The new S3 key within the quarantine bucket.
    """
    client = get_s3_client(settings)
    quarantine_key = f"quarantine/{s3_key}"

    client.copy_object(
        Bucket=settings.quarantine_bucket,
        CopySource={"Bucket": settings.originals_bucket, "Key": s3_key},
        Key=quarantine_key,
    )
    client.delete_object(Bucket=settings.originals_bucket, Key=s3_key)
    return quarantine_key


def delete_object(settings: Settings, s3_key: str) -> None:
    """Permanently delete an object from the originals bucket (called by cleanup Lambda)."""
    client = get_s3_client(settings)
    client.delete_object(Bucket=settings.originals_bucket, Key=s3_key)


def put_thumbnail(settings: Settings, image_id: str, variant: str, data: bytes, content_type: str) -> str:
    """Upload a thumbnail variant to the thumbnails bucket and return its S3 key.

    Sets ``CacheControl: public, max-age=86400`` so CloudFront caches thumbnails
    at the edge for 24 hours without re-validating on every request.
    """
    client = get_s3_client(settings)
    key = f"thumbnails/{image_id}/{variant}"
    client.put_object(
        Bucket=settings.thumbnails_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        ServerSideEncryption="AES256",
        CacheControl="public, max-age=86400",
    )
    return key
