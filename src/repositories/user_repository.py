"""Data access layer for the users DynamoDB table.

Handles all user CRUD operations, Argon2id PII hashing for email addresses,
and atomic storage-quota enforcement via DynamoDB conditional expressions.

Three-tier DynamoDB access:
- ``get_read_resource``   — ``get_user`` (GetItem)
- ``get_write_resource``  — ``create_user``, ``check_and_reserve_quota``,
                            ``release_quota``, ``finalize_quota``
- ``get_delete_resource`` — ``soft_delete_user`` (UpdateItem scoped to
                            status / deleted_at / gdpr_erased_at / ttl only)

PII contract:
  - Plaintext email is **never written to DynamoDB**.
  - Only ``email_hash`` (Argon2id output) and ``email_salt`` are stored.
  - Lookups by email re-hash the candidate with the stored salt + server-side pepper,
    then compare using ``hmac.compare_digest`` to prevent timing attacks.
"""
from __future__ import annotations

import base64
import secrets
from datetime import datetime, timezone
from typing import Optional

from argon2 import low_level as argon2_ll
from boto3.resources.base import ServiceResource

from src.common.config import Settings
from src.common.dynamo import get_delete_resource, get_read_resource, get_write_resource, monitor
from src.common.exceptions import NotFoundError, QuotaExceededError
from src.common.models import UserRecord


def _now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _ttl_90_days() -> int:
    """Return a Unix epoch 90 days from now, used for DynamoDB TTL on GDPR-erased items."""
    return int(datetime.now(timezone.utc).timestamp()) + 90 * 86400


# ── PII Hashing ──────────────────────────────────────────────────────────────

def hash_email(email: str, pepper: str) -> tuple[str, str]:
    """Hash an email address using Argon2id with a fresh random salt and the server-side pepper.

    Args:
        email: Plaintext email address (will be lowercased and stripped).
        pepper: Server-side secret from Secrets Manager — prepended before hashing
                so a database dump alone is insufficient to crack the hashes.

    Returns:
        A tuple of ``(hash_b64, salt_b64)`` — both are base64-encoded strings
        safe to store in DynamoDB.  A new salt is generated on every call so
        two calls for the same email produce different hashes.
    """
    salt = secrets.token_bytes(32)
    value = pepper.encode() + email.lower().strip().encode()
    hash_bytes = argon2_ll.hash_secret_raw(
        secret=value,
        salt=salt,
        time_cost=2,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        type=argon2_ll.Type.ID,
    )
    return base64.b64encode(hash_bytes).decode(), base64.b64encode(salt).decode()


def verify_email(email: str, pepper: str, stored_hash: str, stored_salt: str) -> bool:
    """Verify a plaintext email against a stored Argon2id hash using the same salt and pepper.

    Uses ``hmac.compare_digest`` to prevent timing-based enumeration attacks.
    """
    import hmac
    salt = base64.b64decode(stored_salt)
    value = pepper.encode() + email.lower().strip().encode()
    new_hash_bytes = argon2_ll.hash_secret_raw(
        secret=value, salt=salt,
        time_cost=2, memory_cost=65536, parallelism=2,
        hash_len=32, type=argon2_ll.Type.ID,
    )
    return hmac.compare_digest(
        base64.b64encode(new_hash_bytes).decode(), stored_hash
    )


# ── Repository ───────────────────────────────────────────────────────────────

def _table(resource: ServiceResource, settings: Settings):  # type: ignore[return]
    """Return the boto3 Table object for the users table."""
    return resource.Table(settings.users_table_name)


def create_user(settings: Settings, user_id: str, display_name: str, email: str) -> UserRecord:
    """Create a new user record, hashing the email before writing to DynamoDB.

    Uses a conditional PutItem to prevent overwriting an existing user with the same ID.
    """
    resource = get_write_resource(settings)
    table = _table(resource, settings)
    email_hash, email_salt = hash_email(email, settings.pii_pepper)
    now = _now()

    item = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "user_id": user_id,
        "display_name": display_name,
        "email_hash": email_hash,
        "email_salt": email_salt,
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
    """Fetch a user profile by ID.

    Raises:
        NotFoundError: if the user does not exist or has been soft-deleted.
    """
    resource = get_read_resource(settings)
    table = _table(resource, settings)

    with monitor("users.get"):
        resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})

    item = resp.get("Item")
    if not item or item.get("status") == "DELETED":
        raise NotFoundError(f"User {user_id} not found")

    return _to_record(item)


def check_and_reserve_quota(settings: Settings, user_id: str, size_bytes: int) -> None:
    """Atomically reserve ``size_bytes`` against the user's storage quota.

    Uses a DynamoDB conditional UpdateItem so the increment only succeeds when
    ``storage_used_bytes + size_bytes <= storage_quota_bytes``.  This is
    race-condition safe even under concurrent uploads.

    Raises:
        QuotaExceededError: if adding the bytes would exceed the quota.
    """
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
    """Decrement ``storage_used_bytes`` and ``image_count`` when an upload is aborted or deleted."""
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
    """Increment ``image_count`` after a successful upload completes the scan pipeline."""
    resource = get_write_resource(settings)
    table = _table(resource, settings)

    with monitor("users.finalize_quota"):
        table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression="SET image_count = image_count + :one, updated_at = :now",
            ExpressionAttributeValues={":one": 1, ":now": _now()},
        )


def soft_delete_user(settings: Settings, user_id: str, gdpr: bool = False) -> None:
    """Mark a user as DELETED using the delete-tier DynamoDB resource.

    Uses ``get_delete_resource`` — an IAM role whose ``UpdateItem`` policy is
    restricted to setting ``status``, ``deleted_at``, ``gdpr_erased_at``, and
    ``ttl`` only.  No other user attributes can be modified through this resource.

    Args:
        settings: Application settings (provides the delete role ARN).
        user_id:  The user to soft-delete.
        gdpr:     When ``True``, also sets ``gdpr_erased_at`` and extends the
                  TTL to 90 days (from the standard immediate-removal TTL).
    """
    resource = get_delete_resource(settings)
    table = _table(resource, settings)
    now = _now()
    ttl = _ttl_90_days() if gdpr else int(datetime.now(timezone.utc).timestamp()) + 7 * 86400

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
    """Convert a raw DynamoDB item dict into a typed ``UserRecord``, dropping internal keys."""
    fields = {k: v for k, v in item.items() if k in UserRecord.model_fields}
    return UserRecord(**fields)
