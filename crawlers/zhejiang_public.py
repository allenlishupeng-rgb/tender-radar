import logging
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.settings import LOG_DIR
from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, html_to_text, summarize
from parsers.extractors import (
    build_important_info,
    extract_contact_person,
    extract_deadline,
    extract_after_label,
    extract_phone,
    extract_project_no,
    normalize_publish_date,
)
from scoring.project_profile import expand_project_query_terms


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "zhejiang_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


SEARCH_ENDPOINT = "https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"


def expand_query_terms(query: str) -> list[str]:
    return expand_project_query_terms(clean_text(query), ["展览展示", "展陈设计", "展陈施工", "设计施工一体化", "数字展厅", "多媒体展项"])


def text_matches_query(text: str, query: str) -> bool:
    if not query:
        return True
    return any(term in text for term in expand_query_terms(query))


def extract_budget(text: str) -> str:
    normalized = clean_text(text)
    patterns = [
        r"(?:预算金额|最高限价|最高投标限价|招标控制价|合同估算价|采购预算|项目预算)\s*[:：]?\s*(?:人民币)?\s*([0-9,.]+)\s*(万元|元)",
        r"(?:总投资|工程概算)\s*[:：]?\s*([0-9,.]+)\s*(万元|元)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return f"{match.group(1)}{match.group(2)}"
    return ""


class ZhejiangPublicCrawler(BaseCrawler):
    name = "浙江省公共资源交易服务平台"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("浙江" in clean_text(r or "") for r in regions):
            return []
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        max_pages = int(self.source_config.get("max_pages", 1))
        max_terms = int(self.source_config.get("max_terms", 4))
        categories = self.source_config.get("categories", [])
        result_limit = self.source_result_limit(22)
        deadline = self.source_deadline(45)
        managed_terms = self.source_config.get("search_terms") or ["企业展厅", "展示中心", "展厅", "展陈"]
        terms = [query] if query else managed_terms[:max_terms]
        detail_limit = max(int(self.source_config.get("detail_enrichment_limit", 8) or 8), 0)
        detail_count = 0
        results: list[Tender] = []
        seen: set[str] = set()
        for term in terms:
            for category in categories:
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                for page in range(max_pages):
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    payload = self.build_payload(category.get("categorynum", ""), start, end, page, term)
                    data = self.fetch_search(payload)
                    if not data:
                        continue
                    records = data.get("records") or []
                    for record in records:
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
                        text = f"{record.get('titlenew','')} {record.get('content','')}"
                        if not text_matches_query(text, term):
                            continue
                        url = urljoin(self.source_config.get("base_url", "https://ggzy.zj.gov.cn/"), record.get("linkurl", ""))
                        if url in seen:
                            continue
                        seen.add(url)
                        tender = Tender(
                            title=clean_text(record.get("titlenew") or record.get("title") or ""),
                            announcement_type=record.get("categoryname") or category.get("announcement_type", ""),
                            publish_date=normalize_publish_date(record.get("webdate", "")),
                            region=f"浙江省{clean_text(record.get('infod', ''))}",
                            source_url=url,
                            summary=summarize(html_to_text(record.get("content", ""))),
                            bid_deadline=extract_deadline(html_to_text(record.get("content", ""))),
                            source_name="浙江省公共资源交易服务平台",
                        )
                        if not tender.bid_deadline and detail_count < detail_limit:
                            self.enrich_from_detail(tender)
                            detail_count += 1
                        results.append(self.apply_scoring(tender))
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
        return results

    def build_payload(self, categorynum: str, start: str, end: str, page: int, term: str = "") -> dict:
        return {
            "token": "",
            "pn": page * 20,
            "rn": "20",
            "sdt": "",
            "edt": "",
            "wd": term,
            "inc_wd": "",
            "exc_wd": "",
            "fields": "title",
            "cnum": "001",
            "sort": '{"webdate":"0"}',
            "ssort": "title",
            "cl": 200,
            "terminal": "",
            "condition": [{"fieldName": "categorynum", "isLike": True, "likeType": 2, "equal": categorynum}],
            "time": [{"fieldName": "webdate", "startTime": f"{start} 00:00:00", "endTime": f"{end} 23:59:59"}],
            "highlights": "",
            "statistics": None,
            "unionCondition": None,
            "accuracy": "",
            "noParticiple": "1",
            "searchRange": None,
            "isBusiness": "1",
        }

    def fetch_search(self, payload: dict) -> dict | None:
        try:
            response = self.request_with_retries(
                "POST",
                SEARCH_ENDPOINT,
                json=payload,
                timeout=self.request_timeout(12),
                retries=1,
                headers={"Referer": "https://ggzy.zj.gov.cn/jyxxgk/list.html"},
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}"
                return None
            return (response.json().get("result") or {})
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Zhejiang search failed: %s", exc)
            return None

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                return
            response.encoding = response.apparent_encoding or response.encoding
            soup = BeautifulSoup(response.text, "html.parser")
            text = html_to_text(response.text)
            title_node = soup.select_one("h1") or soup.select_one("h2") or soup.select_one(".title")
            tender.title = clean_text(title_node.get_text(" ")) if title_node else tender.title
            publish = extract_after_label(text, ["发布时间", "发布日期", "信息发布时间"], 50)
            tender.publish_date = normalize_publish_date(publish) or tender.publish_date
            tender.purchaser = extract_after_label(text, ["招标人", "采购人", "建设单位", "项目业主"], 120) or tender.purchaser
            tender.agency = extract_after_label(text, ["招标代理机构", "采购代理机构", "代理机构"], 120) or tender.agency
            tender.budget = extract_budget(text) or tender.budget
            tender.project_no = extract_project_no(text) or tender.project_no
            tender.contact_person = extract_contact_person(text) or tender.contact_person
            tender.contact_phone = extract_phone(text) or tender.contact_phone
            tender.bid_deadline = extract_deadline(text) or tender.bid_deadline
            tender.important_info = build_important_info(text) or tender.important_info
            tender.summary = summarize(text) or tender.summary
        except Exception as exc:
            logger.exception("Zhejiang detail failed for %s: %s", tender.source_url, exc)
