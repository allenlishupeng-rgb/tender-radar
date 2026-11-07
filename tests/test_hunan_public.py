from crawlers.hunan_public import (
    ENDPOINTS,
    HunanPublicCrawler,
    build_detail_url,
    in_date_range,
    merge_government_purchase_detail,
    record_to_tender,
)


def test_hunan_detail_url_uses_single_hash_route():
    url = build_detail_url(
        ENDPOINTS[1],
        {
            "projectId": "project-1",
            "regionCode": "430100",
            "bidSectionId": "section-1",
        },
    )

    assert url.startswith("https://hnsggzy.com/#/resources/projectDetail/governmentPurchase?")
    assert "//#" not in url


def test_hunan_construction_detail_url_uses_transaction_route():
    url = build_detail_url(
        ENDPOINTS[0],
        {
            "regionCode": "430100",
            "bidSectionId": "54739",
            "isPublic": "1",
        },
    )

    assert url.startswith("https://hnsggzy.com/#/resources/transactionDetail/construction?")
    assert "bidSectionId=54739" in url
    assert "isPublic=1" in url
    assert "default=projectInfo" in url


def test_hunan_date_filter_excludes_old_and_empty_dates():
    assert in_date_range("2026-06-08", "2026-06-01", "2026-06-09")
    assert not in_date_range("2024-06-08", "2026-06-01", "2026-06-09")
    assert not in_date_range("", "2026-06-01", "2026-06-09")


def test_hunan_government_purchase_detail_supplies_missing_publish_date_and_budget():
    record = {
        "purchaseProjectName": "全省博物馆省市联动体系改革项目",
        "bidSectionId": "section-1",
        "noticeSendTime": None,
    }
    project_payload = {
        "data": {
            "purchaserName": "湘潭市博物馆",
            "agencyName": "湖南建业管理咨询有限公司",
            "programBudget": "3707137.97",
            "projectCode": "XTCG-2026-0196",
        }
    }
    announcement_payload = {
        "data": {
            "governmentProcureAnnouncementInformation": [
                {
                    "noticeName": "全省博物馆省市联动体系改革项目采购公告",
                    "noticeSendTime": "2026-05-19T16:20:39.000+08:00",
                    "bulletinType": "招标公告",
                }
            ]
        }
    }

    merged = merge_government_purchase_detail(record, project_payload, announcement_payload)

    assert merged["noticeSendTime"] == "2026-05-19T16:20:39.000+08:00"
    assert merged["purchaserName"] == "湘潭市博物馆"
    assert merged["programBudget"] == "3707137.97"


def test_hunan_record_to_tender_extracts_business_fields():
    record = {
        "purchaseProjectName": "湘乡市毛泽东与东山学校陈列馆展陈智能化项目",
        "noticeSendTime": "2026-05-19T16:20:39.000+08:00",
        "regionName": "湘潭",
        "purchaserName": "湘乡市博物馆",
        "agencyName": "湖南建业管理咨询有限公司",
        "programBudget": "3707137.97",
        "projectCode": "XTCG-2026-0196",
        "connector": "王工",
        "phone": "0731-88888888",
        "bidEndTime": "2026-06-08 09:30:00",
        "bidSectionId": "section-1",
    }

    tender = record_to_tender(record, ENDPOINTS[1], "湖南省公共资源交易数据", "湖南")

    assert tender.budget == "3707137.97元"
    assert tender.contact_person == "王工"
    assert tender.contact_phone == "0731-88888888"
    assert tender.bid_deadline == "2026-06-08 09:30:00"


def test_hunan_search_caps_government_detail_enrichment(monkeypatch):
    crawler = HunanPublicCrawler(
        {},
        source_config={
            "name": "湖南测试源",
            "region_name": "湖南",
            "max_pages": 1,
            "max_terms": 3,
            "detail_enrichment_limit": 1,
            "result_limit": 10,
            "source_timeout_seconds": 30,
        },
        request_interval=0,
    )
    detail_calls = []

    def fake_page(path, page, term, region_code, start_date, end_date):
        if "governmentPurchase" not in path:
            return {"data": {"records": []}}
        return {
            "data": {
                "records": [
                    {
                        "purchaseProjectName": f"{term}建设项目",
                        "noticeSendTime": "2026-08-10",
                        "bidSectionId": term,
                    }
                ]
            }
        }

    def fake_enrich(record):
        detail_calls.append(record["bidSectionId"])
        return record

    monkeypatch.setattr(crawler, "fetch_page", fake_page)
    monkeypatch.setattr(crawler, "enrich_government_purchase", fake_enrich)

    results = crawler.search("", start_date="2026-07-13", end_date="2026-08-11")

    assert len(results) == 3
    assert len(detail_calls) == 1
