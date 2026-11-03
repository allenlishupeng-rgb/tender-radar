from datetime import date, timedelta
from urllib.parse import urlencode

from crawlers.regional_static import RegionalStaticCrawler


SEARCH_TYPES = ["gcjszbgg", "zfcg"]
QUERY_EXPANSIONS = {
    "展陈": ["展陈", "展厅", "布展", "馆"],
    "展厅": ["展厅", "展陈", "展示馆", "馆"],
    "布展": ["布展", "展陈", "展厅", "馆"],
}


class AnhuiPublicCrawler(RegionalStaticCrawler):
    source_name = "安徽省公共资源交易监管网"
    province = "安徽省"
    logger_name = "anhui_public"

    def build_list_url(self, base_url: str, category: dict, page: int) -> str:
        query = category.get("_query", "")
        if query:
            params = {
                "currentPage": page,
                "region": "",
                "type": category.get("type", "gcjszbgg"),
                "contenttype": "",
                "param": query,
                "timeParam": category.get("time_param", "month"),
                "order": "time",
            }
            return f"{base_url.rstrip('/')}/souSuo?{urlencode(params)}"
        return super().build_list_url(base_url, category, page)

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None):
        if regions and not any("安徽" in r for r in regions):
            return []
        time_param = "week" if days <= 7 else "month"
        queries = QUERY_EXPANSIONS.get(query, [query])
        original = self.source_config.get("categories")
        all_results = []
        seen = set()
        try:
            for search_query in queries:
                self.source_config["categories"] = [
                    {"name": "工程建设-站内搜索", "type": "gcjszbgg", "_query": search_query, "time_param": time_param, "announcement_type": "招标公告"},
                    {"name": "政府采购-站内搜索", "type": "zfcg", "_query": search_query, "time_param": time_param, "announcement_type": "采购公告"},
                ]
                results = super().search(query=search_query, days=days, start_date=start_date, end_date=end_date, regions=regions)
                for item in results:
                    if item.source_url in seen:
                        continue
                    seen.add(item.source_url)
                    all_results.append(item)
            return all_results
        finally:
            if original is not None:
                self.source_config["categories"] = original
