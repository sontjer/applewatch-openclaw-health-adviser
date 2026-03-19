#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="${HEALTH_RECON_LOCKFILE:-$HOME/.openclaw/ops/health_reconcile.lock}"
LOG_FILE="${HEALTH_RECON_LOGFILE:-$HOME/.openclaw/ops/health_reconcile.log}"
ENV_FILE="${HEALTH_PIPELINE_ENV_FILE:-$HOME/.health_pipeline.env}"
REPO_DIR="${HEALTH_REPO_DIR:-$HOME/.openclaw/workspace/health-data}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HEALTH_RECON_SCRIPT:-$SCRIPT_DIR/reconcile_health_ingest.py}"

mkdir -p "$(dirname "$LOCK_FILE")" "$(dirname "$LOG_FILE")"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "health_reconcile_already_running" >> "$LOG_FILE"
  exit 0
fi

set -a
. "$ENV_FILE"
set +a

python3 "$SCRIPT" --repo-dir "$REPO_DIR" --window-hours 24 --alert-on-anomaly >> "$LOG_FILE" 2>&1
