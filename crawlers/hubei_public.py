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
    handler = logging.FileHandler(LOG_DIR / "hubei_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://www.hbggzyfwpt.cn/"
DEFAULT_TERMS = list(dict.fromkeys(["企业展厅", "产业展示中心", "科技展厅", "展厅", "展陈", "布展", "展示中心", "数字展厅", "多媒体展项", "规划馆"] + PROJECT_SEARCH_TERMS))

ENDPOINTS = [
    {
        "path": "/jyxxAjax/jsgcZbggNew",
        "announcement_type": "工程建设-招标公告",
        "title_field": "bulletinName",
        "content_field": "bulletinContent",
        "date_field": "bulletinIssueTime",
        "deadline_field": "bulletinEndTime",
        "guid_field": "tenderBulletinGuid",
        "detail_path": "/jyxx/jsgcXmxxDetail?guid={guid}&isOther=false",
        "title_param": "projectName",
    },
    {
        "path": "/jyxx/zfcg/cgggNew",
        "announcement_type": "政府采购-采购公告",
        "title_field": "bulletinTitle",
        "content_field": "noticeContent",
        "date_field": "bulletinStartTime",
        "deadline_field": "",
        "guid_field": "guid",
        "detail_path": "/jyxx/zfcg/cgggDetail?guid={guid}&isOther=false",
        "title_param": "bulletinTitle",
    },
]

AREA_NAMES = {
    "420100": "武汉市",
    "420200": "黄石市",
    "420300": "十堰市",
    "420500": "宜昌市",
    "420600": "襄阳市",
    "420700": "鄂州市",
    "420800": "荆门市",
    "420900": "孝感市",
    "421000": "荆州市",
    "421100": "黄冈市",
    "421200": "咸宁市",
    "421300": "随州市",
    "422800": "恩施州",
}


def parse_compact_datetime(value: str) -> str:
    text = clean_text(str(value or ""))
    if not text:
        return ""
    if re.fullmatch(r"\d{14}", text):
        try:
            return datetime.strptime(text, "%Y%m%d%H%M%S").date().isoformat()
        except ValueError:
            return ""
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            return ""
    return normalize_publish_date(text)


def parse_date(value: str) -> date | None:
    normalized = parse_compact_datetime(value)
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
        r"(预算金额|最高限价|招标控制价|合同估算价|投资额|中标金额|成交金额)[:：]?\s*(?:人民币)?\s*([0-9,.]+)\s*(万元|元)",
        r"([0-9,.]+)\s*万元",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        if len(match.groups()) >= 3:
            return f"{match.group(2)}{match.group(3)}"
        return f"{match.group(1)}万元"
    return ""


def infer_region(record: dict, fallback_area_code: str = "") -> str:
    for key in ["secondAreaName", "areaName", "regionName", "cityName"]:
        value = clean_text(record.get(key) or "")
        if value:
            return f"湖北省{value}" if "湖北" not in value else value
    code = clean_text(record.get("regionCode") or record.get("areaCode") or fallback_area_code)
    if code:
        for prefix, name in AREA_NAMES.items():
            if code.startswith(prefix[:4]) or code == prefix:
                return f"湖北省{name}"
    return "湖北省"


def build_detail_url(endpoint: dict, record: dict) -> str:
    guid = clean_text(record.get(endpoint["guid_field"]) or record.get("guid") or "")
    if not guid:
        return BASE_URL
    return urljoin(BASE_URL, endpoint["detail_path"].format(guid=guid))


def record_to_tender(record: dict, endpoint: dict, source_name: str, area_code: str, query: str, start: str, end: str) -> Tender | None:
    title = clean_text(record.get(endpoint["title_field"]) or "")
    content = html_to_text(record.get(endpoint["content_field"]) or "")
    combined = f"{title} {content}"
    if not title or not text_matches_query(combined, query):
        return None
    publish = parse_compact_datetime(record.get(endpoint["date_field"]) or "")
    if publish and start and end and not in_date_range(publish, start, end):
        return None
    deadline = parse_compact_datetime(record.get(endpoint.get("deadline_field", "")) or "") if endpoint.get("deadline_field") else ""
    return Tender(
        title=title,
        announcement_type=endpoint["announcement_type"],
        publish_date=publish,
        region=infer_region(record, area_code),
        budget=extract_budget(content),
        project_no=extract_project_no(combined),
        contact_person=extract_contact_person(combined),
        contact_phone=extract_phone(combined),
        bid_deadline=deadline or extract_deadline(combined),
        important_info=build_important_info(combined),
        source_url=build_detail_url(endpoint, record),
        summary=summarize(content or title),
        source_name=source_name,
    )


def parse_hubei_records(payload: dict, endpoint: dict, source_name: str = "湖北省公共资源交易平台", area_code: str = "", query: str = "", start_date: str = "", end_date: str = "") -> list[Tender]:
    tenders: list[Tender] = []
    seen: set[str] = set()
    for record in payload.get("data") or []:
        try:
            tender = record_to_tender(record, endpoint, source_name, area_code, query, start_date, end_date)
            if not tender or tender.source_url in seen:
                continue
            seen.add(tender.source_url)
            tenders.append(tender)
        except Exception as exc:
            logger.exception("Failed to parse Hubei record: %s", exc)
    return tenders


def parse_detail_html(html: str, url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)
    title = ""
    for selector in ["h1", "h2", ".title", ".article-title", ".detail-title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ")).replace("湖北省公共资源交易电子服务系统", "")
    return {
        "title": title,
        "publish_date": parse_compact_datetime(extract_after_label(text, ["发布时间", "发布日期", "信息发布时间"], 40)),
        "region": infer_region({}, ""),
        "purchaser": extract_after_label(text, ["招标人", "采购人", "建设单位", "项目业主"]),
        "agency": extract_after_label(text, ["招标代理机构", "采购代理机构", "代理机构"]),
        "budget": extract_budget(text),
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(text),
        "source_url": url,
    }


class HubeiPublicCrawler(BaseCrawler):
    name = "湖北省公共资源交易平台"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any(("湖北" in clean_text(region or "") or self.source_config.get("area_name", "") in clean_text(region or "")) for region in regions):
            return []
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        max_pages = int(self.source_config.get("max_pages", 8))
        area_code = clean_text(self.source_config.get("area_code") or "")
        source_name = clean_text(self.source_config.get("name") or self.name)

        results: list[Tender] = []
        seen: set[str] = set()
        for endpoint in ENDPOINTS:
            for page in range(1, max_pages + 1):
                payload = self.fetch_endpoint(endpoint, page, area_code)
                if not payload:
                    continue
                tenders = parse_hubei_records(payload, endpoint, source_name, area_code, query, start, end)
                for tender in tenders:
                    if tender.source_url in seen:
                        continue
                    seen.add(tender.source_url)
                    self.enrich_from_detail(tender)
                    results.append(self.apply_scoring(tender))
        if not results:
            self.last_error = self.last_error or "本次公开近期公告中未发现匹配展厅/展陈关键词的项目。"
        return results

    def fetch_endpoint(self, endpoint: dict, page: int, area_code: str) -> dict | None:
        url = urljoin(BASE_URL, endpoint["path"])
        if not self.can_fetch(url):
            self.last_error = f"robots.txt 不允许访问：{url}"
            return None
        data = {
            "currentPage": page,
            "pageSize": 20,
            "currentArea": area_code,
            "area": "",
            "publishTimeType": "",
            "publishTimeStart": "",
            "publishTimeEnd": "",
        }
        if endpoint["path"].startswith("/jyxx/zfcg"):
            data.update({"bulletinTitle": "", "purchaserMode": 99, "purchaserModeType": 0})
        else:
            data.update({"projectName": "", "industriesTypeCode": 0})
        try:
            time.sleep(self.request_interval)
            response = self.session.post(
                url,
                data=data,
                timeout=30,
                headers={"Referer": urljoin(BASE_URL, f"/jyxx/jsgcXmxx?currentArea={area_code}&businessTypeValue=0")},
            )
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}"
                return None
            return response.json()
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Hubei endpoint request failed: %s", exc)
            return None

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                return
            response.encoding = response.apparent_encoding or response.encoding
            parsed = parse_detail_html(response.text, tender.source_url)
            tender.title = parsed.get("title") or tender.title
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
            logger.exception("Hubei detail parse failed for %s: %s", tender.source_url, exc)


class WuhanPublicCrawler(HubeiPublicCrawler):
    name = "武汉市公共资源交易信息"


def parse_fixture(path: Path) -> list[Tender]:
    return parse_hubei_records(
        {"data": [__import__("json").loads(path.read_text(encoding="utf-8"))]},
        ENDPOINTS[0],
        source_name="湖北省公共资源交易平台",
        query="展厅",
    )
