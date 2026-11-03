import logging
import re
from datetime import date, timedelta
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
from scoring.rules import annotate_notice_stage, is_target_exhibition_tender, NOTICE_STAGE_BID
from scoring.project_profile import is_public_culture_without_target


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "ccgp_public.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


SEARCH_ENDPOINT = "https://search.ccgp.gov.cn/bxsearch"

DEFAULT_BID_TYPES = [
    {"bid_type": "1", "announcement_type": "公开招标公告"},
    {"bid_type": "9", "announcement_type": "竞争性磋商公告"},
]

DEFAULT_TARGET_REGIONS = [
    {"name": "江苏", "display_zone": "江苏", "zone_id": ""},
    {"name": "上海", "display_zone": "上海", "zone_id": ""},
    {"name": "浙江", "display_zone": "浙江", "zone_id": ""},
    {"name": "安徽", "display_zone": "安徽", "zone_id": ""},
    {"name": "湖南", "display_zone": "湖南", "zone_id": ""},
    {"name": "长沙", "display_zone": "长沙", "zone_id": ""},
    {"name": "贵州", "display_zone": "贵州", "zone_id": ""},
    {"name": "贵阳", "display_zone": "贵阳", "zone_id": ""},
    {"name": "新疆", "display_zone": "新疆", "zone_id": ""},
    {"name": "西藏", "display_zone": "西藏", "zone_id": ""},
    {"name": "内蒙古", "display_zone": "内蒙古", "zone_id": ""},
]


def normalize_date(value: str | date | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return clean_text(str(value or ""))


def ccgp_date(value: str) -> str:
    return normalize_date(value).replace("-", ":")


def extract_meta_value(text: str, labels: list[str]) -> str:
    normalized = clean_text(text).replace("：", ":")
    parts = [part.strip() for part in normalized.split("|")]
    for part in parts:
        for label in labels:
            prefix = f"{label}:"
            if part.startswith(prefix):
                return clean_text(part.replace(prefix, "", 1))
    return ""


def parse_search_html(html: str, base_url: str = SEARCH_ENDPOINT) -> list[Tender]:
    if "您的访问过于频繁" in html or "频繁访问" in html or "访问过于频繁" in html:
        logger.warning("CCGP search returned frequent-access page")
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".vT-srch-result-list-bid li")
    tenders: list[Tender] = []

    for item in items:
        try:
            link = item.select_one("a[href]")
            if not link:
                continue
            title = clean_text(link.get_text(" "))
            href = urljoin(base_url, link.get("href", ""))
            meta_text = clean_text(" ".join(span.get_text(" ") for span in item.select("span")))
            summary_text = clean_text(" ".join(p.get_text(" ") for p in item.select("p")))

            tender = Tender(
                title=title,
                announcement_type=extract_meta_value(meta_text, ["公告类型", "公告品目"]) or "采购公告",
                publish_date=normalize_publish_date(extract_meta_value(meta_text, ["发布时间", "发布日期"])) or normalize_publish_date(href),
                region=extract_meta_value(meta_text, ["地区", "行政区域"]),
                purchaser=extract_meta_value(meta_text, ["采购人"]),
                agency=extract_meta_value(meta_text, ["代理机构"]),
                source_url=href,
                summary=summarize(summary_text or meta_text or title),
                source_name="中国政府采购网",
            )
            if tender.title and tender.source_url:
                tenders.append(tender)
        except Exception as exc:
            logger.exception("Failed to parse CCGP search item: %s", exc)

    return tenders


def extract_after_label(text: str, labels: list[str], max_len: int = 80) -> str:
    normalized = clean_text(text).replace("：", ":")
    for label in labels:
        marker = f"{label}:"
        if marker in normalized:
            return clean_text(normalized.split(marker, 1)[1][:max_len]).split(" ")[0]
        match = re.search(rf"{re.escape(label)}\s+([^\s|,，;；。]+)", normalized)
        if match:
            return clean_text(match.group(1))
    return ""


def parse_detail_html(html: str, url: str = "") -> dict[str, str]:
    if "您的访问过于频繁" in html:
        logger.warning("CCGP detail returned frequent-access page: %s", url)
        return {"source_url": url, "summary": ""}

    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)

    title = ""
    for selector in ["h1", "h2", ".vT_detail_header h2", ".article-title", ".detail-title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ")).replace("_中国政府采购网", "")

    content_node = soup.select_one(".vT_detail_content") or soup.select_one(".content") or soup.body
    content_text = html_to_text(str(content_node)) if content_node else text
    contact_text = text.split("联系人及联系方式", 1)[1] if "联系人及联系方式" in text else content_text

    publish_date = normalize_publish_date(extract_after_label(text, ["发布时间", "发布日期"])) or normalize_publish_date(url)

    return {
        "title": title,
        "publish_date": publish_date,
        "region": extract_after_label(text, ["地区", "行政区域"]),
        "announcement_type": extract_after_label(text, ["公告类型", "采购方式", "信息类型"]),
        "purchaser": extract_after_label(text, ["采购单位", "采购人"]),
        "agency": extract_after_label(text, ["代理机构名称", "采购代理机构", "代理机构"]),
        "budget": extract_after_label(text, ["预算金额", "预算金额：", "项目预算"]),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(contact_text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(content_text),
        "source_url": url,
    }


class CcgpPublicCrawler(BaseCrawler):
    name = "中国政府采购网"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._detail_enrichment_count = 0

    def search(
        self,
        query: str,
        days: int = 7,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        regions: list[str] | None = None,
    ) -> list[Tender]:
        end = normalize_date(end_date) or date.today().isoformat()
        start = normalize_date(start_date) or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        max_pages = int(self.source_config.get("max_pages", 2))
        bid_types = self.source_config.get("bid_types") or DEFAULT_BID_TYPES
        target_regions = self.resolve_target_regions(regions)
        source_name = clean_text(self.source_config.get("name") or self.name)
        result_limit = self.source_result_limit(18)
        detail_limit = max(self.config_int("detail_enrichment_limit", 8), 0)
        deadline = self.source_deadline(60)

        results: list[Tender] = []
        seen_urls: set[str] = set()

        for region in target_regions:
            if self.source_should_stop(results, deadline, result_limit):
                return results
            for bid_type in bid_types:
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                for page in range(1, max_pages + 1):
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    html = self.fetch_search_page(query, start, end, bid_type, page, region)
                    if not html:
                        if "访问过于频繁" in self.last_error or "响应超时" in self.last_error:
                            return results
                        continue
                    tenders = parse_search_html(html)
                    if not tenders:
                        break
                    for tender in tenders:
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
                        if tender.source_url in seen_urls:
                            continue
                        seen_urls.add(tender.source_url)
                        tender.region = tender.region or region.get("name", "")
                        tender.announcement_type = tender.announcement_type or bid_type.get("announcement_type", "")
                        tender.source_name = source_name
                        scored = self.apply_scoring(tender)
                        annotate_notice_stage(scored)
                        header = {"title": scored.title, "purchaser": scored.purchaser, "summary": "", "important_info": ""}
                        if (
                            self._detail_enrichment_count < detail_limit
                            and scored.priority != "可能无关"
                            and scored.notice_stage == NOTICE_STAGE_BID
                            and is_target_exhibition_tender(header)
                            and not is_public_culture_without_target(scored.title, scored.profile_project_type)
                            and not self.source_timed_out(deadline)
                        ):
                            self.enrich_from_detail(scored)
                            self._detail_enrichment_count += 1
                            scored = self.apply_scoring(scored)
                        results.append(scored)
                        if self.source_should_stop(results, deadline, result_limit):
                            return results

        return results

    def resolve_target_regions(self, regions: list[str] | None = None) -> list[dict[str, str]]:
        configured = self.source_config.get("target_regions") or DEFAULT_TARGET_REGIONS
        if not regions:
            default_names = self.source_config.get("default_target_regions") or []
            if not default_names:
                return configured
            selected = []
            for region in configured:
                name = region.get("name", "")
                display = region.get("display_zone", "")
                if any(value and (value in name or value in display or name in value or display in value) for value in default_names):
                    selected.append(region)
            return selected or configured
        values = []
        for value in regions:
            text = clean_text(value or "")
            if not text:
                continue
            values.extend([text, text.replace("省", "").replace("市", "")])
        selected = []
        for region in configured:
            name = region.get("name", "")
            display = region.get("display_zone", "")
            if any(value and (value in name or value in display or name in value or display in value) for value in values):
                selected.append(region)
        return selected or configured

    def fetch_search_page(
        self,
        query: str,
        start_date: str,
        end_date: str,
        bid_type: dict[str, str],
        page: int,
        region: dict[str, str] | None = None,
    ) -> str | None:
        region = region or {}
        params = {
            "searchtype": "2",
            "page_index": str(page),
            "bidSort": "0",
            "buyerName": "",
            "projectId": "",
            "pinMu": "0",
            "bidType": bid_type.get("bid_type", "0"),
            "dbselect": "bidx",
            "kw": query,
            "start_time": ccgp_date(start_date),
            "end_time": ccgp_date(end_date),
            "timeType": "6",
            "displayZone": region.get("display_zone", ""),
            "zoneId": region.get("zone_id", ""),
            "pppStatus": "0",
            "agentName": "",
        }
        try:
            if not self.can_fetch(SEARCH_ENDPOINT):
                self.last_error = f"robots.txt 不允许访问：{SEARCH_ENDPOINT}"
                logger.warning("robots.txt disallows CCGP search endpoint: %s", SEARCH_ENDPOINT)
                return None
            response = self.request_with_retries(
                "GET",
                SEARCH_ENDPOINT,
                params=params,
                timeout=self.request_timeout(12),
                retries=1,
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}：{response.url}"
                logger.warning("CCGP search failed: status=%s url=%s", response.status_code, response.url)
                return None
            response.encoding = response.apparent_encoding or response.encoding
            if "频繁访问" in response.text or "访问过于频繁" in response.text:
                self.last_error = friendly_error_message("频繁访问")
                return None
            return response.text
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("CCGP search request failed: %s", exc)
            return None

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                logger.warning("CCGP detail unavailable: %s", tender.source_url)
                return
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
        except Exception as exc:
            logger.exception("CCGP detail parse failed for %s: %s", tender.source_url, exc)


def parse_fixture(path: Path) -> dict[str, str]:
    return parse_detail_html(path.read_text(encoding="utf-8"), url="http://www.ccgp.gov.cn/sample.html")
