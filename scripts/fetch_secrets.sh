#!/usr/bin/env bash
# Pulls secrets from AWS Secrets Manager and writes to two output files:
#
#   .env.secrets        — application-level secrets (PII pepper, alerts, CloudFront)
#   docker/.env.secrets — Docker-level secrets passed into containers via env_file
#
# Neither file is committed. Run once at the start of a dev session.
set -euo pipefail

ENV="${IMAGE_SERVICE_ENV:-local}"
ENDPOINT="${SECRETSMANAGER_ENDPOINT_URL:-${AWS_ENDPOINT_URL:-}}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

APP_SECRETS=".env.secrets"
DOCKER_SECRETS="docker/.env.secrets"

log() { echo "[fetch_secrets] $*"; }

sm_get() {
    local secret_id="$1"
    local args=(secretsmanager get-secret-value --secret-id "$secret_id" --region "$REGION" --query SecretString --output text)
    if [ -n "$ENDPOINT" ]; then
        args=(--endpoint-url "$ENDPOINT" "${args[@]}")
    fi
    aws "${args[@]}"
}

# Ensure docker/ directory exists (it should, but guard anyway)
mkdir -p "$(dirname "$DOCKER_SECRETS")"

log "Fetching secrets for env=$ENV"
: > "$APP_SECRETS"
: > "$DOCKER_SECRETS"

# ── PII pepper (app + docker) ─────────────────────────────────────────────────
PEPPER_JSON=$(sm_get "image-service/${ENV}/pii_pepper")
PEPPER=$(echo "$PEPPER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['pepper'])")
echo "PII_PEPPER=${PEPPER}" >> "$APP_SECRETS"
echo "PII_PEPPER=${PEPPER}" >> "$DOCKER_SECRETS"

# ── Alerts (app only — not needed inside Docker containers) ───────────────────
ALERTS_JSON=$(sm_get "image-service/${ENV}/alerts")
SLACK_WEBHOOK=$(echo "$ALERTS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('slack_webhook',''))")
PAGERDUTY_KEY=$(echo "$ALERTS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pagerduty_api_key',''))")
echo "SLACK_WEBHOOK_URL=${SLACK_WEBHOOK}" >> "$APP_SECRETS"
echo "PAGERDUTY_API_KEY=${PAGERDUTY_KEY}" >> "$APP_SECRETS"

# ── CloudFront signing key (app + docker — needed by sam local via docker network) ──
CF_JSON=$(sm_get "image-service/${ENV}/cloudfront")
CF_KEY_PAIR_ID=$(echo "$CF_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('key_pair_id',''))")
CF_PRIVATE_KEY=$(echo "$CF_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('private_key_pem',''))")
echo "CLOUDFRONT_KEY_PAIR_ID=${CF_KEY_PAIR_ID}" >> "$APP_SECRETS"
echo "CLOUDFRONT_KEY_PAIR_ID=${CF_KEY_PAIR_ID}" >> "$DOCKER_SECRETS"
# Private key PEM may contain newlines — base64-encode for safe env var storage
CF_KEY_B64=$(echo "$CF_PRIVATE_KEY" | base64 | tr -d '\n')
echo "CLOUDFRONT_PRIVATE_KEY_B64=${CF_KEY_B64}" >> "$APP_SECRETS"
echo "CLOUDFRONT_PRIVATE_KEY_B64=${CF_KEY_B64}" >> "$DOCKER_SECRETS"

log "→ $APP_SECRETS    ($(wc -l < "$APP_SECRETS") vars)"
log "→ $DOCKER_SECRETS ($(wc -l < "$DOCKER_SECRETS") vars)"
log "Neither file is committed — both are in .gitignore"
