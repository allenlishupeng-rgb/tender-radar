from datetime import timedelta

from crawlers import runner
from database.models import Tender
from parsers.extractors import radar_today


TODAY = radar_today()
DEADLINE = (TODAY + timedelta(days=30)).isoformat() + " 09:30"


def bid(title, priority="高优先级", score=85, url=None, published=None):
    return Tender(
        title=title,
        publish_date=(published or TODAY).isoformat(),
        source_url=url or f"https://example.com/{abs(hash(title))}",
        source_name="测试来源",
        priority=priority,
        relevance_score=score,
        notice_stage="可投公告",
    )


def test_recovery_candidates_prefer_priority_then_relevance_then_recency():
    low = bid("低", priority="低优先级", score=95)
    high_old = bid("高旧", score=90, published=TODAY - timedelta(days=5))
    high_new = bid("高新", score=90)
    high_weak = bid("高弱", score=80)
    has_deadline = bid("已有")
    has_deadline.days_left = 30
    result = bid("结果")
    result.notice_stage = "中标结果"

    picked = runner.select_recovery_candidates([low, high_old, has_deadline, high_new, high_weak, result], 3)

    assert [t.title for t in picked] == ["高新", "高旧", "高弱"]
    assert runner.select_recovery_candidates([low], 0) == []


def test_reserve_only_when_candidates_are_waiting_and_capped():
    assert runner.recovery_reserve_seconds(60, 0, 12) == 0
    assert runner.recovery_reserve_seconds(60, 5, 0) == 0
    assert runner.recovery_reserve_seconds(60, 2, 12) == 2 * runner.DETAIL_RECOVERY_SECONDS_PER_ITEM
    assert runner.recovery_reserve_seconds(60, 50, 12) == 60 * runner.DETAIL_RECOVERY_RESERVE_RATIO


class RecoveringCrawler:
    enriched = []

    def __init__(self, keywords, source_config=None, request_interval=0):
        self.last_error = ""
        self.execution_deadline = None

    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        return [
            bid("企业展厅设计施工低价值项目招标公告", priority="低优先级", score=45, url="https://example.com/low"),
            bid("企业总部展厅设计施工项目招标公告", score=92, url="https://example.com/high"),
        ]

    def enrich_from_detail(self, tender):
        self.__class__.enriched.append(tender.source_url)
        tender.bid_deadline = DEADLINE


def run_with(monkeypatch, crawler_cls, **source_extra):
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "recovering", crawler_cls)
    source = {"name": "测试来源", "crawler": "recovering", "enabled": True, "max_terms": 1,
              "min_relevance_score": 0, **source_extra}
    monkeypatch.setattr(runner, "load_yaml", lambda path: {"sources": [source]} if "sources" in str(path) else {})
    monkeypatch.setattr(runner, "passes_source_quality_gate", lambda tender, source: True)
    monkeypatch.setattr(runner, "is_target_exhibition_tender", lambda row: True)
    monkeypatch.setattr(runner, "annotate_notice_stage", lambda tender: tender)
    monkeypatch.setattr(runner, "load_source_failure_state", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(runner, "save_source_failure_state", lambda *a, **k: None, raising=False)
    return runner.run_search_with_status(selected_sources=["测试来源"], query="展厅", days=7, enable_ai=False)


def test_runner_recovers_highest_value_bid_first_within_limit(monkeypatch):
    RecoveringCrawler.enriched = []
    tenders, statuses = run_with(monkeypatch, RecoveringCrawler, detail_recovery_limit=1)

    assert RecoveringCrawler.enriched == ["https://example.com/high"]
    by_url = {t.source_url: t for t in tenders}
    assert by_url["https://example.com/high"].days_left == 30
    assert by_url["https://example.com/low"].days_left is None
    status = statuses[0]
    assert status["detail_recovered_count"] == 1
    assert status["detail_recovery_attempted"] == 1
    assert status["actionable_count"] == 1
    assert status["deadline_unknown_count"] == 1


class BrokenDetailCrawler(RecoveringCrawler):
    def enrich_from_detail(self, tender):
        raise RuntimeError("detail page changed")


def test_broken_detail_page_keeps_source_results(monkeypatch):
    tenders, statuses = run_with(monkeypatch, BrokenDetailCrawler)

    assert len(tenders) == 2
    assert statuses[0]["status"] == "成功"
    assert "详情补全失败" in statuses[0]["message"]
