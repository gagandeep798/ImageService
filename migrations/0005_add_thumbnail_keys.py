"""Migration 0005 — Backfill the ``thumbnail_keys`` attribute on existing ACTIVE image records.

When the thumbnail generation feature was added, existing images did not have
this field.  This migration performs a paginated scan + batch-write to set
``thumbnail_keys = {}`` on any ACTIVE item that is missing the attribute.

The migration is idempotent: items that already have the attribute are skipped.
The ``down()`` is intentionally a no-op because the attribute is purely additive.
"""
MIGRATION_NUMBER = 5
MIGRATION_NAME = "add_thumbnail_keys"


def up(dynamo: object, images_table_name: str) -> None:
    """Backfill ``thumbnail_keys = {}`` on ACTIVE image records that lack the attribute."""
    table = dynamo.Table(images_table_name)  # type: ignore[union-attr]
    paginator = dynamo.meta.client.get_paginator("scan")  # type: ignore[union-attr]

    count = 0
    for page in paginator.paginate(
        TableName=images_table_name,
        FilterExpression="#s = :active AND attribute_not_exists(thumbnail_keys)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":active": "ACTIVE"},
    ):
        with table.batch_writer() as batch:
            for item in page.get("Items", []):
                item.setdefault("thumbnail_keys", {})
                batch.put_item(Item=item)
                count += 1

    print(f"  backfilled thumbnail_keys on {count} items")


def down(dynamo: object, images_table_name: str) -> None:
    """No-op — ``thumbnail_keys`` is an additive attribute with no destructive rollback."""
    pass
