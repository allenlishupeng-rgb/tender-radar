import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any
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


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "ggzy_public.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


SEARCH_ENDPOINT = "https://deal.ggzy.gov.cn/ds/deal/dealList_find.jsp"

DEFAULT_SEARCH_PROFILES = [
    {
        "name": "工程建设-招标/资审公告",
        "deal_classify": "01",
        "deal_stage": "0101",
        "announcement_type": "招标/资审公告",
    },
    {
        "name": "政府采购-采购/资审公告",
        "deal_classify": "02",
        "deal_stage": "0201",
        "announcement_type": "采购/资审公告",
    },
]


def normalize_date(value: str | date | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return clean_text(str(value or ""))


def parse_result_item(item: dict[str, Any], fallback_type: str = "") -> Tender | None:
    title = clean_text(item.get("title") or item.get("TITLE") or "")
    url = clean_text(item.get("url") or item.get("URL") or "")
    if not title or not url:
        return None

    region = clean_text(
        item.get("districtShow")
        or item.get("region")
        or item.get("province")
        or item.get("platformName")
        or ""
    )
    publish_date = normalize_publish_date(item.get("timeShow") or item.get("publishTime") or item.get("date") or "")
    announcement_type = clean_text(
        item.get("stageShow")
        or item.get("noticeType")
        or item.get("tradeShow")
        or fallback_type
    )

    return Tender(
        title=title,
        announcement_type=announcement_type,
        publish_date=publish_date,
        region=region,
        source_url=url,
        summary=summarize(clean_text(item.get("content") or item.get("summary") or title)),
        source_name="全国公共资源交易平台",
    )


def region_matches_filter(target_regions: list[dict[str, str]], regions: list[str] | None) -> bool:
    if not regions:
        return True
    selected_text = " ".join(clean_text(region or "") for region in regions)
    short_selected = selected_text.replace("省", "").replace("市", "")
    for target in target_regions:
        target_text = " ".join(
            clean_text(str(target.get(key, "")))
            for key in ("name", "display_zone", "province_name", "city_name")
        )
        short_target = target_text.replace("省", "").replace("市", "")
        if short_target and (short_target in short_selected or short_selected in short_target):
            return True
    return False


def extract_after_label(text: str, labels: list[str], max_len: int = 40) -> str:
    for label in labels:
        marker = f"{label}："
        if marker in text:
            return clean_text(text.split(marker, 1)[1][:max_len]).split(" ")[0]
        marker = f"{label}:"
        if marker in text:
            return clean_text(text.split(marker, 1)[1][:max_len]).split(" ")[0]
    return ""


def parse_detail_html(html: str, url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)

    title = ""
    for selector in ["h1", ".title", ".article-title", ".detail-title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" "))

    return {
        "title": title,
        "publish_date": normalize_publish_date(extract_after_label(text, ["发布时间", "发布日期", "公告时间"])),
        "region": extract_after_label(text, ["地区", "行政区域", "所属地区"]),
        "announcement_type": extract_after_label(text, ["公告类型", "信息类型"]),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(text),
        "source_url": url,
    }


class GgzyPublicCrawler(BaseCrawler):
    name = "全国公共资源交易平台"

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
        profiles = self.source_config.get("search_profiles") or DEFAULT_SEARCH_PROFILES
        target_regions = self.source_config.get("target_regions") or [
            {
                "name": self.source_config.get("name", ""),
                "deal_province": self.source_config.get("deal_province", "0"),
                "deal_city": self.source_config.get("deal_city", "0"),
            }
        ]
        source_name = clean_text(self.source_config.get("name") or self.name)

        if not region_matches_filter(target_regions, regions):
            return []

        results: list[Tender] = []
        seen_urls: set[str] = set()

        for target_region in target_regions:
            for profile in profiles:
                for page in range(1, max_pages + 1):
                    payload = self.fetch_search_page(query, start, end, profile, page, target_region)
                    if not payload:
                        continue
                    items = payload.get("data") or []
                    if not isinstance(items, list):
                        logger.warning("Unexpected GGZY data shape on page %s: %s", page, type(items))
                        continue
                    if not items:
                        break

                    for item in items:
                        try:
                            tender = parse_result_item(item, fallback_type=profile.get("announcement_type", ""))
                            if not tender or tender.source_url in seen_urls:
                                continue
                            seen_urls.add(tender.source_url)
                            tender.region = tender.region or target_region.get("display_zone") or target_region.get("name", "")
                            tender.source_name = source_name
                            self.enrich_from_detail(tender)
                            results.append(self.apply_scoring(tender))
                        except Exception as exc:
                            logger.exception("Failed to parse GGZY item: %s", exc)

        return results

    def fetch_search_page(
        self,
        query: str,
        start_date: str,
        end_date: str,
        profile: dict[str, str],
        page: int,
        target_region: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        target_region = target_region or {}
        params = {
            "TIMEBEGIN_SHOW": start_date,
            "TIMEEND_SHOW": end_date,
            "TIMEBEGIN": start_date,
            "TIMEEND": end_date,
            "SOURCE_TYPE": "1",
            "DEAL_TIME": "06",
            "DEAL_CLASSIFY": profile.get("deal_classify", "01"),
            "DEAL_STAGE": profile.get("deal_stage", "0101"),
            "DEAL_PROVINCE": target_region.get("deal_province", "0"),
            "DEAL_CITY": target_region.get("deal_city", "0"),
            "DEAL_PLATFORM": "0",
            "BID_PLATFORM": "0",
            "DEAL_TRADE": "0",
            "isShowAll": "1",
            "FINDTXT": query,
            "PAGENUMBER": str(page),
        }
        try:
            if not self.can_fetch(SEARCH_ENDPOINT):
                self.last_error = f"robots.txt 不允许访问：{SEARCH_ENDPOINT}"
                logger.warning("robots.txt disallows GGZY search endpoint: %s", SEARCH_ENDPOINT)
                return None
            response = self.session.get(SEARCH_ENDPOINT, params=params, timeout=15)
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}：{response.url}"
                logger.warning("GGZY search failed: status=%s url=%s", response.status_code, response.url)
                return None
            return json.loads(response.text)
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("GGZY search request failed: %s", exc)
            return None

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            detail_url = urljoin(SEARCH_ENDPOINT, tender.source_url)
            response = self.get(detail_url)
            if not response:
                logger.warning("GGZY detail unavailable: %s", detail_url)
                return
            parsed = parse_detail_html(response.text, detail_url)
            tender.title = parsed.get("title") or tender.title
            tender.publish_date = parsed.get("publish_date") or tender.publish_date
            tender.region = parsed.get("region") or tender.region
            tender.announcement_type = parsed.get("announcement_type") or tender.announcement_type
            tender.project_no = parsed.get("project_no") or tender.project_no
            tender.contact_person = parsed.get("contact_person") or tender.contact_person
            tender.contact_phone = parsed.get("contact_phone") or tender.contact_phone
            tender.bid_deadline = parsed.get("bid_deadline") or tender.bid_deadline
            tender.important_info = parsed.get("important_info") or tender.important_info
            tender.summary = parsed.get("summary") or tender.summary
            tender.source_url = detail_url
        except Exception as exc:
            logger.exception("GGZY detail parse failed for %s: %s", tender.source_url, exc)


def parse_fixture(path: Path) -> dict[str, str]:
    return parse_detail_html(path.read_text(encoding="utf-8"), url="https://deal.ggzy.gov.cn/sample.html")
