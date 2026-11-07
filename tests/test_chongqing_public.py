from pathlib import Path

from crawlers.chongqing_public import parse_chongqing_search_html


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_chongqing_search_html_sample():
    html = (FIXTURE_DIR / "chongqing_search_sample.html").read_text(encoding="utf-8")
    tenders = parse_chongqing_search_html(
        html,
        query="展馆",
        start_date="2026-04-01",
        end_date="2026-06-30",
    )

    assert len(tenders) >= 3
    first = tenders[0]
    assert first.source_name == "重庆市公共资源交易网"
    assert first.title == "关于【安居小学艺术展馆装修项目（设计）采购说明】中选结果的公告"
    assert first.publish_date == "2026-05-29"
    assert first.region == "重庆市铜梁区"
    assert first.purchaser == "重庆市铜梁区安居小学"
    assert first.source_url.startswith("https://www.cqggzy.com/xxhz/")
    assert "展馆" in first.summary


def test_parse_chongqing_search_html_extracts_contact_and_budget():
    html = (FIXTURE_DIR / "chongqing_search_sample.html").read_text(encoding="utf-8")
    tenders = parse_chongqing_search_html(
        html,
        query="展馆",
        start_date="2026-04-01",
        end_date="2026-06-30",
    )

    tender = next(item for item in tenders if "安居小学艺术展馆装修项目" in item.title)
    assert tender.budget
    assert tender.contact_phone
