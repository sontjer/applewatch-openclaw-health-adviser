#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="${HEALTH_RECON_LOCKFILE:-/root/.openclaw/ops/health_reconcile.lock}"
LOG_FILE="${HEALTH_RECON_LOGFILE:-/root/.openclaw/ops/health_reconcile.log}"
ENV_FILE="${HEALTH_PIPELINE_ENV_FILE:-/root/.health_pipeline.env}"
REPO_DIR="${HEALTH_REPO_DIR:-/root/.openclaw/workspace/health-data}"
SCRIPT="/root/applewatch_openclaw_pipeline/openclaw_agent/reconcile_health_ingest.py"

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
