from crawlers.hebei_public import DEFAULT_CATEGORIES, build_detail_url, in_date_range, record_to_tender


def test_hebei_record_to_tender_extracts_open_search_record():
    tender = record_to_tender(
        {
            "titlenew": "黄骅市博物馆展陈提升项目（展柜采购）公开招标公告",
            "webdate": "2026-07-20 17:01:39",
            "infod": "黄骅市",
            "categoryname": "采购/资审公告",
            "linkurl": "/jydt/003001/003001001/003001001001/20260720/demo.html",
            "content": "项目编号：HB2026074530010003 投标截止时间：2026-08-11 09:00",
        },
        DEFAULT_CATEGORIES[0],
        "河北省公共资源交易服务平台",
    )

    assert tender is not None
    assert tender.title == "黄骅市博物馆展陈提升项目（展柜采购）公开招标公告"
    assert tender.publish_date == "2026-07-20"
    assert tender.region == "河北省黄骅市"
    assert tender.source_url == "https://szj.hebei.gov.cn/hbggfwpt/jydt/003001/003001001/003001001001/20260720/demo.html"


def test_hebei_detail_url_joins_platform_path():
    assert build_detail_url({"linkurl": "/jydt/demo.html"}) == "https://szj.hebei.gov.cn/hbggfwpt/jydt/demo.html"


def test_hebei_date_filter_excludes_empty_dates():
    assert in_date_range("2026-07-20", "2026-07-15", "2026-07-21")
    assert not in_date_range("", "2026-07-15", "2026-07-21")
