#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="${LOCALSTACK_ACCOUNT_ID:-000000000000}"

log() { echo "[init:s3] $*"; }

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
