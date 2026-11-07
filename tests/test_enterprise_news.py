from crawlers.enterprise_news import EnterpriseNewsCrawler, extract_article_text, extract_news_candidates, infer_lead_stage


def test_extract_enterprise_news_candidates():
    html = """
    <html><body>
      <ul>
        <li><span>2026-06-18</span><a href="/news/detail.html">三一全球总部展示中心正式启用</a></li>
        <li><a href="javascript:void(0)">无效链接</a></li>
      </ul>
    </body></html>
    """

    candidates = extract_news_candidates(
        html,
        "https://www.sanygroup.com/news/",
        {"company_name": "三一重工"},
    )

    assert len(candidates) == 1
    assert candidates[0]["title"] == "三一全球总部展示中心正式启用"
    assert candidates[0]["publish_date"] == "2026-06-18"
    assert candidates[0]["url"] == "https://www.sanygroup.com/news/detail.html"


def test_enterprise_news_crawler_builds_opportunity():
    keywords = {
        "enterprise_hall_keywords": ["总部展示中心", "企业馆", "展厅"],
        "enterprise_expansion_keywords": ["智能制造基地", "总部基地"],
        "enterprise_downrank_keywords": ["展会"],
    }
    crawler = EnterpriseNewsCrawler(
        keywords,
        source_config={
            "name": "上市民企企业馆机会",
            "max_companies": 1,
            "max_links_per_company": 5,
        },
        request_interval=0,
    )
    crawler.apply_scoring = lambda tender: tender
    crawler.fetch_page = lambda url: (
        """
        <html><body>
          <li><span>2026-06-18</span><a href="/news/detail.html">全球总部展示中心正式启用</a></li>
        </body></html>
        """
        if url.endswith("/news/")
        else "三一重工智能制造基地全球总部展示中心正式启用，接待客户参观。"
    )

    import crawlers.enterprise_news as enterprise_news

    original = enterprise_news.load_enterprise_companies
    enterprise_news.load_enterprise_companies = lambda: [
        {
            "company_name": "三一重工",
            "stock_code": "600031",
            "industry": "工程机械",
            "headquarters_city": "长沙",
            "news_urls": ["https://www.sanygroup.com/news/"],
        }
    ]
    try:
        results = crawler.search(query="", days=30, start_date="2026-06-01", end_date="2026-06-30")
    finally:
        enterprise_news.load_enterprise_companies = original

    assert len(results) == 1
    assert results[0].source_name == "上市民企企业馆机会"
    assert results[0].announcement_type == "企业机会/展示空间线索"
    assert results[0].purchaser == "三一重工 600031"
    assert "总部展示中心" in results[0].important_info


def test_infer_enterprise_lead_stage():
    assert infer_lead_stage("企业品牌体验中心正式开放") == "展示空间线索"
    assert infer_lead_stage("全球总部基地开工") == "建设早期"


def test_related_news_and_list_context_cannot_supply_project_evidence():
    crawler = EnterpriseNewsCrawler(
        {"enterprise_hall_keywords": ["体验中心"], "enterprise_expansion_keywords": []},
        request_interval=0,
    )
    crawler.fetch_page = lambda url: """
        <html><head><title>光伏组件性能升级</title></head><body>
        <main><div class="rich-text"></div>
        <a href="/another-article">品牌体验中心正式开业</a></main></body></html>
    """
    tender = crawler.candidate_to_tender(
        {"title": "光伏组件性能升级", "context": "相关推荐：品牌体验中心正式开业",
         "url": "https://example.com/product", "publish_date": "2026-10-14"},
        {"company_name": "某企业"}, "上市民企企业馆机会", "2026-10-01", "2026-10-19",
    )
    assert tender is None


def test_article_body_remains_available_without_recommendation_signals():
    html = """<html><body><nav>数字展厅</nav>
        <article><p>总部基地开工，后续建设客户展示中心。</p>
        <aside>其他新闻：企业馆启用</aside></article>
        <div class="related">品牌体验中心</div></body></html>"""
    text = extract_article_text(html)
    assert "客户展示中心" in text
    assert "数字展厅" not in text
    assert "企业馆启用" not in text
    assert "品牌体验中心" not in text
