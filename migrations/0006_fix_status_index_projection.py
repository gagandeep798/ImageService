"""Migration 0006 — Fix StatusIndex projection from KEYS_ONLY/INCLUDE to ALL.

Earlier environments may have StatusIndex created with KEYS_ONLY (migration 0003)
or INCLUDE (old template.yaml).  The ``list_global`` scatter-gather calls
``_to_record`` on items projected from this index, which requires ALL attributes.
This migration deletes and recreates the index with ALL projection if needed.

Idempotent: no-op if StatusIndex already has ProjectionType ALL.
"""
import time

MIGRATION_NUMBER = 6
MIGRATION_NAME = "fix_status_index_projection"

_INDEX_NAME = "StatusIndex"


def _describe_status_index(client, table_name: str) -> dict | None:
    desc = client.describe_table(TableName=table_name)
    for gsi in desc["Table"].get("GlobalSecondaryIndexes", []):
        if gsi["IndexName"] == _INDEX_NAME:
            return gsi
    return None


def _wait_for_gsi_gone(client, table_name: str) -> None:
    for _ in range(120):
        desc = client.describe_table(TableName=table_name)
        names = {g["IndexName"] for g in desc["Table"].get("GlobalSecondaryIndexes", [])}
        if _INDEX_NAME not in names:
            return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {_INDEX_NAME} deletion")


def _wait_for_gsi_active(client, table_name: str) -> None:
    for _ in range(120):
        gsi = _describe_status_index(client, table_name)
        if gsi and gsi.get("IndexStatus") == "ACTIVE":
            return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {_INDEX_NAME} to become ACTIVE")


def up(dynamo: object, images_table_name: str) -> None:
    """Recreate StatusIndex with ALL projection if current projection is not ALL."""
    client = dynamo.meta.client  # type: ignore[union-attr]

    gsi = _describe_status_index(client, images_table_name)
    if gsi is None:
        # Index doesn't exist — migration 0003 will create it correctly on fresh envs.
        return
    if gsi["Projection"]["ProjectionType"] == "ALL":
        return  # Already correct — nothing to do.

    # Delete the existing index.
    client.update_table(
        TableName=images_table_name,
        GlobalSecondaryIndexUpdates=[{"Delete": {"IndexName": _INDEX_NAME}}],
    )
    _wait_for_gsi_gone(client, images_table_name)

    # Recreate with ALL projection.
    client.update_table(
        TableName=images_table_name,
        AttributeDefinitions=[
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexUpdates=[
            {
                "Create": {
                    "IndexName": _INDEX_NAME,
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            }
        ],
    )
    _wait_for_gsi_active(client, images_table_name)


def down(dynamo: object, images_table_name: str) -> None:
    """Revert StatusIndex to KEYS_ONLY projection."""
    client = dynamo.meta.client  # type: ignore[union-attr]

    gsi = _describe_status_index(client, images_table_name)
    if gsi is None or gsi["Projection"]["ProjectionType"] == "KEYS_ONLY":
        return

    client.update_table(
        TableName=images_table_name,
        GlobalSecondaryIndexUpdates=[{"Delete": {"IndexName": _INDEX_NAME}}],
    )
    _wait_for_gsi_gone(client, images_table_name)

    client.update_table(
        TableName=images_table_name,
        AttributeDefinitions=[
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexUpdates=[
            {
                "Create": {
                    "IndexName": _INDEX_NAME,
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            }
        ],
    )
    _wait_for_gsi_active(client, images_table_name)
