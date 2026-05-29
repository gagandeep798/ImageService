#!/usr/bin/env bash
set -euo pipefail

log() { echo "[init:migrations] $*"; }

if command -v python3 &>/dev/null && [ -f /app/migrations/runner.py ]; then
    python3 /app/migrations/runner.py --env local
    log "migrations applied"
else
    log "skipped (python3 or runner.py not available)"
fi
