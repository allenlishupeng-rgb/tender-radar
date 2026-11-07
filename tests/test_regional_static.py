from crawlers.regional_static import extract_budget, parse_detail_html, parse_static_list_html


def test_regional_budget_preserves_yuan_and_wanyuan_units():
    assert extract_budget("拟采购服务的预算金额：2150000.00元") == "2150000.00元"
    assert extract_budget("项目最高限价：215万元") == "215万元"


def test_regional_detail_does_not_use_site_title_as_tender_title():
    html = "<html><head><title>安徽省公共资源交易监管网</title></head><body>此流程暂无信息</body></html>"

    parsed = parse_detail_html(html, "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=1", "安徽省")

    assert parsed["title"] == ""


def test_anhui_static_list_parse_keeps_list_title():
    html = """
    <ul>
      <li>
        <a href="/zfcg/newDetail?guid=1">【合肥市-长丰县- 采购公告】 中共合肥北乡支部红色法治文化教育基地二期EPC项目</a>
        <span>2026-06-05</span>
      </li>
    </ul>
    """

    tenders = parse_static_list_html(
        html,
        {"announcement_type": "采购公告"},
        "https://ggzy.ah.gov.cn/",
        "安徽省公共资源交易监管网",
        "安徽省",
        "教育基地",
        "2026-06-01",
        "2026-06-05",
    )

    assert len(tenders) == 1
    assert "红色法治文化教育基地" in tenders[0].title
    assert tenders[0].source_url == "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=1"
