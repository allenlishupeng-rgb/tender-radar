import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
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
from scoring.project_profile import PROJECT_SEARCH_TERMS, expand_project_query_terms


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "suzhou_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://ggzy.suzhou.gov.cn/"
SEARCH_ENDPOINT = "https://ggzy.suzhou.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://ggzy.suzhou.gov.cn",
    "Referer": "https://ggzy.suzhou.gov.cn/search/fullsearch.html?wd=%E5%B1%95%E5%8E%85",
    "X-Requested-With": "XMLHttpRequest",
}

DEFAULT_TERMS = list(dict.fromkeys(["展厅", "展馆", "展陈", "布展", "展示中心", "数字展厅", "多媒体展项"] + PROJECT_SEARCH_TERMS))


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


def expand_query_terms(query: str) -> list[str]:
    return expand_project_query_terms(clean_text(query), DEFAULT_TERMS)


def text_matches_query(text: str, query: str) -> bool:
    if not query:
        return True
    return any(term in text for term in expand_query_terms(query))


def infer_region(record: dict, text: str = "") -> str:
    district = clean_text(record.get("diqu") or "")
    if district:
        return f"苏州市{district}" if "苏州" not in district else district
    for district in ["姑苏区", "吴中区", "相城区", "吴江区", "高新区", "工业园区", "太仓市", "昆山市", "常熟市", "张家港市"]:
        if district in text:
            return f"苏州市{district}"
    return "江苏省苏州市"


def extract_after_label(text: str, labels: list[str], max_len: int = 120) -> str:
    normalized = clean_text(text).replace("：", ":")
    for label in labels:
        marker = f"{label}:"
        if marker in normalized:
            return clean_text(normalized.split(marker, 1)[1][:max_len]).split(" ")[0].strip("|,，;；")
    return ""


def extract_budget(text: str) -> str:
    normalized = clean_text(text)
    patterns = [
        r"(预算金额|最高限价|最高投标限价|招标控制价|控制价|中标金额|成交金额|合同估算价|采购预算|项目预算)[:：]?\s*(?:人民币)?\s*([0-9,.]+)\s*(万元|元)",
        r"小写\s*([0-9,.]+)\s*[）)]",
        r"([0-9,.]+)\s*万元",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        if len(match.groups()) >= 3:
            return f"{match.group(2)}{match.group(3)}"
        if "小写" in match.group(0):
            return f"{match.group(1)}元"
        return f"{match.group(1)}万元"
    return ""


def parse_suzhou_search_response(data: dict | str, query: str = "", start_date: str = "", end_date: str = "") -> list[Tender]:
    if isinstance(data, str):
        data = json.loads(data)
    content = data.get("content")
    result = json.loads(content).get("result", {}) if isinstance(content, str) else data.get("result", {})
    records = result.get("records") or []
    tenders: list[Tender] = []
    seen: set[str] = set()
    for record in records:
        try:
            raw_title = record.get("title") or record.get("titlenew") or record.get("customtitle") or ""
            title = clean_text(BeautifulSoup(raw_title, "html.parser").get_text(""))
            content_text = html_to_text(record.get("content") or "")
            combined = f"{title} {content_text}"
            if not title or not text_matches_query(combined, query):
                continue
            publish = normalize_publish_date(record.get("webdate") or record.get("infodate") or "")
            if publish and start_date and end_date and not in_date_range(publish, start_date, end_date):
                continue
            source_url = urljoin(BASE_URL, clean_text(record.get("linkurl") or ""))
            if not source_url or source_url in seen:
                continue
            seen.add(source_url)
            tender = Tender(
                title=title,
                announcement_type=clean_text(record.get("categoryname") or ""),
                publish_date=publish,
                region=infer_region(record, combined),
                budget=extract_budget(content_text),
                project_no=extract_project_no(combined),
                contact_person=extract_contact_person(combined),
                contact_phone=extract_phone(combined),
                bid_deadline=extract_deadline(combined),
                important_info=build_important_info(combined),
                source_url=source_url,
                summary=summarize(content_text or title),
                source_name="苏州市公共资源交易平台",
            )
            tenders.append(tender)
        except Exception as exc:
            logger.exception("Failed to parse Suzhou search record: %s", exc)
    return tenders


def parse_detail_html(html: str, url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)
    title = ""
    for selector in ["h1", "h2", ".article-title", ".ewb-article-title", ".title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ")).replace("苏州市公共资源交易平台", "")

    publish = extract_after_label(text, ["信息发布时间", "发布时间", "发布日期"], 40)
    if not publish:
        match = re.search(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?|\d{4}年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", text)
        publish = match.group(0) if match else ""

    content_node = (
        soup.select_one(".article-info")
        or soup.select_one(".ewb-article-content")
        or soup.select_one(".article-content")
        or soup.select_one(".TRS_Editor")
        or soup.select_one(".content")
        or soup.body
    )
    content_text = html_to_text(str(content_node)) if content_node else text
    return {
        "title": title,
        "publish_date": normalize_publish_date(publish),
        "region": infer_region({}, text),
        "announcement_type": extract_after_label(text, ["公告类型", "信息类型"]) or "",
        "purchaser": extract_after_label(text, ["采购人信息 名称", "采购人名称", "采购人", "招标人名称", "招标人", "建设单位", "项目业主"]),
        "agency": extract_after_label(text, ["采购代理机构信息 名称", "采购代理机构名称", "采购代理机构", "招标代理机构名称", "招标代理机构", "代理机构名称", "代理机构"]),
        "budget": extract_budget(text),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(content_text),
        "source_url": url,
    }


class SuzhouPublicCrawler(BaseCrawler):
    name = "苏州市公共资源交易平台"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session.headers.update(BROWSER_HEADERS)
        self._warmed_up = False

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any(("苏州" in clean_text(region or "") or "江苏" in clean_text(region or "")) for region in regions):
            return []
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        max_pages = int(self.source_config.get("max_pages", 2))
        max_terms = int(self.source_config.get("max_terms", 8))
        managed_terms = self.source_config.get("search_terms") or DEFAULT_TERMS
        terms = expand_query_terms(query)[:max_terms] if query else managed_terms[:max_terms]
        result_limit = self.source_result_limit(22)
        deadline = self.source_deadline(45)
        detail_limit = max(int(self.source_config.get("detail_enrichment_limit", 8) or 8), 0)
        detail_count = 0
        results: list[Tender] = []
        seen: set[str] = set()

        for term in terms:
            if self.source_should_stop(results, deadline, result_limit):
                return results
            for page in range(max_pages):
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                data = self.fetch_search(term, page)
                if not data:
                    continue
                tenders = parse_suzhou_search_response(data, query=query or term, start_date=start, end_date=end)
                if not tenders and page > 0:
                    break
                for tender in tenders:
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    if tender.source_url in seen:
                        continue
                    seen.add(tender.source_url)
                    if detail_count < detail_limit:
                        if not self.enrich_from_detail(tender):
                            continue
                        detail_count += 1
                    results.append(self.apply_scoring(tender))
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
        return results

    def build_payload(self, term: str, page: int) -> dict:
        return {
            "token": "",
            "pn": page * 10,
            "rn": 10,
            "sdt": "",
            "edt": "",
            "wd": term,
            "inc_wd": "",
            "exc_wd": "",
            "fields": "title;content",
            "cnum": "001",
            "sort": "{webdate:0}",
            "ssort": "title",
            "cl": 500,
            "terminal": "",
            "condition": None,
            "time": None,
            "highlights": "title;content",
            "statistics": None,
            "unionCondition": None,
            "accuracy": "",
            "noParticiple": "1",
            "searchRange": None,
        }

    def fetch_search(self, term: str, page: int) -> dict | None:
        if not self.can_fetch(SEARCH_ENDPOINT):
            self.last_error = f"robots.txt 不允许访问：{SEARCH_ENDPOINT}"
            return None
        try:
            self.warmup_public_session()
            time.sleep(self.request_interval)
            response = self.session.post(
                SEARCH_ENDPOINT,
                json=self.build_payload(term, page),
                timeout=self.request_timeout(12),
                headers={"Content-Type": "application/json;charset=UTF-8"},
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}"
                return None
            return response.json()
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Suzhou public search failed: %s", exc)
            return None

    def warmup_public_session(self) -> None:
        if self._warmed_up:
            return
        try:
            self.session.get(BASE_URL, timeout=self.request_timeout(8))
        except Exception as exc:
            logger.warning("Suzhou public session warmup failed: %s", exc)
        finally:
            self._warmed_up = True

    def enrich_from_detail(self, tender: Tender) -> bool:
        try:
            response = self.get(tender.source_url)
            if not response:
                logger.warning("Suzhou detail unavailable: %s", tender.source_url)
                return False
            response.encoding = response.apparent_encoding or response.encoding
            parsed = parse_detail_html(response.text, tender.source_url)
            tender.title = parsed.get("title") or tender.title
            tender.publish_date = parsed.get("publish_date") or tender.publish_date
            tender.region = parsed.get("region") or tender.region
            tender.announcement_type = parsed.get("announcement_type") or tender.announcement_type
            tender.purchaser = parsed.get("purchaser") or tender.purchaser
            tender.agency = parsed.get("agency") or tender.agency
            tender.budget = parsed.get("budget") or tender.budget
            tender.project_no = parsed.get("project_no") or tender.project_no
            tender.contact_person = parsed.get("contact_person") or tender.contact_person
            tender.contact_phone = parsed.get("contact_phone") or tender.contact_phone
            tender.bid_deadline = parsed.get("bid_deadline") or tender.bid_deadline
            tender.important_info = parsed.get("important_info") or tender.important_info
            tender.summary = parsed.get("summary") or tender.summary
            return True
        except Exception as exc:
            logger.exception("Suzhou detail parse failed for %s: %s", tender.source_url, exc)
            return False


def parse_fixture(path: Path) -> list[Tender]:
    return parse_suzhou_search_response(path.read_text(encoding="utf-8"), query="展厅")
