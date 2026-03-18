#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="${HEALTH_PIPELINE_LOCKFILE:-/root/.openclaw/ops/health_pipeline.lock}"
LOG_FILE="${HEALTH_PIPELINE_LOGFILE:-/root/.openclaw/ops/health_pipeline.log}"
ENV_FILE="${HEALTH_PIPELINE_ENV_FILE:-/root/.health_pipeline.env}"
SCRIPT="/root/applewatch_openclaw_pipeline/openclaw_agent/pull_and_score.sh"

mkdir -p "$(dirname "$LOCK_FILE")" "$(dirname "$LOG_FILE")"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "health_pipeline_already_running" >> "$LOG_FILE"
  exit 0
fi

set -a
. "$ENV_FILE"
set +a

"$SCRIPT" >> "$LOG_FILE" 2>&1
