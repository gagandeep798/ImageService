.PHONY: install docker-build localstack-up localstack-start localstack-down \
        cognito-up cognito-down cognito-init \
        migrate-local migrate-staging migrate-dry-run \
        test-unit test-integration test lint format typecheck \
        build start-api logs-list logs-tail \
        deploy-dev deploy-staging deploy-prod \
        frontend-install frontend-dev frontend-build \
        deploy-frontend-staging deploy-frontend-prod _frontend-sync

# Application env — copy .env.template to .env and fill in values (not committed)
include .env
# Docker env (image versions, port mappings)
include docker/.env
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

localstack-start:
	docker compose -f docker/docker-compose.yml up -d --wait

localstack-down:
	docker compose -f docker/docker-compose.yml down -v

cognito-up:
	docker compose -f docker/docker-compose.yml up -d cognito-local

cognito-down:
	docker compose -f docker/docker-compose.yml stop cognito-local
	docker compose -f docker/docker-compose.yml rm -f cognito-local

cognito-init:
	@POOL_ID=$$(aws cognito-idp create-user-pool \
	  --endpoint-url http://localhost:9229 \
	  --region us-east-1 \
	  --pool-name image-service-users \
	  --username-attributes email \
	  --schema '[{"Name":"user_id","AttributeDataType":"String","Mutable":false,"Required":false}]' \
	  --query 'UserPool.Id' --output text) && \
	CLIENT_ID=$$(aws cognito-idp create-user-pool-client \
	  --endpoint-url http://localhost:9229 \
	  --region us-east-1 \
	  --user-pool-id $$POOL_ID \
	  --client-name image-service-client \
	  --no-generate-secret \
	  --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH \
	  --query 'UserPoolClient.ClientId' --output text) && \
	aws cognito-idp create-group \
	  --endpoint-url http://localhost:9229 \
	  --region us-east-1 \
	  --user-pool-id $$POOL_ID \
	  --group-name admins 2>/dev/null || true && \
	echo "" && \
	echo "Add these to your .env:" && \
	echo "COGNITO_USER_POOL_ID=$$POOL_ID" && \
	echo "COGNITO_CLIENT_ID=$$CLIENT_ID" && \
	echo "COGNITO_ENDPOINT_URL=http://localhost:9229"

logs-list:
	$(AWS_CMD) logs describe-log-groups

logs-tail:
	$(AWS_CMD) logs filter-log-events \
	  --log-group-name /aws/lambda/image-service-$(FUNCTION)-$(APP_ENV) \
	  --start-time $$(( ($$(date +%s) - 300) * 1000 ))

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

start-api: localstack-start build
	sam local start-api \
	  --docker-network image-service-net \
	  --port 3000 \
	  --parameter-overrides \
	    AwsEndpointUrl=http://image-service-localstack:4566 \
	    PiiPepper=$(shell grep '^PII_PEPPER=' .env | cut -d= -f2-) \
	    CognitoUserPoolId=$(shell grep '^COGNITO_USER_POOL_ID=' .env | cut -d= -f2-) \
	    CognitoClientId=$(shell grep '^COGNITO_CLIENT_ID=' .env | cut -d= -f2-) \
	    CognitoEndpointUrl=http://image-service-cognito-local:9229

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

deploy-frontend-staging: frontend-build
	@set -e; \
	bucket=$$($(AWS_CMD) cloudformation describe-stacks \
	  --stack-name image-service-staging \
	  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
	  --output text); \
	cf_id=$$($(AWS_CMD) cloudformation describe-stacks \
	  --stack-name image-service-staging \
	  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
	  --output text); \
	$(MAKE) _frontend-sync FRONTEND_BUCKET=$$bucket CLOUDFRONT_DISTRIBUTION_ID=$$cf_id

deploy-frontend-prod: frontend-build
	@echo "Deploying frontend to PRODUCTION. Ctrl-C to abort..."
	@sleep 3
	@set -e; \
	bucket=$$($(AWS_CMD) cloudformation describe-stacks \
	  --stack-name image-service-prod \
	  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
	  --output text); \
	cf_id=$$($(AWS_CMD) cloudformation describe-stacks \
	  --stack-name image-service-prod \
	  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
	  --output text); \
	$(MAKE) _frontend-sync FRONTEND_BUCKET=$$bucket CLOUDFRONT_DISTRIBUTION_ID=$$cf_id
