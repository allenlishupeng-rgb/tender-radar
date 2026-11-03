import logging
import re
from datetime import date, datetime, timedelta
from html import unescape

from bs4 import BeautifulSoup

from config.settings import LOG_DIR
from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, html_to_text, summarize
from parsers.extractors import normalize_publish_date
from scoring.project_profile import PROJECT_SEARCH_TERMS


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "guizhou_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://ggzy.guizhou.gov.cn/"
TRADE_LIST_ENDPOINT = f"{BASE_URL.rstrip('/')}/tradeInfo/es/list"
SEARCH_ENDPOINT = "https://ggzy.guizhou.gov.cn/irs/front/search"
SEARCH_TERMS = list(
    dict.fromkeys(
        ["企业展厅", "产业展示中心", "科技展厅", "展厅", "展陈", "布展", "展示中心", "数字展厅", "规划馆"]
        + PROJECT_SEARCH_TERMS
    )
)


def strip_html(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", "", unescape(value or "")))


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


def timestamp_ms(value: str, end_of_day: bool = False) -> int:
    parsed = parse_date(value)
    if not parsed:
        return 0
    moment = datetime.combine(parsed, datetime.max.time() if end_of_day else datetime.min.time())
    return int(moment.timestamp() * 1000)


def publish_from_timestamp(value) -> str:
    text = clean_text(str(value or ""))
    if not text or not text.isdigit():
        return ""
    try:
        timestamp = int(text)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp).date().isoformat()
    except Exception:
        return ""


def in_date_range(publish_date: str, start_date: str, end_date: str) -> bool:
    published = parse_date(publish_date)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not published or not start or not end:
        return False
    return start <= published <= end


def date_from_url(value: str) -> str:
    match = re.search(r"/t(\d{8})_", value or "")
    if not match:
        return ""
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def best_publish_date(record: dict) -> str:
    timestamp_date = publish_from_timestamp(record.get("docRelTime"))
    if timestamp_date:
        return timestamp_date
    pub_date = normalize_publish_date(record.get("PubDate") or record.get("pubDate") or "")
    if pub_date:
        return pub_date
    url_date = date_from_url(clean_text(record.get("url") or record.get("linkUrl") or ""))
    if url_date:
        return url_date
    return normalize_publish_date(record.get("time") or "")


def result_matches_region(record: dict, region_name: str) -> bool:
    if not region_name or region_name == "贵州":
        return True
    needle = region_name.replace("市", "").replace("省", "")
    text = " ".join(
        strip_html(str(record.get(field) or ""))
        for field in ["docSourceName", "source", "docTitle", "title", "content", "apiUrl", "url"]
    )
    return needle in text.replace("市", "").replace("省", "")


def record_matches_terms(record: dict, terms: list[str]) -> bool:
    text = " ".join(
        strip_html(str(record.get(field) or ""))
        for field in ["docTitle", "title", "content", "announcement", "businessTypeName"]
    )
    return any(term and term in text for term in terms)


def meta_content(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    return clean_text(tag.get("content") if tag else "")


def value_after_label(text: str, labels: list[str]) -> str:
    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for index, line in enumerate(lines):
        normalized = line.rstrip(":：")
        if normalized in labels and index + 1 < len(lines):
            return lines[index + 1]
        for label in labels:
            if line.startswith(f"{label}：") or line.startswith(f"{label}:"):
                return clean_text(line.split("：", 1)[-1] if "：" in line else line.split(":", 1)[-1])
    return ""


def extract_budget(text: str) -> str:
    patterns = [
        r"(?:采购预算|项目预算|预算金额|最高限价|最高投标限价|招标控制价|控制价|成交金额|中标金额|投标总报价)\s*[（(]?元?[）)]?\s*[:：]?\s*([\d,]+(?:\.\d+)?\s*(?:万元|元)?)",
        r"(?:投标总报价|成交结果)\s*[:：]?\s*[\(（]?元[\)）]?\s*([\d,]+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = clean_text(match.group(1)).replace(",", "")
            if re.fullmatch(r"\d+(?:\.\d+)?", value):
                value = f"{value}元"
            return value
    return ""


def parse_trade_detail_html(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = meta_content(soup, "ArticleTitle") or clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    publish_date = normalize_publish_date(meta_content(soup, "PubDate"))
    source = meta_content(soup, "ContentSource")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    text = soup.get_text("\n", strip=True)
    summary_text = html_to_text(str(soup))
    return {
        "title": title,
        "publish_date": publish_date,
        "source": source,
        "text": text,
        "summary_text": summary_text,
        "purchaser": value_after_label(text, ["招标人（采购人）", "招标人(采购人)", "采购人", "招标人"]),
        "agency": value_after_label(text, ["代理机构", "采购代理机构", "招标代理机构"]),
        "budget": extract_budget(text),
        "project_no": value_after_label(text, ["项目编号", "招标编号", "采购项目编号", "标包编号"]),
        "bid_deadline": value_after_label(text, ["投标截止时间", "响应文件提交截止时间", "响应文件递交截止时间", "提交投标文件截止时间", "开标时间"]),
        "contact_person": value_after_label(text, ["项目联系人", "联系人", "招标联系人", "采购联系人"]),
        "contact_phone": value_after_label(text, ["联系电话", "联系方式", "项目联系电话", "采购人联系方式"]),
    }


def trade_record_to_tender(record: dict, source_name: str, region_name: str, detail: dict | None = None) -> Tender:
    detail = detail or {}
    title = clean_text(detail.get("title") or record.get("docTitle") or record.get("title") or "")
    content = clean_text(detail.get("text") or record.get("content") or "")
    summary_content = clean_text(detail.get("summary_text") or content)
    source = clean_text(detail.get("source") or record.get("docSourceName") or record.get("source") or "")
    url = clean_text(record.get("apiUrl") or record.get("url") or record.get("linkUrl") or BASE_URL)
    region = "贵阳市" if "贵阳" in f"{source} {title} {content}" else region_name
    announcement = " ".join(
        item
        for item in [
            clean_text(record.get("businessTypeName") or ""),
            clean_text(record.get("announcement") or ""),
        ]
        if item
    )
    return Tender(
        title=title,
        announcement_type=announcement or "交易信息",
        publish_date=clean_text(detail.get("publish_date") or best_publish_date(record)),
        region=region,
        purchaser=clean_text(detail.get("purchaser") or ""),
        agency=clean_text(detail.get("agency") or ""),
        budget=clean_text(detail.get("budget") or ""),
        project_no=clean_text(detail.get("project_no") or record.get("tenderProjectCode") or ""),
        contact_person=clean_text(detail.get("contact_person") or ""),
        contact_phone=clean_text(detail.get("contact_phone") or ""),
        bid_deadline=clean_text(detail.get("bid_deadline") or ""),
        important_info=summarize(summary_content),
        source_url=url,
        summary=summarize(summary_content or title),
        source_name=source_name,
    )


class GuizhouPublicCrawler(BaseCrawler):
    name = "贵州省公共资源交易数据"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        source_name = clean_text(self.source_config.get("name") or self.name)
        region_name = clean_text(self.source_config.get("region_name") or "贵州")
        max_pages = int(self.source_config.get("max_pages", 3))
        max_terms = int(self.source_config.get("max_terms", 6))
        query_terms = [clean_text(query)] if clean_text(query or "") else []
        terms = list(dict.fromkeys([*query_terms, *SEARCH_TERMS]))[:max_terms]
        end = normalize_date(end_date) or date.today().isoformat()
        start = normalize_date(start_date) or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        result_limit = self.source_result_limit(16)
        deadline = self.source_deadline(40)
        detail_limit = max(int(self.source_config.get("detail_enrichment_limit", 10) or 10), 0)
        detail_count = 0

        if regions and not any(region_name.replace("省", "").replace("市", "") in clean_text(region or "") for region in regions):
            return []

        results: list[Tender] = []
        seen: set[str] = set()
        for term in terms:
            if self.source_should_stop(results, deadline, result_limit):
                return results
            if not term:
                continue
            for page in range(1, max_pages + 1):
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                payload = self.fetch_trade_page(term, page, start, end, region_name)
                records = (payload or {}).get("list") or []
                if not records:
                    break
                for record in records:
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    if not record_matches_terms(record, terms) or not result_matches_region(record, region_name):
                        continue
                    url = clean_text(record.get("apiUrl") or "")
                    if not url or url in seen:
                        continue
                    tender = self.apply_scoring(trade_record_to_tender(record, source_name, region_name))
                    if tender.priority != "可能无关" and detail_count < detail_limit:
                        detail = self.fetch_trade_detail(url)
                        detail_count += 1
                        tender = self.apply_scoring(trade_record_to_tender(record, source_name, region_name, detail))
                    if not tender.title:
                        continue
                    if not tender.publish_date or not in_date_range(tender.publish_date, start, end):
                        continue
                    seen.add(url)
                    results.append(tender)
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
        if not results:
            self.last_error = self.last_error or f"未在{region_name}公共资源交易信息接口中发现展厅/展陈匹配项目"
        return results

    def fetch_trade_page(self, term: str, page: int, start_date: str, end_date: str, region_name: str) -> dict | None:
        payload = {
            "pageNum": page,
            "pageSize": 20,
            "docTitle": term,
            "startTime": f"{start_date} 00:00:00",
            "endTime": f"{end_date} 23:59:59",
        }
        if region_name and region_name != "贵州":
            payload["docSourceName"] = region_name.replace("市", "").replace("省", "")
        try:
            response = self.session.post(
                TRADE_LIST_ENDPOINT,
                json=payload,
                timeout=self.request_timeout(10),
                headers={"Referer": f"{BASE_URL}xxfw/search.html", "Content-Type": "application/json;charset=UTF-8"},
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}: {TRADE_LIST_ENDPOINT}"
                return None
            return response.json()
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Guizhou public trade list failed: %s", exc)
            return None

    def fetch_trade_detail(self, url: str) -> dict:
        try:
            response = self.session.get(url, timeout=self.request_timeout(10), headers={"Referer": BASE_URL})
            if response.status_code != 200:
                logger.info("Guizhou detail HTTP %s: %s", response.status_code, url)
                return {}
            return parse_trade_detail_html(response.text)
        except Exception as exc:
            logger.info("Guizhou detail request skipped: %s", friendly_error_message(exc))
            return {}


class GuiyangPublicCrawler(GuizhouPublicCrawler):
    name = "贵阳市公共资源交易数据"
