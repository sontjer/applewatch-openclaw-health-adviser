#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${HEALTH_REPO_URL:-https://github.com/<your-user>/<your-private-repo>.git}"
GITHUB_PAT="${HEALTH_GITHUB_PAT:-}"
REPO_DIR="${HEALTH_REPO_DIR:-$HOME/.openclaw/workspace/health-data}"
BRANCH="${HEALTH_REPO_BRANCH:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_DIR="${HEALTH_OPS_DIR:-/root/.openclaw/ops}"
FALLBACK_SCORE_PATH="${HEALTH_FALLBACK_SCORE_PATH:-$OPS_DIR/health_latest_score_fallback.json}"
STATE_PATH="${HEALTH_STATE_PATH:-$OPS_DIR/health_state.json}"

mkdir -p "$OPS_DIR"

auth_git() {
  if [ -n "$GITHUB_PAT" ]; then
    git -c credential.helper= \
      -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf "x-access-token:%s" "$GITHUB_PAT" | base64 -w0)" \
      "$@"
  else
    git "$@"
  fi
}

backup_untracked_from_pull_error() {
  local err_file="$1"
  local backup_dir="$OPS_DIR/health-untracked-backup/$(date +%F_%H%M%S)"
  local moved=0

  mkdir -p "$backup_dir"

  awk '
    /would be overwritten by merge:/ {collect=1; next}
    collect && $0 ~ /^[[:space:]]+/ {
      gsub(/^[[:space:]]+/, "", $0)
      print $0
      next
    }
    collect {collect=0}
  ' "$err_file" | while IFS= read -r rel_path; do
    [ -z "$rel_path" ] && continue
    if [ -e "$rel_path" ]; then
      mkdir -p "$backup_dir/$(dirname "$rel_path")"
      mv "$rel_path" "$backup_dir/$rel_path"
      moved=1
      echo "moved_untracked_for_pull: $rel_path -> $backup_dir/$rel_path"
    fi
  done

  echo "untracked_backup_dir=$backup_dir"
}

if [ ! -d "$REPO_DIR/.git" ]; then
  mkdir -p "$(dirname "$REPO_DIR")"
  auth_git clone "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
auth_git fetch origin "$BRANCH"
git checkout "$BRANCH" >/dev/null 2>&1 || git checkout -b "$BRANCH" "origin/$BRANCH"

pull_err="$(mktemp)"
if ! auth_git pull --ff-only origin "$BRANCH" 2>"$pull_err"; then
  if rg -q "would be overwritten by merge" "$pull_err"; then
    backup_untracked_from_pull_error "$pull_err"
    auth_git pull --ff-only origin "$BRANCH"
  else
    cat "$pull_err" >&2
    rm -f "$pull_err"
    exit 1
  fi
fi
rm -f "$pull_err"

if [ ! -f "$REPO_DIR/data/latest.json" ]; then
  echo "data/latest.json not found yet; skip scoring."
  exit 0
fi

score_source="fresh"
if ! python3 "$SCRIPT_DIR/analyze_latest.py" \
  --input "$REPO_DIR/data/latest.json" \
  --output "$REPO_DIR/data/report/latest_score.json"; then
  score_source="fallback"
  echo "analyze_latest failed; fallback to previous latest_score.json if present."

  if [ ! -f "$REPO_DIR/data/report/latest_score.json" ] && [ -f "$FALLBACK_SCORE_PATH" ]; then
    mkdir -p "$REPO_DIR/data/report"
    cp -f "$FALLBACK_SCORE_PATH" "$REPO_DIR/data/report/latest_score.json"
    echo "restored latest_score from fallback cache: $FALLBACK_SCORE_PATH"
  fi

  if [ ! -f "$REPO_DIR/data/report/latest_score.json" ]; then
    echo "no previous latest_score.json, stop."
    exit 0
  fi
fi

# Persist a durable fallback snapshot whenever we have a usable score output.
if [ -f "$REPO_DIR/data/report/latest_score.json" ]; then
  cp -f "$REPO_DIR/data/report/latest_score.json" "$FALLBACK_SCORE_PATH"
fi

python3 "$SCRIPT_DIR/generate_health_report.py" \
  --repo-dir "$REPO_DIR"

python3 "$SCRIPT_DIR/enrich_report_meta.py" \
  --repo-dir "$REPO_DIR" \
  --score-source "$score_source" \
  --state-path "$STATE_PATH"

python3 "$SCRIPT_DIR/notify_telegram.py" \
  --repo-dir "$REPO_DIR"

# Optional: commit score back to repo for history tracking
if [ "${COMMIT_SCORE:-0}" = "1" ]; then
  git add data/report/latest_score.json data/report/insights.json data/report/daily_health_report.md data/report/score_history.jsonl data/report/reconcile_report.json
  if ! git diff --cached --quiet; then
    git commit -m "health: update score and report artifacts"
    auth_git push origin "$BRANCH"
  fi
fi
