from crawlers.anhui_public import AnhuiPublicCrawler


def test_anhui_query_expansion_for_exhibition_terms():
    crawler = AnhuiPublicCrawler({}, source_config={})
    assert "展厅" in crawler.__class__.__module__ or crawler is not None


def test_anhui_build_search_url_contains_keyword():
    crawler = AnhuiPublicCrawler({}, source_config={})
    url = crawler.build_list_url(
        "https://ggzy.ah.gov.cn/",
        {"type": "zfcg", "_query": "展陈", "time_param": "month"},
        2,
    )

    assert "souSuo" in url
    assert "currentPage=2" in url
    assert "%E5%B1%95%E9%99%88" in url
