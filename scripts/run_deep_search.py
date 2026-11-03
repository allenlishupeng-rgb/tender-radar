"""Run a bounded full-source search, retain evidence and rebuild deliverables."""
import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import DB_PATH, EXPORT_DIR
from crawlers.runner import run_search_with_status
from database.db import upsert_many
from presentation.search_report import build_search_report, save_search_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', help='Repeat for selected sources; default: all enabled sources.')
    parser.add_argument('--days', type=int, choices=range(1, 31), default=30)
    parser.add_argument('--depth', choices=['standard', 'deep'], default='deep')
    parser.add_argument('--no-static', action='store_true')
    args = parser.parse_args()
    started = time.monotonic()

    def progress(status, completed, total):
        print(f"[{completed}/{total}] {status['source']}: {status['status']}, candidates={status['count']}, eligible={status.get('actionable_count', 0)}", flush=True)

    tenders, statuses = run_search_with_status(selected_sources=args.source, query='', days=args.days,
        enable_ai=False, search_depth=args.depth, progress_callback=progress)
    upserted = upsert_many(DB_PATH, tenders)
    report = build_search_report(tenders, statuses, days=args.days, depth=args.depth)
    report['elapsed_seconds'] = round(time.monotonic() - started, 1)
    report['upserted_attempts'] = upserted
    save_search_report(report)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    evidence = EXPORT_DIR / 'deep_search_latest.json'
    evidence.write_text(json.dumps({**report, 'rows': [asdict(t) for t in tenders]}, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.no_static:
        subprocess.run([sys.executable, str(ROOT / 'scripts/generate_static_site.py'), '--days', str(args.days)], cwd=ROOT, check=True, timeout=120)
    print(json.dumps({k: v for k, v in report.items() if k != 'source_statuses'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
