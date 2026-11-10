"""Shaanxi's public search endpoint used by subPage_fullsearch.js."""
import json
from datetime import timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from crawlers.regional_static import RegionalStaticCrawler
from database.models import Tender
from parsers.common import clean_text, summarize
from parsers.extractors import extract_deadline, normalize_publish_date, radar_today


ENDPOINT = 'https://www.sxggzyjy.cn/inteligentsearch_new/rest/esinteligentsearch/getFullTextDataNew'


def parse_records(payload, base_url, source_name, start, end):
    content = payload.get('content', payload)
    if isinstance(content, str):
        content = json.loads(content)
    records = (content.get('result') or {}).get('records') or []
    result = []
    for item in records:
        published = normalize_publish_date(item.get('webdate') or item.get('infodate') or '')
        title = clean_text(BeautifulSoup(item.get('title') or '', 'html.parser').get_text())
        link = item.get('linkurl') or ''
        if not title or not link or not published or not start <= published[:10] <= end:
            continue
        url = urljoin(base_url, link)
        if not url.startswith(('https://', 'http://')):
            continue
        body = clean_text(BeautifulSoup(item.get('content') or '', 'html.parser').get_text(' '))
        result.append(Tender(title=title, source_url=url, source_name=source_name,
                             publish_date=published[:10], region=item.get('diqu') or '陕西省',
                             announcement_type='招标/采购公告', summary=summarize(body),
                             bid_deadline=extract_deadline(body)))
    return result


class ShaanxiPublicCrawler(RegionalStaticCrawler):
    def search(self, query, days=7, start_date=None, end_date=None, regions=None):
        if regions and not any('陕西' in value or '西安' in value for value in regions):
            return []
        today = radar_today()
        start = str(start_date or (today - timedelta(days=days - 1)))
        end = str(end_date or today)
        if not self.can_fetch(ENDPOINT):
            self.last_error = 'robots.txt 不允许访问陕西公开搜索接口'
            return []
        results, seen = [], set()
        deadline = self.source_deadline(45)
        limit = self.source_result_limit(12)
        for category in self.source_config.get('categorynums', ['001001001001', '001001004']):
            for page in range(self.config_int('max_pages', 1)):
                if self.source_should_stop(results, deadline, limit):
                    return results
                payload = {'esdsid': '1', 'token': '', 'pn': page * 20, 'rn': 20,
                           'sdt': '', 'edt': '', 'wd': query or '',
                           'inc_wd': '', 'exc_wd': '', 'fields': 'title', 'cnum': '001',
                           'sort': '{"webdate":"0"}', 'ssort': 'title', 'cl': 1000,
                           'cutIngore': 'title;linkurl', 'terminal': '',
                           'condition': [{'fieldName': 'categorynum', 'equal': category,
                                          'isLike': True, 'likeType': 2}],
                           'time': [{'fieldName': 'webdate', 'startTime': start + ' 00:00:00',
                                     'endTime': end + ' 23:59:59',
                                     'containStart': True, 'containEnd': True}],
                           'highlights': 'title', 'statistics': None, 'unionCondition': None,
                           'accuracy': '', 'noParticiple': '1', 'searchRange': [], 'isBusiness': '1'}
                try:
                    response = self.request_with_retries('POST', ENDPOINT, json=payload,
                                                         timeout=self.request_timeout(10), retries=0)
                    response.raise_for_status()
                    rows = parse_records(response.json(), self.source_config['base_url'],
                                         self.source_name, start, end)
                except Exception as exc:
                    self.last_error = str(exc)[:180]
                    return results
                for tender in rows:
                    if tender.source_url not in seen:
                        seen.add(tender.source_url)
                        results.append(self.apply_scoring(tender))
                        if len(results) >= limit:
                            return results
                if len(rows) < 20:
                    break
        return results
