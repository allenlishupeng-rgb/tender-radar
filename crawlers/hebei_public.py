import logging
import re
from datetime import date, datetime, timedelta
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
    extract_phone,
    extract_project_no,
    normalize_publish_date,
)
from scoring.project_profile import PROJECT_SEARCH_TERMS


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "hebei_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://szj.hebei.gov.cn/hbggfwpt/"
SEARCH_ENDPOINT = "https://szj.hebei.gov.cn/inteligentsearchnew/rest/esinteligentsearch/getFullTextDataNew"
REFERER = "https://szj.hebei.gov.cn/hbggfwpt/jydt/salesPlat.html"

DEFAULT_TERMS = list(
    dict.fromkeys(
        [
            "企业展厅",
            "产业展示中心",
            "科技展厅",
            "展厅",
            "展陈",
            "布展",
            "展示中心",
            "数字展厅",
            "多媒体展项",
            "规划馆",
        ]
        + PROJECT_SEARCH_TERMS
    )
)

DEFAULT_CATEGORIES = [
    {"categorynum": "003001001001", "announcement_type": "政府采购-采购/资审公告"},
    {"categorynum": "003001002001", "announcement_type": "工程建设-招标/资审公告"},
    {"categorynum": "003001002005", "announcement_type": "工程建设-招标计划公告"},
]


def normalize_date(value: str | date | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return clean_text(str(value or ""))


def parse_date(value: str) -> date | None:
    normalized = normalize_publish_date(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def in_date_range(publish_date: str, start_date: str, end_date: str) -> bool:
    published = parse_date(publish_date)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not published or not start or not end:
        return False
    return start <= published <= end


def text_matches_terms(text: str, terms: list[str]) -> bool:
    value = clean_text(text)
    return any(term and term in value for term in terms)


def extract_budget(text: str) -> str:
    normalized = clean_text(text)
    patterns = [
        r"(?:预算金额|最高限价|招标控制价|合同估算价|采购预算|项目预算)\s*[:：]?\s*(?:人民币)?\s*([0-9,.]+)\s*(万元|元)",
        r"([0-9,.]+)\s*万元",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        if len(match.groups()) >= 2:
            return f"{match.group(1)}{match.group(2)}"
        return f"{match.group(1)}万元"
    return ""


def build_detail_url(record: dict, base_url: str = BASE_URL) -> str:
    link = clean_text(record.get("linkurl") or record.get("url") or "")
    if link.startswith("/jydt/"):
        link = f"/hbggfwpt{link}"
    return urljoin(base_url, link)


def record_to_tender(record: dict, category: dict, source_name: str, base_url: str = BASE_URL) -> Tender | None:
    title = clean_text(record.get("titlenew") or record.get("title") or "")
    source_url = build_detail_url(record, base_url)
    if not title or not source_url:
        return None
    content = html_to_text(record.get("content") or "")
    combined = f"{title} {content}"
    return Tender(
        title=title,
        announcement_type=clean_text(record.get("categoryname") or category.get("announcement_type", "")),
        publish_date=normalize_publish_date(record.get("webdate") or ""),
        region=f"河北省{clean_text(record.get('infod') or '')}".strip(),
        budget=extract_budget(combined),
        project_no=extract_project_no(combined),
        contact_person=extract_contact_person(combined),
        contact_phone=extract_phone(combined),
        bid_deadline=extract_deadline(combined),
        important_info=build_important_info(combined),
        source_url=source_url,
        summary=summarize(content or title),
        source_name=source_name,
    )


def parse_detail_html(html: str, url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)
    title = ""
    for selector in ["h1", "h2", ".ewb-article-tt", ".article-title", ".detail-title", ".title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ")).replace("河北省全国公共资源交易平台-公告详情", "")
    return {
        "title": title,
        "publish_date": normalize_publish_date(text) or normalize_publish_date(url),
        "budget": extract_budget(text),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(text),
        "source_url": url,
    }


class HebeiPublicCrawler(BaseCrawler):
    name = "河北省公共资源交易服务平台"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("河北" in clean_text(region or "") for region in regions):
            return []
        end = normalize_date(end_date) or date.today().isoformat()
        start = normalize_date(start_date) or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        max_pages = self.config_int("max_pages", 1)
        max_terms = self.config_int("max_terms", 6)
        categories = self.source_config.get("categories") or DEFAULT_CATEGORIES
        configured_terms = self.source_config.get("search_terms") or DEFAULT_TERMS
        terms = list(dict.fromkeys([clean_text(query or ""), *configured_terms]))[:max_terms]
        result_limit = self.source_result_limit(12)
        deadline = self.source_deadline(35)
        source_name = clean_text(self.source_config.get("name") or self.name)
        base_url = self.source_config.get("base_url") or BASE_URL
        detail_limit = max(self.config_int("detail_enrichment_limit", 5), 0)

        results: list[Tender] = []
        seen: set[str] = set()
        detail_count = 0
        for category in categories:
            for term in terms:
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                if not term:
                    continue
                for page in range(max_pages):
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    records = self.fetch_records(category, term, start, end, page)
                    if not records:
                        break
                    for record in records:
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
                        tender = record_to_tender(record, category, source_name, base_url)
                        if not tender or tender.source_url in seen:
                            continue
                        if not tender.publish_date or not in_date_range(tender.publish_date, start, end):
                            continue
                        combined = f"{tender.title} {tender.summary} {tender.important_info}"
                        if not text_matches_terms(combined, terms):
                            continue
                        seen.add(tender.source_url)
                        if detail_count < detail_limit:
                            self.enrich_from_detail(tender)
                            detail_count += 1
                        results.append(self.apply_scoring(tender))
        if not results:
            self.last_error = self.last_error or "河北公开交易接口近期未返回匹配展厅/展陈项目"
        return results

    def build_payload(self, category: dict, term: str, start: str, end: str, page: int) -> dict:
        return {
            "token": "",
            "pn": page * 10,
            "rn": 10,
            "sdt": "",
            "edt": "",
            "wd": " ",
            "inc_wd": "",
            "exc_wd": "",
            "fields": "title",
            "cnum": "001",
            "sort": '{"webdate":0}',
            "ssort": "title",
            "cl": 200,
            "terminal": "",
            "condition": [
                {
                    "fieldName": "categorynum",
                    "equal": category.get("categorynum", ""),
                    "notEqual": None,
                    "equalList": None,
                    "notEqualList": None,
                    "isLike": True,
                    "likeType": 2,
                },
                {
                    "fieldName": "titlenew",
                    "equal": term,
                    "notEqual": None,
                    "equalList": None,
                    "notEqualList": None,
                    "isLike": True,
                    "likeType": 0,
                },
            ],
            "time": [{"fieldName": "webdate", "startTime": f"{start} 00:00:00", "endTime": f"{end} 23:59:59"}],
            "highlights": "title",
            "statistics": None,
            "unionCondition": None,
            "accuracy": "",
            "noParticiple": "0",
            "searchRange": None,
            "isBusiness": "1",
        }

    def fetch_records(self, category: dict, term: str, start: str, end: str, page: int) -> list[dict]:
        if not self.can_fetch(SEARCH_ENDPOINT):
            self.last_error = f"robots.txt 不允许访问：{SEARCH_ENDPOINT}"
            return []
        try:
            response = self.request_with_retries(
                "POST",
                SEARCH_ENDPOINT,
                json=self.build_payload(category, term, start, end, page),
                timeout=self.request_timeout(12),
                retries=1,
                headers={"Referer": REFERER, "Content-Type": "application/json"},
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}: {SEARCH_ENDPOINT}"
                return []
            payload = response.json()
            return (payload.get("result") or {}).get("records") or []
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Hebei public search failed: %s", exc)
            return []

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                return
            response.encoding = response.apparent_encoding or response.encoding
            parsed = parse_detail_html(response.text, tender.source_url)
        except Exception as exc:
            logger.info("Hebei detail skipped for %s: %s", tender.source_url, friendly_error_message(exc))
            return
        tender.title = parsed.get("title") or tender.title
        tender.publish_date = parsed.get("publish_date") or tender.publish_date
        tender.budget = parsed.get("budget") or tender.budget
        tender.project_no = parsed.get("project_no") or tender.project_no
        tender.contact_person = parsed.get("contact_person") or tender.contact_person
        tender.contact_phone = parsed.get("contact_phone") or tender.contact_phone
        tender.bid_deadline = parsed.get("bid_deadline") or tender.bid_deadline
        tender.important_info = parsed.get("important_info") or tender.important_info
        tender.summary = parsed.get("summary") or tender.summary
