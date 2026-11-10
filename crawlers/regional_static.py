import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urljoin, urlparse

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


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


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


def publish_date_from_url(url: str) -> str:
    match = re.search(r"t(\d{4})(\d{2})(\d{2})_", url)
    if match:
        return normalize_publish_date(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    match = re.search(r"/(\d{4})(\d{2})(\d{2})/", url)
    if match:
        return normalize_publish_date(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    return ""


def infer_region(text: str, province: str) -> str:
    if province in {"新疆维吾尔自治区", "西藏自治区", "内蒙古自治区", "吉林省", "黑龙江省"}:
        return province
    if "新疆" in text:
        return "新疆维吾尔自治区"
    if "西藏" in text or any(city in text for city in ["拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"]):
        return "西藏自治区"
    if "内蒙古" in text or any(city in text for city in ["呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "乌兰察布"]):
        return "内蒙古自治区"
    if "吉林" in text or any(city in text for city in ["长春", "吉林市", "四平", "辽源", "通化", "白山", "松原", "白城", "延边"]):
        return "吉林省"
    if "黑龙江" in text or any(city in text for city in ["哈尔滨", "齐齐哈尔", "牡丹江", "佳木斯", "大庆", "鸡西", "双鸭山", "伊春", "七台河", "鹤岗", "黑河", "绥化", "大兴安岭"]):
        return "黑龙江省"
    if "上海" in text:
        return "上海市"
    if "浙江" in text:
        return "浙江省"
    if "安徽" in text:
        return "安徽省"
    return province


def extract_budget(text: str) -> str:
    match = re.search(
        r"(预算金额|最高限价|合同估算价)[:：]?\s*[￥¥]?\s*([0-9,.]+)\s*(万元|万|元)",
        text,
    )
    if not match:
        return ""
    unit = "万元" if match.group(3) in {"万元", "万"} else "元"
    return f"{match.group(2)}{unit}"


def parse_static_list_html(
    html: str,
    category: dict,
    base_url: str,
    source_name: str,
    province: str,
    query: str,
    start_date: str,
    end_date: str,
) -> list[Tender]:
    soup = BeautifulSoup(html, "html.parser")
    tenders: list[Tender] = []
    seen: set[str] = set()
    candidates = [(link, link.get("href", "")) for link in soup.select("a[href]")]
    for node in soup.select("[onclick]"):
        onclick = node.get("onclick", "")
        match = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", onclick)
        if match:
            candidates.append((node, match.group(1)))

    for link, href in candidates:
        title = clean_text(link.get_text(" ") or link.get("title", ""))
        if len(title) < 8 or href.startswith("javascript:"):
            continue
        if not any(token in href for token in ["Detail", "detail", "newDetail", ".html", ".jhtml", "guid="]):
            continue
        source_url = urljoin(base_url, href)
        # Static navigation endpoints are not notices, even when their labels
        # contain "项目" and pass the health probe's broad query.
        filename = urlparse(source_url).path.rstrip('/').rsplit('/', 1)[-1].lower()
        if filename in {'index.html', 'index.htm', 'list.html', 'list.htm',
                        'trading.html', 'subpage.html', 'transaction_notice.html'}:
            continue
        include_patterns = category.get("include_url_patterns") or []
        if include_patterns and not any(pattern in source_url or pattern in href for pattern in include_patterns):
            continue
        exclude_patterns = category.get("exclude_url_patterns") or []
        if exclude_patterns and any(pattern in source_url or pattern in href for pattern in exclude_patterns):
            continue
        container = link.find_parent("li") or link.find_parent("tr") or link.parent
        container_text = clean_text(container.get_text(" ")) if container else title
        if query and query not in f"{title} {container_text}":
            continue
        publish = ""
        match = re.search(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}", container_text)
        if match:
            publish = normalize_publish_date(match.group(0))
        publish = publish or publish_date_from_url(source_url)
        if publish and not in_date_range(publish, start_date, end_date):
            continue
        if source_url in seen:
            continue
        seen.add(source_url)
        tenders.append(
            Tender(
                title=title,
                announcement_type=category.get("announcement_type", ""),
                publish_date=publish,
                region=infer_region(container_text, province),
                source_url=source_url,
                summary=summarize(container_text),
                source_name=source_name,
            )
        )
    return tenders


def parse_detail_html(html: str, url: str, province: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)
    title = ""
    for selector in ["h1", "h2", ".title", ".article-title", ".ewb-article-title", ".detail-title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" "))
    if title in {"安徽省公共资源交易监管网", "上海公共资源交易平台"} or len(title) < 8:
        title = ""
    publish_match = re.search(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}", text)
    content_node = soup.select_one(".article-content") or soup.select_one(".content") or soup.select_one(".ewb-article-content") or soup.body
    content_text = html_to_text(str(content_node)) if content_node else text
    return {
        "title": title,
        "publish_date": publish_date_from_url(url) or (normalize_publish_date(publish_match.group(0)) if publish_match else ""),
        "region": infer_region(text, province),
        "purchaser": "",
        "agency": "",
        "budget": extract_budget(text),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(content_text),
        "source_url": url,
    }


class RegionalStaticCrawler(BaseCrawler):
    source_name = "区域公共资源平台"
    province = ""
    logger_name = "regional_static"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_name = clean_text(self.source_config.get("name") or self.source_name)
        self.province = clean_text(self.source_config.get("province") or self.source_config.get("region_name") or self.province)
        self.logger = get_logger(self.logger_name)

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        province_short = normalize_region_name(self.province)
        if regions and not any(province_short in normalize_region_name(region or "") for region in regions):
            return []
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        max_pages = int(self.source_config.get("max_pages", 1))
        max_items = int(self.source_config.get("max_items", 20))
        base_url = self.source_config.get("base_url", "")
        categories = self.source_config.get("categories", [])
        broad_match = bool(self.source_config.get("broad_match"))
        results: list[Tender] = []
        seen: set[str] = set()
        for category in categories:
            for page in range(1, max_pages + 1):
                url = self.build_list_url(base_url, category, page)
                html = self.fetch_page(url)
                if not html:
                    continue
                list_query = "" if broad_match else query
                tenders = parse_static_list_html(html, category, base_url, self.source_name, self.province, list_query, start, end)
                for tender in tenders:
                    if tender.source_url in seen:
                        continue
                    seen.add(tender.source_url)
                    self.enrich_from_detail(tender)
                    if query and not broad_match and query not in f"{tender.title} {tender.summary} {tender.important_info}":
                        continue
                    results.append(self.apply_scoring(tender))
                    if len(results) >= max_items:
                        return results
        return results

    def build_list_url(self, base_url: str, category: dict, page: int) -> str:
        path = category.get("path", "")
        params = dict(category.get("params", {}))
        if page > 1 and category.get("page_param"):
            params[category["page_param"]] = page
        url = urljoin(base_url, path)
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urlencode(params, doseq=True)
        return url

    def fetch_page(self, url: str) -> str | None:
        try:
            response = self.get(url)
            if not response:
                self.last_error = self.last_error or f"页面不可用：{url}"
                return None
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            self.logger.exception("Request failed for %s: %s", url, exc)
            return None

    def enrich_from_detail(self, tender: Tender) -> None:
        html = self.fetch_page(tender.source_url)
        if not html:
            return
        parsed = parse_detail_html(html, tender.source_url, self.province)
        tender.title = parsed.get("title") or tender.title
        tender.publish_date = parsed.get("publish_date") or tender.publish_date
        tender.region = parsed.get("region") or tender.region
        tender.budget = parsed.get("budget") or tender.budget
        tender.project_no = parsed.get("project_no") or tender.project_no
        tender.contact_person = parsed.get("contact_person") or tender.contact_person
        tender.contact_phone = parsed.get("contact_phone") or tender.contact_phone
        tender.bid_deadline = parsed.get("bid_deadline") or tender.bid_deadline
        tender.important_info = parsed.get("important_info") or tender.important_info
        tender.summary = parsed.get("summary") or tender.summary


def normalize_region_name(value: str) -> str:
    return clean_text(value).replace("省", "").replace("市", "").replace("自治区", "").replace("维吾尔", "")
