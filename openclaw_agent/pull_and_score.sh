#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${HEALTH_REPO_URL:-https://github.com/<your-user>/<your-private-repo>.git}"
GITHUB_PAT="${HEALTH_GITHUB_PAT:-}"
REPO_DIR="${HEALTH_REPO_DIR:-$HOME/.openclaw/workspace/health-data}"
BRANCH="${HEALTH_REPO_BRANCH:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

auth_git() {
  if [ -n "$GITHUB_PAT" ]; then
    git -c credential.helper= \
      -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf "x-access-token:%s" "$GITHUB_PAT" | base64 -w0)" \
      "$@"
  else
    git "$@"
  fi
}

if [ ! -d "$REPO_DIR/.git" ]; then
  mkdir -p "$(dirname "$REPO_DIR")"
  auth_git clone "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
auth_git fetch origin "$BRANCH"
git checkout "$BRANCH" >/dev/null 2>&1 || git checkout -b "$BRANCH" "origin/$BRANCH"
auth_git pull --ff-only origin "$BRANCH"

if [ ! -f "$REPO_DIR/data/latest.json" ]; then
  echo "data/latest.json not found yet; skip scoring."
  exit 0
fi

python3 "$SCRIPT_DIR/analyze_latest.py" \
  --input "$REPO_DIR/data/latest.json" \
  --output "$REPO_DIR/data/report/latest_score.json"

python3 "$SCRIPT_DIR/generate_health_report.py" \
  --repo-dir "$REPO_DIR"

python3 "$SCRIPT_DIR/notify_telegram.py" \
  --repo-dir "$REPO_DIR"

# Optional: commit score back to repo for history tracking
if [ "${COMMIT_SCORE:-0}" = "1" ]; then
  git add data/report/latest_score.json data/report/insights.json data/report/daily_health_report.md data/report/score_history.jsonl
  if ! git diff --cached --quiet; then
    git commit -m "health: update score and report artifacts"
    auth_git push origin "$BRANCH"
  fi
fi
