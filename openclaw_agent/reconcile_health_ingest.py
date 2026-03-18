from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_dt(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def post_telegram(text: str) -> None:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return

    payload = urllib.parse.urlencode(
        {
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': 'true',
        }
    ).encode('utf-8')
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    req = urllib.request.Request(url, data=payload, method='POST')
    with urllib.request.urlopen(req, timeout=20):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo-dir', required=True)
    ap.add_argument('--window-hours', type=int, default=24)
    ap.add_argument('--alert-on-anomaly', action='store_true')
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    manifest = repo / 'data' / 'manifests' / 'ingest_log.jsonl'
    latest_path = repo / 'data' / 'latest.json'
    archive_dir = repo / 'data' / 'archive'
    out_path = repo / 'data' / 'report' / 'reconcile_report.json'

    anomalies: List[str] = []
    now = now_utc()
    window_start = now - timedelta(hours=args.window_hours)

    rows = read_jsonl(manifest)
    recent = []
    for r in rows:
        ts = parse_dt(r.get('ts'))
        if ts is None:
            continue
        if ts.astimezone(timezone.utc) >= window_start:
            recent.append(r)

    if not manifest.exists():
        anomalies.append('manifest_missing')

    ingest_ids = [r.get('ingest_id') for r in recent if r.get('ingest_id')]
    dup = [k for k, v in Counter(ingest_ids).items() if v > 1]
    if dup:
        anomalies.append(f'duplicate_ingest_id:{len(dup)}')

    missing_archive = []
    for r in recent:
        apath = r.get('archive_path')
        if not apath:
            continue
        if not (repo / apath).exists():
            missing_archive.append(apath)
    if missing_archive:
        anomalies.append(f'missing_archive_files:{len(missing_archive)}')

    archive_recent_count = 0
    if archive_dir.exists():
        for p in archive_dir.rglob('*.json'):
            if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) >= window_start:
                archive_recent_count += 1

    latest_meta_ingest_id = None
    if latest_path.exists():
        latest = read_json(latest_path)
        latest_meta_ingest_id = ((latest.get('meta') or {}).get('ingest_id'))

    newest_manifest_ingest_id = recent[-1].get('ingest_id') if recent else None
    if recent and latest_meta_ingest_id and newest_manifest_ingest_id and latest_meta_ingest_id != newest_manifest_ingest_id:
        anomalies.append('latest_not_pointing_to_newest_manifest')

    if recent and archive_recent_count < len(recent):
        anomalies.append(f'archive_count_lt_manifest_recent:{archive_recent_count}<{len(recent)}')

    fatal_anomalies = [a for a in anomalies if a != 'manifest_missing']

    report = {
        'generated_at': now.isoformat().replace('+00:00', 'Z'),
        'window_hours': args.window_hours,
        'window_start': window_start.isoformat().replace('+00:00', 'Z'),
        'manifest_exists': manifest.exists(),
        'manifest_total_rows': len(rows),
        'manifest_recent_rows': len(recent),
        'archive_recent_files': archive_recent_count,
        'latest_meta_ingest_id': latest_meta_ingest_id,
        'newest_manifest_ingest_id': newest_manifest_ingest_id,
        'anomalies': anomalies,
        'status': 'ok' if not anomalies else ('bootstrap' if anomalies == ['manifest_missing'] else 'anomaly'),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

    if fatal_anomalies and args.alert_on_anomaly:
        post_telegram(
            '[health-reconcile] anomaly\n'
            f"window={args.window_hours}h\n"
            f"anomalies={'; '.join(anomalies)}"
        )

    if fatal_anomalies:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
