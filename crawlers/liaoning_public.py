import json
import re
from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

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


DEFAULT_PROFILES = [
    {"channelid": "219677", "announcement_type": "工程建设"},
    {"channelid": "240007", "announcement_type": "政府采购"},
]


def parse_jsonp_payload(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("{"):
        return json.loads(cleaned)
    match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", cleaned, re.S)
    if not match:
        raise ValueError("辽宁公共资源接口返回格式无法解析")
    return json.loads(match.group(1))


def record_to_tender(record: dict, profile: dict, base_url: str, source_name: str) -> Tender | None:
    title = clean_text(record.get("DOCTITLE", ""))
    source_url = clean_text(record.get("DOCPUBURL", ""))
    if not title or not source_url:
        return None
    source_url = urljoin(base_url, source_url)
    return Tender(
        title=title,
        announcement_type=clean_text(record.get("CHNLNAME", "")) or profile.get("announcement_type", ""),
        publish_date=normalize_publish_date(record.get("DOCRELTIME", "")),
        region="辽宁省",
        source_url=source_url,
        summary=summarize(title),
        source_name=source_name,
    )


def parse_detail_html(html: str, source_url: str) -> dict[str, str]:
    text = html_to_text(html)
    title = ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title_match:
        title = clean_text(re.sub(r"<[^>]+>", " ", title_match.group(1))).split("_")[0]
    publish_match = re.search(r"\d{4}[-年]\d{1,2}[-月]\d{1,2}", text)
    budget_match = re.search(
        r"(预算金额|最高限价|合同估算价)[:：]?\s*[￥¥]?\s*([0-9,.]+)\s*(万元|万|元)",
        text,
    )
    budget = ""
    if budget_match:
        unit = "万元" if budget_match.group(3) in {"万元", "万"} else "元"
        budget = f"{budget_match.group(2)}{unit}"
    return {
        "title": title,
        "publish_date": normalize_publish_date(publish_match.group(0)) if publish_match else "",
        "region": "辽宁省",
        "budget": budget,
        "project_no": extract_project_no(text),
        "contact_person": extract_contact_person(text),
        "contact_phone": extract_phone(text),
        "bid_deadline": extract_deadline(text),
        "important_info": build_important_info(text),
        "summary": summarize(text),
        "source_url": source_url,
    }


class LiaoningPublicCrawler(BaseCrawler):
    name = "辽宁省公共资源交易数据"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("辽宁" in clean_text(region or "") for region in regions):
            return []

        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        profiles = self.source_config.get("profiles") or DEFAULT_PROFILES
        max_items = int(self.source_config.get("max_items", 20))
        base_url = self.source_config.get("base_url", "https://ggzy.ln.gov.cn/")
        source_name = clean_text(self.source_config.get("name") or self.name)
        broad_match = bool(self.source_config.get("broad_match"))
        results: list[Tender] = []
        seen: set[str] = set()

        for profile in profiles:
            for record in self.fetch_records(base_url, profile, max_items):
                tender = record_to_tender(record, profile, base_url, source_name)
                if not tender or tender.source_url in seen:
                    continue
                if tender.publish_date and not (start <= tender.publish_date <= end):
                    continue
                if query and not broad_match and query not in f"{tender.title} {tender.summary}":
                    continue
                seen.add(tender.source_url)
                self.enrich_from_detail(tender)
                results.append(self.apply_scoring(tender))
        return results

    def fetch_records(self, base_url: str, profile: dict, max_items: int) -> list[dict]:
        try:
            url = (
                urljoin(base_url, "/was5/web/search")
                + "?"
                + urlencode(
                    {
                        "callback": "jQueryTenderRadar",
                        "page": 1,
                        "perpage": max_items,
                        "channelid": profile.get("channelid", ""),
                    }
                )
            )
            response = self.get(url)
            if not response:
                return []
            response.encoding = response.apparent_encoding or response.encoding
            payload = parse_jsonp_payload(response.text)
            return payload.get("datas") or []
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            return []

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                return
            response.encoding = response.apparent_encoding or response.encoding
            parsed = parse_detail_html(response.text, tender.source_url)
        except Exception:
            return
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
