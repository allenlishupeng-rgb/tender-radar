from pathlib import Path

from crawlers.jiangsu_public import parse_detail_html, parse_list_html


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_jiangsu_list_html_sample_filters_keyword_and_date():
    html = (FIXTURE_DIR / "jiangsu_list_sample.html").read_text(encoding="utf-8")
    tenders = parse_list_html(
        html,
        {"announcement_type": "招标公告/资审公告"},
        base_url="https://jsggzy.jszwfw.gov.cn/jyxx/003001/003001001/",
        query="展陈",
        start_date="2026-06-01",
        end_date="2026-06-10",
    )

    assert len(tenders) == 1
    tender = tenders[0]
    assert tender.title == "〖苏州市〗苏州市某规划馆展陈设计施工一体化项目招标公告"
    assert tender.publish_date == "2026-06-05"
    assert tender.region == "苏州市"
    assert tender.announcement_type == "招标公告/资审公告"
    assert tender.source_url == "https://jsggzy.jszwfw.gov.cn/jyxx/003001/003001001/20260605/abc123.html"


def test_parse_jiangsu_detail_html_sample():
    html = (FIXTURE_DIR / "jiangsu_detail_sample.html").read_text(encoding="utf-8")
    parsed = parse_detail_html(html, "https://jsggzy.jszwfw.gov.cn/sample.html")

    assert parsed["title"] == "苏州市某规划馆展陈设计施工一体化项目招标公告"
    assert parsed["publish_date"] == "2026-06-05"
    assert parsed["region"] == "江苏省苏州市"
    assert parsed["purchaser"] == "苏州市某建设单位"
    assert parsed["agency"] == "江苏某招标代理有限公司"
    assert parsed["budget"] == "1800万元"
    assert "多媒体展项" in parsed["summary"]
