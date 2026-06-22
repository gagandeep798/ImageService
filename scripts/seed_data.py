#!/usr/bin/env python3
"""Seed local DynamoDB with test users."""
import os
import boto3
from ulid import ULID
from datetime import datetime, timezone

ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:8080/api")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
USERS_TABLE = os.environ.get("USERS_TABLE_NAME", "image-service-users")

dynamo = boto3.resource("dynamodb", endpoint_url=ENDPOINT, region_name=REGION,
                        aws_access_key_id="test", aws_secret_access_key="test")

def seed_users() -> list[str]:
    """Write 3 test user records and return their generated user IDs."""
    table = dynamo.Table(USERS_TABLE)
    user_ids = [f"usr_{ULID()}" for _ in range(3)]
    now = datetime.now(timezone.utc).isoformat()
    for uid in user_ids:
        table.put_item(Item={
            "PK": f"USER#{uid}", "SK": "PROFILE",
            "user_id": uid, "display_name": f"Test User {uid[-4:]}",
            "email_hash": "seeded_placeholder", "email_salt": "seeded_placeholder",
            "EmailHashIndex_PK": f"EMAILHASH#seeded_{uid}",
            "status": "ACTIVE", "storage_used_bytes": 0,
            "storage_quota_bytes": 10 * 1024 * 1024 * 1024,
            "image_count": 0, "created_at": now, "updated_at": now,
        })
    print(f"Seeded {len(user_ids)} users")
    return user_ids

if __name__ == "__main__":
    seed_users()
