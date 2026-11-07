"""Collect on this computer, then publish a bundle for the cloud workbench.

Use this when the cloud host cannot reach mainland procurement sites. The
computer inside China runs the search, keeps its own SQLite inventory and
writes ``collection_bundle.json`` with public announcement fields only.

Delivery options (pick one):
  --publish-dir DIR   copy the bundle into a local clone of a PRIVATE data
                      repository, then git commit and push it there; the cloud
                      pulls it from RADAR_SYNC_URL.
  (no option)         only write the file; upload it on the cloud page under
                      "本机采集同步".

This script never schedules itself and sends no notifications.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collection_sync.bundle import build_bundle, write_bundle
from config.settings import DB_PATH, EXPORT_DIR
from database.db import fetch_tenders, upsert_many
from parsers.extractors import radar_today
from presentation.search_report import build_search_report, save_search_report
from utils.date_window import MAX_INTERACTIVE_SEARCH_DAYS


BUNDLE_NAME = "collection_bundle.json"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, choices=range(1, MAX_INTERACTIVE_SEARCH_DAYS + 1), default=30)
    parser.add_argument("--depth", choices=["standard", "deep"], default="deep")
    parser.add_argument("--source", action="append", help="Repeat to limit sources; default: all enabled sources.")
    parser.add_argument("--skip-search", action="store_true", help="Do not search; bundle the existing local inventory.")
    parser.add_argument("--output", type=Path, default=EXPORT_DIR / BUNDLE_NAME)
    parser.add_argument("--publish-dir", type=Path, default=os.getenv("RADAR_SYNC_REPO_DIR") or None,
                        help="Local clone of a private data repository (or set RADAR_SYNC_REPO_DIR).")
    parser.add_argument("--no-push", action="store_true", help="Commit in --publish-dir but do not push.")
    return parser.parse_args(argv)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120)


def check_publish_dir(repo: Path) -> None:
    repo = repo.resolve()
    if repo == ROOT.resolve() or ROOT.resolve() in repo.parents:
        raise SystemExit("--publish-dir 不能是招标雷达源码仓库本身（它是公开仓库）。请使用单独的私有数据仓库。")
    if git(repo, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise SystemExit(f"{repo} 不是 git 仓库。请先克隆你的私有数据仓库。")


def publish(bundle_path: Path, repo: Path, push: bool) -> str:
    check_publish_dir(repo)
    target = repo / BUNDLE_NAME
    shutil.copyfile(bundle_path, target)
    git(repo, "add", BUNDLE_NAME)
    if not git(repo, "status", "--porcelain", "--", BUNDLE_NAME).stdout.strip():
        return "采集包与上次相同，无需提交"
    commit = git(repo, "commit", "-m", f"collection {time.strftime('%Y-%m-%d %H:%M')}", "--", BUNDLE_NAME)
    if commit.returncode:
        raise SystemExit("git commit 失败：" + (commit.stderr or commit.stdout).strip())
    if not push:
        return "已提交到本地数据仓库（未推送）"
    for attempt in range(4):
        pushed = git(repo, "push")
        if pushed.returncode == 0:
            return "已推送到数据仓库"
        time.sleep(2 ** (attempt + 1))
    raise SystemExit("git push 失败：" + (pushed.stderr or pushed.stdout).strip())


def main(argv=None) -> int:
    args = parse_args(argv)
    end = radar_today()
    start = end - timedelta(days=args.days - 1)
    report = {}
    if not args.skip_search:
        from crawlers.runner import run_search_with_status

        def progress(status, completed, total):
            print(f"[{completed}/{total}] {status['source']}: {status['status']}，候选 {status['count']} 条，"
                  f"20天可用 {status.get('actionable_count', 0)} 条", flush=True)

        started = time.monotonic()
        tenders, statuses = run_search_with_status(
            selected_sources=args.source, query="", days=args.days, enable_ai=False,
            search_depth=args.depth, progress_callback=progress,
        )
        upsert_many(DB_PATH, tenders)
        report = build_search_report(tenders, statuses, days=args.days, depth=args.depth)
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        save_search_report(report)

    # Ship the whole local window, not only this run, so a cloud restart that
    # wiped its database is fully restored by one import.
    rows = fetch_tenders(DB_PATH, start_date=start.isoformat(), end_date=end.isoformat())
    bundle = build_bundle(rows, report=report, window=(start.isoformat(), end.isoformat()))
    path = write_bundle(bundle, args.output)
    signed = "已签名" if bundle.get("signature") else "未签名（未设置 RADAR_SYNC_KEY）"
    print(f"采集包：{path}（{bundle['row_count']} 条，{signed}）", flush=True)
    if args.publish_dir:
        print(publish(path, Path(args.publish_dir), push=not args.no_push), flush=True)
    else:
        print("未设置 --publish-dir：请在云端页面“本机采集同步”中上传这个文件。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
