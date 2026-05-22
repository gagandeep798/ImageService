"""Migration 0001 — Create the images DynamoDB table with base key schema.

Creates the table only if it does not already exist (idempotent).  The init
script may have created it already; the migration records the fact that the
table is present so subsequent migrations can apply GSI changes on top.
"""
MIGRATION_NUMBER = 1
MIGRATION_NAME = "create_images_table"


def up(dynamo: object, images_table_name: str) -> None:
    """Create the images table if it does not already exist."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    try:
        client.describe_table(TableName=images_table_name)
        return  # already exists (e.g., created by init_localstack.sh)
    except client.exceptions.ResourceNotFoundException:
        pass

    client.create_table(
        TableName=images_table_name,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"},
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=images_table_name)


def down(dynamo: object, images_table_name: str) -> None:
    """Drop the images table (destructive — only for dev/test teardown)."""
    dynamo.meta.client.delete_table(TableName=images_table_name)  # type: ignore[union-attr]
