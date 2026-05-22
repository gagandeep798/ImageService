"""Migration 0003 — Add UserImagesIndex and StatusIndex GSIs to the images table.

``UserImagesIndex``: PK = USER#<user_id>, SK = <created_at>#<image_id>
  Enables time-sorted per-user image listing.

``StatusIndex``: PK = STATUS#<status>#<shard>, SK = <created_at>#<image_id>
  Enables global listing by status using a scatter-gather across all shards.

Both GSIs are added in a single ``UpdateTable`` call.  The migration is idempotent
— it skips GSIs that already exist.
"""
MIGRATION_NUMBER = 3
MIGRATION_NAME = "add_gsi_indexes"


def up(dynamo: object, images_table_name: str) -> None:
    """Add missing GSIs to the images table (idempotent — skips already-existing indexes)."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    desc = client.describe_table(TableName=images_table_name)
    existing_gsis = {g["IndexName"] for g in desc["Table"].get("GlobalSecondaryIndexes", [])}

    updates = []
    attr_defs = []

    if "UserImagesIndex" not in existing_gsis:
        updates.append({
            "Create": {
                "IndexName": "UserImagesIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        })
        attr_defs += [
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ]

    if "StatusIndex" not in existing_gsis:
        updates.append({
            "Create": {
                "IndexName": "StatusIndex",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }
        })
        attr_defs += [
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ]

    if not updates:
        return

    client.update_table(
        TableName=images_table_name,
        AttributeDefinitions=attr_defs,
        GlobalSecondaryIndexUpdates=updates,
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=images_table_name)


def down(dynamo: object, images_table_name: str) -> None:
    """Remove both GSIs from the images table."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    for index_name in ("UserImagesIndex", "StatusIndex"):
        try:
            client.update_table(
                TableName=images_table_name,
                GlobalSecondaryIndexUpdates=[{"Delete": {"IndexName": index_name}}],
            )
        except Exception:
            pass
