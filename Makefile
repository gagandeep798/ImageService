.PHONY: install fetch-secrets docker-build localstack-up localstack-down \
        migrate-local migrate-staging migrate-dry-run \
        test-unit test-integration test lint format typecheck \
        build start-api dashboards-open seed \
        deploy-dev deploy-staging deploy-prod

# Application env (table names, bucket prefixes, upload limits, etc.)
include .env
# Docker env (image versions, port mappings) — needed for dashboards-open target
include docker/.env
export

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	poetry install

fetch-secrets:
	@mkdir -p docker
	@bash scripts/fetch_secrets.sh

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build:
	docker compose -f docker/docker-compose.yml build

localstack-up: docker-build
	docker compose -f docker/docker-compose.yml up -d --wait

localstack-down:
	docker compose -f docker/docker-compose.yml down -v

dashboards-open:
	open http://localhost:$(NGINX_PORT)/dashboards/

seed: localstack-up
	poetry run python scripts/seed_data.py

# ── Migrations ────────────────────────────────────────────────────────────────

migrate-local: localstack-up
	ENV=local poetry run python migrations/runner.py --env local

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

deploy-prod: build
	@echo "Deploying to PRODUCTION. Ctrl-C to abort..."
	@sleep 3
	sam deploy --config-env prod --no-fail-on-empty-changeset
	poetry run python migrations/runner.py --env prod
