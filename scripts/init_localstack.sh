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

