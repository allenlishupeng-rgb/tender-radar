from crawlers.errors import friendly_error_message
from crawlers.runner import run_search_with_status


def test_friendly_error_message_hides_connection_codes():
    msg = friendly_error_message("ConnectionResetError(10054, '远程主机强迫关闭了一个现有的连接。')")

    assert "10054" not in msg
    assert "重置" in msg


def test_friendly_error_message_handles_frequent_access():
    msg = friendly_error_message("频繁访问")

    assert "访问过于频繁" in msg


def test_runner_marks_timeout_source_as_access_limited(monkeypatch):
    from crawlers import runner
    from crawlers.base import BaseCrawler

    class TimeoutCrawler(BaseCrawler):
        name = "timeout"

        def search(self, *args, **kwargs):
            self.last_error = "对方网站响应超时，已跳过。本次没有从该来源获取到新线索。"
            return []

    monkeypatch.setattr(runner, "load_yaml", lambda path: {"sources": [{"name": "测试源", "crawler": "timeout"}]})
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "timeout", TimeoutCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    _results, statuses = run_search_with_status(selected_sources=["测试源"])

    assert statuses[0]["status"] == "访问失败/受限"


def test_high_risk_source_failure_alert(tmp_path):
    from crawlers.runner import apply_source_failure_alerts

    sources = [{"name": "高风险源", "risk_level": "高", "source_weight": 0.35, "failure_alert_threshold": 2}]
    statuses = [{"source": "高风险源", "status": "访问失败/受限", "count": 0, "message": ""}]

    first = apply_source_failure_alerts([dict(statuses[0])], sources, state_path=tmp_path / "failures.json")
    second = apply_source_failure_alerts([dict(statuses[0])], sources, state_path=tmp_path / "failures.json")

    assert first[0]["failure_streak"] == 1
    assert "alert" not in first[0]
    assert second[0]["failure_streak"] == 2
    assert "连续 2 次" in second[0]["alert"]


def test_no_result_resets_stale_failure_streak(tmp_path):
    import json

    from crawlers.runner import apply_source_failure_alerts

    state_path = tmp_path / "failures.json"
    state_path.write_text(
        json.dumps({"高风险源": {"failure_streak": 9}}, ensure_ascii=False),
        encoding="utf-8",
    )
    sources = [{"name": "高风险源", "risk_level": "高", "source_weight": 0.35, "failure_alert_threshold": 2}]
    statuses = [{"source": "高风险源", "status": "无结果", "count": 0, "message": ""}]

    result = apply_source_failure_alerts(statuses, sources, state_path=state_path)

    assert result[0]["failure_streak"] == 0
    assert "alert" not in result[0]


def test_unexpected_crawler_failures_are_counted_for_recovery_scheduling(tmp_path):
    from crawlers.source_health import apply_source_failure_alerts, source_status_failed

    path = tmp_path / "failures.json"
    status = {"source": "故障来源", "status": "失败", "count": 0}
    assert source_status_failed(status)
    apply_source_failure_alerts([dict(status)], [], state_path=path)
    second = apply_source_failure_alerts([dict(status)], [], state_path=path)
    assert second[0]["failure_streak"] == 2
