from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, html_to_text, summarize
from parsers.extractors import normalize_publish_date


class NeimengguPublicCrawler(BaseCrawler):
    name = "内蒙古自治区公共资源交易数据"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("内蒙古" in clean_text(region or "") for region in regions):
            return []
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        profiles = self.source_config.get("profiles") or [
            {"notice_type_name": "招标公告", "transaction_type_name": "工程建设", "announcement_type": "招标公告"},
            {"notice_type_name": "采购/资格预审公告", "transaction_type_name": "政府采购", "announcement_type": "采购/资格预审公告"},
        ]
        max_items = int(self.source_config.get("max_items", 20))
        base_url = self.source_config.get("base_url", "https://ggzyjy.nmg.gov.cn/")
        source_name = clean_text(self.source_config.get("name") or self.name)
        results: list[Tender] = []
        seen: set[str] = set()

        for profile in profiles:
            payload = self.fetch_deal_list(base_url, profile, max_items)
            for record in payload:
                tender = record_to_tender(record, profile, base_url, source_name)
                if not tender or tender.source_url in seen:
                    continue
                if tender.publish_date and not (start <= tender.publish_date <= end):
                    continue
                if query and query not in f"{tender.title} {tender.summary}":
                    continue
                seen.add(tender.source_url)
                self.enrich_from_detail(tender)
                results.append(self.apply_scoring(tender))
        return results

    def fetch_deal_list(self, base_url: str, profile: dict, max_items: int) -> list[dict]:
        try:
            url = (
                urljoin(base_url, "/trssearch/openSearch/getPublishResourceDealList")
                + "?"
                + urlencode(
                    {
                    "noticeTypeName": profile.get("notice_type_name", ""),
                    "transactionTypeName": profile.get("transaction_type_name", ""),
                    "num": str(max_items),
                    }
                )
            )
            response = self.get(url)
            if not response:
                self.last_error = self.last_error or "内蒙古公开交易接口不可用"
                return []
            data = response.json()
            if str(data.get("state")) != "200":
                self.last_error = data.get("msg") or "内蒙古公开交易接口返回异常"
                return []
            return data.get("data") or []
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            return []

    def enrich_from_detail(self, tender: Tender) -> None:
        try:
            response = self.get(tender.source_url)
            if not response:
                return
            response.encoding = response.apparent_encoding or response.encoding
            text = html_to_text(response.text)
            tender.summary = summarize(text) or tender.summary
            tender.important_info = text[:500]
        except Exception:
            return


def record_to_tender(record: dict, profile: dict, base_url: str, source_name: str) -> Tender | None:
    title = clean_text(record.get("noticeName", ""))
    key = clean_text(record.get("sourceDataKey", ""))
    if not title or not key:
        return None
    transaction_type = profile.get("transaction_type_name", "")
    detail_path = "/jyxx/index_24.html" if transaction_type == "工程建设" else "/jyxx/index_39.html"
    region = clean_text(record.get("platformName") or record.get("regionName") or "内蒙古自治区")
    publish_date = normalize_publish_date(record.get("noticeSendTime", ""))
    return Tender(
        title=title,
        announcement_type=profile.get("announcement_type", "") or clean_text(record.get("noticeTypeName", "")),
        publish_date=publish_date,
        region=region,
        source_url=urljoin(base_url, f"{detail_path}?id={key}"),
        summary=summarize(f"{region} {title} {publish_date}"),
        source_name=source_name,
    )
