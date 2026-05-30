"""Data access layer for the images DynamoDB table.

Key design decisions:
- Primary key: ``PK = IMG#<image_id>``, ``SK = META#<image_id>``.
- ``UserImagesIndex`` GSI enables time-sorted per-user listing.
- ``StatusIndex`` GSI uses write-sharding via ``gsi2_pk()`` to distribute writes
  across ``shard_count`` logical partitions and prevent hot-partition throttling.
  Reads use a scatter-gather fan-out across all shards (see ``list_global``).
- Deletion is always soft: the record's ``status`` is set to ``DELETED`` and a
  ``ttl`` attribute triggers DynamoDB's TTL mechanism to remove the item after
  7 days, giving the asynchronous S3 cleanup Lambda time to fire first.

Three-tier DynamoDB access:
- ``get_read_resource``   — all read operations (GetItem, Query)
- ``get_write_resource``  — create and non-delete updates (PutItem, UpdateItem)
- ``get_delete_resource`` — soft-delete only (UpdateItem restricted to status/ttl fields)
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key
from boto3.resources.base import ServiceResource

from src.common.config import Settings
from src.common.dynamo import (
    get_delete_resource,
    get_read_resource,
    get_write_resource,
    gsi2_pk,
    gsi2_pk_all_shards,
    monitor,
)
from src.common.exceptions import NotFoundError
from src.common.models import ImageRecord, ImageResponse, ListImagesResponse


def _now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _ttl_7_days() -> int:
    """Return a Unix epoch 7 days from now for DynamoDB TTL on soft-deleted images."""
    return int(datetime.now(UTC).timestamp()) + 7 * 86400


def _table(resource: ServiceResource, settings: Settings):  # type: ignore[return]
    """Return the boto3 Table object for the images table."""
    return resource.Table(settings.images_table_name)


# ── Write Operations ──────────────────────────────────────────────────────────

def create_pending(
    settings: Settings,
    image_id: str,
    user_id: str,
    s3_key: str,
    upload_id: str,
    content_type: str,
    title: str | None,
    description: str | None,
    tags: list[str],
    filename: str | None = None,
) -> None:
    """Write a new image record in PENDING status after the multipart upload is initiated.

    All GSI projection attributes (GSI1PK, GSI1SK, GSI2PK, GSI2SK) are written
    here so the item is immediately visible in both indexes.
    """
    resource = get_write_resource(settings)
    table = _table(resource, settings)
    now = _now()

    item: dict = {
        "PK": f"IMG#{image_id}",
        "SK": f"META#{image_id}",
        "image_id": image_id,
        "user_id": user_id,
        "s3_key": s3_key,
        "upload_id": upload_id,
        "content_type": content_type,
        "status": "PENDING",
        "parts": {},
        "GSI1PK": f"USER#{user_id}",
        "GSI1SK": f"{now}#{image_id}",
        "GSI2PK": gsi2_pk("PENDING", image_id, settings.gsi2_shard_count),
        "GSI2SK": f"{now}#{image_id}",
        "created_at": now,
        "updated_at": now,
    }
    if filename:
        item["filename"] = filename
    if title:
        item["title"] = title
    if description:
        item["description"] = description
    if tags:
        item["tags"] = set(tags)

    with monitor("images.put_pending"):
        table.put_item(Item=item)


def record_part(settings: Settings, image_id: str, part_number: int, etag: str) -> None:
    """Persist a completed S3 part's ETag so interrupted uploads can resume.

    The ``parts`` map (``{part_number_str: etag}``) lets the client determine
    which parts still need to be uploaded without re-uploading successful ones.
    """
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    with monitor("images.record_part"):
        table.update_item(
            Key={"PK": f"IMG#{image_id}", "SK": f"META#{image_id}"},
            UpdateExpression="SET parts.#pn = :etag, updated_at = :now",
            ExpressionAttributeNames={"#pn": str(part_number)},
            ExpressionAttributeValues={":etag": etag, ":now": _now()},
        )


def set_status(settings: Settings, image_id: str, status: str, extra: dict | None = None) -> None:
    """Transition an image to a new status, updating the GSI2PK shard key accordingly.

    ``extra`` can contain additional attribute updates (e.g., ``size_bytes``,
    ``width``, ``height``) to merge into the same UpdateExpression.
    """
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    update_expr = "SET #s = :s, updated_at = :now, GSI2PK = :gsi2pk"
    attr_names = {"#s": "status"}
    attr_values: dict = {
        ":s": status,
        ":now": _now(),
        ":gsi2pk": gsi2_pk(status, image_id, settings.gsi2_shard_count),
    }

    if extra:
        for k, v in extra.items():
            update_expr += f", {k} = :{k}"
            attr_values[f":{k}"] = v

    with monitor("images.set_status"):
        table.update_item(
            Key={"PK": f"IMG#{image_id}", "SK": f"META#{image_id}"},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )


def soft_delete(settings: Settings, image_id: str) -> None:
    """Mark an image as DELETED using the delete-tier DynamoDB resource.

    Uses ``get_delete_resource`` — an IAM role scoped exclusively to
    ``UpdateItem`` with a condition that only allows setting ``status``,
    ``deleted_at``, ``ttl``, and ``GSI2PK``.  No other attributes can be
    modified through this resource, preventing accidental data mutation in
    delete-path code.

    The 7-day TTL gives the DynamoDB Streams cleanup Lambda time to remove
    the S3 object before the metadata record disappears.
    """
    resource = get_delete_resource(settings)
    table = _table(resource, settings)
    now = _now()
    ttl = _ttl_7_days()

    with monitor("images.soft_delete"):
        table.update_item(
            Key={"PK": f"IMG#{image_id}", "SK": f"META#{image_id}"},
            UpdateExpression=(
                "SET #s = :deleted, deleted_at = :now, #ttl = :ttl, GSI2PK = :gsi2pk"
            ),
            ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":deleted": "DELETED",
                ":now": now,
                ":ttl": ttl,
                ":gsi2pk": gsi2_pk("DELETED", image_id, settings.gsi2_shard_count),
            },
        )


def update_after_finalize(
    settings: Settings,
    image_id: str,
    size_bytes: int,
    width: int | None,
    height: int | None,
) -> None:
    """Transition to SCANNING and store the physical dimensions extracted by the finalize Lambda."""
    set_status(
        settings, image_id, "SCANNING",
        {"size_bytes": size_bytes, "width": width, "height": height},
    )


def update_thumbnail_keys(settings: Settings, image_id: str, thumbnail_keys: dict) -> None:
    """Store the S3 keys for generated thumbnail variants (128px, 400px, 1200px)."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    with monitor("images.update_thumbnails"):
        table.update_item(
            Key={"PK": f"IMG#{image_id}", "SK": f"META#{image_id}"},
            UpdateExpression="SET thumbnail_keys = :tk, updated_at = :now",
            ExpressionAttributeValues={":tk": thumbnail_keys, ":now": _now()},
        )


# ── Read Operations ───────────────────────────────────────────────────────────

def get_by_id(settings: Settings, image_id: str, consistent: bool = False) -> ImageRecord:
    """Fetch a single image record by its ID.

    Args:
        consistent: Pass ``True`` when the caller just wrote the record and needs
                    the latest version (e.g., immediately after upload completion).

    Raises:
        NotFoundError: if the image does not exist or has been soft-deleted.
    """
    resource = get_read_resource(settings)
    table = _table(resource, settings)

    with monitor("images.get"):
        resp = table.get_item(
            Key={"PK": f"IMG#{image_id}", "SK": f"META#{image_id}"},
            ConsistentRead=consistent,
        )

    item = resp.get("Item")
    if not item or item.get("status") == "DELETED":
        raise NotFoundError(f"Image {image_id} not found")

    return _to_record(item)


def list_by_user(
    settings: Settings,
    user_id: str,
    status_filter: str | None = "ACTIVE",
    tag_filter: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> ListImagesResponse:
    """List images owned by a specific user via the UserImagesIndex GSI.

    Results are returned newest-first (``ScanIndexForward=False``).  Tag
    filtering is applied as a DynamoDB ``FilterExpression`` after the index
    query — acceptable because tags are a secondary filter, not the primary
    access pattern.  The cursor is a base64-encoded ``LastEvaluatedKey``.
    """
    resource = get_read_resource(settings)
    table = _table(resource, settings)

    key_cond = Key("GSI1PK").eq(f"USER#{user_id}")
    filter_expr = None
    expr_attr_names = {}
    expr_attr_values = {}

    if status_filter:
        filter_expr = "#s = :status"
        expr_attr_names["#s"] = "status"
        expr_attr_values[":status"] = status_filter
    else:
        filter_expr = "#s <> :deleted AND #s <> :aborted"
        expr_attr_names["#s"] = "status"
        expr_attr_values[":deleted"] = "DELETED"
        expr_attr_values[":aborted"] = "ABORTED"

    if tag_filter:
        tag_clause = "contains(tags, :tag)"
        filter_expr = f"{filter_expr} AND {tag_clause}" if filter_expr else tag_clause
        expr_attr_values[":tag"] = tag_filter

    kwargs: dict = {
        "IndexName": "UserImagesIndex",
        "KeyConditionExpression": key_cond,
        "ScanIndexForward": False,
        "Limit": min(limit, 100),
    }
    if filter_expr:
        kwargs["FilterExpression"] = filter_expr
        if expr_attr_names:
            kwargs["ExpressionAttributeNames"] = expr_attr_names
        kwargs["ExpressionAttributeValues"] = expr_attr_values
    if cursor:
        kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor).decode())

    with monitor("images.list_user"):
        resp = table.query(**kwargs)

    items = [_to_response(settings, item) for item in resp.get("Items", [])]
    next_cursor = None
    if resp.get("LastEvaluatedKey"):
        next_cursor = base64.b64encode(json.dumps(resp["LastEvaluatedKey"]).encode()).decode()

    return ListImagesResponse(items=items, next_cursor=next_cursor, count=len(items))


def list_global(
    settings: Settings,
    status: str = "ACTIVE",
    tag_filter: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> ListImagesResponse:
    """List images globally using a scatter-gather across all StatusIndex shards.

    Fans out ``shard_count`` concurrent async queries (one per GSI2PK shard),
    merges the results by ``created_at`` descending, and returns the top
    ``limit`` items.  Global cursor support is omitted because merging per-shard
    cursors correctly requires additional state; callers should prefer per-user
    listing for paginated use-cases.
    """
    import asyncio
    return asyncio.run(_scatter_gather(settings, status, tag_filter, limit, cursor))


async def _scatter_gather(
    settings: Settings,
    status: str,
    tag_filter: str | None,
    limit: int,
    cursor: str | None,
) -> ListImagesResponse:
    """Async scatter step: fan out to all shards in parallel then merge results."""
    import asyncio

    shard_keys = gsi2_pk_all_shards(status, settings.gsi2_shard_count)
    tasks = [
        _query_shard(settings, shard_key, tag_filter, limit, cursor)
        for shard_key in shard_keys
    ]
    results = await asyncio.gather(*tasks)

    all_items = sorted(
        [item for shard_items in results for item in shard_items],
        key=lambda x: x.created_at,
        reverse=True,
    )[:limit]

    return ListImagesResponse(items=all_items, next_cursor=None, count=len(all_items))


async def _query_shard(
    settings: Settings,
    gsi2_pk_value: str,
    tag_filter: str | None,
    limit: int,
    cursor: str | None,
) -> list[ImageResponse]:
    """Query a single StatusIndex shard asynchronously using aioboto3."""
    import aioboto3

    kwargs_base: dict = {"region_name": settings.aws_region}
    if settings.dynamodb_endpoint_url:
        kwargs_base["endpoint_url"] = settings.dynamodb_endpoint_url

    session = aioboto3.Session()
    async with session.resource("dynamodb", **kwargs_base) as dynamo:
        table = await dynamo.Table(settings.images_table_name)
        kwargs: dict = {
            "IndexName": "StatusIndex",
            "KeyConditionExpression": Key("GSI2PK").eq(gsi2_pk_value),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if tag_filter:
            kwargs["FilterExpression"] = "contains(tags, :tag)"
            kwargs["ExpressionAttributeValues"] = {":tag": tag_filter}
        if cursor:
            kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor).decode())

        resp = await table.query(**kwargs)
        return [_to_response(settings, item) for item in resp.get("Items", [])]


def get_parts(settings: Settings, image_id: str) -> dict:
    """Return the ``parts`` map ``{part_number_str: etag}`` for upload resume support.

    The upload_part handler calls this when the client re-connects after a crash
    so it can skip parts that were already successfully uploaded to S3.
    """
    resource = get_read_resource(settings)
    table = _table(resource, settings)

    with monitor("images.get_parts"):
        resp = table.get_item(
            Key={"PK": f"IMG#{image_id}", "SK": f"META#{image_id}"},
            ProjectionExpression="parts, upload_id, #s",
            ExpressionAttributeNames={"#s": "status"},
        )

    item = resp.get("Item", {})
    return item.get("parts", {})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_record(item: dict) -> ImageRecord:
    """Convert a raw DynamoDB item dict into a typed ``ImageRecord``."""
    tags = list(item.get("tags", set()) or [])
    return ImageRecord(
        image_id=item["image_id"],
        user_id=item["user_id"],
        filename=item.get("filename"),
        title=item.get("title"),
        description=item.get("description"),
        tags=tags,
        status=item["status"],
        s3_key=item["s3_key"],
        upload_id=item.get("upload_id"),
        size_bytes=item.get("size_bytes"),
        content_type=item["content_type"],
        width=item.get("width"),
        height=item.get("height"),
        thumbnail_keys=dict(item.get("thumbnail_keys") or {}),
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        deleted_at=item.get("deleted_at"),
    )


def to_response(settings: Settings, record: ImageRecord) -> ImageResponse:
    """Convert an ImageRecord into a public ImageResponse, signing the thumbnail URL."""
    thumbnail_url = None
    if record.thumbnail_keys:
        thumb_key = (
            record.thumbnail_keys.get("400")
            or record.thumbnail_keys.get("128")
            or record.thumbnail_keys.get("1200")
            or next(iter(record.thumbnail_keys.values()), None)
        )
        if thumb_key:
            from src.common.s3 import get_s3_presign_client, generate_thumbnail_url
            s3_client = get_s3_presign_client(settings)
            thumbnail_url = generate_thumbnail_url(s3_client, settings, thumb_key)

    return ImageResponse(
        thumbnail_url=thumbnail_url,
        **record.model_dump(exclude={"s3_key", "upload_id", "deleted_at"})
    )


def _to_response(settings: Settings, item: dict) -> ImageResponse:
    """Convert a DynamoDB item into a public ``ImageResponse``, stripping internal fields."""
    record = _to_record(item)
    return to_response(settings, record)
