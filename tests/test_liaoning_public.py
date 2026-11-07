from crawlers.liaoning_public import parse_detail_html, parse_jsonp_payload, record_to_tender


def test_liaoning_detail_preserves_budget_unit():
    yuan = parse_detail_html("<html><body>预算金额：2150000.00元</body></html>", "https://example.com/1")
    wanyuan = parse_detail_html("<html><body>最高限价：215万元</body></html>", "https://example.com/2")

    assert yuan["budget"] == "2150000.00元"
    assert wanyuan["budget"] == "215万元"


def test_parse_liaoning_jsonp_payload():
    payload = parse_jsonp_payload(
        'jQueryTenderRadar({"datas":[{"DOCTITLE":"辽宁展馆项目招标公告","DOCPUBURL":"https://ggzy.ln.gov.cn/a.html","DOCRELTIME":"2026-06-12"}]})'
    )

    assert payload["datas"][0]["DOCTITLE"] == "辽宁展馆项目招标公告"


def test_liaoning_record_to_tender():
    tender = record_to_tender(
        {
            "DOCTITLE": "沈阳博物馆陈列项目招标公告",
            "DOCPUBURL": "/jyfb/demo.html",
            "DOCRELTIME": "2026-06-12",
        },
        {"announcement_type": "工程建设"},
        "https://ggzy.ln.gov.cn/",
        "辽宁省公共资源交易数据",
    )

    assert tender.title == "沈阳博物馆陈列项目招标公告"
    assert tender.publish_date == "2026-06-12"
    assert tender.region == "辽宁省"
    assert tender.source_url == "https://ggzy.ln.gov.cn/jyfb/demo.html"
