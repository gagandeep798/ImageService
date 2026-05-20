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
```

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
