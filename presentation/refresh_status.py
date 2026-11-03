"""Display persisted refresh time without treating page visits as searches."""

import json
from datetime import datetime, timedelta
from pathlib import Path


def load_refresh_status(path: Path, now: datetime | None = None, search_at: str | None = None) -> dict:
    refreshed = None
    label = "最近完整刷新"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        refreshed = datetime.fromisoformat(summary["run_at"]).astimezone()
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if search_at:
        try:
            searched = datetime.fromisoformat(search_at).astimezone()
            if refreshed is None or searched > refreshed:
                refreshed = searched
                label = "最近搜索"
        except ValueError:
            pass
    if refreshed is None:
        return {"stale": True, "text": "暂无有效刷新记录"}
    current = (now or datetime.now().astimezone()).astimezone()
    age = current - refreshed
    stale = age >= timedelta(days=7) or age < timedelta(0)
    text = f"{label}：{refreshed:%Y-%m-%d %H:%M}"
    if stale:
        text += "；数据已过期，请重新搜索" if age >= timedelta(0) else "；刷新时间异常，请核对系统时间"
    return {"stale": stale, "text": text}
