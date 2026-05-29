#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

log() { echo "[init:cognito] $*"; }

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

log "Cognito ready"
