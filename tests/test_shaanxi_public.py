import json

from crawlers.shaanxi_public import parse_records
from parsers.extractors import normalize_deadline_date


def test_public_response_filters_dates_and_extracts_deadline():
    records = [
        {'title': '<em>企业展厅</em>设计招标', 'webdate': '2026-11-10 12:00:00',
         'linkurl': '/jydt/20261110/a.html', 'content': '投标截止时间：2026年12月10日'},
        {'title': '旧公告', 'webdate': '2020-01-01', 'linkurl': '/old.html'},
        {'title': '日期不明', 'linkurl': '/unknown.html'},
    ]
    payload = {'content': json.dumps({'result': {'records': records}})}
    rows = parse_records(payload, 'https://www.sxggzyjy.cn/', '陕西', '2026-11-01', '2026-11-10')
    assert len(rows) == 1
    assert rows[0].title == '企业展厅设计招标'
    assert normalize_deadline_date(rows[0].bid_deadline) == '2026-12-10'
    assert rows[0].source_url == 'https://www.sxggzyjy.cn/jydt/20261110/a.html'
