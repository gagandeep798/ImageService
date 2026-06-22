#!/usr/bin/env python3
"""Seed local DynamoDB with test users and placeholder image records.

Creates 3 users and 2 ACTIVE image records per user so that list/get endpoints
return meaningful data without going through a full upload flow.  Intended for
local development only — never run against staging or production.

Usage::

    python scripts/seed_data.py
"""
import os
import boto3
from ulid import ULID
from datetime import datetime, timezone

ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:8080/api")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
IMAGES_TABLE = os.environ.get("IMAGES_TABLE_NAME", "image-service-images")
USERS_TABLE = os.environ.get("USERS_TABLE_NAME", "image-service-users")

dynamo = boto3.resource(
    "dynamodb",
    endpoint_url=ENDPOINT,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

def seed_users() -> list[str]:
    """Write 3 test user records and return their generated user IDs."""
    table = dynamo.Table(USERS_TABLE)
    user_ids = [f"usr_{ULID()}" for _ in range(3)]
    now = datetime.now(timezone.utc).isoformat()
    for uid in user_ids:
        table.put_item(Item={
            "PK": f"USER#{uid}",
            "SK": "PROFILE",
            "user_id": uid,
            "display_name": f"Test User {uid[-4:]}",
            "email_hash": "seeded_placeholder",
            "email_salt": "seeded_placeholder",
            "EmailHashIndex_PK": f"EMAILHASH#seeded_{uid}",
            "status": "ACTIVE",
            "storage_used_bytes": 0,
            "storage_quota_bytes": 10 * 1024 * 1024 * 1024,
            "image_count": 0,
            "created_at": now,
            "updated_at": now,
        })
    print(f"Seeded {len(user_ids)} users: {user_ids}")
    return user_ids

def seed_images(user_ids: list[str]) -> None:
    """Write 2 ACTIVE placeholder image records per user."""
    table = dynamo.Table(IMAGES_TABLE)
    now = datetime.now(timezone.utc).isoformat()
    for uid in user_ids:
        for i in range(2):
            img_id = f"img_{ULID()}"
            table.put_item(Item={
                "PK": f"IMG#{img_id}",
                "SK": f"META#{img_id}",
                "image_id": img_id,
                "user_id": uid,
                "title": f"Sample Image {i+1}",
                "description": "Seeded for local dev",
                "tags": {"nature", "sample"},
                "status": "ACTIVE",
                "s3_key": f"originals/{uid}/2026/05/{img_id}/sample.jpg",
                "size_bytes": 1024 * 512,
                "content_type": "image/jpeg",
                "width": 1920,
                "height": 1080,
                "GSI1PK": f"USER#{uid}",
                "GSI1SK": f"{now}#{img_id}",
                "GSI2PK": f"STATUS#ACTIVE#0",
                "GSI2SK": f"{now}#{img_id}",
                "created_at": now,
                "updated_at": now,
            })
    print(f"Seeded 2 images per user ({len(user_ids)*2} total)")

if __name__ == "__main__":
    user_ids = seed_users()
    seed_images(user_ids)
    print("Seed complete.")
