# ImageService

Production-grade image upload service — AWS Lambda + S3 + DynamoDB.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | `brew install python@3.12` |
| Poetry | 1.8+ | `pip install poetry` |
| Docker Desktop | 4.x | https://www.docker.com/products/docker-desktop |
| AWS SAM CLI | latest | `brew install aws-sam-cli` |
| AWS CLI | v2 | `brew install awscli` |

## Setup

```bash
make install                    # install Python dependencies
cp docker/.env.sample docker/.env  # Docker image versions + port mappings
cp .env.template .env           # fill in AWS credentials and local overrides
make setup                      # start LocalStack + init Cognito (first time only)
```

After `make setup`, copy the printed `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, and `COGNITO_ENDPOINT_URL` values into your `.env`.

## Local Development

```bash
make localstack-up    # rebuild images + start all services (blocks until healthy)
make localstack-start # start without rebuilding
make localstack-down  # stop and remove volumes

make build            # sam build --use-container
make start-api        # SAM local API on http://localhost:3000
                      # use ?_dev_user_id=<uid> query param instead of a JWT
```

| Local service | URL |
|---------------|-----|
| SAM API | `http://localhost:3000` |
| LocalStack (AWS) | `http://localhost:4566` |
| Cognito local | `http://localhost:9229` |

## Tests

```bash
make test-unit         # moto-mocked, no Docker required (≥80% coverage)
make test-integration  # hits real LocalStack — requires localstack-up
make test              # both
```

## Code Quality

```bash
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy (strict)
```

## Migrations

DynamoDB schema changes live in `migrations/` and are applied automatically before every deploy.

| Migration | Description |
|-----------|-------------|
| 0001 | Create images table |
| 0002 | Create users table with EmailHashIndex |
| 0003 | Add UserImagesIndex and StatusIndex GSIs |
| 0004 | Enable TTL on images and users tables |
| 0005 | Backfill thumbnail_keys on existing records |

```bash
make migrate-local    # apply to LocalStack
make migrate-staging  # apply to staging
make migrate-dry-run  # preview against prod (no changes)
```

## Deploy

### Dev

```bash
make deploy-dev
```

Runs: `sam build` → `sam deploy --config-env dev` → migrations.

### Staging

```bash
make deploy-staging
```

Runs: `sam build` → `sam deploy --config-env staging` → migrations → frontend sync to S3.

### Production

```bash
make deploy-prod
```

Runs: `sam build` → 3-second abort window → `sam deploy --config-env prod` → migrations → frontend sync to S3.

Frontend only (without full backend deploy):

```bash
make deploy-frontend-staging
make deploy-frontend-prod     # 3-second abort window
```

## Logs

```bash
make logs-list                            # list all Lambda log groups
make logs-tail FUNCTION=upload-initiate APP_ENV=staging  # tail last 5 min
```

## Architecture

```
Client → API Gateway (Cognito JWT authorizer) → Lambda → DynamoDB / S3
                                                       → SQS → finalize → scan → thumbnails
CloudFront ← S3 originals (OAC)
```

**Upload flow (4 steps):**
1. `POST /images` — validates request, reserves quota, creates S3 multipart session, returns `{image_id, upload_id, s3_key, chunk_size_bytes}`
2. `POST /images/{id}/parts` — returns presigned S3 URL per chunk; client uploads directly to S3
3. `POST /images/{id}/complete` — completes S3 multipart, enqueues to FinalizeQueue
4. `DELETE /images/{id}/upload` — aborts S3 multipart, marks `ABORTED`

**Async processing:** FinalizeQueue → `finalize_upload` → ScanQueue → `scan_complete` → ThumbnailQueue → `generate_thumbnails`

**Image status lifecycle:** `PENDING` → `PENDING_FINALIZE` → `SCANNING` → `ACTIVE | QUARANTINE | ABORTED | DELETED`

## Infrastructure

All AWS resources are defined in `template.yaml` (AWS SAM), parameterised by `Env` (dev/staging/prod).

**DynamoDB:** images table (UserImagesIndex + write-sharded StatusIndex GSIs), users, migrations, secret-hashes — all with PITR and TTL. Deletion is always soft: status → `DELETED`, TTL set to 7 days.

**S3:** originals (lifecycle: IA@30d, Glacier@180d), thumbnails, quarantine (SSE-KMS), logs.

**SQS:** FinalizeQueue, ScanQueue, ThumbnailQueue — all with DLQ redrive after 3 failures.

**IAM:** Three DynamoDB roles assumed via STS — read (GetItem/Query/Scan), write (PutItem/UpdateItem), delete (UpdateItem restricted to soft-delete fields only).

**Observability:** CloudWatch alarms + composite alarms, SNS alerts, CloudTrail with S3 data events, Athena workgroup with saved queries, X-Ray tracing.

## Configuration

Settings are loaded from AWS Secrets Manager at Lambda cold-start via `src/common/config.get_settings()` (`@lru_cache` — one call per cold start). Local dev falls back to env vars from `.env`.

All API responses use the envelope: `{"data": ..., "error": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.

## CI/CD

Every pull request runs: lint → typecheck → unit tests (≥80% coverage) → SAM build → integration tests.

Merging to `main` deploys automatically to staging. Production requires manual approval in GitHub.
