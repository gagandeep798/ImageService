#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${AWS_ENDPOINT_URL:-}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="${AWS_ACCOUNT_ID:-${LOCALSTACK_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "000000000000")}}"

log() { echo "[init:secrets] $*"; }

aws_cmd() { [ -n "$ENDPOINT" ] && aws --endpoint-url="$ENDPOINT" "$@" || aws "$@"; }

create_secret() {
    local name="$1"
    local value="$2"
    aws_cmd secretsmanager create-secret \
        --name "$name" \
        --secret-string "$value" \
        --region "$REGION" 2>/dev/null || true
    log "secret: $name"
}

# Bucket names mirror s3.sh (self-contained — no shared state between scripts)
ORIGINALS="image-service-originals-${ACCOUNT}-${REGION}"
THUMBNAILS="image-service-thumbnails-${ACCOUNT}-${REGION}"
QUARANTINE="image-service-quarantine-${ACCOUNT}-${REGION}"
LOGS="image-service-logs-${ACCOUNT}-${REGION}"

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
