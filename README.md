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
