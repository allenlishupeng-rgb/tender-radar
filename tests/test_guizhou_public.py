from crawlers.guizhou_public import (
    GuizhouPublicCrawler,
    best_publish_date,
    date_from_url,
    in_date_range,
    parse_trade_detail_html,
    trade_record_to_tender,
)


def test_guizhou_publish_date_prefers_original_url_date():
    record = {
        "time": "2026-03-20",
        "url": "https://ggzy.guizhou.gov.cn/xxfw/qttzjy/202207/t20220721_75609761.html",
    }

    assert best_publish_date(record) == "2022-07-21"


def test_guizhou_old_original_url_is_excluded_from_recent_range():
    assert date_from_url("https://ggzy.guizhou.gov.cn/path/t20220721_75609761.html") == "2022-07-21"
    assert not in_date_range("2022-07-21", "2026-03-12", "2026-06-09")


def test_guizhou_trade_record_uses_doc_rel_time_and_detail_url():
    record = {
        "apiUrl": "https://ggzy.guizhou.gov.cn/tradeInfo/detailHtml?metaId=1219785383835160576",
        "businessTypeName": "政府采购",
        "announcement": "采购公告",
        "docSourceName": "贵州省公共资源交易中心",
        "docTitle": "自然教育基地展厅布展采购公告",
        "docRelTime": 1779433846000,
        "tenderProjectCode": "P52000020260003LU",
    }

    tender = trade_record_to_tender(record, "贵州省公共资源交易数据", "贵州")

    assert tender.publish_date == "2026-05-22"
    assert tender.source_url.endswith("metaId=1219785383835160576")
    assert tender.project_no == "P52000020260003LU"


def test_guizhou_detail_html_extracts_meta_and_budget():
    html = """
    <html><head>
      <meta name="ArticleTitle" content="自然教育基地展厅布展交易证明书">
      <meta name="PubDate" content="2026-05-28">
      <meta name="ContentSource" content="贵州省公共资源交易中心">
    </head><body>
      <p>招标人（采购人）</p><p>贵州大沙河国家级自然保护区管理局</p>
      <p>代理机构</p><p>贵州锦阳项目管理咨询有限公司</p>
      <p>项目编号</p><p>P52000020260003LU</p>
      <p>开标时间</p><p>2026-06-08 09:30</p>
      <p>项目联系人</p><p>李工</p>
      <p>联系电话</p><p>0851-88888888</p>
      <p>投标总报价(元)2381106.35</p>
    </body></html>
    """

    detail = parse_trade_detail_html(html)

    assert detail["title"] == "自然教育基地展厅布展交易证明书"
    assert detail["publish_date"] == "2026-05-28"
    assert detail["source"] == "贵州省公共资源交易中心"
    assert detail["purchaser"] == "贵州大沙河国家级自然保护区管理局"
    assert detail["budget"] == "2381106.35元"
    assert detail["bid_deadline"] == "2026-06-08 09:30"
    assert detail["contact_person"] == "李工"
    assert detail["contact_phone"] == "0851-88888888"


def test_guizhou_search_caps_detail_enrichment(monkeypatch):
    crawler = GuizhouPublicCrawler(
        {},
        source_config={
            "name": "贵州测试源",
            "region_name": "贵州",
            "max_pages": 1,
            "max_terms": 3,
            "detail_enrichment_limit": 1,
            "result_limit": 10,
            "source_timeout_seconds": 30,
        },
        request_interval=0,
    )
    detail_calls = []

    def fake_page(term, page, start_date, end_date, region_name):
        return {
            "list": [
                {
                    "apiUrl": f"https://example.test/{term}",
                    "docTitle": f"{term}建设项目采购公告",
                    "docRelTime": 1786320000000,
                    "docSourceName": "贵州省公共资源交易中心",
                    "announcement": "采购公告",
                }
            ]
        }

    def fake_detail(url):
        detail_calls.append(url)
        return {"title": "企业展厅建设项目采购公告"}

    monkeypatch.setattr(crawler, "fetch_trade_page", fake_page)
    monkeypatch.setattr(crawler, "fetch_trade_detail", fake_detail)

    results = crawler.search("", start_date="2026-07-13", end_date="2026-08-11")

    assert len(results) == 3
    assert len(detail_calls) == 1
