import logging
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from config.settings import LOG_DIR
from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, summarize
from parsers.extractors import extract_deadline, normalize_publish_date
from scoring.project_profile import PROJECT_SEARCH_TERMS


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "hunan_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://hnsggzy.com/"
TRADE_API = "https://hnsggzy.com/tradeApi"

SEARCH_TERMS = list(dict.fromkeys(["企业展厅", "产业展示中心", "科技展厅", "展厅", "展陈", "布展", "展示中心", "数字展厅", "规划馆"] + PROJECT_SEARCH_TERMS))

ENDPOINTS = [
    {
        "path": "/constructionTender/listByFile",
        "announcement_type": "工程建设公告",
        "title_fields": ["bidSectionName", "tenderProjectName", "noticeTitle"],
        "date_fields": ["noticeSendTime", "noticeSendDate"],
        "detail_path": "/#/resources/transactionDetail/construction",
    },
    {
        "path": "/governmentPurchase/projectInformation/selectAll",
        "announcement_type": "政府采购公告",
        "title_fields": ["purchaseProjectName", "purchaseSectionName", "noticeTitle"],
        "date_fields": ["noticeSendTime", "noticeSendDate"],
        "detail_path": "/#/resources/projectDetail/governmentPurchase",
    },
    {
        "path": "/constructionTender/ListConstructionTenderPlan",
        "announcement_type": "招标计划",
        "title_fields": ["noticeTitle", "projectName", "tenderProjectName"],
        "date_fields": ["noticeSendDate", "noticeSendTime"],
        "detail_path": "/#/jygk",
    },
]


def parse_time(value) -> str:
    text = clean_text(str(value or ""))
    if not text:
        return ""
    if text.isdigit():
        try:
            timestamp = int(text)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp).date().isoformat()
        except Exception:
            return ""
    return normalize_publish_date(text.replace("T", " "))


def parse_date(value: str) -> date | None:
    normalized = parse_time(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_date(value: str | date | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return clean_text(str(value or ""))


def in_date_range(publish_date: str, start_date: str, end_date: str) -> bool:
    published = parse_date(publish_date)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not published or not start or not end:
        return False
    return start <= published <= end


def first_value(record: dict, fields: list[str]) -> str:
    for field in fields:
        value = clean_text(record.get(field) or "")
        if value:
            return value
    return ""


def budget_value(record: dict) -> str:
    value = first_value(
        record,
        [
            "programBudget",
            "investmentAmount",
            "budgetAmount",
            "budget",
            "projectBudget",
            "controlPrice",
            "maximumPrice",
            "contractEstimatePrice",
            "bidSectionAmount",
            "projectAmount",
        ],
    )
    if value and value.replace(".", "", 1).isdigit():
        return f"{value}元"
    return value


def deadline_value(record: dict) -> str:
    value = first_value(
        record,
        [
            "bidEndTime",
            "openTime",
            "tenderEndTime",
            "submitEndTime",
            "bidDeadline",
            "responseEndTime",
            "noticeEndTime",
            "endTime",
        ],
    )
    return value or extract_deadline(" ".join(clean_text(str(item or "")) for item in record.values()))


def build_detail_url(endpoint: dict, record: dict) -> str:
    params = {
        "id": record.get("id") or record.get("fileId") or record.get("projectId") or "",
        "regionCode": record.get("regionCode") or "",
        "bidSectionId": record.get("bidSectionId") or record.get("sectionId") or "",
        "isPublic": record.get("isPublic") or "",
    }
    if endpoint["detail_path"].startswith("/#/resources/transactionDetail/"):
        params["default"] = "projectInfo"
    params = {key: value for key, value in params.items() if value}
    suffix = endpoint["detail_path"]
    return f"{BASE_URL.rstrip('/')}{suffix}?{urlencode(params)}" if params else BASE_URL


def record_matches(record: dict, terms: list[str]) -> bool:
    text = " ".join(clean_text(str(value or "")) for value in record.values())
    return any(term in text for term in terms)


def record_matches_region(record: dict, region_name: str) -> bool:
    if not region_name or region_name == "湖南":
        return True
    needle = region_name.replace("省", "").replace("市", "")
    text = " ".join(
        clean_text(str(record.get(field) or ""))
        for field in [
            "name",
            "regionName",
            "purchaseProjectName",
            "purchaseSectionName",
            "tenderProjectName",
            "bidSectionName",
            "noticeTitle",
        ]
    )
    return needle in text.replace("省", "").replace("市", "")


def merge_government_purchase_detail(record: dict, project_payload: dict | None, announcement_payload: dict | None) -> dict:
    merged = dict(record)
    project = (project_payload or {}).get("data") or {}
    if isinstance(project, dict):
        for key in [
            "purchaserName",
            "agencyName",
            "agency",
            "programBudget",
            "budgetAmount",
            "controlPrice",
            "projectCode",
            "projectNo",
            "connector",
            "contactPerson",
            "phone",
            "contactPhone",
            "bidEndTime",
            "openTime",
            "submitEndTime",
            "purchaseProjectName",
            "purchaseSectionName",
        ]:
            if project.get(key) and not merged.get(key):
                merged[key] = project.get(key)

    announcement_data = (announcement_payload or {}).get("data") or {}
    announcements = []
    if isinstance(announcement_data, dict):
        announcements = announcement_data.get("governmentProcureAnnouncementInformation") or []
    elif isinstance(announcement_data, list):
        announcements = announcement_data
    if announcements:
        preferred = next(
            (
                item
                for item in announcements
                if isinstance(item, dict) and clean_text(item.get("noticeSendTime") or item.get("noticeSendDate") or "")
            ),
            announcements[0],
        )
        if isinstance(preferred, dict):
            for key in ["noticeName", "noticeSendTime", "noticeSendDate", "noticeContent", "bulletinType", "openTime", "bidEndTime", "endTime"]:
                if preferred.get(key) and not merged.get(key):
                    merged[key] = preferred.get(key)
    return merged


def record_to_tender(record: dict, endpoint: dict, source_name: str, fallback_region: str) -> Tender:
    title = first_value(record, endpoint["title_fields"])
    publish = first_value(record, endpoint["date_fields"])
    region = clean_text(record.get("name") or record.get("regionName") or fallback_region)
    summary_text = " ".join(
        clean_text(record.get(field) or "")
        for field in ["tenderProjectName", "purchaseProjectName", "bidSectionName", "purchaseSectionName", "noticeTitle"]
    )
    return Tender(
        title=title,
        announcement_type=endpoint["announcement_type"],
        publish_date=parse_time(publish),
        region=region,
        purchaser=clean_text(record.get("purchaserName") or record.get("tendererName") or ""),
        agency=clean_text(record.get("agencyName") or record.get("agency") or ""),
        budget=clean_text(budget_value(record)),
        project_no=clean_text(record.get("projectCode") or record.get("projectNo") or ""),
        contact_person=clean_text(record.get("connector") or record.get("contactPerson") or record.get("linkMan") or ""),
        contact_phone=clean_text(record.get("phone") or record.get("contactPhone") or record.get("linkPhone") or ""),
        bid_deadline=clean_text(deadline_value(record)),
        source_url=build_detail_url(endpoint, record),
        summary=summarize(summary_text or title),
        source_name=source_name,
    )


class HunanPublicCrawler(BaseCrawler):
    name = "湖南省公共资源交易数据"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        source_name = clean_text(self.source_config.get("name") or self.name)
        region_code = clean_text(self.source_config.get("region_code") or "")
        region_name = clean_text(self.source_config.get("region_name") or "湖南")
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
        for endpoint in ENDPOINTS:
            if self.source_should_stop(results, deadline, result_limit):
                return results
            for term in terms:
                if self.source_should_stop(results, deadline, result_limit):
                    return results
                if not term:
                    continue
                for page in range(1, max_pages + 1):
                    if self.source_should_stop(results, deadline, result_limit):
                        return results
                    payload = self.fetch_page(endpoint["path"], page, term, region_code, start, end)
                    records = ((payload or {}).get("data") or {}).get("records") or []
                    if not records:
                        break
                    for record in records:
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
                        if not record_matches_region(record, region_name):
                            continue
                        if not record_matches(record, terms):
                            continue
                        if (
                            endpoint["path"] == "/governmentPurchase/projectInformation/selectAll"
                            and detail_count < detail_limit
                        ):
                            record = self.enrich_government_purchase(record)
                            detail_count += 1
                        tender = record_to_tender(record, endpoint, source_name, region_name)
                        if not tender.title or tender.source_url in seen:
                            continue
                        if not tender.publish_date or not in_date_range(tender.publish_date, start, end):
                            continue
                        seen.add(tender.source_url)
                        results.append(self.apply_scoring(tender))
                        if self.source_should_stop(results, deadline, result_limit):
                            return results
        if not results:
            self.last_error = self.last_error or f"未在{region_name}公开交易接口中发现展厅/展陈匹配项目"
        return results

    def fetch_page(self, path: str, page: int, term: str, region_code: str, start_date: str, end_date: str) -> dict | None:
        url = f"{TRADE_API}{path}"
        params = {
            "current": page,
            "size": 20,
            "regionCode": region_code,
            "noticeName": term,
            "noticeSendTimeStart": start_date,
            "noticeSendtimeEnd": end_date,
            "noticeSendDateStart": start_date,
            "noticeSendDateEnd": end_date,
        }
        try:
            response = self.session.get(url, params=params, timeout=self.request_timeout(10), headers={"Referer": BASE_URL})
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}: {url}"
                return None
            return response.json()
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Hunan public request failed: %s", exc)
            return None

    def enrich_government_purchase(self, record: dict) -> dict:
        section_id = clean_text(record.get("bidSectionId") or record.get("sectionId") or "")
        if not section_id:
            return record
        project_payload = self.fetch_detail_api(
            "/governmentPurchase/projectInformation/getBySectionId",
            {"sectionId": section_id},
        )
        announcement_payload = self.fetch_detail_api(
            "/governmentPurchase/projectInformation/getAnnouncementBySectionId",
            {"sectionId": section_id},
        )
        return merge_government_purchase_detail(record, project_payload, announcement_payload)

    def fetch_detail_api(self, path: str, params: dict) -> dict | None:
        url = f"{TRADE_API}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.request_timeout(8), headers={"Referer": BASE_URL})
            if response.status_code != 200:
                logger.info("Hunan detail HTTP %s: %s", response.status_code, url)
                return None
            return response.json()
        except Exception as exc:
            logger.info("Hunan detail request skipped: %s", friendly_error_message(exc))
            return None


class ChangshaPublicCrawler(HunanPublicCrawler):
    name = "长沙市公共资源交易数据"
