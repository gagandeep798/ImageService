"""Data access layer for the users DynamoDB table."""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from boto3.resources.base import ServiceResource

from src.common.config import Settings
from src.common.dynamo import get_delete_resource, get_read_resource, get_write_resource, monitor
from src.common.exceptions import NotFoundError, QuotaExceededError
from src.common.models import UserRecord

_ph = PasswordHasher()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ttl_90_days() -> int:
    return int(datetime.now(UTC).timestamp()) + 90 * 86400


def _email_index_key(email: str, pepper: str) -> str:
    """Deterministic HMAC-SHA256 of the canonical email — safe to use as a GSI key."""
    mac = _hmac.new(pepper.encode(), email.lower().strip().encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _ph.verify(stored_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ── Repository ───────────────────────────────────────────────────────────────

def _table(resource: ServiceResource, settings: Settings):  # type: ignore[return]
    return resource.Table(settings.users_table_name)


def create_user(settings: Settings, user_id: str, display_name: str, email: str, password: str) -> UserRecord:
    """Create a new user record. Raises ConditionalCheckFailedException if user_id already exists."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)
    email_hash = _email_index_key(email, settings.pii_pepper)
    password_hash = hash_password(password)
    now = _now()

    item = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "user_id": user_id,
        "display_name": display_name,
        "email_hash": email_hash,
        "password_hash": password_hash,
        "EmailHashIndex_PK": f"EMAILHASH#{email_hash}",
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


def get_user_by_email(settings: Settings, email: str) -> UserRecord:
    """Look up a user by email using the EmailHashIndex GSI. Raises NotFoundError if missing."""
    resource = get_read_resource(settings)
    table = _table(resource, settings)
    lookup_key = f"EMAILHASH#{_email_index_key(email, settings.pii_pepper)}"

    with monitor("users.get_by_email"):
        resp = table.query(
            IndexName="EmailHashIndex",
            KeyConditionExpression="EmailHashIndex_PK = :pk",
            ExpressionAttributeValues={":pk": lookup_key},
            Limit=1,
        )

    items = resp.get("Items", [])
    if not items:
        raise NotFoundError("User not found")

    # GSI may be KEYS_ONLY — fetch the full item
    pk = items[0]["PK"]
    sk = items[0].get("SK", "PROFILE")
    with monitor("users.get_by_email_full"):
        full_resp = table.get_item(Key={"PK": pk, "SK": sk})

    item = full_resp.get("Item")
    if not item or item.get("status") == "DELETED":
        raise NotFoundError("User not found")

    return _to_record(item)


def check_and_reserve_quota(settings: Settings, user_id: str, size_bytes: int) -> None:
    """Atomically reserve storage bytes. Raises QuotaExceededError if quota would be exceeded."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    try:
        with monitor("users.quota_check"):
            table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
                UpdateExpression="SET storage_used_bytes = storage_used_bytes + :delta, updated_at = :now",
                ConditionExpression="storage_used_bytes + :delta <= storage_quota_bytes AND #s = :active",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":delta": size_bytes,
                    ":now": _now(),
                    ":active": "ACTIVE",
                },
            )
    except resource.meta.client.exceptions.ConditionalCheckFailedException as exc:
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
