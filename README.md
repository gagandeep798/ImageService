# ImageService

Production-grade image upload service — AWS Lambda + S3 + DynamoDB.

> See `.gitignore` for the full list of files that are never committed (secrets, Docker env, SAM artifacts).

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | `brew install python@3.12` |
| Poetry | 1.8+ | `pip install poetry` |
| Docker Desktop | 4.x | https://www.docker.com/products/docker-desktop |
| AWS SAM CLI | latest | `brew install aws-sam-cli` |
| AWS CLI | v2 | `brew install awscli` |

**Dev tooling:** ruff (lint), mypy (type check), pytest + moto (tests).

## Setup

```bash
# 1. Install dependencies
make install

# 2. Copy the local config template
cp .env.local.template .env.local
# Edit .env.local — AWS credentials are always "test" for LocalStack
```

**SAM deploy profiles** are configured in `samconfig.toml` for environments: `local`, `dev`, `staging`, `prod`.

## Quick Start

```bash
make install          # install Python dependencies
make localstack-up    # build custom images and start all services
make localstack-down  # stop all services and remove volumes
make dashboards-open  # open OpenSearch Dashboards in browser
```

## Project Layout

```
src/common/          Shared utilities — config, DynamoDB pool, S3, models, middleware
src/repositories/    Data access — image, user, storage
migrations/          DynamoDB schema migrations (applied before every deploy)
```

## Database Migrations

DynamoDB schema changes are tracked in `migrations/` and applied before every deploy.

| Migration | Description |
|-----------|-------------|
| 0001 | Create images table |
| 0002 | Create users table with EmailHashIndex |
| 0003 | Add UserImagesIndex and StatusIndex GSIs |
| 0004 | Enable TTL on images and users tables |
| 0005 | Backfill thumbnail_keys on existing records |

```bash
make migrate-local   # apply pending migrations to LocalStack
```

## Configuration

All settings are loaded from AWS Secrets Manager at Lambda cold-start via `src/common/config.get_settings()`.
No environment variables are read in application code — only in `config.py` as fallbacks for local development.
DynamoDB uses three separate IAM roles (read/write/delete) assumed via STS for least-privilege access.
Email addresses are stored only as Argon2id hashes — never plaintext.
All API responses follow the envelope: `{"data": ..., "error": ..., "meta": {request_id, timestamp}}`.

## Running Tests

```bash
make test-unit   # fast unit tests — no Docker required
```

Unit tests use `moto` to mock all AWS services in-process. Handler tests cover all 17 Lambda functions.
 `TEST_SETTINGS` (in `tests/conftest.py`) is the single source of truth for all test configuration — no hardcoded strings in test files.

> **Docker env:** copy `docker/.env.sample` → `docker/.env` before starting services.

## Local Services

| Service | Access via Nginx |
|---------|-----------------|
| LocalStack (AWS) | `http://localhost:8080/api/` |
| OpenSearch | `http://localhost:8080/opensearch/` |
| OpenSearch Dashboards | `http://localhost:8080/dashboards/` |
| Nginx (reverse proxy) | host-exposed on `NGINX_PORT` (default 8080) |

> **Nginx reverse proxy** — only Nginx exposes a host port. Upstream service ports are container-internal only. Security headers are applied to all responses. Custom error pages (no stack traces or version info) at `docker/nginx/error_pages/`. Upstream ports are injected via `envsubst` from `docker/nginx/templates/default.conf.template` at container start — all port values come from `docker/.env`.

ImageService is a production-grade, Instagram-style image upload backend built on AWS Lambda, S3, and DynamoDB. It supports chunked multipart uploads, an async processing pipeline (AV scan → thumbnails), paginated listing with write-sharded DynamoDB GSIs, GDPR erasure, and full observability via CloudWatch, X-Ray, and OpenSearch.

## Infrastructure

All AWS resources are defined in `template.yaml` (AWS SAM). Parameterised by `Env` (local/dev/staging/prod).
**DynamoDB tables:** images (with UserImagesIndex + StatusIndex GSIs), users, migrations, secret-hashes — all with PITR and TTL.
**S3 buckets:** originals (lifecycle: IA@30d, Glacier@180d, abort incomplete multipart@7d), thumbnails, quarantine (SSE-KMS), logs.
**SQS queues:** FinalizeQueue → FinalizeDLQ, ScanQueue → ScanDLQ, ThumbnailQueue — all with DLQ redrive after 3 failures.
**IAM roles:** DynamoDBReadRole (GetItem/Query/Scan), DynamoDBWriteRole (PutItem/UpdateItem), DynamoDBDeleteRole (UpdateItem restricted to soft-delete fields only).
**Upload Lambda functions:** UploadInitiate, UploadPart, UploadComplete, UploadAbort, FinalizeUpload (SQS, 1024MB, 60s).
**Processing Lambda functions:** ScanComplete, GenerateThumbnails (both SQS-triggered).
**API Lambda functions:** GetImage, ListImages, DeleteImage, Download, Health (unauthenticated), GdprDeleteUser (300s timeout).
**Operational Lambda functions:** LogShipper (Kinesis), SlackNotifier (SNS), ScaleLambda (EventBridge), BackupSecrets (daily cron).

## Architecture

```
Client → API Gateway (WAF + JWT Authorizer) → Lambda → DynamoDB / S3
                                                      → SQS → finalize → scan → thumbnails
CloudFront ← S3 originals (OAC)
Kinesis ← CloudWatch Logs → log_shipper Lambda → OpenSearch
```
**Observability:** CloudWatch alarms (per-service + composite), SNS alerts topic, CloudTrail with S3 data events, Athena workgroup with saved queries.

## Deploy

```bash
make deploy-staging   # sam deploy → migrate → smoke test
make deploy-prod      # same + manual GitHub approval gate
```

**Running locally:**
```bash
make build      # sam build --use-container
make start-api  # SAM local API on http://localhost:3000
```

## CI/CD

Every pull request runs a full CI pipeline before merging.
**CI pipeline:**
- Lint (ruff)
- Type check (mypy)
- Unit tests (≥80% coverage)
- SAM build
- Integration tests with LocalStack

Merging to `main` automatically deploys to staging; production requires manual approval in GitHub.
Deploy pipeline: staging → run migrations → smoke test /health → manual approval → prod.

## Operational Scripts

| Script | Purpose |
|--------|---------|
| `scripts/init_localstack.sh` | Creates all AWS resources inside LocalStack at startup |
| `scripts/fetch_secrets.sh` | Pulls Secrets Manager values → .env.secrets files |
| `scripts/seed_data.py` | Seeds local DynamoDB with test users and images |

```bash
make install          # install Python dependencies
make fetch-secrets    # pull secrets → .env.secrets + docker/.env.secrets
make localstack-up    # start all services
make seed             # seed test data
make start-api        # SAM local API on http://localhost:3000
```
| `scripts/gdpr_erase_user.py` | Operator CLI for out-of-band GDPR erasure |

make dashboards-open  # open OpenSearch Dashboards

## Documentation

### Services
| Doc | What it covers |
|-----|----------------|
| [Upload Service](docs/services/upload-service.md) | Chunked multipart upload flow, resume, abort |
| [Image Service](docs/services/image-service.md) | Metadata CRUD, listing, download |
| [User Service](docs/services/user-service.md) | User management, quota, PII hashing |
| [Processing Pipeline](docs/services/processing-pipeline.md) | Finalize → scan → thumbnail generation |
| [Observability](docs/services/observability.md) | Logs, metrics, tracing, CloudTrail, Athena, OpenSearch |
| [Security](docs/services/security.md) | Auth, WAF, VPC, Secrets Manager, IAM, PII |
| [Infrastructure](docs/services/infrastructure.md) | SAM template, DynamoDB schema, S3 buckets, SQS, Kinesis |
