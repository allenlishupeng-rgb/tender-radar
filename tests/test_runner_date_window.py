from database.models import Tender
from crawlers import runner


class DummyLookbackCrawler:
    last_error = ""

    def __init__(self, keywords, source_config=None, request_interval=0):
        self.last_error = ""

    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        return [
            Tender(
                title="近期企业展厅设计施工项目招标公告",
                publish_date="2026-06-24",
                source_url="https://example.com/current",
                source_name="测试来源",
                relevance_score=85,
                priority="高优先级",
            ),
            Tender(
                title="过期企业展厅设计施工项目招标公告",
                publish_date="2025-10-17",
                source_url="https://example.com/old",
                source_name="测试来源",
                relevance_score=85,
                priority="高优先级",
            ),
            Tender(
                title="无日期企业展厅设计施工项目招标公告",
                publish_date="",
                source_url="https://example.com/no-date",
                source_name="测试来源",
                relevance_score=85,
                priority="高优先级",
            ),
        ]


class RecordingCrawler:
    last_error = ""
    queries = []

    def __init__(self, keywords, source_config=None, request_interval=0):
        self.last_error = ""

    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        self.__class__.queries.append(query)
        return []


class WindowRecordingCrawler:
    last_error = ""
    calls = []

    def __init__(self, keywords, source_config=None, request_interval=0):
        self.last_error = ""

    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        self.__class__.calls.append(
            {
                "query": query,
                "days": days,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return []


class InstanceCountingCrawler:
    instances = 0
    close_count = 0
    queries = []

    def __init__(self, keywords, source_config=None, request_interval=0):
        self.__class__.instances += 1
        self.last_error = ""

    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        self.__class__.queries.append(query)
        return []

    def close(self):
        self.__class__.close_count += 1


class ReviewCandidateCrawler:
    last_error = ""

    def __init__(self, keywords, source_config=None, request_interval=0):
        self.last_error = ""

    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        return [
            Tender(
                title="企业展厅设计施工项目招标公告",
                publish_date="2026-06-24",
                source_url="https://example.com/review",
                source_name="候选来源",
                relevance_score=10,
                priority="可能无关",
            )
        ]


def test_split_query_terms_expands_project_profile_terms():
    terms = runner.split_query_terms(
        "低空经济",
        {
            "default_search_terms": ["展厅"],
        },
    )

    assert "低空经济" in terms
    assert "展示中心" in terms
    assert len(terms) <= runner.DEFAULT_PROFILE_QUERY_LIMIT


def test_default_query_terms_use_priority_discovery_lanes_within_source_budget():
    terms = runner.split_query_terms(
        "",
        {
            "query_priority_terms": [
                "展厅",
                "展陈",
                "布展",
                "展示中心",
                "数字展厅",
                "展厅设计",
            ],
            "default_search_terms": ["企业展厅", "总部展厅"],
        },
    )

    assert terms[:6] == ["展厅", "展陈", "布展", "展示中心", "数字展厅", "展厅设计"]
    assert "企业展厅" in terms


def test_crawler_managed_source_runs_once_without_outer_term_replay():
    assert runner.source_query_terms(
        {"query_strategy": "crawler_managed", "max_terms": 8},
        ["企业展厅", "展示中心", "展厅"],
    ) == [""]


def test_runner_keeps_configured_quality_rejections_in_review_pool(monkeypatch):
    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {"default_search_terms": ["企业展厅"]}
        return {
            "sources": [
                {
                    "name": "候选来源",
                    "enabled": True,
                    "crawler": "review_candidate",
                    "max_terms": 1,
                    "min_relevance_score": 25,
                    "keep_quality_rejected_as_review": True,
                }
            ]
        }

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "review_candidate", ReviewCandidateCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    results, statuses = runner.run_search_with_status(
        selected_sources=["候选来源"],
        query="企业展厅",
        days=7,
        end_date="2026-06-25",
        enable_ai=False,
    )

    assert len(results) == 1
    assert results[0].review_bucket == "待研判"
    assert statuses[0]["quality_count"] == 0
    assert statuses[0]["quality_rejected_count"] == 1
    assert statuses[0]["review_count"] == 1


def test_source_quality_gate_can_require_header_exhibition_anchor():
    unrelated = Tender(
        title="雄安新区机动车污染防治综合监管项目公开招标公告",
        purchaser="雄安新区管理委员会",
        summary="页面片段包含展示中心等导航文字。",
        relevance_score=70,
        priority="中优先级",
    )
    exhibition = Tender(
        title="雄安新区产业展示中心布展项目公开招标公告",
        purchaser="雄安新区管理委员会",
        summary="包含展陈与多媒体展项。",
        relevance_score=70,
        priority="中优先级",
    )
    source = {"require_header_target": True, "min_relevance_score": 40}

    assert not runner.passes_source_quality_gate(unrelated, source)
    assert runner.passes_source_quality_gate(exhibition, source)


def test_source_max_terms_limits_profile_search_queries(monkeypatch):
    RecordingCrawler.queries = []

    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {
                "default_search_terms": ["展厅"],
                "strong_keywords": ["展厅"],
                "business_keywords": ["设计施工"],
                "extended_keywords": [],
                "downrank_keywords": [],
                "preferred_regions": [],
                "enterprise_hall_keywords": ["企业展厅"],
                "enterprise_expansion_keywords": [],
                "enterprise_downrank_keywords": [],
            }
        return {
            "sources": [
                {
                    "name": "记录来源",
                    "enabled": True,
                    "crawler": "recording",
                    "max_terms": 2,
                }
            ]
        }

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "recording", RecordingCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    _results, statuses = runner.run_search_with_status(
        selected_sources=["记录来源"],
        query="展厅、展示中心、博物馆",
        days=7,
        end_date="2026-06-25",
        enable_ai=False,
    )

    assert RecordingCrawler.queries == ["展厅", "展示中心"]
    assert statuses[0]["executed_terms"] == ["展厅", "展示中心"]


def test_runner_reuses_one_crawler_instance_per_source(monkeypatch):
    InstanceCountingCrawler.instances = 0
    InstanceCountingCrawler.close_count = 0
    InstanceCountingCrawler.queries = []

    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {"default_search_terms": ["灞曞巺"]}
        return {
            "sources": [
                {
                    "name": "瀹炰緥澶嶇敤鏉ユ簮",
                    "enabled": True,
                    "crawler": "instance_counting",
                    "max_terms": 3,
                }
            ]
        }

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setattr(runner, "split_query_terms", lambda query, keywords: ["term-a", "term-b", "term-c"])
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "instance_counting", InstanceCountingCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    runner.run_search_with_status(
        selected_sources=["瀹炰緥澶嶇敤鏉ユ簮"],
        query="灞曞巺",
        days=7,
        end_date="2026-06-25",
        enable_ai=False,
    )

    assert InstanceCountingCrawler.instances == 1
    assert InstanceCountingCrawler.close_count == 1
    assert InstanceCountingCrawler.queries == ["term-a", "term-b", "term-c"]


def test_run_search_filters_lookback_results_to_requested_date_window(monkeypatch):
    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {
                "default_search_terms": ["展厅"],
                "strong_keywords": ["展厅"],
                "business_keywords": ["设计施工"],
                "extended_keywords": [],
                "downrank_keywords": [],
                "preferred_regions": [],
                "enterprise_hall_keywords": ["企业展厅"],
                "enterprise_expansion_keywords": [],
                "enterprise_downrank_keywords": [],
            }
        return {
            "sources": [
                    {
                        "name": "测试来源",
                        "enabled": True,
                        "crawler": "dummy_lookback",
                        "lookback_days": 540,
                        "max_terms": 1,
                    }
                ]
            }

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "dummy_lookback", DummyLookbackCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    results, status = runner.run_search_with_status(
        selected_sources=["测试来源"],
        query="展厅",
        days=7,
        end_date="2026-06-25",
    )

    assert [item.title for item in results] == ["近期企业展厅设计施工项目招标公告"]
    assert status[0]["count"] == 1
    assert status[0]["raw_count"] == 3
    assert status[0]["date_count"] == 1
    assert status[0]["target_count"] == 1
    assert status[0]["quality_count"] == 1
    assert "过滤链路" in status[0]["message"]


def test_search_passes_strict_seven_day_window_to_crawlers_even_with_lookback(monkeypatch):
    WindowRecordingCrawler.calls = []

    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {
                "default_search_terms": ["展厅"],
                "strong_keywords": ["展厅"],
                "business_keywords": ["设计施工"],
                "extended_keywords": [],
                "downrank_keywords": [],
                "preferred_regions": [],
                "enterprise_hall_keywords": ["企业展厅"],
                "enterprise_expansion_keywords": [],
                "enterprise_downrank_keywords": [],
            }
        return {
            "sources": [
                {
                    "name": "窗口记录来源",
                    "enabled": True,
                    "crawler": "window_recording",
                    "lookback_days": 540,
                }
            ]
        }

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "window_recording", WindowRecordingCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    runner.run_search_with_status(
        selected_sources=["窗口记录来源"],
        query="展厅",
        days=30,
        end_date="2026-06-25",
        enable_ai=False,
    )

    assert WindowRecordingCrawler.calls
    assert WindowRecordingCrawler.calls[0]["days"] == 30
    assert WindowRecordingCrawler.calls[0]["start_date"] == "2026-05-27"
    assert WindowRecordingCrawler.calls[0]["end_date"] == "2026-06-25"


def test_source_result_limit_prevents_one_source_from_dominating(monkeypatch):
    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {
                "default_search_terms": ["展厅"],
                "strong_keywords": ["展厅"],
                "business_keywords": ["设计施工"],
                "extended_keywords": [],
                "downrank_keywords": [],
                "preferred_regions": [],
                "enterprise_hall_keywords": ["企业展厅"],
                "enterprise_expansion_keywords": [],
                "enterprise_downrank_keywords": [],
            }
        return {
            "sources": [
                {
                    "name": "限额来源",
                    "enabled": True,
                    "crawler": "dummy_lookback",
                    "result_limit": 1,
                }
            ]
        }

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "dummy_lookback", DummyLookbackCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    results, status = runner.run_search_with_status(
        selected_sources=["限额来源"],
        query="展厅",
        days=365,
        end_date="2026-06-25",
        enable_ai=False,
    )

    assert len(results) == 1
    assert status[0]["count"] == 1
    assert "来源上限" in status[0]["message"]


def test_explicit_empty_source_selection_runs_nothing(monkeypatch):
    monkeypatch.setattr(
        runner,
        "load_yaml",
        lambda path: {"sources": [{"name": "不应运行", "enabled": True, "crawler": "fake"}]} if "sources" in str(path) else {},
    )
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "fake", object)

    results, statuses = runner.run_search_with_status(selected_sources=[], enable_ai=False)

    assert results == []
    assert statuses == []


def test_source_timeout_stops_remaining_terms(monkeypatch):
    RecordingCrawler.queries = []

    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {
                "default_search_terms": ["展厅"],
                "strong_keywords": ["展厅"],
                "business_keywords": ["设计施工"],
                "extended_keywords": [],
                "downrank_keywords": [],
                "preferred_regions": [],
                "enterprise_hall_keywords": ["企业展厅"],
                "enterprise_expansion_keywords": [],
                "enterprise_downrank_keywords": [],
            }
        return {
            "sources": [
                {
                    "name": "限时来源",
                    "enabled": True,
                    "crawler": "recording",
                    "max_terms": 3,
                    "source_timeout_seconds": 1,
                }
            ]
        }

    times = iter([0, 0, 2])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(times, 2))
    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "recording", RecordingCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    _results, status = runner.run_search_with_status(
        selected_sources=["限时来源"],
        query="展厅、展示中心、数字展厅",
        days=7,
        end_date="2026-06-25",
        enable_ai=False,
    )

    assert RecordingCrawler.queries == ["展厅"]
    assert status[0]["status"] == "访问失败/受限"
    assert "超时" in status[0]["message"]


def test_runner_isolates_unexpected_worker_failure(monkeypatch):
    class BrokenCrawler:
        def __init__(self, *_args, **_kwargs):
            self.session = None

        def close(self):
            raise RuntimeError("cleanup failed")

        def search(self, **_kwargs):
            return []

    def fake_load_yaml(path):
        if str(path).endswith("keywords.yaml"):
            return {"default_search_terms": ["展厅"]}
        return {"sources": [{"name": "故障来源", "enabled": True, "crawler": "broken"}]}

    monkeypatch.setattr(runner, "load_yaml", fake_load_yaml)
    monkeypatch.setitem(runner.CRAWLER_REGISTRY, "broken", BrokenCrawler)
    monkeypatch.setattr(runner, "apply_source_failure_alerts", lambda statuses, sources: statuses)

    results, statuses = runner.run_search_with_status(selected_sources=["故障来源"], enable_ai=False)

    assert results == []
    assert statuses[0]["status"] == "失败"
    assert "cleanup failed" in statuses[0]["message"]


def test_result_date_window_includes_exact_day_boundary():
    start, end = runner.result_date_window(days=7, end_date="2026-06-25")

    assert start.isoformat() == "2026-06-19"
    assert end.isoformat() == "2026-06-25"


def test_result_date_window_excludes_eighth_day():
    start, end = runner.result_date_window(days=7, end_date="2026-06-25")

    assert not runner.tender_in_result_date_window(
        Tender(
            title="第八天旧公告",
            publish_date="2026-06-18",
            source_url="https://example.com/eighth-day",
        ),
        start,
        end,
    )


def test_explicit_old_start_date_is_clamped_to_thirty_interactive_days():
    start, end = runner.result_date_window(days=90, start_date="2026-01-01", end_date="2026-06-25")

    assert start.isoformat() == "2026-05-27"
    assert end.isoformat() == "2026-06-25"
    assert runner.tender_in_result_date_window(
        Tender(
            title="第三十天内公告",
            publish_date="2026-05-27",
            source_url="https://example.com/thirtieth-day",
        ),
        start,
        end,
    )
