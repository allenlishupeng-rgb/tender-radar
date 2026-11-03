import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

from config.settings import ENTERPRISE_COMPANIES_PATH, REQUEST_TIMEOUT
from crawlers.base import BaseCrawler
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.common import clean_text, html_to_text, summarize
from parsers.extractors import normalize_publish_date


DATE_PATTERNS = [
    re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日?"),
    re.compile(r"/(\d{4})(\d{2})(\d{2})/"),
]


def load_enterprise_companies(path=ENTERPRISE_COMPANIES_PATH) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("companies", [])


def normalize_date_text(text: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            year, month, day = match.groups()
            try:
                return date(int(year), int(month), int(day)).isoformat()
            except ValueError:
                return ""
    return ""


def in_date_range(publish_date: str, start_date: str, end_date: str) -> bool:
    if not publish_date:
        return True
    try:
        pub = datetime.strptime(publish_date[:10], "%Y-%m-%d").date()
        start = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
        end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    except Exception:
        return True
    return start <= pub <= end


def deadline_reached(deadline: float | None) -> bool:
    return bool(deadline and time.monotonic() >= deadline)


def same_site(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(base_url)
    if not parsed.netloc:
        return True
    return parsed.netloc.lower().endswith(base.netloc.lower().replace("www.", ""))


def extract_news_candidates(html: str, page_url: str, company: dict, max_links: int = 20) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict] = []
    seen: set[str] = set()
    exclude_tokens = ["javascript:", "mailto:", "#", ".pdf", ".jpg", ".png", ".zip", ".doc", ".xls"]

    for link in soup.select("a[href]"):
        href = clean_text(link.get("href", ""))
        href_lower = href.lower()
        if not href or any(token in href_lower for token in exclude_tokens) or re.search(r"index_\d+\.html?$", href_lower):
            continue
        url = urljoin(page_url, href)
        if not same_site(url, page_url) or url in seen:
            continue

        title = clean_text(link.get_text(" ") or link.get("title", ""))
        container = link.find_parent(["li", "article", "div", "tr"]) or link.parent
        context = clean_text(container.get_text(" ")) if container else title
        if len(title) < 4:
            title = clean_text(link.get("title", "") or context[:80])
        if len(title) < 4:
            continue

        seen.add(url)
        date_text = normalize_publish_date(normalize_date_text(f"{context} {url}"))
        keyword_hint = any(
            word in f"{title} {context} {url}"
            for word in [
                "展厅",
                "展示中心",
                "体验中心",
                "企业馆",
                "品牌馆",
                "总部",
                "研发中心",
                "产业园",
                "基地",
                "投产",
                "启用",
                "开工",
            ]
        )
        url_hint = any(token in url.lower() for token in ["news", "detail", "article", "press", "media"])
        candidates.append(
            {
                "title": title,
                "url": url,
                "context": context,
                "publish_date": date_text,
                "company": company.get("company_name", ""),
                "_rank": (2 if date_text else 0) + (3 if keyword_hint else 0) + (1 if url_hint else 0) + min(len(title), 60) / 100,
            }
        )
        if len(candidates) >= max(max_links * 12, 80):
            break
    candidates.sort(key=lambda item: item["_rank"], reverse=True)
    return candidates[:max_links]


def enterprise_text_hits(text: str, keywords: dict) -> tuple[list[str], list[str], list[str]]:
    hall_hits = [word for word in keywords.get("enterprise_hall_keywords", []) if word and word in text]
    expansion_hits = [word for word in keywords.get("enterprise_expansion_keywords", []) if word and word in text]
    downrank_hits = [word for word in keywords.get("enterprise_downrank_keywords", []) if word and word in text]
    return hall_hits, expansion_hits, downrank_hits


def extract_article_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.select("header, footer, nav, aside, script, style, noscript, [class*='related'], [class*='recommend']"):
        node.decompose()
    for selector in [
        "[itemprop='articleBody']", ".rich-text", ".article-content", ".news-content",
        ".news-detail-content", ".detail-content", "article",
    ]:
        content = soup.select_one(selector)
        if content is not None:
            return html_to_text(str(content))
    # Unstructured pages often mix adjacent-news links into the article wrapper.
    for link in soup.select("a"):
        link.decompose()
    return html_to_text(str(soup.select_one("main") or soup.body or soup))


def infer_lead_stage(text: str) -> str:
    if any(word in text for word in ["招标", "采购", "竞价", "比选", "询价"]):
        return "采购/招标阶段"
    if any(word in text for word in ["展厅", "展示中心", "体验中心", "品牌馆", "企业馆", "企业文化馆"]):
        return "展示空间线索"
    if any(word in text for word in ["启用", "投产", "落成", "竣工"]):
        return "启用/投产阶段"
    if any(word in text for word in ["开工", "奠基", "签约", "封顶"]):
        return "建设早期"
    if any(word in text for word in ["总部基地", "研发中心", "产业园", "智能制造基地", "未来工厂"]):
        return "总部/基地线索"
    return "企业新闻线索"


def suggested_action(stage: str, hall_hits: list[str], expansion_hits: list[str]) -> str:
    if hall_hits:
        return "优先核验项目负责人、设计/装修/展陈采购窗口。"
    if stage in {"建设早期", "总部/基地线索"} or expansion_hits:
        return "关注后续装修、展厅、客户接待中心和品牌展示需求。"
    return "保留观察，等待更明确的展示空间或采购信号。"


class EnterpriseNewsCrawler(BaseCrawler):
    name = "上市民企企业馆机会"

    def search(self, query: str, days: int = 30, start_date=None, end_date=None, regions=None) -> list[Tender]:
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        companies = load_enterprise_companies()
        max_companies = int(self.source_config.get("max_companies", 10))
        max_links = int(self.source_config.get("max_links_per_company", 14))
        max_items = int(self.source_config.get("max_items", 40))
        source_timeout = int(self.source_config.get("source_timeout_seconds", 80))
        deadline = time.monotonic() + max(source_timeout, 1)
        source_name = clean_text(self.source_config.get("name") or self.name)
        results: list[Tender] = []
        seen: set[str] = set()

        for company in companies[:max_companies]:
            if deadline_reached(deadline):
                self.last_error = "达到企业新闻来源时间上限"
                return results
            for news_url in company.get("news_urls", []):
                if deadline_reached(deadline):
                    self.last_error = "达到企业新闻来源时间上限"
                    return results
                html = self.fetch_page(news_url)
                if not html:
                    continue
                for candidate in extract_news_candidates(html, news_url, company, max_links=max_links):
                    if deadline_reached(deadline):
                        self.last_error = "达到企业新闻来源时间上限"
                        return results
                    if candidate["url"] in seen:
                        continue
                    tender = self.candidate_to_tender(candidate, company, source_name, start, end, deadline=deadline)
                    if not tender:
                        continue
                    seen.add(candidate["url"])
                    results.append(self.apply_scoring(tender))
                    if len(results) >= max_items:
                        self.last_error = ""
                        return results
        if results:
            self.last_error = ""
        return results

    def fetch_page(self, url: str) -> str | None:
        try:
            if not self.can_fetch(url):
                self.last_error = f"robots.txt 不允许访问：{url}"
                return None
            timeout = int(self.source_config.get("request_timeout", REQUEST_TIMEOUT))
            response = self.request_with_retries("GET", url, timeout=timeout)
            if response.status_code >= 400:
                self.last_error = f"HTTP {response.status_code}：{url}"
                return None
            response.encoding = response.apparent_encoding or response.encoding
            self.last_error = ""
            return response.text
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            return None

    def candidate_to_tender(
        self,
        candidate: dict,
        company: dict,
        source_name: str,
        start_date: str,
        end_date: str,
        deadline: float | None = None,
    ) -> Tender | None:
        candidate_text = clean_text(f"{candidate['title']} {candidate.get('context', '')} {candidate['url']}")
        candidate_hall_hits, candidate_expansion_hits, candidate_downrank_hits = enterprise_text_hits(candidate_text, self.keywords)
        if not candidate_hall_hits and not candidate_expansion_hits:
            return None
        if candidate_downrank_hits and not candidate_hall_hits:
            return None

        if deadline_reached(deadline):
            self.last_error = "达到企业新闻来源时间上限"
            return None
        detail_html = self.fetch_page(candidate["url"])
        detail_text = extract_article_text(detail_html) if detail_html else ""
        detail_title = self.extract_detail_title(detail_html or "")
        combined = clean_text(f"{detail_title or candidate['title']} {detail_text}")
        hall_hits, expansion_hits, downrank_hits = enterprise_text_hits(combined, self.keywords)
        if not hall_hits and not expansion_hits:
            return None
        core_expansion_hits = [
            word
            for word in expansion_hits
            if word
            in {
                "总部基地",
                "全球总部",
                "中国总部",
                "区域总部",
                "研发中心",
                "创新中心",
                "产业园",
                "智能制造基地",
                "未来工厂",
                "生产基地",
                "新基地",
                "客户参观",
                "考察调研",
            }
            or word.endswith("基地")
            or word.endswith("中心")
        ]
        if downrank_hits and not hall_hits:
            return None

        publish = candidate.get("publish_date") or normalize_publish_date(normalize_date_text(combined))
        if publish and not in_date_range(publish, start_date, end_date):
            return None

        company_name = company.get("company_name", "")
        stock_code = company.get("stock_code", "")
        industry = company.get("industry", "")
        stage = infer_lead_stage(combined)
        action = suggested_action(stage, hall_hits, core_expansion_hits or expansion_hits)
        evidence = "、".join(list(dict.fromkeys(hall_hits + expansion_hits))[:8])
        title = f"{company_name}：{detail_title or candidate['title']}"

        important = clean_text(
            f"线索类型：企业馆机会；企业：{company_name}；股票代码：{stock_code}；行业：{industry}；"
            f"阶段：{stage}；命中信号：{evidence}；建议：{action}"
        )

        return Tender(
            title=title,
            announcement_type=f"企业机会/{stage}",
            publish_date=publish,
            region=company.get("headquarters_city", ""),
            purchaser=f"{company_name} {stock_code}".strip(),
            agency=industry,
            source_url=candidate["url"],
            summary=summarize(detail_text or candidate.get("context", "") or candidate["title"]),
            important_info=important,
            source_name=source_name,
        )

    def extract_detail_title(self, html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for selector in ["h1", "h2", ".title", ".article-title", ".news-title"]:
            node = soup.select_one(selector)
            if node:
                title = clean_text(node.get_text(" "))
                if 4 <= len(title) <= 120:
                    return title
        if soup.title:
            title = clean_text(soup.title.get_text(" ")).split("_")[0].split("-")[0]
            if 4 <= len(title) <= 120:
                return title
        return ""
