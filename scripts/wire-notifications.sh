#!/usr/bin/env bash
# Wire S3 originals-bucket → FinalizeUploadFunction notification for a given env.
# Called post-deploy by all deploy targets (local, staging, prod).
#
# Usage: bash scripts/wire-notifications.sh <env>
#   env: local | dev | staging | prod
set -euo pipefail

ENV="${1:-local}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

log() { echo "[wire-notifications] $*"; }

if [ "$ENV" = "local" ]; then
    ENDPOINT="${AWS_ENDPOINT_URL:-http://localhost:4566}"
    ACCOUNT="${LOCALSTACK_ACCOUNT_ID:-000000000000}"
    aws_cmd() { aws --endpoint-url="$ENDPOINT" --region="$REGION" "$@"; }
else
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    aws_cmd() { aws --region="$REGION" "$@"; }
fi

# For local env the .env-exported ORIGINALS_BUCKET overrides the CF-resolved
# bucket name in SAM Lambda containers, so uploads land in the bare bucket.
if [ "$ENV" = "local" ]; then
    BUCKET="image-service-originals-${ACCOUNT}-${REGION}"
else
    BUCKET="image-service-originals-${ACCOUNT}-${REGION}-${ENV}"
fi
FUNC_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:image-service-finalize-upload-${ENV}"

aws_cmd lambda add-permission \
    --function-name "$FUNC_ARN" \
    --statement-id "s3-originals-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "s3.amazonaws.com" \
    --source-arn "arn:aws:s3:::${BUCKET}" 2>/dev/null || true
log "lambda:InvokeFunction permission set"

aws_cmd s3api put-bucket-notification-configuration \
    --bucket "$BUCKET" \
    --notification-configuration '{
        "LambdaFunctionConfigurations": [{
            "LambdaFunctionArn": "'"$FUNC_ARN"'",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {
                    "FilterRules": [{"Name": "prefix", "Value": "originals/"}]
                }
            }
        }]
    }'
log "S3 notification wired: ${BUCKET} → image-service-finalize-upload-${ENV}"
