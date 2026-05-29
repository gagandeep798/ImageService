#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${AWS_ENDPOINT_URL:-}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
APP_ENV="${APP_ENV:-local}"

log() { echo "[init:cognito] $*"; }

aws_cmd() { [ -n "$ENDPOINT" ] && aws --endpoint-url="$ENDPOINT" "$@" || aws "$@"; }

POOL_ID=$(aws_cmd cognito-idp create-user-pool \
    --pool-name "image-service-${APP_ENV}" \
    --region "$REGION" \
    --query 'UserPool.Id' --output text 2>/dev/null || echo "")

if [ -n "$POOL_ID" ]; then
    aws_cmd cognito-idp create-user-pool-client \
        --user-pool-id "$POOL_ID" \
        --client-name image-service-app-client \
        --no-generate-secret \
        --region "$REGION" 2>/dev/null || true
    log "Cognito User Pool: $POOL_ID"
fi

log "Cognito ready"
