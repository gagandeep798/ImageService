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
    --username-attributes email \
    --auto-verified-attributes email \
    --policies 'PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=true}' \
    --query 'UserPool.Id' --output text 2>/dev/null || echo "")

if [ -n "$POOL_ID" ]; then
    CLIENT_ID=$(aws_cmd cognito-idp create-user-pool-client \
        --user-pool-id "$POOL_ID" \
        --client-name image-service-app \
        --no-generate-secret \
        --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
        --callback-urls "http://localhost:5173/callback" \
        --logout-urls "http://localhost:5173/" \
        --region "$REGION" \
        --query 'UserPoolClient.ClientId' --output text 2>/dev/null || echo "")

    log "Cognito User Pool: $POOL_ID"
    log "App Client ID:     $CLIENT_ID"
    log ""
    log "Add to frontend/.env.local:"
    log "  VITE_COGNITO_USER_POOL_ID=$POOL_ID"
    log "  VITE_COGNITO_CLIENT_ID=$CLIENT_ID"
    log "  VITE_COGNITO_ENDPOINT=${ENDPOINT:-}"
fi

log "Cognito ready"
