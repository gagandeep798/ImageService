#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${AWS_ENDPOINT_URL:-}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="${AWS_ACCOUNT_ID:-${LOCALSTACK_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "000000000000")}}"

log() { echo "[init:s3] $*"; }

aws_cmd() { [ -n "$ENDPOINT" ] && aws --endpoint-url="$ENDPOINT" "$@" || aws "$@"; }

create_bucket() {
    local name="$1"
    aws_cmd s3 mb "s3://$name" --region "$REGION" 2>/dev/null || true
    log "bucket: $name"
}

ORIGINALS="image-service-originals-${ACCOUNT}-${REGION}"
THUMBNAILS="image-service-thumbnails-${ACCOUNT}-${REGION}"
QUARANTINE="image-service-quarantine-${ACCOUNT}-${REGION}"
LOGS="image-service-logs-${ACCOUNT}-${REGION}"
CLOUDTRAIL_LOGS="image-service-cloudtrail-logs-${ACCOUNT}-${REGION}"
BACKUPS="image-service-backups-${ACCOUNT}-${REGION}"
FRONTEND="image-service-frontend-${ACCOUNT}-${REGION}"

for bucket in "$ORIGINALS" "$THUMBNAILS" "$QUARANTINE" "$LOGS" "$CLOUDTRAIL_LOGS" "$BACKUPS" "$FRONTEND"; do
    create_bucket "$bucket"
done

aws_cmd s3api put-bucket-versioning --bucket "$FRONTEND" \
    --versioning-configuration Status=Enabled 2>/dev/null || true

# CORS for originals bucket (browser direct upload)
aws_cmd s3api put-bucket-cors \
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
