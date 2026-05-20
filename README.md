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
make install   # install Python dependencies
```

> **Docker env:** copy `docker/.env.sample` → `docker/.env` before starting services.

## Local Services

| Service | Access via Nginx |
|---------|-----------------|
| LocalStack (AWS) | `http://localhost:8080/api/` |
| OpenSearch | `http://localhost:8080/opensearch/` |
| OpenSearch Dashboards | `http://localhost:8080/dashboards/` |

ImageService is a production-grade, Instagram-style image upload backend built on AWS Lambda, S3, and DynamoDB. It supports chunked multipart uploads, an async processing pipeline (AV scan → thumbnails), paginated listing with write-sharded DynamoDB GSIs, GDPR erasure, and full observability via CloudWatch, X-Ray, and OpenSearch.
