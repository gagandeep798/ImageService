#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${AWS_ENDPOINT_URL:-}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

log() { echo "[init:sqs] $*"; }

aws_cmd() { [ -n "$ENDPOINT" ] && aws --endpoint-url="$ENDPOINT" "$@" || aws "$@"; }

create_queue() {
    local name="$1"
    aws_cmd sqs create-queue --queue-name "$name" --region "$REGION" \
        --attributes '{"VisibilityTimeout":"60","MessageRetentionPeriod":"86400"}' 2>/dev/null || true
    log "queue: $name"
}

for q in image-service-finalize image-service-finalize-dlq \
          image-service-scan image-service-scan-dlq \
          image-service-thumbnails; do
    create_queue "$q"
done

log "SQS queues ready"
