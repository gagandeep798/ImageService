"""Unit tests for user_repository — Argon2 hashing, quota management."""
from datetime import datetime, timezone

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.common.exceptions import NotFoundError, QuotaExceededError
from src.repositories import user_repository as user_repo

pytestmark = pytest.mark.unit


# ── PII hashing tests (no DynamoDB needed) ────────────────────────────────────

def test_hash_email_produces_different_hashes_per_call(mock_settings: Settings):
    h1, s1 = user_repo.hash_email("user@example.com", mock_settings.pii_pepper)
    h2, s2 = user_repo.hash_email("user@example.com", mock_settings.pii_pepper)
    assert h1 != h2  # different salts → different hashes
    assert s1 != s2


def test_verify_email_correct(mock_settings: Settings):
    email = "user@example.com"
    h, s = user_repo.hash_email(email, mock_settings.pii_pepper)
    assert user_repo.verify_email(email, mock_settings.pii_pepper, h, s) is True


def test_verify_email_wrong_email(mock_settings: Settings):
    h, s = user_repo.hash_email("user@example.com", mock_settings.pii_pepper)
    assert user_repo.verify_email("other@example.com", mock_settings.pii_pepper, h, s) is False


def test_verify_email_case_insensitive(mock_settings: Settings):
    h, s = user_repo.hash_email("User@Example.COM", mock_settings.pii_pepper)
    assert user_repo.verify_email("user@example.com", mock_settings.pii_pepper, h, s) is True


# ── DynamoDB tests ────────────────────────────────────────────────────────────

@mock_aws
def test_get_user_not_found(dynamodb_tables, mock_settings: Settings):
    with pytest.raises(NotFoundError):
        user_repo.get_user(mock_settings, "usr_nonexistent")


@mock_aws
def test_create_and_get_user(dynamodb_tables, mock_settings: Settings):
    user = user_repo.create_user(mock_settings, "usr_abc", "Alice", "alice@example.com")
    assert user.user_id == "usr_abc"
    assert user.display_name == "Alice"
    assert user.storage_used_bytes == 0

    fetched = user_repo.get_user(mock_settings, "usr_abc")
    assert fetched.user_id == "usr_abc"


@mock_aws
def test_quota_check_passes(dynamodb_tables, mock_settings: Settings):
    user_repo.create_user(mock_settings, "usr_quota", "Bob", "bob@example.com")
    user_repo.check_and_reserve_quota(mock_settings, "usr_quota", 1024)

    fetched = user_repo.get_user(mock_settings, "usr_quota")
    assert fetched.storage_used_bytes == 1024


@mock_aws
def test_quota_check_fails_when_exceeded(dynamodb_tables, mock_settings: Settings):
    # Write a user directly with a tiny quota via the DynamoDB resource
    table = dynamodb_tables.Table(mock_settings.users_table_name)
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(Item={
        "PK": "USER#usr_tight",
        "SK": "PROFILE",
        "user_id": "usr_tight",
        "display_name": "Tight",
        "email_hash": "x",
        "email_salt": "y",
        "EmailHashIndex_PK": "EMAILHASH#x",
        "status": "ACTIVE",
        "storage_used_bytes": 0,
        "storage_quota_bytes": 100,
        "image_count": 0,
        "created_at": now,
        "updated_at": now,
    })

    with pytest.raises(QuotaExceededError):
        user_repo.check_and_reserve_quota(mock_settings, "usr_tight", 200)


@mock_aws
def test_soft_delete_user_sets_status(dynamodb_tables, mock_settings: Settings):
    user_repo.create_user(mock_settings, "usr_del", "Del User", "del@example.com")
    user_repo.soft_delete_user(mock_settings, "usr_del", gdpr=False)

    table = dynamodb_tables.Table(mock_settings.users_table_name)
    item = table.get_item(Key={"PK": "USER#usr_del", "SK": "PROFILE"})["Item"]
    assert item["status"] == "DELETED"
    assert "deleted_at" in item
    assert "ttl" in item
    assert "gdpr_erased_at" not in item


@mock_aws
def test_soft_delete_user_gdpr_sets_erased_at(dynamodb_tables, mock_settings: Settings):
    user_repo.create_user(mock_settings, "usr_gdpr", "GDPR User", "gdpr@example.com")
    user_repo.soft_delete_user(mock_settings, "usr_gdpr", gdpr=True)

    table = dynamodb_tables.Table(mock_settings.users_table_name)
    item = table.get_item(Key={"PK": "USER#usr_gdpr", "SK": "PROFILE"})["Item"]
    assert item["status"] == "DELETED"
    assert "gdpr_erased_at" in item
    assert int(item["ttl"]) > 0
