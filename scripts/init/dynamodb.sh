#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${AWS_ENDPOINT_URL:-}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

log() { echo "[init:dynamodb] $*"; }

aws_cmd() { [ -n "$ENDPOINT" ] && aws --endpoint-url="$ENDPOINT" "$@" || aws "$@"; }

create_table() {
    local name="$1"
    shift
    aws_cmd dynamodb create-table \
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

log "DynamoDB tables ready"
