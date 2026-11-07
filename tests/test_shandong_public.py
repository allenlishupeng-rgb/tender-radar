from crawlers.shandong_public import ShandongPublicCrawler


def test_shandong_crawler_respects_disallowed_robots(monkeypatch):
    crawler = ShandongPublicCrawler({}, {"base_url": "https://ggzyjy.shandong.gov.cn/"})
    monkeypatch.setattr(crawler, "can_fetch", lambda _url: False)

    assert crawler.search("展厅") == []
    assert "robots.txt" in crawler.last_error
