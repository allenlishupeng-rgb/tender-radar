from pathlib import Path

from crawlers import ccgp_public
from crawlers.ccgp_public import CcgpPublicCrawler, parse_detail_html, parse_search_html
from database.models import Tender


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_ccgp_search_html_sample():
    html = (FIXTURE_DIR / "ccgp_search_sample.html").read_text(encoding="utf-8")
    tenders = parse_search_html(html)

    assert len(tenders) == 1
    tender = tenders[0]
    assert tender.title == "苏州市某博物馆展陈设计施工一体化项目公开招标公告"
    assert tender.publish_date == "2026-06-05"
    assert tender.region == "江苏"
    assert tender.purchaser == "苏州市某博物馆"
    assert tender.agency == "苏州某代理有限公司"
    assert tender.announcement_type == "公开招标公告"
    assert "多媒体展项" in tender.summary


def test_parse_ccgp_detail_html_sample():
    html = (FIXTURE_DIR / "ccgp_detail_sample.html").read_text(encoding="utf-8")
    parsed = parse_detail_html(html, "http://www.ccgp.gov.cn/sample.html")

    assert parsed["title"] == "苏州市某博物馆展陈设计施工一体化项目公开招标公告"
    assert parsed["publish_date"] == "2026-06-05"
    assert parsed["region"] == "江苏"
    assert parsed["announcement_type"] == "公开招标公告"
    assert parsed["purchaser"] == "苏州市某博物馆"
    assert parsed["agency"] == "苏州某代理有限公司"
    assert parsed["budget"] == "1200万元"


def test_ccgp_detail_enrichment_budget_is_shared_across_query_terms(monkeypatch):
    keywords = {
        "strong_keywords": ["展厅", "展陈"],
        "business_keywords": ["设计施工", "布展"],
        "extended_keywords": [],
        "downrank_keywords": [],
        "preferred_regions": [],
    }
    crawler = CcgpPublicCrawler(
        keywords,
        source_config={
            "target_regions": [{"name": "全国", "display_zone": "", "zone_id": ""}],
            "default_target_regions": ["全国"],
            "bid_types": [{"bid_type": "1", "announcement_type": "公开招标公告"}],
            "max_pages": 1,
            "result_limit": 20,
            "detail_enrichment_limit": 1,
            "source_timeout_seconds": 30,
        },
        request_interval=0,
    )
    monkeypatch.setattr(crawler, "fetch_search_page", lambda query, *_args, **_kwargs: query)
    monkeypatch.setattr(
        ccgp_public,
        "parse_search_html",
        lambda query: [
            Tender(
                title=f"企业数字展厅设计施工项目{query}公开招标公告",
                publish_date="2026-08-04",
                source_url=f"https://example.com/{query}",
                summary="包含展厅设计施工和多媒体展项。",
            )
        ],
    )
    enriched = []

    def fake_enrich(tender):
        enriched.append(tender.source_url)
        tender.budget = "1000万元"

    monkeypatch.setattr(crawler, "enrich_from_detail", fake_enrich)

    first = crawler.search("展厅", start_date="2026-07-30", end_date="2026-08-05")
    second = crawler.search("展陈", start_date="2026-07-30", end_date="2026-08-05")

    assert len(first) == 1
    assert len(second) == 1
    assert len(enriched) == 1
    assert first[0].budget == "1000万元"
    assert second[0].budget == ""
