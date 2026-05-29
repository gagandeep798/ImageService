#!/usr/bin/env bash
set -euo pipefail

log() { echo "[init:migrations] $*"; }

APP_ENV="${APP_ENV:-local}"

if command -v python3 &>/dev/null && [ -f /app/migrations/runner.py ]; then
    python3 /app/migrations/runner.py --env "$APP_ENV"
    log "migrations applied (env: $APP_ENV)"
else
    log "skipped (python3 or runner.py not available)"
fi
