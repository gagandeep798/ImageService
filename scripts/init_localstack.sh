#!/usr/bin/env bash
# Runs inside LocalStack on startup (baked into the custom image).
# Creates all AWS resources needed for local development.
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="${LOCALSTACK_ACCOUNT_ID:-000000000000}"

log() { echo "[init_localstack] $*"; }

# ── S3 Buckets ────────────────────────────────────────────────────────────────
create_bucket() {
    local name="$1"
    aws --endpoint-url="$ENDPOINT" s3 mb "s3://$name" --region "$REGION" 2>/dev/null || true
    log "bucket: $name"
}

ORIGINALS="image-service-originals-${ACCOUNT}-${REGION}"
THUMBNAILS="image-service-thumbnails-${ACCOUNT}-${REGION}"
QUARANTINE="image-service-quarantine-${ACCOUNT}-${REGION}"
LOGS="image-service-logs-${ACCOUNT}-${REGION}"
CLOUDTRAIL_LOGS="image-service-cloudtrail-logs-${ACCOUNT}-${REGION}"
BACKUPS="image-service-backups-${ACCOUNT}-${REGION}"

for bucket in "$ORIGINALS" "$THUMBNAILS" "$QUARANTINE" "$LOGS" "$CLOUDTRAIL_LOGS" "$BACKUPS"; do
    create_bucket "$bucket"
done

# CORS for originals bucket (browser direct upload)
aws --endpoint-url="$ENDPOINT" s3api put-bucket-cors \
    --bucket "$ORIGINALS" \
    --cors-configuration '{
        "CORSRules": [{
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["PUT", "GET", "HEAD"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3600
        }]
    }' 2>/dev/null || true

log "S3 buckets ready"

# ── DynamoDB Tables ───────────────────────────────────────────────────────────
create_table() {
    local name="$1"
    shift
    aws --endpoint-url="$ENDPOINT" dynamodb create-table \
        --table-name "$name" \
        --region "$REGION" \
        "$@" 2>/dev/null || true
    log "table: $name"
}

# images table
create_table "image-service-images" \
    --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
        AttributeName=GSI1PK,AttributeType=S \
        AttributeName=GSI1SK,AttributeType=S \
        AttributeName=GSI2PK,AttributeType=S \
        AttributeName=GSI2SK,AttributeType=S \
    --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
        {"IndexName":"UserImagesIndex","KeySchema":[{"AttributeName":"GSI1PK","KeyType":"HASH"},{"AttributeName":"GSI1SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}},
        {"IndexName":"StatusIndex","KeySchema":[{"AttributeName":"GSI2PK","KeyType":"HASH"},{"AttributeName":"GSI2SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"KEYS_ONLY"}}
    ]' \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES

# users table
create_table "image-service-users" \
    --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
        AttributeName=EmailHashIndex_PK,AttributeType=S \
    --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
        {"IndexName":"EmailHashIndex","KeySchema":[{"AttributeName":"EmailHashIndex_PK","KeyType":"HASH"}],"Projection":{"ProjectionType":"KEYS_ONLY"}}
    ]' \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES

# migrations tracking table
create_table "image-service-migrations" \
    --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
    --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST

# secret hashes table
create_table "image-service-secret-hashes" \
    --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
    --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST

log "DynamoDB tables ready"

# ── SQS Queues ────────────────────────────────────────────────────────────────
create_queue() {
    local name="$1"
    aws --endpoint-url="$ENDPOINT" sqs create-queue --queue-name "$name" --region "$REGION" \
        --attributes '{"VisibilityTimeout":"60","MessageRetentionPeriod":"86400"}' 2>/dev/null || true
    log "queue: $name"
}

for q in image-service-finalize image-service-finalize-dlq \
          image-service-scan image-service-scan-dlq \
          image-service-thumbnails; do
    create_queue "$q"
done

log "SQS queues ready"

# ── Secrets Manager ───────────────────────────────────────────────────────────
create_secret() {
    local name="$1"
    local value="$2"
    aws --endpoint-url="$ENDPOINT" secretsmanager create-secret \
        --name "$name" \
        --secret-string "$value" \
        --region "$REGION" 2>/dev/null || true
    log "secret: $name"
}

create_secret "image-service/local/dynamodb" \
    "{\"images_table\":\"image-service-images\",\"users_table\":\"image-service-users\",\"migrations_table\":\"image-service-migrations\",\"secret_hashes_table\":\"image-service-secret-hashes\",\"region\":\"us-east-1\",\"read_role_arn\":\"\",\"write_role_arn\":\"\",\"delete_role_arn\":\"\"}"
# Note: role ARNs are empty for local dev — LocalStack does not enforce IAM role boundaries,
# so dynamo.py falls back to the default credentials without STS assumption.

create_secret "image-service/local/s3" \
    "{\"originals_bucket\":\"${ORIGINALS}\",\"thumbnails_bucket\":\"${THUMBNAILS}\",\"quarantine_bucket\":\"${QUARANTINE}\",\"logs_bucket\":\"${LOGS}\"}"

create_secret "image-service/local/pii_pepper" \
    '{"pepper":"localdev-placeholder-pepper-change-in-prod-aabbccddeeff00112233445566778899"}'

create_secret "image-service/local/cloudfront" \
    '{"private_key_pem":"LOCAL_DEV_NO_CLOUDFRONT","key_pair_id":"LOCAL_DEV"}'

create_secret "image-service/local/alerts" \
    '{"slack_webhook":"http://localhost/dev-null","pagerduty_api_key":"local-dev"}'

log "Secrets Manager entries ready"

# ── Cognito User Pool ─────────────────────────────────────────────────────────
POOL_ID=$(aws --endpoint-url="$ENDPOINT" cognito-idp create-user-pool \
    --pool-name image-service-local \
    --region "$REGION" \
    --query 'UserPool.Id' --output text 2>/dev/null || echo "")

if [ -n "$POOL_ID" ]; then
    aws --endpoint-url="$ENDPOINT" cognito-idp create-user-pool-client \
        --user-pool-id "$POOL_ID" \
        --client-name image-service-app-client \
        --no-generate-secret \
        --region "$REGION" 2>/dev/null || true
    log "Cognito User Pool: $POOL_ID"
fi

# ── Run DynamoDB Migrations ───────────────────────────────────────────────────
if command -v python3 &>/dev/null && [ -f /app/migrations/runner.py ]; then
    python3 /app/migrations/runner.py --env local
    log "Migrations applied"
fi

log "LocalStack init complete"
