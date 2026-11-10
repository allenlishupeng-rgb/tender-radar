from crawlers.regional_static import parse_static_list_html


def test_column_navigation_is_not_a_tender():
    html = '''<ul>
      <li><a href="/jydt/001001/trading.html">公共资源交易项目交易大厅</a></li>
      <li><a href="/jydt/001001/001001001/subPage.html">工程建设项目招标投标</a></li>
      <li><a href="/jyxx/20261110/notice-123.html">企业展厅建设项目招标公告</a>2026-11-10</li>
    </ul>'''
    rows = parse_static_list_html(html, {}, 'https://example.com', 'test', '陕西省',
                                  '项目', '2026-11-01', '2026-11-10')
    assert len(rows) == 1
    assert rows[0].source_url.endswith('notice-123.html')
