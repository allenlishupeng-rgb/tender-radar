from crawlers.base import BaseCrawler
from database.models import Tender


class ShandongPublicCrawler(BaseCrawler):
    name = "山东省公共资源交易网"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        if regions and not any("山东" in str(region or "") for region in regions):
            return []
        base_url = self.source_config.get("base_url") or "https://ggzyjy.shandong.gov.cn/"
        if not self.can_fetch(base_url):
            self.last_error = f"robots.txt 不允许访问：{base_url}；山东省公共资源交易网当前禁止抓取，已合规跳过"
            return []
        self.last_error = "山东省公共资源交易网未配置可合规抓取的公开搜索接口"
        return []
