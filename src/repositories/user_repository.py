"""Data access layer for the users DynamoDB table."""
from __future__ import annotations

from datetime import UTC, datetime

from boto3.resources.base import ServiceResource

from src.common.config import Settings
from src.common.dynamo import get_delete_resource, get_read_resource, get_write_resource, monitor
from src.common.exceptions import NotFoundError, QuotaExceededError
from src.common.models import UserRecord


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ttl_90_days() -> int:
    return int(datetime.now(UTC).timestamp()) + 90 * 86400


def _table(resource: ServiceResource, settings: Settings):  # type: ignore[return]
    return resource.Table(settings.users_table_name)


def create_user(settings: Settings, user_id: str, display_name: str) -> UserRecord:
    """Create a new user profile record. Cognito owns credentials; this stores quota/metadata only."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)
    now = _now()

    item = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "user_id": user_id,
        "display_name": display_name,
        "status": "ACTIVE",
        "storage_used_bytes": 0,
        "storage_quota_bytes": 10 * 1024 * 1024 * 1024,
        "image_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    with monitor("users.put"):
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")

    return UserRecord(**{k: v for k, v in item.items() if k in UserRecord.model_fields})


def get_user(settings: Settings, user_id: str) -> UserRecord:
    """Fetch a user profile by ID. Raises NotFoundError if missing or deleted."""
    resource = get_read_resource(settings)
    table = _table(resource, settings)

    with monitor("users.get"):
        resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})

    item = resp.get("Item")
    if not item or item.get("status") == "DELETED":
        raise NotFoundError(f"User {user_id} not found")

    return _to_record(item)


def check_and_reserve_quota(settings: Settings, user_id: str, size_bytes: int) -> None:
    """Reserve storage bytes with optimistic locking. Raises QuotaExceededError if quota exceeded."""
    read_resource = get_read_resource(settings)
    write_resource = get_write_resource(settings)
    read_table = _table(read_resource, settings)
    write_table = _table(write_resource, settings)

    with monitor("users.quota_check"):
        resp = read_table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    item = resp.get("Item")
    if not item:
        raise NotFoundError(f"User {user_id} not found")
    if item.get("status") != "ACTIVE":
        raise QuotaExceededError("User account is not active")

    current = int(item.get("storage_used_bytes", 0))
    quota = int(item.get("storage_quota_bytes", 0))
    if current + size_bytes > quota:
        raise QuotaExceededError("Storage quota exceeded")

    try:
        with monitor("users.quota_reserve"):
            write_table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
                UpdateExpression="SET storage_used_bytes = :new_val, updated_at = :now",
                ConditionExpression="storage_used_bytes = :current AND #s = :active",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":new_val": current + size_bytes,
                    ":current": current,
                    ":now": _now(),
                    ":active": "ACTIVE",
                },
            )
    except write_resource.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise QuotaExceededError("Storage quota exceeded") from exc


def release_quota(settings: Settings, user_id: str, size_bytes: int) -> None:
    """Decrement storage_used_bytes and image_count when an upload is aborted or deleted."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    with monitor("users.release_quota"):
        table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression=(
                "SET storage_used_bytes = if_not_exists(storage_used_bytes, :zero) - :delta, "
                "image_count = if_not_exists(image_count, :zero) - :one, "
                "updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":delta": size_bytes,
                ":one": 1,
                ":zero": 0,
                ":now": _now(),
            },
        )


def finalize_quota(settings: Settings, user_id: str, size_bytes: int) -> None:
    """Increment image_count after a successful upload completes the scan pipeline."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    with monitor("users.finalize_quota"):
        table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression="SET image_count = image_count + :one, updated_at = :now",
            ExpressionAttributeValues={":one": 1, ":now": _now()},
        )


def soft_delete_user(settings: Settings, user_id: str, gdpr: bool = False) -> None:
    """Soft-delete a user via the delete-tier DynamoDB resource."""
    resource = get_delete_resource(settings)
    table = _table(resource, settings)
    now = _now()
    ttl = _ttl_90_days() if gdpr else int(datetime.now(UTC).timestamp()) + 7 * 86400

    update_expr = "SET #s = :deleted, deleted_at = :now, #ttl = :ttl, updated_at = :now"
    attr_values: dict = {
        ":deleted": "DELETED",
        ":now": now,
        ":ttl": ttl,
    }

    if gdpr:
        update_expr += ", gdpr_erased_at = :era"
        attr_values[":era"] = now

    with monitor("users.soft_delete"):
        table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
            ExpressionAttributeValues=attr_values,
        )


def _to_record(item: dict) -> UserRecord:
    fields = {k: v for k, v in item.items() if k in UserRecord.model_fields}
    return UserRecord(**fields)
