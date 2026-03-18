from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def parse_dt(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    t = str(s).strip()
    try:
        return datetime.fromisoformat(t.replace('Z', '+00:00'))
    except ValueError:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo-dir', required=True)
    ap.add_argument('--score-source', required=True, choices=['fresh', 'fallback'])
    ap.add_argument('--state-path', required=True)
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    state_path = Path(args.state_path)

    latest_data_path = repo / 'data' / 'latest.json'
    latest_score_path = repo / 'data' / 'report' / 'latest_score.json'
    insights_path = repo / 'data' / 'report' / 'insights.json'

    if not latest_data_path.exists() or not latest_score_path.exists() or not insights_path.exists():
        raise SystemExit('required files missing for enrich_report_meta')

    latest_data = load_json(latest_data_path, {})
    latest_score = load_json(latest_score_path, {})
    insights = load_json(insights_path, {})
    state = load_json(state_path, {'consecutive_fallback_count': 0})

    ingest_at = parse_dt((latest_data.get('meta') or {}).get('ingested_at'))
    freshness_min = None
    if ingest_at is not None:
        delta = now_utc() - ingest_at.astimezone(timezone.utc)
        freshness_min = round(delta.total_seconds() / 60.0, 2)

    prev_count = int(state.get('consecutive_fallback_count') or 0)
    if args.score_source == 'fallback':
        fb_count = prev_count + 1
    else:
        fb_count = 0

    score_meta = {
        'score_source': args.score_source,
        'consecutive_fallback_count': fb_count,
        'is_fresh_score': args.score_source == 'fresh',
        'data_freshness_minutes': freshness_min,
        'latest_ingested_at': (latest_data.get('meta') or {}).get('ingested_at'),
        'meta_updated_at': now_utc().isoformat().replace('+00:00', 'Z'),
    }

    latest_score['score_meta'] = score_meta
    insights['score_meta'] = score_meta

    alerts = insights.get('alerts')
    if not isinstance(alerts, list):
        alerts = []
    if args.score_source == 'fallback':
        alerts.append(f'评分新鲜度告警：本次使用 fallback（连续 {fb_count} 次）。')
    if freshness_min is not None and freshness_min > 180:
        alerts.append(f'数据时效告警：最新入库距今 {freshness_min} 分钟。')
    insights['alerts'] = alerts

    state['consecutive_fallback_count'] = fb_count
    state['last_score_source'] = args.score_source
    state['last_meta_updated_at'] = score_meta['meta_updated_at']

    save_json(latest_score_path, latest_score)
    save_json(insights_path, insights)
    save_json(state_path, state)

    print(json.dumps({'ok': True, 'score_meta': score_meta}, ensure_ascii=False))


if __name__ == '__main__':
    main()
