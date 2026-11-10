from crawlers.anhui_public import AnhuiPublicCrawler
from crawlers.ccgp_public import CcgpPublicCrawler
from crawlers.chongqing_public import ChongqingPublicCrawler
from crawlers.example_public_page import ExamplePublicPageCrawler
from crawlers.enterprise_news import EnterpriseNewsCrawler
from crawlers.enterprise_tender import EnterpriseTenderCrawler
from crawlers.ggzy_public import GgzyPublicCrawler
from crawlers.guizhou_public import GuiyangPublicCrawler, GuizhouPublicCrawler
from crawlers.hubei_public import HubeiPublicCrawler, WuhanPublicCrawler
from crawlers.hunan_public import ChangshaPublicCrawler, HunanPublicCrawler
from crawlers.hebei_public import HebeiPublicCrawler
from crawlers.jiangsu_public import JiangsuPublicCrawler
from crawlers.liaoning_public import LiaoningPublicCrawler
from crawlers.neimenggu_public import NeimengguPublicCrawler
from crawlers.regional_static import RegionalStaticCrawler
from crawlers.shandong_public import ShandongPublicCrawler
from crawlers.shaanxi_public import ShaanxiPublicCrawler
from crawlers.shanghai_public import ShanghaiPublicCrawler
from crawlers.suzhou_public import SuzhouPublicCrawler
from crawlers.xinjiang_public import XinjiangPublicCrawler
from crawlers.zhejiang_public import ZhejiangPublicCrawler


CRAWLER_REGISTRY = {
    "ccgp_public": CcgpPublicCrawler,
    "chongqing_public": ChongqingPublicCrawler,
    "anhui_public": AnhuiPublicCrawler,
    "example_public_page": ExamplePublicPageCrawler,
    "enterprise_news": EnterpriseNewsCrawler,
    "enterprise_tender": EnterpriseTenderCrawler,
    "ggzy_public": GgzyPublicCrawler,
    "guizhou_public": GuizhouPublicCrawler,
    "guiyang_public": GuiyangPublicCrawler,
    "hunan_public": HunanPublicCrawler,
    "hubei_public": HubeiPublicCrawler,
    "jiangsu_public": JiangsuPublicCrawler,
    "hebei_public": HebeiPublicCrawler,
    "liaoning_public": LiaoningPublicCrawler,
    "neimenggu_public": NeimengguPublicCrawler,
    "regional_static": RegionalStaticCrawler,
    "shandong_public": ShandongPublicCrawler,
    "shaanxi_public": ShaanxiPublicCrawler,
    "shanghai_public": ShanghaiPublicCrawler,
    "suzhou_public": SuzhouPublicCrawler,
    "changsha_public": ChangshaPublicCrawler,
    "wuhan_public": WuhanPublicCrawler,
    "xinjiang_public": XinjiangPublicCrawler,
    "zhejiang_public": ZhejiangPublicCrawler,
}


def get_crawler_class(crawler_name: str):
    return CRAWLER_REGISTRY.get(crawler_name)
