import json
from datetime import datetime, timezone

from presentation.refresh_status import load_refresh_status


def test_refresh_status_distinguishes_fresh_and_stale_data(tmp_path):
    path = tmp_path / "refresh.json"
    path.write_text(json.dumps({"run_at": "2026-10-01T12:00:00+00:00"}), encoding="utf-8")
    fresh = load_refresh_status(path, now=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc))
    stale = load_refresh_status(path, now=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc))
    assert fresh["stale"] is False
    assert stale["stale"] is True
    assert "数据已过期" in stale["text"]


def test_missing_refresh_record_is_visible(tmp_path):
    result = load_refresh_status(tmp_path / "missing.json")
    assert result["stale"] is True
    assert result["text"] == "暂无有效刷新记录"


def test_current_search_supersedes_stale_manual_refresh(tmp_path):
    path = tmp_path / "refresh.json"
    path.write_text(json.dumps({"run_at": "2026-09-01T12:00:00+00:00"}), encoding="utf-8")
    result = load_refresh_status(
        path, now=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
        search_at="2026-10-19T11:00:00+00:00",
    )
    assert result["stale"] is False
    assert result["text"].startswith("最近搜索：")
