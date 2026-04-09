#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MEAL_LOG_SCRIPT="${MEAL_LOG_SCRIPT:-${MEAL_SKILL_PATH:-$WORKSPACE_ROOT/skills/meal-intake-log/scripts/log_meal_text.py}}"
REPO_DIR="${HEALTH_REPO_DIR:-/root/.hermes/heath-data}"
INPUT_TEXT="${1:-}"

usage() {
  cat <<'EOF'
Usage:
  log_meal_from_text.sh "记饮食：今天早上吃了一个水煮蛋、一碗芝麻糊"
  log_meal_from_text.sh --repo-dir /root/.hermes/heath-data --text "今天中午吃了鸡胸和沙拉"

Options:
  --repo-dir <path>   Health data repo path (default: $HEALTH_REPO_DIR or ~/.hermes/heath-data)
  --text <text>       Natural-language meal text
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo-dir)
      [ "$#" -ge 2 ] || { echo "missing value for --repo-dir" >&2; exit 2; }
      REPO_DIR="$2"
      shift 2
      ;;
    --text)
      [ "$#" -ge 2 ] || { echo "missing value for --text" >&2; exit 2; }
      INPUT_TEXT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      INPUT_TEXT="$1"
      shift
      ;;
  esac
done

if [ -z "${INPUT_TEXT// }" ]; then
  usage
  exit 2
fi

MEAL_TEXT="${INPUT_TEXT#记饮食：}"
MEAL_TEXT="${MEAL_TEXT#记饮食:}"
MEAL_TEXT="${MEAL_TEXT#"${MEAL_TEXT%%[![:space:]]*}"}"
if [ -z "${MEAL_TEXT// }" ]; then
  echo "meal text is empty after removing prefix" >&2
  exit 2
fi

if [ ! -f "$MEAL_LOG_SCRIPT" ]; then
  echo "log script not found: $MEAL_LOG_SCRIPT" >&2
  exit 2
fi

CSV_PATH="$REPO_DIR/data/diet/meal_text_log.csv"
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT

python3 "$MEAL_LOG_SCRIPT" --repo-dir "$REPO_DIR" --text "$MEAL_TEXT" | tee "$tmp_out"

if [ ! -f "$CSV_PATH" ]; then
  echo "write failed: csv not found: $CSV_PATH" >&2
  exit 1
fi

LOG_TS="$(awk -F= '/^timestamp=/{print $2}' "$tmp_out" | tail -1)"
LOG_MEAL="$(awk -F= '/^meal=/{print $2}' "$tmp_out" | tail -1)"
LOG_DESC="$(awk -F= '/^description=/{sub(/^description=/,""); print}' "$tmp_out" | tail -1)"

python3 - "$CSV_PATH" "$LOG_TS" "$LOG_MEAL" "$LOG_DESC" <<'PY'
import csv
import sys

csv_path, log_ts, log_meal, log_desc = sys.argv[1:5]
with open(csv_path, "r", encoding="utf-8", newline="") as f:
    rows = list(csv.reader(f))
if len(rows) < 2:
    raise SystemExit("csv has no data rows")
last = rows[-1]
if len(last) != 3:
    raise SystemExit("csv last row malformed")
if [last[0], last[1], last[2]] != [log_ts, log_meal, log_desc]:
    raise SystemExit("csv verification failed: last row != script output")
PY

echo "ok: verified write -> $CSV_PATH"
echo "timestamp=$LOG_TS"
echo "meal=$LOG_MEAL"
echo "description=$LOG_DESC"
