from datetime import date

from crawlers.base import BaseCrawler
from database.models import Tender
from parsers.common import summarize


class ExamplePublicPageCrawler(BaseCrawler):
    """A safe MVP adapter.

    It creates a realistic sample lead so the local workflow can run end-to-end.
    Replace `search` with platform-specific public search parsing when each data
    source is connected.
    """

    name = "示例公开页面适配器"

    def search(self, query: str, days: int = 7, start_date=None, end_date=None, regions=None) -> list[Tender]:
        source_name = self.source_config.get("name", self.name)
        base_url = self.source_config.get("base_url", "https://www.ggzy.gov.cn/")
        sample_body = (
            "某产业展示中心展陈设计施工一体化项目，包含展陈设计、深化设计、"
            "多媒体展项、数字沙盘、导视系统及布展施工等内容。"
        )
        tender = Tender(
            title=f"{query}相关示例项目：{source_name}产业展示中心展陈设计施工一体化招标公告",
            announcement_type="公开招标公告",
            publish_date=date.today().isoformat(),
            region="江苏省苏州市",
            purchaser="示例建设单位",
            agency="示例招标代理有限公司",
            budget="1200万元",
            project_no=f"MVP-EXAMPLE-{sum(ord(ch) for ch in source_name) % 10000:04d}",
            source_url=base_url,
            summary=summarize(sample_body),
            source_name=source_name,
        )
        return [self.apply_scoring(tender)]
