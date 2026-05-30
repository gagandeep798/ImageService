# Local Development

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | `brew install python@3.12` |
| Poetry | 1.8+ | `pip install poetry` |
| Docker Desktop | 4.x | https://www.docker.com/products/docker-desktop |
| AWS SAM CLI | latest | `brew install aws-sam-cli` |
| AWS CLI | v2 | `brew install awscli` |

---

## First-Time Setup

```bash
# 1. Install Python dependencies
make install

# 2. Copy the .env.local template and fill in values
cp .env.local.template .env.local
# Edit .env.local — the AWS credentials are always "test" for LocalStack

# 3. Pull secrets from LocalStack Secrets Manager
#    (LocalStack must be running for this to work — see step 4 first on first run)
make fetch-secrets
# Writes:  .env.secrets        (app-level secrets)
#          docker/.env.secrets  (Docker-level secrets)

# 4. Build custom Docker images and start all services
make localstack-up
# Starts: LocalStack, OpenSearch, OpenSearch Dashboards, Nginx

# 5. Start the SAM local API
make start-api
# API available at http://localhost:3000
```

---

## Environment Files

| File | Committed | Purpose |
|------|-----------|---------|
| `.env` | Yes | Application config (table names, limits, etc.) |
| `docker/.env` | Yes | Docker config (image versions, ports) |
| `.env.local` | No | Local overrides for app config + dev credentials |
| `.env.secrets` | No | App-level secrets from Secrets Manager |
| `docker/.env.secrets` | No | Docker-level secrets from Secrets Manager |

To override a port, create `docker/.env.local`:
```bash
echo "NGINX_PORT=9090" >> docker/.env.local
```

---

## Docker Services

| Service | Internal port | Access via Nginx |
|---------|--------------|-----------------|
| LocalStack | `${LOCALSTACK_PORT}` (4566) | `http://localhost:8080/api/` |
| OpenSearch | `${OPENSEARCH_PORT}` (9200) | `http://localhost:8080/opensearch/` |
| OpenSearch Dashboards | `${OPENSEARCH_DASHBOARDS_PORT}` (5601) | `http://localhost:8080/dashboards/` |

Only Nginx exposes a host port (`NGINX_PORT`, default 8080). All other services are container-internal.

```bash
make localstack-up    # start all services
make localstack-down  # stop and remove volumes
make dashboards-open  # open Dashboards in browser
```

---

## Running the API Locally

```bash
make build      # sam build --use-container
make start-api  # sam local start-api on port 3000
```

SAM uses the `image-service-net` Docker network to reach LocalStack through Nginx. All endpoint URLs in `.env.local` point to `http://localhost:8080/api`.

**Test the health endpoint**:
```bash
curl http://localhost:3000/health
# {"status":"healthy","checks":{"dynamodb_images":"ok","s3_originals":"ok"}}
```

**Test the upload flow**:
```bash
# Step 1 — initiate
curl -s -X POST http://localhost:3000/images \
  -H "Content-Type: application/json" \
  -d '{"user_id":"usr_abc","filename":"test.jpg","content_type":"image/jpeg","total_size_bytes":5242880}' \
  | python3 -m json.tool

# Step 2 — upload a part (5 MB minimum)
dd if=/dev/urandom bs=5242880 count=1 of=/tmp/chunk.bin
PRESIGNED_URL="<presigned_part_url from step 1>"
curl -X PUT "$PRESIGNED_URL" --data-binary @/tmp/chunk.bin

# Step 3 — complete
curl -X POST http://localhost:3000/images/<image_id>/complete \
  -H "Content-Type: application/json" \
  -d '{"upload_id":"<upload_id>","parts":[{"part_number":1,"etag":"<etag>"}]}'
```

---

## Running Tests

```bash
make test-unit          # fast, no Docker required
make test-integration   # requires LocalStack running (auto-starts if not up)
make test               # both
```

Unit tests use `moto` to mock all AWS services in-process. Integration tests hit LocalStack via the boto3 clients configured in `tests/integration/conftest.py`.

---

## Applying Migrations

DynamoDB migrations run automatically when LocalStack starts (the init script calls `migrations/runner.py --env local`). To re-run manually:

```bash
make migrate-local
```

See [Database Migrations](migrations.md) for how to write a new migration.

---

## Common Problems

**`make localstack-up` fails with "image not found"**
Custom images have not been built yet. Run `make docker-build` first, or use `make localstack-up` which calls `docker-build` as a prerequisite.

**`make start-api` cannot connect to DynamoDB**
Check that `DYNAMODB_ENDPOINT_URL` in `.env.local` points to `http://localhost:8080/api` (through Nginx, not directly to port 4566) and that `make localstack-up` has completed successfully.

**`fetch-secrets` fails with "ResourceNotFoundException"**
LocalStack must be running before `fetch-secrets` can read from its Secrets Manager. Run `make localstack-up` first.

**Migrations fail with "table already exists"**
Migrations are idempotent for table creation — they skip tables that already exist. If you see a non-creation error, check the migration checksum table (`image-service-migrations`) to see what has been applied.
