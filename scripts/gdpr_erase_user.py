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
import os
import sys
import boto3
from datetime import datetime, timezone

def get_dynamo(env: str) -> boto3.resource:
    """Build a DynamoDB boto3 resource for the target environment."""
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL") if env == "local" else None
    return boto3.resource(
        "dynamodb",
        endpoint_url=endpoint,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )

def erase_user(user_id: str, env: str) -> None:
    """Soft-delete all images and the user record, setting GDPR fields and DynamoDB TTL."""
    dynamo = get_dynamo(env)
    images_table = dynamo.Table(os.environ.get("IMAGES_TABLE_NAME", "image-service-images"))
    users_table = dynamo.Table(os.environ.get("USERS_TABLE_NAME", "image-service-users"))

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
