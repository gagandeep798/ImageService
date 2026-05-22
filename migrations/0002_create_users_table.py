"""Migration 0002 — Create the users DynamoDB table with the EmailHashIndex GSI.

The ``EmailHashIndex`` allows efficient lookup by hashed email for login flows
without exposing plaintext email as a DynamoDB key.  Streams are enabled so
that GDPR-erasure events can trigger downstream cleanup via DynamoDB Streams.
"""
import os

MIGRATION_NUMBER = 2
MIGRATION_NAME = "create_users_table"

USERS_TABLE = os.environ.get("USERS_TABLE_NAME", "image-service-users")


def up(dynamo: object, images_table_name: str) -> None:
    """Create the users table if it does not already exist."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    try:
        client.describe_table(TableName=USERS_TABLE)
        return
    except client.exceptions.ResourceNotFoundException:
        pass

    client.create_table(
        TableName=USERS_TABLE,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "EmailHashIndex_PK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[{
            "IndexName": "EmailHashIndex",
            "KeySchema": [{"AttributeName": "EmailHashIndex_PK", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "KEYS_ONLY"},
        }],
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"},
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=USERS_TABLE)


def down(dynamo: object, images_table_name: str) -> None:
    """Drop the users table (destructive — only for dev/test teardown)."""
    dynamo.meta.client.delete_table(TableName=USERS_TABLE)  # type: ignore[union-attr]
