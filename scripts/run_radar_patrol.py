"""Run the tender radar once and record only genuinely new alert candidates."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import DATA_DIR, DB_PATH, SOURCES_PATH
from crawlers.runner import run_search_with_status
from database.db import build_merged_rows, fetch_tenders, normalize_merge_key, upsert_many
from parsers.extractors import annotate_deadline_fields, is_open_for_tendering
from scoring.rules import NOTICE_STAGE_BID, annotate_notice_stage
from utils.date_window import STRICT_RECENT_DAYS, recent_date_window


RUN_DIR = DATA_DIR / "automation_runs"
RUN_SUMMARY_PATH = RUN_DIR / "last_radar_patrol.json"
LEGACY_SUMMARY_PATH = DATA_DIR / "last_automation_run.json"
ALERT_PRIORITIES = {"高优先级", "中优先级"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the tender radar patrol and persist new-project alerts.")
    parser.add_argument("--skip-static", action="store_true", help="Skip static export regeneration.")
    parser.add_argument("--no-ai", action="store_true", help="Skip optional AI secondary classification.")
    parser.add_argument(
        "--max-ai-candidates",
        type=int,
        default=None,
        help="Limit optional AI secondary classification to this many candidates.",
    )
    return parser.parse_args()


def load_sources() -> list[dict[str, Any]]:
    data = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("sources", [])


def balanced_source_names(sources: list[dict[str, Any]]) -> list[str]:
    return [
        source["name"]
        for source in sources
        if source.get("enabled", True)
        and source.get("crawler") != "example_public_page"
        and source.get("risk_level") != "高"
    ]


def project_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {normalize_merge_key(row) for row in rows}


def tender_to_row(tender: Any) -> dict[str, Any]:
    return dict(tender) if isinstance(tender, dict) else dict(tender.__dict__)


def is_alert_candidate(row: dict[str, Any]) -> bool:
    annotate_deadline_fields(row)
    annotate_notice_stage(row, preserve_existing=True)
    priority = str(row.get("priority") or "")
    notice_stage = str(row.get("notice_stage") or "")
    # New records stay visible in the radar, but low-priority public-culture
    # tenders and non-actionable intelligence must not produce notifications.
    return (
        row.get("review_bucket") != "待研判"
        and priority in ALERT_PRIORITIES
        and notice_stage == NOTICE_STAGE_BID
        and is_open_for_tendering(row)
    )


def alert_preview(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": row.get("title", ""),
        "publish_date": row.get("publish_date", ""),
        "bid_deadline": row.get("bid_deadline", ""),
        "budget": row.get("budget", ""),
        "priority": row.get("priority", ""),
        "notice_stage": row.get("notice_stage", ""),
        "source_name": row.get("source_name", ""),
        "source_url": row.get("source_url", ""),
    }


def write_summary(summary: dict[str, Any]) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    RUN_SUMMARY_PATH.write_text(payload, encoding="utf-8")
    LEGACY_SUMMARY_PATH.write_text(payload, encoding="utf-8")


def rebuild_static_export() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_static_site.py")],
        cwd=ROOT,
        check=True,
        timeout=120,
    )


def run_patrol(
    *,
    enable_ai: bool = True,
    rebuild_static: bool = True,
    max_ai_candidates: int | None = None,
) -> dict[str, Any]:
    start_date, end_date = recent_date_window(STRICT_RECENT_DAYS)
    # Compare against the complete pre-run inventory so an older known project
    # cannot become "new" again when a source republishes it inside this window.
    before_rows = fetch_tenders(DB_PATH)
    before_keys = project_keys(before_rows)
    sources = load_sources()

    tenders, source_statuses = run_search_with_status(
        selected_sources=balanced_source_names(sources),
        query="",
        days=STRICT_RECENT_DAYS,
        enable_ai=enable_ai,
        max_ai_candidates=max_ai_candidates,
    )
    rows = [tender_to_row(tender) for tender in tenders]
    new_raw_rows = [row for row in rows if normalize_merge_key(row) not in before_keys]
    new_rows = build_merged_rows(new_raw_rows)
    alert_rows = [row for row in new_rows if is_alert_candidate(row)]
    upserted_attempts = upsert_many(DB_PATH, tenders)

    summary = {
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workspace": str(ROOT),
        "db_path": str(DB_PATH),
        "strict_recent_days": STRICT_RECENT_DAYS,
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
        "source_count": len(balanced_source_names(sources)),
        "max_ai_candidates": max_ai_candidates,
        "raw_results": len(rows),
        "upserted_attempts": upserted_attempts,
        "new_raw_records": len(new_raw_rows),
        "new_unique_projects": len(new_rows),
        "alert_count": len(alert_rows),
        "alerts": [alert_preview(row) for row in alert_rows],
        "new_unique_preview": [alert_preview(row) for row in new_rows[:20]],
        "source_statuses": source_statuses,
    }
    write_summary(summary)
    if rebuild_static:
        rebuild_static_export()
    return summary


def main() -> int:
    args = parse_args()
    summary = run_patrol(
        enable_ai=not args.no_ai,
        rebuild_static=not args.skip_static,
        max_ai_candidates=args.max_ai_candidates,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
