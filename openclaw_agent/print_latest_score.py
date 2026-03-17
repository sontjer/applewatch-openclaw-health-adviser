from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--repo-dir', required=True)
    args = p.parse_args()

    path = Path(args.repo_dir) / 'data' / 'report' / 'latest_score.json'
    if not path.exists():
        raise SystemExit(f'not found: {path}')

    d = json.loads(path.read_text(encoding='utf-8'))
    score = d.get('score', {})
    print(f"generated_at: {d.get('generated_at')}")
    print(f"score: {score.get('total')} {score.get('grade')}")


if __name__ == '__main__':
    main()
