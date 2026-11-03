import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.settings import REQUEST_TIMEOUT
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
from scoring.project_profile import PROJECT_SEARCH_TERMS, PROJECT_VENUE_TERMS


STRICT_HALL_WORDS = [
    "展厅",
    "企业展厅",
    "企业文化展厅",
    "总部展厅",
    "直营展厅",
    "展示厅",
    "展示厅设计",
    "展示厅装修",
    "企业总部展示中心",
    "数字展厅",
    "元宇宙数字展厅",
    "品牌馆",
    "品牌展厅",
    "展示中心",
    "展陈",
    "展陈工程",
    "展陈设计",
    "展陈施工",
    "展厅升级",
    "展厅建设",
    "展厅设计",
    "展厅施工",
    "展厅装饰",
    "展陈布展",
    "陈列布展",
    "展览展示",
    "布展设计",
]

STRICT_HALL_WORDS = list(dict.fromkeys(STRICT_HALL_WORDS + PROJECT_VENUE_TERMS))

TENDER_WORDS = [
    "招标公告",
    "采购公告",
    "公开招标",
    "竞争性磋商",
    "询比",
    "比选",
    "中标候选人",
    "中标结果",
    "中标公示",
    "结果公示",
    "成交结果",
    "成交公告",
    "评标结果",
    "采购招标",
]

TERMINAL_STATUS_WORDS = [
    "终止公告",
    "流标公告",
    "废标公告",
    "暂停公告",
]

EXCLUDE_WORDS = [
    "展会",
    "参展",
    "展位",
    "展台搭建",
    "体博会",
    "博览会",
    "新闻",
    "战略合作",
    "合作协议",
    "签署",
]


def parse_date(text: str) -> str:
    patterns = [
        r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if not match:
            continue
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return ""
    return ""


def extract_publish_date(html: str, text: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for attr in ["PubDate", "publishdate", "publish_date", "date"]:
        node = soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"property": attr})
        if node:
            publish = parse_date(node.get("content", ""))
            if publish:
                return publish
    for pattern in [
        r"发布日期[:：]\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)",
        r"发布时间[:：]\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)",
        r"公示日期[:：]\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)",
    ]:
        match = re.search(pattern, text or "")
        if match:
            publish = parse_date(match.group(1))
            if publish:
                return publish
    return parse_date(text)


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


def has_strict_hall_signal(text: str) -> bool:
    return any(word in text for word in STRICT_HALL_WORDS)


def has_tender_signal(text: str) -> bool:
    return any(word in text for word in TENDER_WORDS)


def is_excluded(text: str) -> bool:
    return any(word in text for word in EXCLUDE_WORDS) and not has_strict_hall_signal(text)


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def normalize_title(title: str) -> str:
        title = clean_text(title)
        title = re.split(r"\s*[-—|]\s*(?:公司公告|新闻中心|采购公告|招标公告|物产中大金属集团|浙江新和成股份有限公司).*$", title)[0].strip()
        return title

    for attr in ["ArticleTitle", "og:title"]:
        node = soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"property": attr})
        if node:
            title = normalize_title(node.get("content", ""))
            if 4 <= len(title) <= 160:
                return title
    for selector in ["h1", "h2", ".title", ".article-title", ".news-title", ".detail-title"]:
        node = soup.select_one(selector)
        if node:
            title = normalize_title(node.get_text(" "))
            if 4 <= len(title) <= 160:
                return title
    if soup.title:
        title = normalize_title(soup.title.get_text(" "))
        title = re.split(r"[-_—|]", title)[0].strip()
        if 4 <= len(title) <= 160:
            return title
    return ""


def infer_title_from_text(text: str, fallback: str = "") -> str:
    fallback = clean_text(fallback)
    generic_titles = {"采购招标", "招标公告", "采购公告", "一、招标条件", "Sorry，当前栏目暂无内容!"}
    if 6 <= len(fallback) <= 80 and has_strict_hall_signal(fallback) and fallback not in generic_titles:
        return fallback
    compact = clean_text(text)
    regexes = [
        r"招标公告(?:（[^）]+）)?[:：]\s*([^。；\s]{4,80}展厅[^。；\s]{0,40}项目)",
        r"项目名称[:：]\s*([^。；\s]{4,80}展厅[^。；\s]{0,40}项目)",
        r"本招标项目为\s*([^，。；\s]{4,80}展厅[^，。；\s]{0,40}项目)",
        r"本项目为\s*([^，。；\s]{4,80}展厅[^，。；\s]{0,40}项目)",
    ]
    for pattern in regexes:
        match = re.search(pattern, compact)
        if match:
            return clean_text(match.group(1))
    parts = re.split(r"[\n\r。；;]", text or "")
    for part in parts:
        line = clean_text(part)
        if 6 <= len(line) <= 120 and has_strict_hall_signal(line) and has_tender_signal(line):
            return line
    for part in parts:
        line = clean_text(part)
        if 6 <= len(line) <= 120 and has_strict_hall_signal(line):
            return line
    return fallback


def extract_list_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for node in soup.select("a[href]"):
        href = clean_text(node.get("href", ""))
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue
        if any(href.lower().endswith(ext) for ext in [".jpg", ".png", ".zip", ".doc", ".xls"]):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        title = clean_text(node.get_text(" ") or node.get("title", ""))
        container = node.find_parent(["li", "tr", "article", "div"]) or node.parent
        context = clean_text(container.get_text(" ")) if container else title
        text = f"{title} {context}"
        if has_strict_hall_signal(text) and has_tender_signal(text):
            seen.add(url)
            links.append({"title": title or context[:80], "url": url, "context": context})
    return links


def build_company_aliases(source_config: dict) -> list[dict]:
    aliases: list[dict] = []
    for company in source_config.get("monitored_companies", []):
        name = clean_text(company.get("company_name", ""))
        stock_code = clean_text(str(company.get("stock_code", "")))
        region = clean_text(company.get("region", ""))
        raw_aliases = [name, name.replace("股份", ""), name.replace("集团", "")]
        raw_aliases.extend(company.get("aliases", []) or [])
        for alias in raw_aliases:
            alias = clean_text(str(alias))
            if len(alias) < 2:
                continue
            aliases.append({"alias": alias, "company_name": name, "stock_code": stock_code, "region": region})
    return sorted(aliases, key=lambda item: len(item["alias"]), reverse=True)


def build_source_aliases(source: dict) -> list[str]:
    company_name = clean_text(source.get("company_name", ""))
    base_name = re.sub(r"[（(].*?[）)]", "", company_name)
    aliases = [company_name, base_name]
    aliases.extend(source.get("aliases", []) or [])
    for suffix in ["股份有限公司", "有限责任公司", "集团有限公司", "集团股份有限公司", "有限公司", "集团", "股份"]:
        aliases.append(base_name.replace(suffix, ""))
    cleaned = []
    for alias in aliases:
        alias = clean_text(str(alias))
        if len(alias) >= 3 and alias not in cleaned:
            cleaned.append(alias)
    return sorted(cleaned, key=len, reverse=True)


def source_company_matches(text: str, source: dict) -> bool:
    if not source.get("require_company_signal"):
        return True
    text = clean_text(text)
    return any(alias and alias in text for alias in build_source_aliases(source))


def match_company_alias(text: str, aliases: list[dict]) -> dict | None:
    text = clean_text(text)
    for item in aliases:
        if item["alias"] and item["alias"] in text:
            return item
    return None


def infer_jzh_region(text: str, fallback: str = "") -> str:
    text = clean_text(text)
    city_map = {
        "南京": "江苏省南京市",
        "苏州": "江苏省苏州市",
        "无锡": "江苏省无锡市",
        "南通": "江苏省南通市",
        "徐州": "江苏省徐州市",
        "常州": "江苏省常州市",
        "杭州": "浙江省杭州市",
        "宁波": "浙江省宁波市",
        "绍兴": "浙江省绍兴市",
        "嘉兴": "浙江省嘉兴市",
        "温州": "浙江省温州市",
        "湖州": "浙江省湖州市",
        "台州": "浙江省台州市",
        "上海": "上海市",
    }
    for city, region in city_map.items():
        if city in text:
            return region
    if "江苏" in text:
        return "江苏省"
    if "浙江" in text:
        return "浙江省"
    if fallback:
        return fallback
    return ""


def parse_enterprise_tender_detail(html: str, url: str, source: dict) -> Tender | None:
    text = html_to_text(html)
    title = extract_title(html)
    if any(word in title for word in TERMINAL_STATUS_WORDS):
        return None
    combined = clean_text(f"{title} {text}")
    if not has_strict_hall_signal(combined):
        return None
    if not has_tender_signal(combined):
        return None
    if is_excluded(combined):
        return None
    if not source_company_matches(combined, source):
        return None

    publish = normalize_publish_date(source.get("publish_date") or extract_publish_date(html, combined))
    company_name = source.get("company_name", "")
    stock_code = source.get("stock_code", "")
    industry = source.get("industry", "")
    region = source.get("region", "")
    hits = [word for word in STRICT_HALL_WORDS if word in combined]
    important = clean_text(
        f"线索类型：上市公司展厅招投标；企业：{company_name}；股票代码：{stock_code}；"
        f"行业：{industry}；命中信号：{'、'.join(hits[:8])}；建议：优先核验招标文件、投标截止时间、资质要求和现场踏勘安排。"
    )
    title = infer_title_from_text(text, source.get("fallback_title", "") or title)
    return Tender(
        title=title,
        announcement_type="上市公司展厅招投标",
        publish_date=publish,
        region=region,
        purchaser=f"{company_name} {stock_code}".strip(),
        agency=industry,
        source_url=url,
        summary=summarize(text),
        budget="",
        project_no=extract_project_no(text),
        contact_person=extract_contact_person(text),
        contact_phone=extract_phone(text),
        bid_deadline=extract_deadline(text),
        important_info=important,
        source_name="上市公司展厅招投标",
    )


def parse_enterprise_lead_detail(html: str, url: str, source: dict) -> Tender | None:
    text = html_to_text(html)
    title = extract_title(html)
    combined = clean_text(f"{title} {text} {source.get('fallback_title', '')}")
    if not has_strict_hall_signal(combined):
        return None
    if is_excluded(combined):
        return None

    publish = normalize_publish_date(source.get("publish_date") or extract_publish_date(html, combined))
    company_name = source.get("company_name", "")
    stock_code = source.get("stock_code", "")
    industry = source.get("industry", "")
    region = source.get("region", "")
    lead_type = source.get("lead_type", "江浙沪上市公司展厅需求线索")
    lead_note = source.get(
        "lead_note",
        "该信息不是招标公告，仅用于监测江浙沪上市公司已公开出现的总部展厅、企业展厅、客户接待展示空间需求，后续需人工跟进官网招采入口。",
    )
    hits = [word for word in STRICT_HALL_WORDS if word in combined]
    important = clean_text(
        f"线索类型：{lead_type}；企业：{company_name}；股票代码：{stock_code}；"
        f"行业：{industry}；命中信号：{'、'.join(hits[:8])}；"
        f"说明：{lead_note}"
    )
    title = source.get("fallback_title", "") or infer_title_from_text(text, title)
    return Tender(
        title=title,
        announcement_type=lead_type,
        publish_date=publish,
        region=region,
        purchaser=f"{company_name} {stock_code}".strip(),
        agency=industry,
        source_url=url,
        summary=summarize(text),
        budget="",
        project_no=extract_project_no(text),
        contact_person=extract_contact_person(text),
        contact_phone=extract_phone(text),
        bid_deadline=extract_deadline(text),
        important_info=important,
        source_name="上市公司展厅招投标",
    )


class EnterpriseTenderCrawler(BaseCrawler):
    name = "上市公司展厅招投标"

    def search(self, query: str, days: int = 365, start_date=None, end_date=None, regions=None) -> list[Tender]:
        end = clean_text(str(end_date or date.today().isoformat()))
        start = clean_text(str(start_date or (date.today() - timedelta(days=max(days - 1, 0))).isoformat()))
        sources = self.source_config.get("procurement_sources", [])
        max_items = int(self.source_config.get("max_items", 40))
        results: list[Tender] = []
        seen: set[str] = set()
        aliases = build_company_aliases(self.source_config)

        def append_tender(tender: Tender | None, url: str) -> bool:
            if not tender:
                return False
            tender.source_name = self.source_config.get("name") or self.name
            if tender.publish_date and not in_date_range(tender.publish_date, start, end):
                return False
            results.append(self.apply_scoring(tender))
            return len(results) >= max_items

        for source in sources:
            candidate_urls = []
            candidate_urls.extend((url, source) for url in source.get("detail_urls", []))
            for list_url in source.get("list_urls", []):
                html = self.fetch_page(list_url)
                if not html:
                    continue
                list_source = dict(source)
                list_source.pop("fallback_title", None)
                list_source.pop("publish_date", None)
                list_source["require_company_signal"] = True
                candidate_urls.extend((link["url"], list_source) for link in extract_list_links(html, list_url))

            for url, candidate_source in candidate_urls:
                if url in seen:
                    continue
                seen.add(url)
                html = self.fetch_page(url)
                if not html:
                    continue
                tender = parse_enterprise_tender_detail(html, url, candidate_source)
                if append_tender(tender, url):
                    self.last_error = ""
                    return results

        for source in self.source_config.get("lead_sources", []):
            for url in source.get("detail_urls", []):
                if url in seen:
                    continue
                seen.add(url)
                html = self.fetch_page(url)
                if not html:
                    continue
                tender = parse_enterprise_lead_detail(html, url, source)
                if append_tender(tender, url):
                    self.last_error = ""
                    return results

        for source in self.source_config.get("service_sources", []):
            for url in source.get("detail_urls", []):
                if url in seen:
                    continue
                seen.add(url)
                html = self.fetch_page(url)
                if not html:
                    continue
                tender = parse_enterprise_lead_detail(html, url, source)
                if append_tender(tender, url):
                    self.last_error = ""
                    return results

        for tender in self.discover_public_platform_tenders(start, end, aliases):
            key = tender.source_url or f"{tender.title}|{tender.publish_date}"
            if key in seen:
                continue
            seen.add(key)
            if append_tender(tender, key):
                self.last_error = ""
                return results
        if results:
            self.last_error = ""
        return results

    def discover_public_platform_tenders(self, start: str, end: str, aliases: list[dict]) -> list[Tender]:
        if not self.source_config.get("public_discovery", {}).get("enabled", True):
            return []
        if not aliases:
            return []

        discovery = self.source_config.get("public_discovery", {})
        search_terms = discovery.get("search_terms") or PROJECT_SEARCH_TERMS
        max_pages = int(discovery.get("max_pages", 1))
        sources = discovery.get("sources", [])
        results: list[Tender] = []
        seen: set[str] = set()

        for source in sources:
            crawler = source.get("crawler", "")
            for term in search_terms:
                records = []
                if crawler == "jiangsu_public":
                    records = self.fetch_jiangsu_public_records(source, term, max_pages)
                elif crawler == "zhejiang_public":
                    records = self.fetch_zhejiang_public_records(source, term, start, end, max_pages)
                elif crawler == "shanghai_public":
                    records = self.fetch_shanghai_home_records(source, term)

                for record in records:
                    tender = self.public_record_to_tender(record, source, term, aliases)
                    if not tender:
                        continue
                    key = tender.source_url or f"{tender.title}|{tender.publish_date}"
                    if key in seen:
                        continue
                    seen.add(key)
                    if tender.publish_date and not in_date_range(tender.publish_date, start, end):
                        continue
                    self.enrich_public_tender_detail(tender, aliases)
                    results.append(tender)
        return results

    def fetch_jiangsu_public_records(self, source: dict, term: str, max_pages: int) -> list[dict]:
        records: list[dict] = []
        endpoint = source.get("endpoint", "http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew")
        for category in source.get("categories", []):
            for page in range(max_pages):
                payload = {
                    "token": "",
                    "pn": page * 20,
                    "rn": 20,
                    "sdt": "",
                    "edt": "",
                    "wd": term,
                    "inc_wd": "",
                    "exc_wd": "",
                    "fields": "title",
                    "cnum": "001",
                    "sort": '{"infodatepx":"0"}',
                    "ssort": "title",
                    "cl": 200,
                    "terminal": "",
                    "condition": [{"fieldName": "categorynum", "isLike": True, "likeType": 2, "equal": category.get("categorynum", "")}],
                    "time": None,
                    "highlights": "title",
                    "statistics": None,
                    "unionCondition": None,
                    "accuracy": "",
                    "noParticiple": "0",
                    "searchRange": None,
                    "isBusiness": "1",
                }
                try:
                    response = self.request_with_retries(
                        "POST",
                        endpoint,
                        json=payload,
                        timeout=int(source.get("timeout", 20)),
                        retries=1,
                        headers={"Content-Type": "application/json;charset=UTF-8", "Referer": source.get("referer", source.get("base_url", ""))},
                    )
                    if response.status_code != 200:
                        continue
                    for record in (response.json().get("result") or {}).get("records") or []:
                        record["_platform_source"] = source
                        record["_category"] = category
                        records.append(record)
                except Exception:
                    continue
        return records

    def fetch_zhejiang_public_records(self, source: dict, term: str, start: str, end: str, max_pages: int) -> list[dict]:
        records: list[dict] = []
        endpoint = source.get("endpoint", "https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew")
        for category in source.get("categories", []):
            for page in range(max_pages):
                payload = {
                    "token": "",
                    "pn": page * 20,
                    "rn": "20",
                    "sdt": "",
                    "edt": "",
                    "wd": term,
                    "inc_wd": "",
                    "exc_wd": "",
                    "fields": "title",
                    "cnum": "001",
                    "sort": '{"webdate":"0"}',
                    "ssort": "title",
                    "cl": 200,
                    "terminal": "",
                    "condition": [{"fieldName": "categorynum", "isLike": True, "likeType": 2, "equal": category.get("categorynum", "")}],
                    "time": [{"fieldName": "webdate", "startTime": f"{start} 00:00:00", "endTime": f"{end} 23:59:59"}],
                    "highlights": "",
                    "statistics": None,
                    "unionCondition": None,
                    "accuracy": "",
                    "noParticiple": "0",
                    "searchRange": None,
                    "isBusiness": "1",
                }
                try:
                    response = self.request_with_retries(
                        "POST",
                        endpoint,
                        json=payload,
                        timeout=int(source.get("timeout", 25)),
                        retries=1,
                        headers={"Referer": source.get("referer", source.get("base_url", ""))},
                    )
                    if response.status_code != 200:
                        continue
                    for record in (response.json().get("result") or {}).get("records") or []:
                        record["_platform_source"] = source
                        record["_category"] = category
                        records.append(record)
                except Exception:
                    continue
        return records

    def fetch_shanghai_home_records(self, source: dict, term: str) -> list[dict]:
        try:
            html = self.fetch_page(source.get("base_url", "https://www.shggzy.com/"))
            if not html:
                return []
            records = []
            pattern = re.compile(
                r"<li[^>]+onclick=\"window\.open\('([^']+)'\).*?data-dd='([^']+)'[^>]*>.*?<p title=\"([^\"]+)\"",
                re.S,
            )
            for path, raw_date, raw_title in pattern.findall(html):
                text = html_to_text(raw_title)
                if term not in text:
                    continue
                records.append(
                    {
                        "title": text,
                        "titlenew": text,
                        "webdate": raw_date,
                        "linkurl": path,
                        "content": text,
                        "_platform_source": source,
                        "_category": {"announcement_type": "上海公共资源公告"},
                    }
                )
            return records
        except Exception:
            return []

    def public_record_to_tender(self, record: dict, source: dict, term: str, aliases: list[dict]) -> Tender | None:
        title = clean_text(html_to_text(record.get("titlenew") or record.get("title") or ""))
        content = clean_text(html_to_text(record.get("content") or ""))
        combined = clean_text(f"{title} {content}")
        if not has_strict_hall_signal(combined):
            return None
        if is_excluded(combined):
            return None
        matched = match_company_alias(combined, aliases)
        if not matched:
            return None

        base_url = source.get("base_url", "")
        url = urljoin(base_url, clean_text(record.get("linkurl") or ""))
        publish = normalize_publish_date(record.get("infodatepx") or record.get("infodate") or record.get("webdate") or "")
        category = record.get("_category", {})
        announcement_type = category.get("announcement_type") or record.get("categoryname") or "江浙沪上市公司公开平台线索"
        important = clean_text(
            f"线索类型：江浙沪上市公司公开平台线索；命中上市公司：{matched['company_name']} {matched['stock_code']}；"
            f"命中词：{matched['alias']}；检索词：{term}；来源平台：{source.get('name', '')}。"
        )
        return Tender(
            title=title,
            announcement_type=announcement_type,
            publish_date=publish,
            region=infer_jzh_region(combined, matched.get("region", "")),
            purchaser=f"{matched['company_name']} {matched['stock_code']}".strip(),
            agency=source.get("name", ""),
            source_url=url,
            summary=summarize(content or title),
            important_info=important,
            source_name=self.source_config.get("name") or self.name,
        )

    def enrich_public_tender_detail(self, tender: Tender, aliases: list[dict]) -> None:
        html = self.fetch_page(tender.source_url)
        if not html:
            return
        text = html_to_text(html)
        title = extract_title(html)
        combined = clean_text(f"{title} {text}")
        if not has_strict_hall_signal(combined) or is_excluded(combined):
            return
        matched = match_company_alias(combined, aliases)
        if matched:
            tender.purchaser = f"{matched['company_name']} {matched['stock_code']}".strip()
            tender.region = infer_jzh_region(combined, matched.get("region", "")) or tender.region
        if title and title not in {"采购公告", "招标公告", "中标候选人公示", "中标结果公告"}:
            tender.title = infer_title_from_text(text, title) or tender.title
        tender.publish_date = normalize_publish_date(extract_publish_date(html, combined)) or tender.publish_date
        tender.summary = summarize(text) or tender.summary
        tender.project_no = extract_project_no(text) or tender.project_no
        tender.contact_person = extract_contact_person(text) or tender.contact_person
        tender.contact_phone = extract_phone(text) or tender.contact_phone
        tender.bid_deadline = extract_deadline(text) or tender.bid_deadline

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
