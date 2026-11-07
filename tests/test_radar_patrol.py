from database.models import Tender
from scripts import run_radar_patrol as patrol
from datetime import timedelta

from parsers.extractors import radar_today


# The team build hides bids with fewer than 20 days left or an unknown deadline.
FUTURE_DEADLINE = (radar_today() + timedelta(days=25)).isoformat() + " 09:30"


def test_patrol_alerts_only_for_new_qualified_projects(monkeypatch, tmp_path):
    new_tender = Tender(
        title="企业展厅设计采购公告",
        publish_date="2026-07-20",
        source_url="https://example.com/new",
        source_name="测试来源",
        priority="高优先级",
        notice_stage="可投公告",
        bid_deadline=FUTURE_DEADLINE,
    )
    existing_tender = Tender(
        title="已知展厅项目",
        publish_date="2026-07-20",
        source_url="https://example.com/known",
        source_name="测试来源",
        priority="高优先级",
        notice_stage="可投公告",
        bid_deadline=FUTURE_DEADLINE,
    )
    known_row = dict(existing_tender.__dict__)

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [known_row])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([existing_tender, new_tender], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 2)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 1
    assert summary["alerts"][0]["title"] == "企业展厅设计采购公告"


def test_patrol_does_not_alert_new_unqualified_result(monkeypatch, tmp_path):
    tender = Tender(
        title="中标结果公告",
        publish_date="2026-07-20",
        source_url="https://example.com/result",
        source_name="测试来源",
        priority="可能无关",
    )

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([tender], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 1)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 0


def test_patrol_does_not_alert_low_priority_open_bid(monkeypatch, tmp_path):
    tender = Tender(
        title="公共文化布展服务采购公告",
        publish_date="2026-07-20",
        source_url="https://example.com/low-priority-bid",
        source_name="测试来源",
        priority="低优先级",
        notice_stage="可投公告",
        bid_deadline=FUTURE_DEADLINE,
    )

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([tender], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 1)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 0


def test_patrol_does_not_alert_high_priority_intelligence(monkeypatch, tmp_path):
    tender = Tender(
        title="产业园数字展厅合同公示",
        publish_date="2026-07-20",
        source_url="https://example.com/contract",
        source_name="测试来源",
        priority="高优先级",
        notice_stage="情报参考",
    )

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([tender], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 1)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 0


def test_patrol_does_not_alert_review_candidate(monkeypatch, tmp_path):
    tender = Tender(
        title="企业数字展厅设计采购公告",
        publish_date="2026-07-20",
        source_url="https://example.com/review",
        source_name="测试来源",
        priority="高优先级",
        notice_stage="可投公告",
        bid_deadline=FUTURE_DEADLINE,
        review_bucket="待研判",
    )

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([tender], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 1)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 0


def test_patrol_does_not_alert_bid_with_insufficient_time(monkeypatch, tmp_path):
    tender = Tender(
        title="企业展厅设计采购公告",
        publish_date="2026-07-20",
        source_url="https://example.com/closing",
        source_name="测试来源",
        priority="高优先级",
        notice_stage="可投公告",
        bid_deadline="2000-01-01 09:30",
    )

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([tender], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 1)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 0


def test_patrol_merges_same_new_project_across_sources(monkeypatch, tmp_path):
    source_a = Tender(
        title="企业总部展厅设计施工项目采购公告",
        publish_date="2026-07-20",
        source_url="https://example.com/source-a",
        source_name="来源甲",
        priority="高优先级",
        notice_stage="可投公告",
        bid_deadline=FUTURE_DEADLINE,
    )
    source_b = Tender(
        title="企业总部展厅设计施工项目",
        publish_date="2026-07-21",
        source_url="https://example.com/source-b",
        source_name="来源乙",
        priority="高优先级",
        notice_stage="可投公告",
        bid_deadline=FUTURE_DEADLINE,
    )

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([source_a, source_b], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 2)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_raw_records"] == 2
    assert summary["new_unique_projects"] == 1
    assert summary["alert_count"] == 1


def test_patrol_checks_full_inventory_for_known_projects(monkeypatch, tmp_path):
    known_row = {
        "title": "企业品牌展厅设计施工项目",
        "publish_date": "2026-06-01",
        "source_url": "https://example.com/known",
        "source_name": "历史来源",
        "priority": "高优先级",
    }
    republished = Tender(
        title="企业品牌展厅设计施工项目采购公告",
        publish_date="2026-07-21",
        source_url="https://example.com/republished",
        source_name="当前来源",
        priority="高优先级",
    )

    def fetch_inventory(_db_path, start_date=None, end_date=None):
        return [known_row] if start_date is None and end_date is None else []

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "测试来源", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", fetch_inventory)
    monkeypatch.setattr(patrol, "run_search_with_status", lambda **_kwargs: ([republished], []))
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 1)

    summary = patrol.run_patrol(enable_ai=False, rebuild_static=False)

    assert summary["new_raw_records"] == 0
    assert summary["new_unique_projects"] == 0
    assert summary["alert_count"] == 0


def test_patrol_passes_ai_candidate_limit(monkeypatch, tmp_path):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [], []

    monkeypatch.setattr(patrol, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(patrol, "RUN_SUMMARY_PATH", tmp_path / "runs" / "last.json")
    monkeypatch.setattr(patrol, "LEGACY_SUMMARY_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(patrol, "load_sources", lambda: [{"name": "test source", "crawler": "test"}])
    monkeypatch.setattr(patrol, "fetch_tenders", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(patrol, "run_search_with_status", fake_search)
    monkeypatch.setattr(patrol, "upsert_many", lambda *_args, **_kwargs: 0)

    summary = patrol.run_patrol(enable_ai=True, rebuild_static=False, max_ai_candidates=3)

    assert captured["max_ai_candidates"] == 3
    assert summary["max_ai_candidates"] == 3
