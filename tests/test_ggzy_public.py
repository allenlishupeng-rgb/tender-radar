from pathlib import Path

import yaml

from crawlers.ggzy_public import GgzyPublicCrawler, parse_detail_html, parse_result_item
from crawlers.runner import split_query_terms, split_region_terms


FIXTURE_DIR = Path(__file__).parent / "fixtures"
ROOT_DIR = Path(__file__).resolve().parents[1]


def test_parse_ggzy_detail_html_sample():
    html = (FIXTURE_DIR / "ggzy_detail_sample.html").read_text(encoding="utf-8")
    parsed = parse_detail_html(html, "https://deal.ggzy.gov.cn/sample.html")

    assert parsed["title"] == "苏州市产业展示中心展陈设计施工一体化项目招标公告"
    assert parsed["publish_date"] == "2026-06-05"
    assert parsed["region"] == "江苏省苏州市"
    assert parsed["announcement_type"] == "招标/资审公告"
    assert "多媒体展项" in parsed["summary"]


def test_parse_ggzy_result_item():
    item = {
        "title": "某展示中心展陈设计项目采购公告",
        "url": "https://deal.ggzy.gov.cn/example.html",
        "districtShow": "江苏",
        "timeShow": "2026-06-05",
        "stageShow": "采购/资审公告",
    }
    tender = parse_result_item(item)

    assert tender is not None
    assert tender.title == "某展示中心展陈设计项目采购公告"
    assert tender.region == "江苏"
    assert tender.publish_date == "2026-06-05"


def test_ggzy_fetch_search_page_uses_configured_region_codes():
    crawler = GgzyPublicCrawler({}, source_config={})
    captured = {}

    class Response:
        status_code = 200
        text = '{"data":[]}'
        url = "https://deal.ggzy.gov.cn/sample"

    crawler.can_fetch = lambda url: True
    crawler.session.get = lambda url, params, timeout: captured.update(params) or Response()

    crawler.fetch_search_page(
        query="展厅",
        start_date="2026-06-01",
        end_date="2026-06-09",
        profile={"deal_classify": "02", "deal_stage": "0201"},
        page=1,
        target_region={"deal_province": "430000", "deal_city": "430100"},
    )

    assert captured["DEAL_PROVINCE"] == "430000"
    assert captured["DEAL_CITY"] == "430100"


def test_ggzy_search_uses_configured_source_name():
    crawler = GgzyPublicCrawler(
        {},
        source_config={
            "name": "湖南省公共资源交易数据",
            "target_regions": [{"name": "湖南", "deal_province": "430000", "deal_city": "0"}],
            "search_profiles": [{"announcement_type": "采购公告"}],
        },
    )
    crawler.fetch_search_page = lambda *args, **kwargs: {
        "data": [{"title": "湖南展厅项目采购公告", "url": "https://deal.ggzy.gov.cn/hunan.html"}]
    }
    crawler.enrich_from_detail = lambda tender: None
    crawler.apply_scoring = lambda tender: tender

    results = crawler.search(query="展厅", days=1)

    assert len(results) == 1
    assert results[0].source_name == "湖南省公共资源交易数据"


def test_ggzy_sources_include_new_western_regions():
    config = yaml.safe_load((ROOT_DIR / "config" / "sources.yaml").read_text(encoding="utf-8"))
    sources = {source["name"]: source for source in config["sources"]}

    expected = {
        "新疆维吾尔自治区公共资源交易数据": "xinjiang_public",
        "西藏自治区公共资源交易数据": "regional_static",
        "内蒙古自治区公共资源交易数据": "neimenggu_public",
    }

    for source_name, crawler_name in expected.items():
        source = sources[source_name]
        assert source["enabled"] is True
        assert source["crawler"] == crawler_name
        assert "ggzy.gov.cn" not in source["base_url"]


def test_split_query_terms_uses_configured_defaults():
    keywords = {"default_search_terms": ["展馆", "文旅", "布展"]}

    default_terms = split_query_terms("", keywords)
    explicit_terms = split_query_terms("展馆、文旅,布展 数字化", keywords)

    assert default_terms[:3] == ["展馆", "文旅", "布展"]
    assert "展示中心" in default_terms
    assert explicit_terms[:4] == ["展馆", "文旅", "布展", "数字化"]


def test_split_region_terms_accepts_multiple_regions():
    assert split_region_terms("新疆、西藏,内蒙古") == ["新疆", "西藏", "内蒙古"]
    assert split_region_terms("") is None
