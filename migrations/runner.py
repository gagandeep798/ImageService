#!/usr/bin/env python3
"""DynamoDB migration runner.

Usage::

    python migrations/runner.py [--env local|staging|prod] [--dry-run] [--rollback <number>]

Must be run **before** ``sam deploy`` in CI/CD so that new Lambda code always
finds the schema it expects (new GSIs, TTL config, etc.).

Each migration file exposes:
  - ``MIGRATION_NUMBER``: 4-digit integer prefix matching the filename.
  - ``up(dynamo, images_table_name)``: applies the migration.
  - ``down(dynamo, images_table_name)`` *(optional)*: rolls it back.

Applied migrations are recorded in the ``image-service-migrations`` DynamoDB
table with a SHA-256 checksum of the migration file.  The runner refuses to
proceed if a previously applied migration's file has been modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.common.config import get_env, get_env_settings

MIGRATIONS_DIR = Path(__file__).parent
MIGRATION_TABLE = "image-service-migrations"


def _dynamo(env: str) -> Any:
    """Create a boto3 DynamoDB resource pointed at the correct endpoint for ``env``."""
    cfg = get_env_settings()
    kwargs: dict = {"region_name": cfg.aws_region}
    if env == "local" and cfg.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = cfg.dynamodb_endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def _ensure_migrations_table(dynamo: Any) -> Any:
    """Create the migrations tracking table if it does not already exist."""
    client = dynamo.meta.client
    try:
        client.describe_table(TableName=MIGRATION_TABLE)
    except client.exceptions.ResourceNotFoundException:
        print(f"Creating migrations table: {MIGRATION_TABLE}")
        client.create_table(
            TableName=MIGRATION_TABLE,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=MIGRATION_TABLE)
    return dynamo.Table(MIGRATION_TABLE)


def _load_migrations() -> list[tuple[int, str, Any]]:
    """Discover and import all ``NNNN_*.py`` migration modules, sorted by number."""
    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py")):
        num = int(path.stem[:4])
        mod_name = f"migrations.{path.stem}"
        mod = importlib.import_module(mod_name)
        migrations.append((num, path.stem, mod))
    return migrations


def _checksum(path: Path) -> str:
    """Compute the SHA-256 hex digest of a migration file for tamper detection."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _applied_set(table: Any) -> dict[int, str]:
    """Return a mapping of ``{migration_number: checksum}`` for all applied migrations."""
    resp = table.scan(FilterExpression="begins_with(PK, :prefix)", ExpressionAttributeValues={":prefix": "MIG#"})
    return {
        int(item["PK"].split("#")[1]): item.get("checksum", "")
        for item in resp.get("Items", [])
        if item.get("SK") == "RECORD"
    }


def run(env: str, dry_run: bool = False) -> None:
    """Apply all pending migrations to ``env``.

    Exits with a non-zero code if any migration fails or a checksum mismatch
    is detected.  In dry-run mode, migrations are listed but not applied.
    """
    dynamo = _dynamo(env)
    table = _ensure_migrations_table(dynamo)
    applied = _applied_set(table)
    migrations = _load_migrations()
    now = datetime.now(timezone.utc).isoformat()

    for num, name, mod in migrations:
        path = MIGRATIONS_DIR / f"{name}.py"
        checksum = _checksum(path)

        if num in applied:
            if applied[num] != checksum:
                print(f"ERROR: Migration {name} checksum mismatch — file was modified after application!")
                sys.exit(1)
            continue

        print(f"{'[DRY-RUN] ' if dry_run else ''}Applying migration {name}...")
        if not dry_run:
            try:
                mod.up(dynamo, get_env_settings().images_table_name)
            except Exception as exc:
                print(f"FAILED migration {name}: {exc}")
                sys.exit(1)

            table.put_item(Item={
                "PK": f"MIG#{num:04d}",
                "SK": "RECORD",
                "name": name,
                "applied_at": now,
                "checksum": checksum,
                "applied_by": get_env("GITHUB_ACTOR", get_env("USER", "unknown")),
            })
            print(f"  ✓ {name}")


def rollback(env: str, number: int) -> None:
    """Roll back a specific migration by calling its ``down()`` function."""
    dynamo = _dynamo(env)
    table = _ensure_migrations_table(dynamo)
    migrations = {num: (name, mod) for num, name, mod in _load_migrations()}

    if number not in migrations:
        print(f"Migration {number} not found")
        sys.exit(1)

    name, mod = migrations[number]
    if not hasattr(mod, "down"):
        print(f"Migration {name} has no down() method")
        sys.exit(1)

    print(f"Rolling back migration {name}...")
    mod.down(dynamo, get_env_settings().images_table_name)
    table.delete_item(Key={"PK": f"MIG#{number:04d}", "SK": "RECORD"})
    print(f"  ✓ rolled back {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="local", choices=["local", "staging", "prod"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", type=int, default=None)
    args = parser.parse_args()

    if args.rollback is not None:
        rollback(args.env, args.rollback)
    else:
        run(args.env, dry_run=args.dry_run)
