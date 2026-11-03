import json
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote, urljoin

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


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "chongqing_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://www.cqggzy.com/"
SEARCH_URL = "https://www.cqggzy.com/search"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE_URL,
}


def parse_date(value: str) -> date | None:
    normalized = normalize_publish_date(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def in_date_range(publish_date: str, start_date: str, end_date: str) -> bool:
    pub = parse_date(publish_date)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not pub or not start or not end:
        return True
    return start <= pub <= end


def extract_budget(text: str) -> str:
    normalized = clean_text(text)
    patterns = [
        r"(预算金额|最高限价|中标（成交）金额|中标金额|服务金额|投资额)[:：]?\s*[￥¥]?\s*([0-9,.]+)\s*(万)?元",
        r"[￥¥]\s*([0-9,.]+)\s*(万)?元",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        amount = match.group(2) if len(match.groups()) >= 2 and match.group(2) else match.group(1)
        unit = "万元" if "万" in match.group(0) else "元"
        return f"{amount}{unit}"
    return ""


def decode_record(raw: str) -> dict | None:
    try:
        value = raw.replace(r"\"", '"').replace(r"\/", "/").replace(r"\u002F", "/")
        return json.loads(value)
    except Exception as exc:
        logger.exception("Failed to decode Chongqing record: %s", exc)
        return None


def extract_record_objects(html: str) -> list[dict]:
    pattern = re.compile(r'\{\\"pubinwebdate\\":\\".*?\\"infodate\\":\\".*?\\"\}', re.S)
    records = []
    for raw in pattern.findall(html):
        record = decode_record(raw)
        if record:
            records.append(record)
    return records


def parse_chongqing_search_html(
    html: str,
    query: str = "",
    start_date: str = "",
    end_date: str = "",
    base_url: str = BASE_URL,
) -> list[Tender]:
    tenders: list[Tender] = []
    seen: set[str] = set()
    records = extract_record_objects(html)

    for record in records:
        try:
            title = clean_text(record.get("titlenew") or record.get("title") or "")
            content = clean_text(record.get("content") or "")
            combined_text = f"{title} {content}"
            if query and query not in combined_text:
                continue

            publish_date = normalize_publish_date(record.get("webdate") or record.get("pubinwebdate") or record.get("infodate") or "")
            if publish_date and start_date and end_date and not in_date_range(publish_date, start_date, end_date):
                continue

            source_url = urljoin(base_url, record.get("linkurl") or "")
            if not title or not source_url or source_url in seen:
                continue
            seen.add(source_url)

            tender = Tender(
                title=title,
                announcement_type=clean_text(record.get("categorytype2") or record.get("categorytype") or ""),
                publish_date=publish_date,
                region=f"重庆市{clean_text(record.get('infoc') or '')}",
                purchaser=clean_text(record.get("companyname") or ""),
                budget=extract_budget(content),
                project_no=extract_project_no(content),
                contact_person=extract_contact_person(content),
                contact_phone=extract_phone(content),
                bid_deadline=extract_deadline(content),
                important_info=build_important_info(content),
                source_url=source_url,
                summary=summarize(content or title),
                source_name="重庆市公共资源交易网",
            )
            tenders.append(tender)
        except Exception as exc:
            logger.exception("Failed to parse Chongqing search record: %s", exc)

    return tenders


def parse_detail_html(html: str, url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)
    title = ""
    for selector in ["h1", "h2", ".title", ".article-title", ".detail-title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ")).replace("重庆市公共资源交易网_重庆市公共资源交易中心", "")

    content_node = soup.select_one(".article-content") or soup.select_one(".content") or soup.select_one("main") or soup.body
    content_text = html_to_text(str(content_node)) if content_node else text
    return {
        "title": title,
        "budget": extract_budget(text),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(content_text),
        "source_url": url,
    }


class ChongqingPublicCrawler(BaseCrawler):
    name = "重庆市公共资源交易网"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session.headers.update(BROWSER_HEADERS)

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("重庆" in clean_text(region or "") for region in regions):
            return []

        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        html = self.fetch_search_page(query)
        if not html:
            return []

        tenders = parse_chongqing_search_html(html, query=query, start_date=start, end_date=end)
        results = []
        seen = set()
        for tender in tenders:
            if tender.source_url in seen:
                continue
            seen.add(tender.source_url)
            if not self.enrich_from_detail(tender):
                continue
            results.append(self.apply_scoring(tender))
        return results

    def fetch_search_page(self, query: str) -> str | None:
        url = f"{SEARCH_URL}?keyword={quote(query or '')}"
        if not self.can_fetch(url):
            self.last_error = f"robots.txt 不允许访问：{url}"
            return None
        try:
            response = self.request_with_retries("GET", url, timeout=45, retries=1)
            response.encoding = response.apparent_encoding or response.encoding
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}"
                logger.warning("Chongqing search unavailable: %s", self.last_error)
                return None
            if "records" not in response.text and r"\"records\"" not in response.text:
                self.last_error = "搜索页未返回可解析的公开结果数据"
            return response.text
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Chongqing search request failed: %s", exc)
            return None

    def enrich_from_detail(self, tender: Tender) -> bool:
        try:
            response = self.get(tender.source_url)
            if not response:
                return False
            response.encoding = response.apparent_encoding or response.encoding
            parsed = parse_detail_html(response.text, tender.source_url)
            tender.title = parsed.get("title") or tender.title
            tender.budget = parsed.get("budget") or tender.budget
            tender.project_no = parsed.get("project_no") or tender.project_no
            tender.contact_person = parsed.get("contact_person") or tender.contact_person
            tender.contact_phone = parsed.get("contact_phone") or tender.contact_phone
            tender.bid_deadline = parsed.get("bid_deadline") or tender.bid_deadline
            tender.important_info = parsed.get("important_info") or tender.important_info
            tender.summary = parsed.get("summary") or tender.summary
            return True
        except Exception as exc:
            logger.exception("Chongqing detail parse failed for %s: %s", tender.source_url, exc)
            return False
