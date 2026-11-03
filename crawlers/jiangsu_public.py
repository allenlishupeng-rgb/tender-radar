import logging
import re
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
from scoring.project_profile import expand_project_query_terms


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "jiangsu_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://jsggzy.jszwfw.gov.cn/"
SEARCH_ENDPOINT = "https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://jsggzy.jszwfw.gov.cn",
    "Referer": "https://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html?type=zfcg",
}

DEFAULT_CATEGORIES = [
    {"name": "工程建设-招标公告", "categorynum": "003001001", "announcement_type": "招标公告/资审公告"},
    {"name": "政府采购-采购预告", "categorynum": "003004001", "announcement_type": "采购预告"},
    {"name": "政府采购-采购公告", "categorynum": "003004002", "announcement_type": "采购公告"},
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
    return expand_project_query_terms(clean_text(query), ["展览展示", "展陈设计", "展陈施工", "设计施工一体化", "数字展厅", "多媒体展项"])


def text_matches_query(text: str, query: str) -> bool:
    if not query:
        return True
    terms = expand_query_terms(query)
    return any(term in text for term in terms)


def extract_after_label(text: str, labels: list[str], max_len: int = 100) -> str:
    normalized = clean_text(text).replace("：", ":")
    for label in labels:
        marker = f"{label}:"
        if marker in normalized:
            return clean_text(normalized.split(marker, 1)[1][:max_len]).split(" ")[0]
    return ""


def infer_region(text: str) -> str:
    for city in ["南京", "苏州", "无锡", "常州", "镇江", "扬州", "南通", "泰州", "盐城", "淮安", "宿迁", "徐州", "连云港"]:
        if city in text:
            return f"江苏省{city}市"
    return "江苏省"


def extract_budget(text: str) -> str:
    patterns = [
        r"(预算金额|最高限价|合同估算价|投资额|采购预算)[:：]?\s*([0-9,.]+)\s*(万元|元)",
        r"([0-9,.]+)\s*万元",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_text(text))
        if not match:
            continue
        if len(match.groups()) >= 3:
            return f"{match.group(2)}{match.group(3)}"
        return f"{match.group(1)}万元"
    return ""


def parse_list_html(
    html: str,
    category: dict[str, str],
    base_url: str = BASE_URL,
    query: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list[Tender]:
    """Compatibility parser for saved Jiangsu HTML fixtures and legacy static pages."""
    soup = BeautifulSoup(html, "html.parser")
    tenders: list[Tender] = []
    seen_urls: set[str] = set()
    for link in soup.select("a[href]"):
        try:
            title = clean_text(link.get_text(" "))
            href = link.get("href", "")
            if not title or not href:
                continue
            container = link.find_parent("li") or link.parent
            container_text = clean_text(container.get_text(" ")) if container else title
            if not text_matches_query(f"{title} {container_text}", query):
                continue
            publish = ""
            date_match = re.search(r"\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}|\d{2}-\d{2}", container_text)
            if date_match:
                publish = date_match.group(0).replace("/", "-")
                if re.fullmatch(r"\d{2}-\d{2}", publish):
                    publish = f"{date.today().year}-{publish}"
            if publish and start_date and end_date and not in_date_range(publish, start_date, end_date):
                continue
            source_url = urljoin(base_url, href)
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            region_match = re.search(r"〖([^〗]+)〗", title)
            tenders.append(
                Tender(
                    title=title,
                    announcement_type=category.get("announcement_type", ""),
                    publish_date=normalize_publish_date(publish),
                    region=region_match.group(1) if region_match else infer_region(title or container_text),
                    source_url=source_url,
                    summary=summarize(container_text or title),
                    source_name="江苏省公共资源交易平台",
                )
            )
        except Exception as exc:
            logger.exception("Failed to parse Jiangsu static list item: %s", exc)
    return tenders


def parse_detail_html(html: str, url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)

    title = ""
    for selector in ["h1", "h2", ".ewb-article-title", ".article-title", ".detail-title", ".title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ")).replace("江苏省公共资源交易网", "")

    publish = extract_after_label(text, ["信息发布时间", "发布时间", "发布日期"], 40)
    if not publish:
        match = re.search(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?", text)
        publish = match.group(0) if match else ""

    content_node = (
        soup.select_one(".ewb-article-content")
        or soup.select_one(".article-content")
        or soup.select_one(".content")
        or soup.body
    )
    content_text = html_to_text(str(content_node)) if content_node else text

    return {
        "title": title,
        "publish_date": normalize_publish_date(publish),
        "region": infer_region(text),
        "announcement_type": extract_after_label(text, ["公告类型", "信息类型"]) or "",
        "purchaser": extract_after_label(text, ["招标人", "采购人", "项目业主"]),
        "agency": extract_after_label(text, ["招标代理机构", "采购代理机构", "代理机构"]),
        "budget": extract_budget(text),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(content_text),
        "source_url": url,
    }


class JiangsuPublicCrawler(BaseCrawler):
    name = "江苏省公共资源交易平台"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session.headers.update(BROWSER_HEADERS)
        self._warmed_up = False

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("江苏" in clean_text(region or "") for region in regions):
            return []

        end = normalize_date(end_date) or date.today().isoformat()
        start = normalize_date(start_date) or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        max_pages = int(self.source_config.get("max_pages", 4))
        max_terms = int(self.source_config.get("max_terms", 10))
        categories = self.source_config.get("categories") or DEFAULT_CATEGORIES
        base_url = self.source_config.get("base_url", BASE_URL)
        result_limit = self.source_result_limit(22)
        deadline = self.source_deadline(45)
        detail_limit = max(int(self.source_config.get("detail_enrichment_limit", 10) or 10), 0)
        detail_count = 0

        results: list[Tender] = []
        seen_urls: set[str] = set()
        # The runner already expands the profile; do not replay it per term.
        search_terms = [query] if query else (self.source_config.get("search_terms") or ["展厅", "展陈", "布展", "展示中心"])[:max_terms]
        for category in categories:
            if self.source_should_stop(results, deadline, result_limit):
                return results
            for term in search_terms:
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                for page in range(max_pages):
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    payload = self.build_payload(category.get("categorynum", ""), page, term)
                    payload["time"] = [{"fieldName": "infodatepx", "startTime": f"{start} 00:00:00", "endTime": f"{end} 23:59:59"}]
                    payload["ssort"] = ""
                    data = self.fetch_search(payload)
                    if not data:
                        continue
                    records = data.get("records") or []
                    if not records and page > 0:
                        break
                    for record in records:
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
                        tender = self.record_to_tender(record, category, base_url)
                        if not tender or tender.source_url in seen_urls:
                            continue
                        combined = f"{tender.title} {tender.summary}"
                        if not text_matches_query(combined, query):
                            continue
                        if not in_date_range(tender.publish_date, start, end):
                            continue
                        seen_urls.add(tender.source_url)
                        tender = self.apply_scoring(tender)
                        if tender.priority != "可能无关" and detail_count < detail_limit:
                            self.enrich_from_detail(tender)
                            detail_count += 1
                            tender = self.apply_scoring(tender)
                        results.append(tender)
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
        return results

    def build_payload(self, categorynum: str, page: int, wd: str = "") -> dict:
        return {
            "token": "",
            "pn": page * 20,
            "rn": 20,
            "sdt": "",
            "edt": "",
            "wd": wd,
            "inc_wd": "",
            "exc_wd": "",
            "fields": "title",
            "cnum": "001",
            "sort": '{"infodatepx":"0"}',
            "ssort": "title",
            "cl": 200,
            "terminal": "",
            "condition": [{"fieldName": "categorynum", "isLike": True, "likeType": 2, "equal": categorynum}],
            "time": None,
            "highlights": "title",
            "statistics": None,
            "unionCondition": None,
            "accuracy": "",
            "noParticiple": "0" if wd else "1",
            "searchRange": None,
            "isBusiness": "1",
        }

    def fetch_search(self, payload: dict) -> dict | None:
        if not self.can_fetch(SEARCH_ENDPOINT):
            self.last_error = f"robots.txt 不允许访问：{SEARCH_ENDPOINT}"
            return None
        try:
            self.warmup_public_session()
            response = self.request_with_retries(
                "POST", SEARCH_ENDPOINT,
                json=payload,
                timeout=self.request_timeout(12),
                headers={"Content-Type": "application/json;charset=UTF-8"},
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}"
                return None
            return response.json().get("result") or {}
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Jiangsu public API request failed: %s", exc)
            return None

    def warmup_public_session(self) -> None:
        if self._warmed_up:
            return
        try:
            timeout = self.request_timeout(8)
            self.request_with_retries("GET", BASE_URL, timeout=timeout, retries=0)
        except Exception as exc:
            logger.warning("Jiangsu public session warmup failed: %s", exc)
        finally:
            self._warmed_up = True

    def record_to_tender(self, record: dict, category: dict, base_url: str) -> Tender | None:
        title = clean_text(record.get("titlenew") or record.get("title") or "")
        link = clean_text(record.get("linkurl") or "")
        if not title or not link:
            return None
        content = html_to_text(record.get("content") or "")
        publish = normalize_publish_date(record.get("infodatepx") or record.get("infodate") or record.get("webdate") or "")
        source_url = urljoin(base_url, link)
        source_url = source_url.replace("http://jsggzy.jszwfw.gov.cn/", BASE_URL)
        return Tender(
            title=title,
            announcement_type=record.get("categoryname") or category.get("announcement_type", ""),
            publish_date=publish,
            region=infer_region(f"{title} {content} {record.get('zhuanzai', '')}"),
            budget=extract_budget(content),
            project_no=extract_project_no(content),
            contact_person=extract_contact_person(content),
            contact_phone=extract_phone(content),
            bid_deadline=extract_deadline(content),
            important_info=build_important_info(content),
            source_url=source_url,
            summary=summarize(content or title),
            source_name="江苏省公共资源交易平台",
        )

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                logger.warning("Jiangsu detail unavailable: %s", tender.source_url)
                return
            response.encoding = response.apparent_encoding or response.encoding
            parsed = parse_detail_html(response.text, tender.source_url)
            detail_title = parsed.get("title") or ""
            generic_titles = {"评标办法", "招标公告", "采购公告", "中标候选人公示", "中标结果公告"}
            if detail_title and detail_title not in generic_titles:
                tender.title = detail_title
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
        except Exception as exc:
            logger.exception("Jiangsu detail parse failed for %s: %s", tender.source_url, exc)


def parse_fixture(path: Path) -> dict[str, str]:
    return parse_detail_html(path.read_text(encoding="utf-8"), url="http://jsggzy.jszwfw.gov.cn/sample.html")
