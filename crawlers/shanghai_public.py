import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from config.settings import LOG_DIR
from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, html_to_text, summarize
from parsers.extractors import normalize_publish_date
from scoring.project_profile import expand_project_query_terms


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "shanghai_public.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_URL = "https://www.shggzy.com/"
CHANNEL_TYPES = {
    "jyxxgc": "工程建设",
    "jyxxzc": "政府采购",
    "jyxxgt": "土地交易",
    "gqcg": "国企采购",
}


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
    return any(term in text for term in expand_query_terms(query))


def parse_homepage_items(html: str, query: str = "", start_date: str = "", end_date: str = "") -> list[Tender]:
    pattern = re.compile(
        r"<li[^>]+data-id=\"([^\"]+)\"[^>]+onclick=\"window\.open\('([^']+)'\).*?data-dd='([^']+)'[^>]*>.*?<p title=\"([^\"]+)\"",
        re.S,
    )
    tenders: list[Tender] = []
    seen: set[str] = set()
    for channel, path, raw_date, raw_title in pattern.findall(html):
        try:
            title = clean_text(html_to_text(raw_title))
            publish = normalize_publish_date(raw_date)
            if not title or not text_matches_query(title, query):
                continue
            if publish and start_date and end_date and not in_date_range(publish, start_date, end_date):
                continue
            source_url = urljoin(BASE_URL, path)
            if source_url in seen:
                continue
            seen.add(source_url)
            announcement_type = CHANNEL_TYPES.get(channel, "交易公告")
            tenders.append(
                Tender(
                    title=title,
                    announcement_type=announcement_type,
                    publish_date=publish,
                    region="上海市",
                    source_url=source_url,
                    summary=summarize(f"{announcement_type}：{title}"),
                    source_name="上海市公共资源交易平台",
                )
            )
        except Exception as exc:
            logger.exception("Shanghai homepage item parse failed: %s", exc)
    return tenders


class ShanghaiPublicCrawler(BaseCrawler):
    name = "上海市公共资源交易平台"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("上海" in clean_text(region or "") for region in regions):
            return []

        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        html = self.fetch_homepage()
        if not html:
            return []
        tenders = parse_homepage_items(html, query=query, start_date=start, end_date=end)
        results = [self.apply_scoring(tender) for tender in tenders]
        if not results:
            self.last_error = "上海平台 robots.txt 禁止抓取 /search/ 和 /jyxx*/，本次只检查首页公开公告，未发现匹配线索。"
        return results

    def fetch_homepage(self) -> str | None:
        try:
            response = self.get(BASE_URL)
            if not response:
                logger.warning("Shanghai homepage unavailable: %s", self.last_error)
                return None
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            logger.exception("Shanghai homepage request failed: %s", exc)
            return None
