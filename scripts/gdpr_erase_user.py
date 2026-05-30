#!/usr/bin/env python3
"""Operator CLI: cascade-delete all data for a user (GDPR right to erasure).

Use this script for out-of-band erasure requests that arrive outside the API
(e.g., email requests, legal notices).  For self-service erasure the user calls
``DELETE /users/{user_id}`` directly via the API.

Usage::

    python scripts/gdpr_erase_user.py --user-id usr_01HZ... [--env local|staging|prod]

The script prompts for confirmation before making any changes.
"""
import argparse
import sys
import boto3
from datetime import datetime, timezone

from src.common.config import get_env_settings

def get_dynamo(env: str) -> boto3.resource:
    """Build a DynamoDB boto3 resource for the target environment."""
    cfg = get_env_settings()
    endpoint = cfg.dynamodb_endpoint_url if env == "local" else None
    return boto3.resource(
        "dynamodb",
        endpoint_url=endpoint,
        region_name=cfg.aws_region,
    )

def erase_user(user_id: str, env: str) -> None:
    """Soft-delete all images and the user record, setting GDPR fields and DynamoDB TTL."""
    cfg = get_env_settings()
    dynamo = get_dynamo(env)
    images_table = dynamo.Table(cfg.images_table_name)
    users_table = dynamo.Table(cfg.users_table_name)

    now = datetime.now(timezone.utc).isoformat()
    ttl_epoch = int(datetime.now(timezone.utc).timestamp()) + 90 * 86400

    # Paginate all images for this user
    deleted_count = 0
    exclusive_start_key: dict | None = None
    while True:
        kwargs: dict = {
            "IndexName": "UserImagesIndex",
            "KeyConditionExpression": "GSI1PK = :pk",
            "ExpressionAttributeValues": {":pk": f"USER#{user_id}"},
        }
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key

        resp = images_table.query(**kwargs)
        for item in resp.get("Items", []):
            images_table.update_item(
                Key={"PK": item["PK"], "SK": item["SK"]},
                UpdateExpression="SET #s = :s, deleted_at = :da, #ttl = :ttl",
                ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":s": "DELETED",
                    ":da": now,
                    ":ttl": ttl_epoch,
                },
            )
            deleted_count += 1

        exclusive_start_key = resp.get("LastEvaluatedKey")
        if not exclusive_start_key:
            break

    # Mark user as erased
    users_table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        UpdateExpression="SET #s = :s, deleted_at = :da, gdpr_erased_at = :ea, #ttl = :ttl",
        ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
        ExpressionAttributeValues={
            ":s": "DELETED",
            ":da": now,
            ":ea": now,
            ":ttl": ttl_epoch,
        },
    )

    print(f"GDPR erasure complete: user_id={user_id}, images_deleted={deleted_count}, erased_at={now}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--env", default="local", choices=["local", "staging", "prod"])
    args = parser.parse_args()

    confirm = input(f"Permanently erase all data for {args.user_id} in {args.env}? [yes/N]: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        sys.exit(0)

    erase_user(args.user_id, args.env)
