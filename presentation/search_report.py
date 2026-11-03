"""Persist search coverage separately from the visible opportunity list."""
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from parsers.extractors import annotate_deadline_fields, is_open_for_tendering
from config.settings import DATA_DIR


REPORT_PATH = DATA_DIR / 'last_search_report.json'


def build_search_report(tenders, statuses, *, days=30, depth='standard'):
    reasons = Counter()
    for tender in tenders:
        row = dict(tender) if isinstance(tender, dict) else dict(vars(tender))
        annotate_deadline_fields(row)
        reasons['eligible' if is_open_for_tendering(row) else ('unknown' if row['days_left'] is None else 'short')] += 1
    return {
        'run_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'days': days, 'depth': depth, 'returned': len(tenders),
        'eligible': reasons['eligible'], 'unknown': reasons['unknown'], 'short': reasons['short'],
        'sources': len(statuses),
        'failed_sources': sum(s.get('status') in {'失败', '访问失败/受限'} for s in statuses),
        'detail_recovered': sum(s.get('detail_recovered_count', 0) for s in statuses),
        'source_statuses': statuses,
    }


def save_search_report(report, path=REPORT_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as handle:
        temporary = handle.name
        json.dump(report, handle, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_search_report(path=REPORT_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
