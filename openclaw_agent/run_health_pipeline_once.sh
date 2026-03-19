#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="${HEALTH_PIPELINE_LOCKFILE:-$HOME/.openclaw/ops/health_pipeline.lock}"
LOG_FILE="${HEALTH_PIPELINE_LOGFILE:-$HOME/.openclaw/ops/health_pipeline.log}"
ENV_FILE="${HEALTH_PIPELINE_ENV_FILE:-$HOME/.health_pipeline.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HEALTH_PIPELINE_SCRIPT:-$SCRIPT_DIR/pull_and_score.sh}"

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
