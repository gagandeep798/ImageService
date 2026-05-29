#!/usr/bin/env bash
# Orchestrator — runs each service-level init script in dependency order.
# Mounted into LocalStack at /etc/localstack/init/ready.d/01_init.sh
# and executed automatically once LocalStack is healthy.
set -euo pipefail

INIT_DIR="/opt/localstack-init"

bash "$INIT_DIR/vpc.sh"
bash "$INIT_DIR/s3.sh"
bash "$INIT_DIR/dynamodb.sh"
bash "$INIT_DIR/sqs.sh"
bash "$INIT_DIR/secrets.sh"
bash "$INIT_DIR/cognito.sh"
bash "$INIT_DIR/migrations.sh"

echo "[init] LocalStack init complete"
