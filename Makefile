.PHONY: install docker-build localstack-up localstack-down \
        migrate-local migrate-staging migrate-dry-run \
        test-unit test-integration test lint format typecheck \
        build start-api logs-list logs-tail seed \
        deploy-dev deploy-staging deploy-prod \
        frontend-install frontend-dev frontend-build \
        deploy-frontend-staging deploy-frontend-prod _frontend-sync

# Application env (table names, bucket prefixes, upload limits, etc.)
include .env
# Docker env (image versions, port mappings)
include docker/.env
# Local overrides (credentials, AWS_ENDPOINT_URL) — not committed
-include .env.local
export

# AWS CLI with optional endpoint — set AWS_ENDPOINT_URL for LocalStack, unset for real AWS
AWS_CMD = aws$(if $(AWS_ENDPOINT_URL), --endpoint-url=$(AWS_ENDPOINT_URL),)

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	poetry install

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build:
	docker compose -f docker/docker-compose.yml build

localstack-up: docker-build
	docker compose -f docker/docker-compose.yml up -d --wait

localstack-down:
	docker compose -f docker/docker-compose.yml down -v

logs-list:
	$(AWS_CMD) logs describe-log-groups

logs-tail:
	$(AWS_CMD) logs filter-log-events \
	  --log-group-name /aws/lambda/image-service-$(FUNCTION)-$(APP_ENV) \
	  --start-time $$(( ($$(date +%s) - 300) * 1000 ))

seed: localstack-up
	poetry run python scripts/seed_data.py

# ── Migrations ────────────────────────────────────────────────────────────────

migrate-local: localstack-up
	poetry run python migrations/runner.py --env local

migrate-staging:
	poetry run python migrations/runner.py --env staging

migrate-dry-run:
	poetry run python migrations/runner.py --env prod --dry-run

# ── Tests ─────────────────────────────────────────────────────────────────────

test-unit:
	poetry run pytest -m unit --cov=src --cov-report=term-missing --cov-fail-under=80

test-integration: localstack-up
	poetry run pytest -m integration -v

test: test-unit test-integration

# ── Code Quality ──────────────────────────────────────────────────────────────

lint:
	poetry run ruff check src tests

format:
	poetry run ruff format src tests

typecheck:
	poetry run mypy src

# ── SAM ───────────────────────────────────────────────────────────────────────

build:
	sam build --use-container

start-api: localstack-up build
	sam local start-api \
	  --env-vars .env.local \
	  --docker-network image-service-net \
	  --port 3000

# ── Deploys ───────────────────────────────────────────────────────────────────

deploy-dev: build
	sam deploy --config-env dev
	poetry run python migrations/runner.py --env dev

deploy-staging: build
	sam deploy --config-env staging --no-fail-on-empty-changeset
	poetry run python migrations/runner.py --env staging
	$(MAKE) deploy-frontend-staging

deploy-prod: build
	@echo "Deploying to PRODUCTION. Ctrl-C to abort..."
	@sleep 3
	sam deploy --config-env prod --no-fail-on-empty-changeset
	poetry run python migrations/runner.py --env prod
	$(MAKE) deploy-frontend-prod

# ── Frontend ──────────────────────────────────────────────────────────────────

FRONTEND_DIR = frontend

frontend-install:
	docker compose -f docker/docker-compose.yml run --rm frontend npm install

frontend-dev:
	docker compose -f docker/docker-compose.yml up frontend

frontend-build:
	docker compose -f docker/docker-compose.yml run --rm frontend \
	  sh -c "npm install && npm run build"

# Sync dist/ → S3. All assets: immutable cache (content-hashed names).
# index.html: no-cache (always fresh — points to hashed assets).
_frontend-sync:
	$(AWS_CMD) s3 sync $(FRONTEND_DIR)/dist/ s3://$(FRONTEND_BUCKET)/ \
	  --delete \
	  --cache-control "max-age=31536000,immutable" \
	  --exclude "index.html"
	$(AWS_CMD) s3 cp $(FRONTEND_DIR)/dist/index.html s3://$(FRONTEND_BUCKET)/index.html \
	  --cache-control "no-cache,no-store,must-revalidate"
	$(AWS_CMD) cloudfront create-invalidation \
	  --distribution-id $(CLOUDFRONT_DISTRIBUTION_ID) \
	  --paths "/*"

_stack_output = $(shell $(AWS_CMD) cloudformation describe-stacks \
  --stack-name image-service-$(1) \
  --query "Stacks[0].Outputs[?OutputKey=='$(2)'].OutputValue" \
  --output text)

deploy-frontend-staging: frontend-build
	$(MAKE) _frontend-sync \
	  FRONTEND_BUCKET=$(call _stack_output,staging,FrontendBucketName) \
	  CLOUDFRONT_DISTRIBUTION_ID=$(call _stack_output,staging,CloudFrontDistributionId)

deploy-frontend-prod: frontend-build
	@echo "Deploying frontend to PRODUCTION. Ctrl-C to abort..."
	@sleep 3
	$(MAKE) _frontend-sync \
	  FRONTEND_BUCKET=$(call _stack_output,prod,FrontendBucketName) \
	  CLOUDFRONT_DISTRIBUTION_ID=$(call _stack_output,prod,CloudFrontDistributionId)
