#!/usr/bin/env bash
# Orchestrator — runs each service-level init script in dependency order.
# Works against LocalStack (set AWS_ENDPOINT_URL=http://localhost:4566) or real AWS (unset).
# When mounted into LocalStack via ready.d, INIT_DIR defaults to /opt/localstack-init.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INIT_DIR="${INIT_DIR:-$SCRIPT_DIR}"

bash "$INIT_DIR/vpc.sh"
bash "$INIT_DIR/s3.sh"
bash "$INIT_DIR/dynamodb.sh"
bash "$INIT_DIR/sqs.sh"
bash "$INIT_DIR/cognito.sh"
bash "$INIT_DIR/migrations.sh"

echo "[init] LocalStack init complete"
