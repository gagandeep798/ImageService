# Database Migrations

DynamoDB is schemaless but schema changes still need to be tracked and applied in a controlled order — new GSIs, TTL configuration, attribute backfills, and table creation all require coordination with deploys.

## How It Works

The migration runner (`migrations/runner.py`) maintains an `image-service-migrations` DynamoDB table that records which migrations have been applied and the SHA-256 checksum of each migration file. Modifying an already-applied migration file causes the runner to refuse to proceed.

Migration files live in `migrations/` and are named `NNNN_<description>.py`. They are applied in numeric order.

---

## Applying Migrations

```bash
# Local
make migrate-local

# Staging (run after sam deploy)
make migrate-staging

# Production (preview first)
make migrate-dry-run     # shows pending migrations without applying
python migrations/runner.py --env prod
```

In CI/CD, migrations run automatically after each `sam deploy` step.

---

## Writing a New Migration

**1. Create the file** with the next sequential number:

```bash
touch migrations/0006_add_new_index.py
```

**2. Implement `up()` and optionally `down()`**:

```python
"""Migration 0006 — Add MyNewIndex GSI to the images table."""
MIGRATION_NUMBER = 6
MIGRATION_NAME = "add_my_new_index"


def up(dynamo: object, images_table_name: str) -> None:
    """Add MyNewIndex if it does not already exist."""
    client = dynamo.meta.client  # type: ignore[union-attr]
    desc = client.describe_table(TableName=images_table_name)
    existing = {g["IndexName"] for g in desc["Table"].get("GlobalSecondaryIndexes", [])}

    if "MyNewIndex" in existing:
        return  # idempotent

    client.update_table(
        TableName=images_table_name,
        AttributeDefinitions=[
            {"AttributeName": "MyPK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexUpdates=[{
            "Create": {
                "IndexName": "MyNewIndex",
                "KeySchema": [{"AttributeName": "MyPK", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }
        }],
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=images_table_name)


def down(dynamo: object, images_table_name: str) -> None:
    """Remove MyNewIndex."""
    dynamo.meta.client.update_table(  # type: ignore[union-attr]
        TableName=images_table_name,
        GlobalSecondaryIndexUpdates=[{"Delete": {"IndexName": "MyNewIndex"}}],
    )
```

**3. Test locally**:

```bash
make migrate-local
```

**4. Verify the migration was recorded**:

```bash
aws --endpoint-url http://localhost:8080/api \
  dynamodb scan \
  --table-name image-service-migrations \
  --region us-east-1
```

---

## Writing a Backfill Migration

For migrations that populate a new attribute on existing items:

```python
def up(dynamo: object, images_table_name: str) -> None:
    """Backfill new_attr on all ACTIVE images (idempotent)."""
    table = dynamo.Table(images_table_name)  # type: ignore[union-attr]
    paginator = dynamo.meta.client.get_paginator("scan")  # type: ignore[union-attr]

    count = 0
    for page in paginator.paginate(
        TableName=images_table_name,
        FilterExpression="#s = :active AND attribute_not_exists(new_attr)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":active": "ACTIVE"},
    ):
        with table.batch_writer() as batch:
            for item in page.get("Items", []):
                item["new_attr"] = "default_value"
                batch.put_item(Item=item)
                count += 1

    print(f"  backfilled {count} items")
```

Keep backfill migrations **idempotent** — they must be safe to re-run. Use `attribute_not_exists` or conditional writes to skip already-migrated items.

---

## Rolling Back a Migration

```bash
python migrations/runner.py --env local --rollback 6
```

This calls `down()` on migration 6 and removes its record from the tracking table. Subsequent runs will re-apply it.

Rollback is only available for migrations that implement `down()`. If a migration has no `down()`, you must write a new forward migration to undo the change.

---

## Rules

- **Never modify a migration file after it has been applied** to any environment. The runner will detect the checksum mismatch and refuse to continue.
- **Always make migrations idempotent** — they may be re-run if a deploy is retried.
- **Run dry-run before applying to prod**: `make migrate-dry-run`
- **Migrations run before Lambda code receives traffic** — schema must support both old and new code during the deploy window (expand/contract pattern for breaking changes).

---

## Migration Tracking Table

`image-service-migrations-{env}`:

| PK | SK | Attributes |
|----|-----|-----------|
| `MIG#0001` | `RECORD` | `name`, `applied_at`, `checksum`, `applied_by` |
| `MIG#0002` | `RECORD` | … |
