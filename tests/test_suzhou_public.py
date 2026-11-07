from pathlib import Path

from crawlers.suzhou_public import parse_suzhou_search_response


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_suzhou_search_response_sample():
    html = (FIXTURE_DIR / "suzhou_search_sample.json").read_text(encoding="utf-8")
    tenders = parse_suzhou_search_response(
        html,
        query="展厅",
        start_date="2026-05-01",
        end_date="2026-06-30",
    )

    assert len(tenders) == 1
    tender = tenders[0]
    assert tender.source_name == "苏州市公共资源交易平台"
    assert tender.title == "苏州市低空运营服务有限公司关于苏州市低空经济展示与服务中心S6栋展厅设计与布展服务的中标公告"
    assert tender.publish_date == "2026-05-25"
    assert tender.region == "苏州市吴江区"
    assert tender.budget == "2941550.00元"
    assert tender.contact_phone == "0512-68303723"
    assert tender.source_url.startswith("https://ggzy.suzhou.gov.cn/jyxx/")
