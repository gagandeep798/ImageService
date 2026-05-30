"""Migration 0004 — Enable DynamoDB TTL on the images and users tables.

The ``ttl`` attribute (Unix epoch integer) is set by soft-delete and GDPR-
erasure operations.  DynamoDB deletes items asynchronously after the epoch
passes, which triggers DynamoDB Streams events used by the S3 cleanup Lambda.
"""
MIGRATION_NUMBER = 4
MIGRATION_NAME = "enable_ttl"

USERS_TABLE = "image-service-users"


def up(dynamo: object, images_table_name: str) -> None:
    """Enable TTL on the ``ttl`` attribute for both tables (idempotent — skips if already enabled)."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    for table_name in (images_table_name, USERS_TABLE):
        desc = client.describe_time_to_live(TableName=table_name)
        status = desc["TimeToLiveDescription"]["TimeToLiveStatus"]
        if status not in ("ENABLED", "ENABLING"):
            client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
            )


def down(dynamo: object, images_table_name: str) -> None:
    """Disable TTL on both tables."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    for table_name in (images_table_name, USERS_TABLE):
        client.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={"Enabled": False, "AttributeName": "ttl"},
        )
