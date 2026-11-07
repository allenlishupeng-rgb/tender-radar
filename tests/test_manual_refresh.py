import pytest
import json
from datetime import datetime, timezone

from scripts.run_manual_refresh import (
    deferred_retry_due,
    healthy_source_names,
    load_healthy_source_names,
    select_refresh_sources,
    refresh_health_if_needed,
)


def test_healthy_source_names_uses_structural_health_fields():
    report = {
        "sources": [
            {"source": "稳定来源", "crawl_ok": True, "count": 4, "status": "任意显示文本"},
            {"source": "空来源", "crawl_ok": False, "count": 0, "status": "可用"},
            {"source": "稳定来源", "crawl_ok": True, "count": 2},
        ]
    }

    assert healthy_source_names(report) == ["稳定来源"]


def test_manual_refresh_rejects_empty_health_selection(tmp_path):
    report = tmp_path / "health.json"
    report.write_text('{"sources": []}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="no usable sources"):
        load_healthy_source_names(report)


def test_select_refresh_sources_defers_only_repeated_formal_failures():
    healthy_names = ["稳定来源", "暂时无结果", "首次失败", "连续失败", "新来源"]
    previous_summary = {
        "source_statuses": [
            {"source": "稳定来源", "status": "成功", "count": 3, "failure_streak": 0},
            {"source": "暂时无结果", "status": "无结果", "count": 0, "failure_streak": 0},
            {"source": "首次失败", "status": "访问失败/受限", "count": 0, "failure_streak": 1},
            {"source": "连续失败", "status": "访问失败/受限", "count": 0, "failure_streak": 4},
        ]
    }

    previous_summary["run_at"] = "2026-09-13T12:00:00+00:00"
    selected, deferred = select_refresh_sources(
        healthy_names,
        previous_summary,
        now=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert selected == ["稳定来源", "暂时无结果", "首次失败", "新来源"]
    assert [item["source"] for item in deferred] == ["连续失败"]
    assert deferred[0]["failure_streak"] == 4
    assert datetime.fromisoformat(deferred[0]["last_checked_at"]) == datetime.fromisoformat(previous_summary["run_at"])


def test_select_refresh_sources_can_force_full_retry():
    healthy_names = ["稳定来源", "连续失败"]
    previous_summary = {
        "source_statuses": [
            {"source": "连续失败", "status": "访问失败/受限", "count": 0, "failure_streak": 9}
        ]
    }

    selected, deferred = select_refresh_sources(healthy_names, previous_summary, include_deferred=True)

    assert selected == healthy_names
    assert deferred == []


def test_deferred_retry_due_after_seven_days():
    summary = {"run_at": "2026-09-01T12:00:00+00:00"}

    assert deferred_retry_due(
        summary,
        now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )


def test_daily_refresh_does_not_postpone_weekly_recheck():
    summary = {
        "run_at": "2026-09-07T12:00:00+00:00",
        "last_full_recheck_at": "2026-09-01T12:00:00+00:00",
    }
    assert deferred_retry_due(summary, now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc))


def test_deferred_sources_survive_consecutive_runs_and_retry_when_due():
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    summary = {
        "run_at": "2026-09-01T12:00:00+00:00",
        "source_statuses": [
            {"source": "连续失败", "status": "访问失败/受限", "count": 0, "failure_streak": 9}
        ],
    }
    selected, deferred = select_refresh_sources(["稳定来源", "连续失败"], summary, now=now)
    assert selected == ["稳定来源"]
    next_summary = {"run_at": now.isoformat(), "source_statuses": [], "deferred_sources": deferred}
    selected, retained = select_refresh_sources(
        ["稳定来源", "连续失败"], next_summary,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert selected == ["稳定来源"]
    assert retained[0]["last_checked_at"] == deferred[0]["last_checked_at"]
    selected, retained = select_refresh_sources(
        ["稳定来源", "连续失败"], next_summary,
        now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )
    assert selected == ["稳定来源", "连续失败"]
    assert retained == []


def test_latest_formal_success_restores_deferred_source():
    summary = {
        "run_at": "2026-09-01T12:00:00+00:00",
        "source_statuses": [
            {"source": "恢复来源", "status": "访问失败/受限", "count": 0, "failure_streak": 9}
        ],
    }
    state = {"恢复来源": {
        "last_status": "成功", "last_count": 2, "failure_streak": 0,
        "updated_at": "2026-09-02T12:00:00+00:00",
    }}
    selected, deferred = select_refresh_sources(
        ["恢复来源"], summary, failure_state=state,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert selected == ["恢复来源"]
    assert deferred == []


def test_stale_health_report_is_refreshed_before_source_selection(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    path.write_text('{"checked_at": "2026-08-01T12:00:00+00:00"}', encoding="utf-8")
    calls = []

    def refresh(command, **kwargs):
        calls.append(command)
        path.write_text(json.dumps({"checked_at": "2026-09-03T12:00:00+00:00"}), encoding="utf-8")

    monkeypatch.setattr("scripts.run_manual_refresh.subprocess.run", refresh)
    report = refresh_health_if_needed(path, now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc))
    assert len(calls) == 1
    assert report["checked_at"] == "2026-09-03T12:00:00+00:00"
    refresh_health_if_needed(path, now=datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc))
    assert len(calls) == 1


def test_health_refresh_failure_does_not_search_with_old_report(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    path.write_text('{"checked_at": "2026-08-01T12:00:00+00:00"}', encoding="utf-8")
    monkeypatch.setattr("scripts.run_manual_refresh.subprocess.run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="did not produce a recent report"):
        refresh_health_if_needed(path, now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc))


def test_select_refresh_sources_rechecks_all_sources_when_due():
    healthy_names = ["稳定来源", "连续失败"]
    previous_summary = {
        "run_at": "2026-09-01T12:00:00+00:00",
        "source_statuses": [
            {"source": "连续失败", "status": "访问失败/受限", "count": 0, "failure_streak": 9}
        ],
    }

    selected, deferred = select_refresh_sources(
        healthy_names,
        previous_summary,
        now=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert selected == healthy_names
    assert deferred == []
