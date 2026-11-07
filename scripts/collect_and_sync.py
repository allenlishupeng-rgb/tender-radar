"""Collect on this computer, then publish a bundle for the cloud workbench.

Use this when the cloud host cannot reach mainland procurement sites. The
computer inside China runs the search, keeps its own SQLite inventory and
writes ``collection_bundle.json`` with public announcement fields only.

First time on this computer:
  python scripts/collect_and_sync.py --setup D:/tender-radar-data
      checks the private data clone, creates the signing key, saves both in
      config/sync.local.yaml (git-ignored) and prints the cloud Secrets.
  python scripts/collect_and_sync.py --check
      re-checks the setup without collecting anything.

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
import re
import secrets
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

import requests
import yaml


BUNDLE_NAME = "collection_bundle.json"
LOCAL_CONFIG_PATH = ROOT / "config" / "sync.local.yaml"


def load_local_config(path: Path | None = None) -> dict:
    path = path or LOCAL_CONFIG_PATH
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except OSError:
        return {}


def save_local_config(config: dict, path: Path | None = None) -> None:
    Path(path or LOCAL_CONFIG_PATH).write_text(
        "# Local sync settings for this computer only. Never commit this file.\n"
        + yaml.safe_dump(config, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def github_remote(repo: Path) -> tuple[str, str] | None:
    url = git(repo, "remote", "get-url", "origin").stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return (match.group(1), match.group(2)) if match else None


def github_visibility(owner: str, name: str, getter=requests.get) -> str:
    """'public', 'private' (anonymous 404) or 'unknown' (network/rate limit)."""
    try:
        response = getter(f"https://api.github.com/repos/{owner}/{name}", timeout=10,
                          headers={"Accept": "application/vnd.github+json", "User-Agent": "tender-radar-sync"})
    except requests.RequestException:
        return "unknown"
    if response.status_code == 404:
        return "private"
    if response.status_code == 200:
        return "private" if response.json().get("private") else "public"
    return "unknown"


def sync_url_for(owner: str, name: str) -> str:
    return f"https://api.github.com/repos/{owner}/{name}/contents/{BUNDLE_NAME}"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, choices=range(1, MAX_INTERACTIVE_SEARCH_DAYS + 1), default=30)
    parser.add_argument("--depth", choices=["standard", "deep"], default="deep")
    parser.add_argument("--source", action="append", help="Repeat to limit sources; default: all enabled sources.")
    parser.add_argument("--skip-search", action="store_true", help="Do not search; bundle the existing local inventory.")
    parser.add_argument("--output", type=Path, default=EXPORT_DIR / BUNDLE_NAME)
    parser.add_argument("--publish-dir", type=Path, default=None,
                        help="Local clone of a private data repository (default: RADAR_SYNC_REPO_DIR or the saved setup).")
    parser.add_argument("--no-push", action="store_true", help="Commit in --publish-dir but do not push.")
    parser.add_argument("--setup", type=Path, metavar="DATA_REPO_DIR", help="One-time setup for this computer.")
    parser.add_argument("--check", action="store_true", help="Check the saved setup and exit.")
    args = parser.parse_args(argv)
    config = load_local_config()
    if args.publish_dir is None:
        configured = os.getenv("RADAR_SYNC_REPO_DIR") or config.get("publish_dir")
        args.publish_dir = Path(configured) if configured else None
    if not os.getenv("RADAR_SYNC_KEY") and config.get("sync_key"):
        os.environ["RADAR_SYNC_KEY"] = str(config["sync_key"])
    if not os.getenv("RADAR_COLLECTOR_NAME") and config.get("collector_name"):
        os.environ["RADAR_COLLECTOR_NAME"] = str(config["collector_name"])
    return args


GIT_TIMEOUT_SECONDS = 60


def git(repo: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    command = ["git", "-C", str(repo), *args]
    # git prints UTF-8; Chinese Windows would otherwise decode it as GBK and crash.
    # GIT_TERMINAL_PROMPT=0 makes a missing login fail fast instead of waiting
    # for a hidden password prompt.
    try:
        return subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError:
        raise SystemExit("找不到 git 命令：请安装 Git for Windows（https://git-scm.com/download/win），安装后重新打开 PowerShell。")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"git {' '.join(args)} 超过 {timeout:.0f} 秒未完成")


def git_error(result: subprocess.CompletedProcess) -> str:
    lines = [line.strip() for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
    return lines[-1] if lines else f"git 退出码 {result.returncode}"


def check_publish_dir(repo: Path) -> None:
    repo = repo.resolve()
    if repo == ROOT.resolve() or ROOT.resolve() in repo.parents:
        raise SystemExit("--publish-dir 不能是招标雷达源码仓库本身（它是公开仓库）。请使用单独的私有数据仓库。")
    if git(repo, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise SystemExit(f"{repo} 不是 git 仓库。请先克隆你的私有数据仓库。")
    remote = github_remote(repo)
    if remote and github_visibility(*remote) == "public":
        raise SystemExit(f"数据仓库 {remote[0]}/{remote[1]} 是公开的。采集包会暴露你的业务画像，请在 GitHub 把它改为 Private。")


def setup(repo: Path) -> int:
    check_publish_dir(repo)
    remote = github_remote(repo)
    if not remote:
        raise SystemExit("数据仓库的 origin 不是 GitHub 地址。请克隆 GitHub 上的私有仓库。")
    config = load_local_config()
    config["publish_dir"] = str(repo.resolve())
    config["sync_key"] = config.get("sync_key") or os.getenv("RADAR_SYNC_KEY") or secrets.token_urlsafe(32)
    config.setdefault("collector_name", "本机采集")
    save_local_config(config)
    print(f"已保存本机设置：{LOCAL_CONFIG_PATH}（不会提交到 Git）")
    print("\n把下面几行粘贴到 Streamlit Cloud → App settings → Secrets（保留原有的 RADAR_TEAM_PASSWORD）：\n")
    print('RADAR_COLLECTION_MODE = "local"')
    print(f'RADAR_SYNC_URL = "{sync_url_for(*remote)}"')
    print('RADAR_SYNC_TOKEN = "<在 GitHub 为该仓库生成的只读 token>"')
    print(f'RADAR_SYNC_KEY = "{config["sync_key"]}"')
    print("\n签名密钥只在这台电脑和 Streamlit Secrets 中保存，不要发到聊天或邮件里。")
    return 0


def check(args) -> int:
    ok = True

    def report(passed: bool, text: str) -> None:
        nonlocal ok
        ok = ok and passed
        print(("[通过] " if passed else "[问题] ") + text)

    report(bool(os.getenv("RADAR_SYNC_KEY")), "签名密钥已设置" if os.getenv("RADAR_SYNC_KEY") else "未设置签名密钥：先运行 --setup")
    if not args.publish_dir:
        report(False, "未设置数据仓库目录：先运行 --setup")
        return 1
    repo = Path(args.publish_dir)
    try:
        check_publish_dir(repo)
        report(True, f"数据仓库目录：{repo}")
    except SystemExit as exc:
        report(False, str(exc))
        return 1
    remote = github_remote(repo)
    if remote:
        visibility = github_visibility(*remote)
        report(visibility != "public", f"数据仓库 {remote[0]}/{remote[1]}：" +
               {"private": "私有", "public": "公开（必须改为 Private）", "unknown": "无法确认可见性（网络受限）"}[visibility])
        print(f"       云端 RADAR_SYNC_URL 应为：{sync_url_for(*remote)}")
    listing = git(repo, "ls-remote", "--heads", "origin")
    if listing.returncode == 0:
        report(True, "可以连接数据仓库")
    else:
        report(False, "连不上数据仓库：" + git_error(listing))
        print("       在数据仓库目录运行一次 git pull，按提示登录 GitHub 后再重试。")
    print("全部通过，可以运行采集。" if ok else "请先处理上面的问题。")
    return 0 if ok else 1


def publish(bundle_path: Path, repo: Path, push: bool) -> str:
    check_publish_dir(repo)
    target = repo / BUNDLE_NAME
    shutil.copyfile(bundle_path, target)
    git(repo, "add", BUNDLE_NAME)
    if not git(repo, "status", "--porcelain", "--", BUNDLE_NAME).stdout.strip():
        return "采集包与上次相同，无需提交"
    commit = git(repo, "commit", "-m", f"collection {time.strftime('%Y-%m-%d %H:%M')}", "--", BUNDLE_NAME)
    if commit.returncode:
        raise SystemExit("git commit 失败：" + git_error(commit))
    if not push:
        return "已提交到本地数据仓库（未推送）"
    for attempt in range(4):
        pushed = git(repo, "push")
        if pushed.returncode == 0:
            return "已推送到数据仓库"
        time.sleep(2 ** (attempt + 1))
    raise SystemExit("git push 失败：" + git_error(pushed))


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.setup:
        return setup(args.setup)
    if args.check:
        return check(args)
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
