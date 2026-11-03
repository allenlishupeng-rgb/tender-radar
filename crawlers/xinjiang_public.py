from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, html_to_text, summarize
from parsers.extractors import normalize_publish_date


class XinjiangPublicCrawler(BaseCrawler):
    name = "新疆维吾尔自治区公共资源交易数据"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("新疆" in clean_text(region or "") for region in regions):
            return []
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        viewers = self.source_config.get("viewers") or [
            {"viewer": "tenderBulletinViewer", "announcement_type": "招标公告"},
        ]
        base_url = self.source_config.get("base_url", "https://xj.86ztbb.com/")
        source_name = clean_text(self.source_config.get("name") or self.name)
        results: list[Tender] = []
        seen: set[str] = set()

        for viewer in viewers:
            html = self.fetch_viewer(base_url, viewer.get("viewer", ""))
            if not html:
                continue
            for tender in parse_xinjiang_viewer_html(
                html,
                base_url,
                source_name,
                viewer.get("announcement_type", ""),
                query,
                start,
                end,
            ):
                if tender.source_url in seen:
                    continue
                seen.add(tender.source_url)
                self.enrich_from_detail(tender)
                if query and query not in f"{tender.title} {tender.summary} {tender.important_info}":
                    continue
                results.append(self.apply_scoring(tender))
        return results

    def fetch_viewer(self, base_url: str, viewer: str) -> str | None:
        try:
            url = urljoin(base_url, "/queryNavBarBulletins") + "?" + urlencode({"view": viewer, "pf": "xj"})
            response = self.get(url)
            if not response:
                self.last_error = self.last_error or "新疆公开公告接口不可用"
                return None
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            return None

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


def in_range(value: str, start: str, end: str) -> bool:
    if not value:
        return True
    return start <= value <= end


def parse_xinjiang_viewer_html(
    html: str,
    base_url: str,
    source_name: str,
    announcement_type: str,
    query: str,
    start_date: str,
    end_date: str,
) -> list[Tender]:
    soup = BeautifulSoup(html, "html.parser")
    tenders: list[Tender] = []
    for link in soup.select("a[href]"):
        title = clean_text(link.get("title", "") or link.get_text(" "))
        href = clean_text(link.get("href", ""))
        if len(title) < 8 or "BulletinData" not in href:
            continue
        container = link.find_parent("li") or link.parent
        container_text = clean_text(container.get_text(" ")) if container else title
        if query and query not in f"{title} {container_text}":
            continue
        time_node = link.select_one(".time") or (container.select_one(".time") if container else None)
        publish_date = normalize_publish_date(time_node.get_text(" ") if time_node else container_text)
        if not in_range(publish_date, start_date, end_date):
            continue
        tenders.append(
            Tender(
                title=title,
                announcement_type=announcement_type,
                publish_date=publish_date,
                region="新疆维吾尔自治区",
                source_url=normalize_detail_url(urljoin(base_url, href)),
                summary=summarize(container_text),
                source_name=source_name,
            )
        )
    return tenders


def normalize_detail_url(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query) if key != "_t"])
    return urlunparse(parsed._replace(query=query))
