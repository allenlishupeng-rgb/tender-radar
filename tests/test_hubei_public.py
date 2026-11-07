import json
from pathlib import Path

from crawlers.hubei_public import ENDPOINTS, parse_hubei_records


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_hubei_record_sample():
    record = json.loads((FIXTURE_DIR / "hubei_record_sample.json").read_text(encoding="utf-8"))
    tenders = parse_hubei_records(
        {"data": [record]},
        ENDPOINTS[0],
        source_name="武汉市公共资源交易信息",
        area_code="420100",
        query="展厅",
        start_date="2026-06-01",
        end_date="2026-06-30",
    )

    assert len(tenders) == 1
    tender = tenders[0]
    assert tender.source_name == "武汉市公共资源交易信息"
    assert tender.title == "武汉某数字展厅建设项目招标公告"
    assert tender.publish_date == "2026-06-08"
    assert tender.bid_deadline == "2026-06-29"
    assert tender.region == "湖北省武汉市"
    assert tender.budget == "980万元"
    assert tender.project_no == "HB-202606-ZB-001"
    assert tender.contact_phone == "027-88888888"
    assert tender.source_url == "https://www.hbggzyfwpt.cn/jyxx/jsgcXmxxDetail?guid=abc-123&isOther=false"
