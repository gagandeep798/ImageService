# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
make install          # install Python deps (Poetry)
cp docker/.env.sample docker/.env   # required before first run
cp .env.template .env               # fill in credentials and local overrides

# Local stack
make localstack-up    # build image + start LocalStack (blocks until healthy + init scripts run)
make localstack-down  # stop and remove volumes

# SAM local API (after localstack-up)
make start-api        # SAM on http://localhost:3000 — pass ?_dev_user_id=<uid> instead of JWT

# Tests
make test-unit        # moto-mocked, no Docker needed, ≥80% coverage required
make test-integration # requires localstack-up; hits real LocalStack
poetry run pytest tests/unit/test_upload_initiate.py -v   # single test file

# Code quality
make lint             # ruff check
make format           # ruff format
make typecheck        # mypy (strict)

# Logs (LocalStack CloudWatch via awslocal)
make logs-list                          # list all Lambda log groups
make logs-tail FUNCTION=upload-initiate # tail last 5 min of a function

# Migrations
make migrate-local    # apply pending migrations to LocalStack
make migrate-staging  # apply to staging
make migrate-dry-run  # dry-run against prod

# Deploy
make deploy-staging   # sam build + deploy + migrate
make deploy-prod      # same + 3s abort window
```

## Architecture

### Request flow

```
Client → API Gateway (Cognito JWT authorizer) → Lambda → DynamoDB / S3
                                                       → SQS → finalize → scan → thumbnails
CloudFront ← S3 originals (OAC)
```

All Lambda functions share the same `src/` package. Each handler in `src/handlers/` corresponds to one Lambda function defined in `template.yaml`.

### Chunked multipart upload (4-step flow)

1. **POST /images** (`upload_initiate`) — validates request, reserves quota in users table, creates S3 multipart session, writes `PENDING` record to DynamoDB, returns `{image_id, upload_id, s3_key, chunk_size_bytes}`.
2. **POST /images/{id}/parts** (`upload_part`) — returns a presigned S3 URL for each chunk. Client uploads directly to S3.
3. **POST /images/{id}/complete** (`upload_complete`) — completes S3 multipart, moves status to `PENDING_FINALIZE`, enqueues to `FinalizeQueue`.
4. **DELETE /images/{id}/upload** (`upload_abort`) — aborts the S3 multipart and marks `ABORTED`.

SQS then drives async processing: `FinalizeQueue` → `finalize_upload` (status → `SCANNING`) → `ScanQueue` → `scan_complete` (status → `ACTIVE` or `QUARANTINE`) → `ThumbnailQueue` → `generate_thumbnails`.

**Image status lifecycle:** `PENDING` → `PENDING_FINALIZE` → `SCANNING` → `ACTIVE | QUARANTINE | ABORTED | DELETED`

### Settings / configuration

`src/common/config.py` — `get_settings()` is `@lru_cache`-wrapped. It calls Secrets Manager once per cold start and returns a frozen `Settings` dataclass. All handlers call `get_settings()` rather than reading `os.environ` directly. Local fallbacks use env vars from `.env.local`.

### DynamoDB access tiers

`src/common/dynamo.py` — three module-level singleton resources, each assuming a separate IAM role via STS:

- `get_read_resource` — `GetItem`, `Query`, `Scan` only
- `get_write_resource` — `PutItem`, `UpdateItem` (non-delete attributes)
- `get_delete_resource` — `UpdateItem` restricted to soft-delete fields only

In local dev (LocalStack), role ARNs are empty so the Lambda execution role is used directly.

### DynamoDB key design

Images table:
- Primary: `PK = IMG#<image_id>`, `SK = META#<image_id>`
- `UserImagesIndex` GSI — `GSI1PK = USER#<user_id>`, `GSI1SK = <created_at>` — time-sorted per-user listing
- `StatusIndex` GSI — write-sharded to prevent hot partitions: `gsi2_pk()` in `dynamo.py` hashes the image ULID to a shard bucket; `gsi2_pk_all_shards()` scatter-gathers across all shards for global admin listings

Deletion is always soft: status → `DELETED`, TTL set to 7 days.

### Response envelope

Every handler returns via `src/common/response.py`. All responses follow:
```json
{"data": <payload|null>, "error": <null|{code,message}>, "meta": {"request_id": "...", "timestamp": "..."}}
```
Use `resp.ok()`, `resp.created()`, `resp.accepted()`, `resp.redirect()`, or `resp.error()` — never build the dict manually.

### Auth

`src/common/middleware.py` — `get_caller_user_id(event)` extracts `sub` from the Cognito JWT claims in `event.requestContext.authorizer.jwt.claims`. When running `sam local`, pass `?_dev_user_id=<uid>` as a query parameter to bypass Cognito.

### Local stack internals

`docker/docker-compose.yml` runs a single LocalStack container on port 4566. Init scripts in `scripts/init/` are volume-mounted at runtime (no image rebuild needed when scripts change):

- `init.sh` — orchestrator, calls the others in order
- `vpc.sh` — VPC, subnets, service-level security groups
- `s3.sh`, `dynamodb.sh`, `sqs.sh`, `secrets.sh`, `cognito.sh`, `migrations.sh`

To add a new AWS resource to the local environment, edit the relevant script in `scripts/init/` and run `make localstack-down && make localstack-up`.

### Testing conventions

Unit tests (`tests/unit/`) use `moto` with `@mock_aws` — no Docker, no LocalStack. All test configuration is in `TEST_SETTINGS` in `tests/conftest.py`; never hardcode resource names in test files.

Integration tests (`tests/integration/`) hit real LocalStack. The `integration_settings` fixture in `tests/integration/conftest.py` builds a `Settings` instance pointing at `http://localhost:4566`.

### Migrations

`migrations/runner.py` applies numbered migration scripts (`0001_*.py`, `0002_*.py`, …) tracked in the `image-service-migrations` DynamoDB table. Each migration is idempotent and records its hash to detect tampering.
