"""Collection bundles: collect on a machine inside China, import in the cloud.

A bundle is one JSON file holding public announcement fields only. Personal
fields (read flag, remarks, feedback labels, scores) are never exported, and
importing never overwrites the team's own fields in the cloud database,
because ``upsert_tender`` leaves them untouched on conflict.

When ``RADAR_SYNC_KEY`` is set on both sides, the bundle carries an
HMAC-SHA256 signature and the importer rejects unsigned or altered files.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config.settings import DATA_DIR
from database.db import upsert_many
from database.models import Tender


BUNDLE_FORMAT = "tender-radar-collection"
BUNDLE_VERSION = 1
MAX_BUNDLE_BYTES = 30 * 1024 * 1024
MAX_BUNDLE_ROWS = 20000
MAX_TEXT_LENGTH = 20000
SYNC_STATE_PATH = DATA_DIR / "last_sync.json"
AUTO_PULL_INTERVAL_SECONDS = 10 * 60

PERSONAL_FIELDS = {"is_read", "remark", "feedback_label", "user_score", "user_score_updated_at"}
PUBLIC_FIELDS = [f.name for f in fields(Tender) if f.name not in PERSONAL_FIELDS]
INT_FIELDS = {"days_left", "relevance_score", "ai_score_adjustment"}
BOOL_FIELDS = {"ai_classified"}
OPTIONAL_BOOL_FIELDS = {"ai_is_relevant"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")

_pull_lock = threading.Lock()


class BundleError(ValueError):
    """The file is not a usable collection bundle."""


def _canonical(payload: dict) -> bytes:
    body = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict, key: str) -> str:
    return hmac.new(key.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def _public_row(item: Any) -> dict:
    source = item if isinstance(item, dict) else vars(item)
    row = {name: source.get(name) for name in PUBLIC_FIELDS if name in source}
    keywords = row.get("matched_keywords")
    if isinstance(keywords, str):
        try:
            row["matched_keywords"] = json.loads(keywords)
        except ValueError:
            row["matched_keywords"] = [part for part in re.split(r"[、,，]", keywords) if part]
    return row


def build_bundle(
    tenders: list[Any],
    *,
    report: dict | None = None,
    collector: str | None = None,
    window: tuple[str, str] | None = None,
    key: str | None = None,
) -> dict:
    rows = [_public_row(item) for item in tenders]
    payload = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "collector": collector or os.getenv("RADAR_COLLECTOR_NAME") or "本机采集",
        "window": {"start": window[0], "end": window[1]} if window else None,
        "row_count": len(rows),
        "report": {k: v for k, v in (report or {}).items() if k != "rows"},
        "rows": rows,
    }
    payload["bundle_id"] = hashlib.sha256(_canonical(payload)).hexdigest()[:16]
    key = key if key is not None else os.getenv("RADAR_SYNC_KEY", "")
    if key:
        payload["signature"] = sign_payload(payload, key)
    return payload


def write_bundle(bundle: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=1)
        temporary = handle.name
    os.replace(temporary, path)
    return path


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)[:MAX_TEXT_LENGTH]


def _row_to_tender(row: Any, index: int) -> Tender:
    if not isinstance(row, dict):
        raise BundleError(f"第 {index + 1} 行不是对象")
    title = _text(row.get("title")).strip()
    url = _text(row.get("source_url")).strip()
    if not title:
        raise BundleError(f"第 {index + 1} 行缺少标题")
    # Links are rendered as clickable anchors: only plain web links are allowed.
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise BundleError(f"第 {index + 1} 行原文链接无效：{url[:80]}")
    values: dict[str, Any] = {}
    for name in PUBLIC_FIELDS:
        if name not in row:
            continue
        value = row[name]
        if name in INT_FIELDS:
            try:
                values[name] = None if value in (None, "") else int(value)
            except (TypeError, ValueError):
                values[name] = None if name == "days_left" else 0
        elif name in BOOL_FIELDS:
            values[name] = bool(value)
        elif name in OPTIONAL_BOOL_FIELDS:
            values[name] = None if value is None else bool(value)
        elif name == "matched_keywords":
            values[name] = [_text(item)[:100] for item in value][:100] if isinstance(value, list) else []
        else:
            values[name] = _text(value)
    for name in ("publish_date", "bid_deadline_date"):
        if values.get(name) and not DATE_PATTERN.match(values[name]):
            values[name] = ""
    values["title"], values["source_url"] = title, url
    if values.get("relevance_score") is None:
        values["relevance_score"] = 0
    return Tender(**values)


def parse_bundle(raw: bytes, key: str | None = None) -> tuple[list[Tender], dict]:
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleError(f"采集包超过 {MAX_BUNDLE_BYTES // 1024 // 1024} MB 上限")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BundleError("不是有效的 JSON 采集包") from exc
    if not isinstance(payload, dict) or payload.get("format") != BUNDLE_FORMAT:
        raise BundleError("文件不是招标雷达采集包")
    if payload.get("version") != BUNDLE_VERSION:
        raise BundleError(f"不支持的采集包版本：{payload.get('version')}")
    key = key if key is not None else os.getenv("RADAR_SYNC_KEY", "")
    if key:
        signature = payload.get("signature")
        if not isinstance(signature, str) or not hmac.compare_digest(signature, sign_payload(payload, key)):
            raise BundleError("采集包签名无效：文件被修改，或两端 RADAR_SYNC_KEY 不一致")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise BundleError("采集包缺少 rows 列表")
    if len(rows) > MAX_BUNDLE_ROWS:
        raise BundleError(f"采集包超过 {MAX_BUNDLE_ROWS} 行上限")
    tenders = [_row_to_tender(row, index) for index, row in enumerate(rows)]
    meta = {key_: payload.get(key_) for key_ in ("bundle_id", "generated_at", "collector", "window", "report")}
    meta["row_count"] = len(tenders)
    meta["signed"] = bool(payload.get("signature"))
    return tenders, meta


def load_sync_state(path: Path = SYNC_STATE_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_sync_state(state: dict, path: Path = SYNC_STATE_PATH) -> None:
    write_bundle(state, Path(path))


def import_bundle(
    db_path: Path,
    raw: bytes,
    *,
    key: str | None = None,
    origin: str = "上传",
    state_path: Path = SYNC_STATE_PATH,
    report_saver=None,
) -> dict:
    tenders, meta = parse_bundle(raw, key=key)
    state = load_sync_state(state_path)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if meta["bundle_id"] and meta["bundle_id"] == state.get("bundle_id"):
        state.update({"checked_at": now, "last_result": "已是最新"})
        save_sync_state(state, state_path)
        return {**meta, "imported": 0, "skipped": True, "origin": origin}
    imported = upsert_many(db_path, tenders)
    if report_saver is not None and meta.get("report"):
        report_saver({**meta["report"], "run_at": meta.get("generated_at"), "collector": meta.get("collector")})
    state = {
        "bundle_id": meta["bundle_id"],
        "generated_at": meta["generated_at"],
        "collector": meta["collector"],
        "row_count": meta["row_count"],
        "imported_at": now,
        "checked_at": now,
        "origin": origin,
        "signed": meta["signed"],
        "last_result": f"导入 {imported} 条",
    }
    save_sync_state(state, state_path)
    return {**meta, "imported": imported, "skipped": False, "origin": origin}


def fetch_bundle(url: str, token: str = "", timeout: float = 20) -> bytes:
    headers = {"Accept": "application/vnd.github.raw", "User-Agent": "tender-radar-sync"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
        if response.status_code != 200:
            raise BundleError(f"同步地址返回 HTTP {response.status_code}")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BUNDLE_BYTES:
                raise BundleError("同步地址的采集包超过大小上限")
            chunks.append(chunk)
    return b"".join(chunks)


def sync_settings() -> dict:
    return {
        "url": os.getenv("RADAR_SYNC_URL", "").strip(),
        "token": os.getenv("RADAR_SYNC_TOKEN", "").strip(),
        "key": os.getenv("RADAR_SYNC_KEY", ""),
    }


def pull_and_import(db_path: Path, *, force: bool = False, state_path: Path = SYNC_STATE_PATH,
                    report_saver=None, fetcher=fetch_bundle, now: float | None = None) -> dict | None:
    """Pull the bundle from RADAR_SYNC_URL; throttled unless forced.

    Returns None when nothing was attempted (no URL, throttled, or another
    pull is running in this process).
    """
    settings = sync_settings()
    if not settings["url"]:
        return None
    state = load_sync_state(state_path)
    current = time.time() if now is None else now
    last_checked = state.get("checked_epoch", 0)
    if not force and current - float(last_checked or 0) < AUTO_PULL_INTERVAL_SECONDS:
        return None
    if not _pull_lock.acquire(blocking=False):
        return None
    try:
        state["checked_epoch"] = current
        save_sync_state(state, state_path)
        try:
            raw = fetcher(settings["url"], settings["token"])
            result = import_bundle(db_path, raw, key=settings["key"], origin="同步地址",
                                   state_path=state_path, report_saver=report_saver)
        except (BundleError, requests.RequestException) as exc:
            state = load_sync_state(state_path)
            state.update({"last_result": f"拉取失败：{exc}", "checked_epoch": current})
            save_sync_state(state, state_path)
            return {"error": str(exc)}
        state = load_sync_state(state_path)
        state["checked_epoch"] = current
        save_sync_state(state, state_path)
        return result
    finally:
        _pull_lock.release()
