"""S3 client factory and low-level object/multipart helpers.

The module-level ``_s3_client`` singleton is created once per Lambda container.
All upload-path functions work with presigned URLs so binary data never flows
through Lambda (avoids the 6 MB API Gateway payload limit).

Download URLs are signed with CloudFront keys when a key-pair ID is configured;
otherwise they fall back to plain S3 presigned GET URLs for local development.
"""
import time
from datetime import UTC

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

from src.common.config import Settings

logger = Logger(service="image-service")
metrics = Metrics(namespace="ImageService")

_s3_client = None
_s3_presign_client = None


def get_s3_client(settings: Settings) -> boto3.client:
    """Return the module-level S3 boto3 client, creating it on the first call."""
    global _s3_client
    if _s3_client is None:
        kwargs: dict = {"region_name": settings.aws_region}
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


def get_s3_presign_client(settings: Settings) -> boto3.client:
    """Return an S3 client whose endpoint is browser-reachable, used only for presigned URLs.

    In local dev, Lambda reaches LocalStack at the internal Docker hostname but the
    browser needs localhost:4566. s3_presigned_endpoint_url holds the external address;
    in prod it is None and boto3 signs against the real AWS endpoint.
    """
    global _s3_presign_client
    if _s3_presign_client is None:
        kwargs: dict = {"region_name": settings.aws_region}
        endpoint = settings.s3_presigned_endpoint_url or settings.s3_endpoint_url
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        _s3_presign_client = boto3.client("s3", **kwargs)
    return _s3_presign_client


def create_multipart_upload(client: boto3.client, bucket: str, key: str, content_type: str) -> str:
    """Initiate an S3 multipart upload and return the UploadId."""
    resp = client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )
    return resp["UploadId"]


def _rewrite_presigned_host(url: str, presigned_endpoint: str) -> str:
    """Replace the scheme+host in a presigned URL with the client-accessible endpoint.

    Needed in local dev where Lambda generates URLs using the Docker-internal
    hostname (image-service-localstack:4566) but browsers hit localhost:4566.
    """
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    target = urlparse(presigned_endpoint)
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


def generate_upload_part_url(
    client: boto3.client,
    bucket: str,
    key: str,
    upload_id: str,
    part_number: int,
    ttl: int,
    presigned_endpoint_url: str | None = None,
) -> str:
    """Generate a presigned URL the client uses to PUT a single multipart chunk directly to S3.

    Records presign latency as a CloudWatch metric.
    """
    start = time.monotonic()
    try:
        url = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
            ExpiresIn=ttl,
        )
        if presigned_endpoint_url:
            url = _rewrite_presigned_host(url, presigned_endpoint_url)
        return url
    finally:
        ms = (time.monotonic() - start) * 1000
        metrics.add_metric(name="s3.presign_latency_ms", unit=MetricUnit.Milliseconds, value=ms)


def complete_multipart_upload(
    client: boto3.client,
    bucket: str,
    key: str,
    upload_id: str,
    parts: list[dict],
) -> None:
    """Tell S3 to assemble all uploaded parts into the final object."""
    client.complete_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": p["part_number"], "ETag": p["etag"]} for p in parts]},
    )


def abort_multipart_upload(client: boto3.client, bucket: str, key: str, upload_id: str) -> None:
    """Cancel an in-progress multipart upload and release its staged parts.

    Silently ignores errors because the upload may already have expired or been
    aborted by the S3 lifecycle rule that cleans up incomplete uploads after 7 days.
    """
    try:
        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
    except ClientError:
        pass


def generate_download_url(
    client: boto3.client,
    settings: Settings,
    s3_key: str,
) -> str:
    """
    Generate a download URL. In prod this is a CloudFront signed URL.
    In local dev (no CloudFront), falls back to a direct S3 presigned GET URL.
    """
    if settings.cloudfront_key_pair_id and settings.cloudfront_key_pair_id != "LOCAL_DEV":
        return _cloudfront_signed_url(settings, s3_key)
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.originals_bucket, "Key": s3_key},
        ExpiresIn=settings.download_url_ttl_seconds,
    )
    if settings.s3_presigned_endpoint_url:
        url = _rewrite_presigned_host(url, settings.s3_presigned_endpoint_url)
    return url


def _cloudfront_signed_url(settings: Settings, s3_key: str) -> str:
    """Build a CloudFront canned-policy signed URL using the RSA private key from Secrets Manager.

    CloudFront's signing protocol requires SHA-1 (AWS requirement, not a choice).
    The private key is loaded from ``settings.cloudfront_private_key_pem`` which
    was fetched from Secrets Manager at cold-start.
    """
    import base64
    import json

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    expire_time = int(time.time()) + settings.download_url_ttl_seconds
    resource_url = f"https://your-cloudfront-domain/{s3_key}"

    policy = json.dumps(
        {"Statement": [{"Resource": resource_url, "Condition": {"DateLessThan": {"AWS:EpochTime": expire_time}}}]},
        separators=(",", ":"),
    )

    private_key = serialization.load_pem_private_key(
        settings.cloudfront_private_key_pem.encode(), password=None
    )
    signature = private_key.sign(policy.encode(), padding.PKCS1v15(), hashes.SHA1())  # noqa: S303 CloudFront requires SHA1

    def _cf_b64(data: bytes) -> str:
        return base64.b64encode(data).decode().replace("+", "-").replace("=", "_").replace("/", "~")

    return (
        f"{resource_url}"
        f"?Policy={_cf_b64(policy.encode())}"
        f"&Signature={_cf_b64(signature)}"
        f"&Key-Pair-Id={settings.cloudfront_key_pair_id}"
    )


def sanitize_filename(filename: str) -> str:
    """Replace characters that are unsafe in S3 object keys with underscores, capped at 200 chars."""
    import re
    name = re.sub(r"[^\w.\-]", "_", filename)
    return name[:200]


def build_s3_key(user_id: str, image_id: str, filename: str) -> str:
    """Construct the canonical S3 object key for an original upload.

    Pattern: ``originals/{user_id}/{year}/{month:02d}/{image_id}/{sanitized_filename}``

    The year/month prefix enables targeted S3 lifecycle rules and inventory.
    """
    from datetime import datetime
    now = datetime.now(UTC)
    safe_name = sanitize_filename(filename)
    return f"originals/{user_id}/{now.year}/{now.month:02d}/{image_id}/{safe_name}"
