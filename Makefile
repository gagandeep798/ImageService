# ── Variables ─────────────────────────────────────────────────────────────────

# Application env — copy .env.template to .env and fill in values (not committed)
include .env
# Docker env (image versions, port mappings)
include docker/.env
export

DC               = docker compose -f docker/docker-compose.yml
FRONTEND_DIR     = frontend
COGNITO_ENDPOINT = http://localhost:9229

STACK_DEV     = image-service-dev
STACK_STAGING = image-service-staging
STACK_PROD    = image-service-prod

# AWS CLI with optional endpoint — set AWS_ENDPOINT_URL for LocalStack, unset for real AWS
AWS_CMD = aws$(if $(AWS_ENDPOINT_URL), --endpoint-url=$(AWS_ENDPOINT_URL),)

.DEFAULT_GOAL := help

.PHONY: help install \
        docker-build localstack-up localstack-start localstack-down \
        cognito-up cognito-down cognito-init setup \
        logs-list logs-tail \
        migrate-local migrate-staging migrate-dry-run \
        test-unit test-integration test \
        lint format typecheck \
        build start-api \
        deploy-dev deploy-staging deploy-prod \
        frontend-install frontend-dev frontend-build \
        deploy-frontend-staging deploy-frontend-prod \
        _frontend-sync _deploy-frontend

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(firstword $(MAKEFILE_LIST)) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────

install: ## Install Python dependencies (Poetry)
	poetry install

setup: localstack-up cognito-init ## First-time local setup: start stack + init Cognito

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build: ## Build Docker images
	$(DC) build

localstack-up: docker-build ## Rebuild images and start LocalStack (blocks until healthy)
	$(DC) up -d --wait

localstack-start: ## Start LocalStack without rebuilding
	$(DC) up -d --wait

localstack-down: ## Stop LocalStack and remove volumes
	$(DC) down -v

cognito-up: ## Start only the Cognito container
	$(DC) up -d cognito-local

cognito-down: ## Stop and remove the Cognito container
	$(DC) stop cognito-local
	$(DC) rm -f cognito-local

cognito-init: ## Initialize Cognito user pool/client (prints env vars to add to .env)
	@POOL_ID=$$(aws cognito-idp create-user-pool \
	  --endpoint-url $(COGNITO_ENDPOINT) \
	  --region us-east-1 \
	  --pool-name image-service-users \
	  --username-attributes email \
	  --schema '[{"Name":"user_id","AttributeDataType":"String","Mutable":false,"Required":false}]' \
	  --query 'UserPool.Id' --output text) && \
	CLIENT_ID=$$(aws cognito-idp create-user-pool-client \
	  --endpoint-url $(COGNITO_ENDPOINT) \
	  --region us-east-1 \
	  --user-pool-id $$POOL_ID \
	  --client-name image-service-client \
	  --no-generate-secret \
	  --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH \
	  --query 'UserPoolClient.ClientId' --output text) && \
	aws cognito-idp create-group \
	  --endpoint-url $(COGNITO_ENDPOINT) \
	  --region us-east-1 \
	  --user-pool-id $$POOL_ID \
	  --group-name admins 2>/dev/null || true && \
	echo "" && \
	echo "Add these to your .env:" && \
	echo "COGNITO_USER_POOL_ID=$$POOL_ID" && \
	echo "COGNITO_CLIENT_ID=$$CLIENT_ID" && \
	echo "COGNITO_ENDPOINT_URL=$(COGNITO_ENDPOINT)"

logs-list: ## List all CloudWatch log groups
	$(AWS_CMD) logs describe-log-groups

logs-tail: ## Tail last 5 min of a function — usage: make logs-tail FUNCTION=upload-initiate APP_ENV=local
	$(AWS_CMD) logs filter-log-events \
	  --log-group-name /aws/lambda/image-service-$(FUNCTION)-$(APP_ENV) \
	  --start-time $$(( ($$(date +%s) - 300) * 1000 ))

# ── Migrations ────────────────────────────────────────────────────────────────

migrate-local: localstack-up ## Apply pending migrations to LocalStack
	poetry run python migrations/runner.py --env local

migrate-staging: ## Apply pending migrations to staging
	poetry run python migrations/runner.py --env staging

migrate-dry-run: ## Preview migrations against prod (no changes)
	poetry run python migrations/runner.py --env prod --dry-run

# ── Tests ─────────────────────────────────────────────────────────────────────

test-unit: ## Run unit tests with coverage (≥80% required)
	poetry run pytest -m unit --cov=src --cov-report=term-missing --cov-fail-under=80

test-integration: localstack-up ## Run integration tests against LocalStack
	poetry run pytest -m integration -v

test: test-unit test-integration ## Run all tests

# ── Code Quality ──────────────────────────────────────────────────────────────

lint: ## Lint with Ruff
	poetry run ruff check src tests

format: ## Format with Ruff
	poetry run ruff format src tests

typecheck: ## Type-check with mypy (strict)
	poetry run mypy src

# ── SAM ───────────────────────────────────────────────────────────────────────

build: ## Build SAM project using Docker
	sam build --use-container

start-api: localstack-start build ## Start SAM local API on http://localhost:3000
	sam local start-api \
	  --docker-network image-service-net \
	  --port 3000 \
	  --parameter-overrides \
	    AwsEndpointUrl=http://image-service-localstack:4566 \
	    PiiPepper=$(PII_PEPPER) \
	    CognitoUserPoolId=$(COGNITO_USER_POOL_ID) \
	    CognitoClientId=$(COGNITO_CLIENT_ID) \
	    CognitoEndpointUrl=http://image-service-cognito-local:9229

# ── Deploys ───────────────────────────────────────────────────────────────────

deploy-dev: build ## Build and deploy to dev; run migrations
	sam deploy --config-env dev
	poetry run python migrations/runner.py --env dev

deploy-staging: build ## Build and deploy to staging; run migrations; deploy frontend
	sam deploy --config-env staging --no-fail-on-empty-changeset
	poetry run python migrations/runner.py --env staging
	$(MAKE) deploy-frontend-staging

deploy-prod: build ## Build and deploy to prod (3s abort window); run migrations; deploy frontend
	@echo "Deploying to PRODUCTION. Ctrl-C to abort..."
	@sleep 3
	sam deploy --config-env prod --no-fail-on-empty-changeset
	poetry run python migrations/runner.py --env prod
	$(MAKE) deploy-frontend-prod

# ── Frontend ──────────────────────────────────────────────────────────────────

frontend-install: ## Install frontend npm dependencies
	$(DC) run --rm frontend npm install

frontend-dev: ## Start frontend dev server on port 5173
	$(DC) up frontend

frontend-build: ## Build production frontend assets
	$(DC) run --rm frontend sh -c "npm install && npm run build"

# Sync dist/ → S3. Assets get immutable cache headers; index.html gets no-cache.
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

# Shared CloudFormation query + sync. Call with STACK_ENV=staging|prod.
_deploy-frontend:
	@set -e; \
	stack=image-service-$(STACK_ENV); \
	bucket=$$($(AWS_CMD) cloudformation describe-stacks \
	  --stack-name $$stack \
	  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
	  --output text); \
	cf_id=$$($(AWS_CMD) cloudformation describe-stacks \
	  --stack-name $$stack \
	  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
	  --output text); \
	$(MAKE) _frontend-sync FRONTEND_BUCKET=$$bucket CLOUDFRONT_DISTRIBUTION_ID=$$cf_id

deploy-frontend-staging: frontend-build ## Build frontend and deploy to staging S3
	$(MAKE) _deploy-frontend STACK_ENV=staging

deploy-frontend-prod: frontend-build ## Build frontend and deploy to prod S3 (3s abort window)
	@echo "Deploying frontend to PRODUCTION. Ctrl-C to abort..."
	@sleep 3
	$(MAKE) _deploy-frontend STACK_ENV=prod
