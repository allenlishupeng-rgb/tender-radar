"""Refresh the interactive radar from sources proven usable by the health report."""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import DATA_DIR, DB_PATH, EXPORT_DIR
from crawlers.runner import run_search_with_status
from crawlers.source_health import load_source_failure_state, source_status_failed
from database.db import upsert_many
from utils.date_window import DEFAULT_INTERACTIVE_SEARCH_DAYS, MAX_INTERACTIVE_SEARCH_DAYS


HEALTH_REPORT = EXPORT_DIR / "source_health.json"
SUMMARY_PATH = DATA_DIR / "manual_runs" / "last_manual_refresh.json"
DEFERRED_RETRY_DAYS = 7
HEALTH_MAX_AGE_DAYS = 7


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the interactive tender radar without sending alerts.")
    parser.add_argument("--days", type=int, default=DEFAULT_INTERACTIVE_SEARCH_DAYS)
    parser.add_argument("--no-static", action="store_true", help="Skip rebuilding the static export.")
    parser.add_argument(
        "--include-deferred",
        action="store_true",
        help="Also retry sources that have repeatedly failed formal searches.",
    )
    return parser.parse_args()


def healthy_source_names(report: dict) -> list[str]:
    return list(
        dict.fromkeys(
            str(item.get("source") or "").strip()
            for item in report.get("sources", [])
            if item.get("crawl_ok") and int(item.get("count") or 0) > 0 and str(item.get("source") or "").strip()
        )
    )


def load_healthy_source_names(path: Path = HEALTH_REPORT) -> list[str]:
    if not path.exists():
        raise RuntimeError(f"Source health report not found: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    names = healthy_source_names(report)
    if not names:
        raise RuntimeError("Source health report contains no usable sources; refresh health before searching.")
    return names


def load_previous_summary(path: Path = SUMMARY_PATH) -> dict:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def parse_timestamp(value) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return timestamp.astimezone()


def refresh_health_if_needed(path: Path = HEALTH_REPORT, now: datetime | None = None) -> dict:
    current = (now or datetime.now().astimezone()).astimezone()
    report = load_previous_summary(path)
    checked_at = parse_timestamp(report.get("checked_at"))
    if checked_at is None or not timedelta(0) <= current - checked_at < timedelta(days=HEALTH_MAX_AGE_DAYS):
        print("Refreshing expired source health report...", flush=True)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_source_health.py")],
            cwd=ROOT,
            check=True,
            timeout=300,
        )
        report = load_previous_summary(path)
        checked_at = parse_timestamp(report.get("checked_at"))
        current = (now or datetime.now().astimezone()).astimezone()
        if checked_at is None or not timedelta(0) <= current - checked_at < timedelta(days=HEALTH_MAX_AGE_DAYS):
            raise RuntimeError("Source health refresh did not produce a recent report.")
    return report


def deferred_retry_due(previous_summary: dict, now: datetime | None = None) -> bool:
    last_run = parse_timestamp(previous_summary.get("last_full_recheck_at") or previous_summary.get("run_at"))
    if last_run is None:
        return False
    current = (now or datetime.now().astimezone()).astimezone()
    return current - last_run >= timedelta(days=DEFERRED_RETRY_DAYS)


def select_refresh_sources(
    healthy_names: list[str],
    previous_summary: dict,
    include_deferred: bool = False,
    now: datetime | None = None,
    failure_state: dict | None = None,
) -> tuple[list[str], list[dict]]:
    if include_deferred:
        return healthy_names, []

    current = (now or datetime.now().astimezone()).astimezone()
    previous_statuses = {
        str(item.get("source") or "").strip(): {
            **item,
            "status": item.get("last_status", ""),
            "count": 0,
        }
        for item in previous_summary.get("deferred_sources", [])
        if str(item.get("source") or "").strip()
    }
    previous_statuses.update({
        str(item.get("source") or "").strip(): item
        for item in previous_summary.get("source_statuses", [])
        if str(item.get("source") or "").strip()
    })
    for source_name, record in (failure_state or {}).items():
        previous_statuses[source_name] = {
            "status": record.get("last_status", ""),
            "count": record.get("last_count", 0),
            "failure_streak": record.get("failure_streak", 0),
            "last_checked_at": record.get("updated_at", ""),
        }
    selected: list[str] = []
    deferred: list[dict] = []
    for source_name in healthy_names:
        status = previous_statuses.get(source_name)
        failure_streak = int((status or {}).get("failure_streak") or 0)
        returned_count = int((status or {}).get("count") or 0)
        last_checked = parse_timestamp(
            (status or {}).get("last_checked_at") or previous_summary.get("run_at")
        )
        retry_due = last_checked is None or current - last_checked >= timedelta(days=DEFERRED_RETRY_DAYS)
        if status and source_status_failed(status) and failure_streak >= 2 and returned_count == 0 and not retry_due:
            deferred.append(
                {
                    "source": source_name,
                    "last_status": status.get("status", ""),
                    "failure_streak": failure_streak,
                    "last_checked_at": last_checked.isoformat(timespec="seconds"),
                    "reason": "连续正式搜索访问失败，本轮暂缓；可用 --include-deferred 强制重试",
                }
            )
            continue
        selected.append(source_name)
    return selected, deferred


def rebuild_static(days: int) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_static_site.py"), "--days", str(days)],
        cwd=ROOT,
        check=True,
        timeout=120,
    )


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    days = min(max(int(args.days), 1), MAX_INTERACTIVE_SEARCH_DAYS)
    health_report = refresh_health_if_needed()
    healthy_names = load_healthy_source_names()
    previous_summary = load_previous_summary()
    retry_due = deferred_retry_due(previous_summary)
    selected, deferred = select_refresh_sources(
        healthy_names,
        previous_summary,
        include_deferred=args.include_deferred,
        failure_state=load_source_failure_state(),
    )
    if not selected:
        raise RuntimeError("All healthy sources are deferred; rerun with --include-deferred.")
    print(f"Searching {len(selected)} sources; deferring {len(deferred)} repeatedly failing sources...", flush=True)
    tenders, statuses = run_search_with_status(
        selected_sources=selected,
        query="",
        days=days,
        enable_ai=False,
    )
    upserted = upsert_many(DB_PATH, tenders)
    main_count = sum(1 for item in tenders if getattr(item, "review_bucket", "主结果") != "待研判")
    review_count = len(tenders) - main_count
    if not args.no_static:
        rebuild_static(days)

    run_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for status in statuses:
        status["last_checked_at"] = run_at
    summary = {
        "run_at": run_at,
        "last_full_recheck_at": run_at if not deferred else (
            previous_summary.get("last_full_recheck_at") or previous_summary.get("run_at")
        ),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "health_checked_at": health_report.get("checked_at", ""),
        "days": days,
        "healthy_source_count": len(healthy_names),
        "deferred_recheck_due": retry_due,
        "deferred_recheck_days": DEFERRED_RETRY_DAYS,
        "selected_source_count": len(selected),
        "selected_sources": selected,
        "deferred_source_count": len(deferred),
        "deferred_sources": deferred,
        "returned": len(tenders),
        "main_count": main_count,
        "review_count": review_count,
        "upserted_attempts": upserted,
        "source_statuses": statuses,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
