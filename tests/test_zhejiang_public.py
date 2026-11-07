from types import SimpleNamespace

from crawlers.zhejiang_public import ZhejiangPublicCrawler, extract_budget
from database.models import Tender


def test_zhejiang_extract_budget_variants():
    assert extract_budget("最高投标限价：123.45万元") == "123.45万元"
    assert extract_budget("预算金额：980000元") == "980000元"


def test_zhejiang_detail_enriches_business_fields():
    crawler = ZhejiangPublicCrawler({}, source_config={})
    html = """
    <html><body>
      <h1>产业展示中心展陈设计施工项目招标公告</h1>
      <p>发布时间：2026-06-20</p>
      <p>招标人：浙江某产业园有限公司</p>
      <p>招标代理机构：浙江某代理有限公司</p>
      <p>最高投标限价：520.5万元</p>
      <p>项目编号：ZJ-2026-001</p>
      <p>联系人：王工</p>
      <p>联系电话：0571-88888888</p>
      <p>投标截止时间：2026-07-08 09:30</p>
    </body></html>
    """
    crawler.get = lambda _url: SimpleNamespace(text=html, encoding="utf-8", apparent_encoding="utf-8")
    tender = Tender(title="产业展示中心展陈设计施工项目", source_url="https://example.com/detail")

    crawler.enrich_from_detail(tender)

    assert tender.publish_date == "2026-06-20"
    assert tender.purchaser == "浙江某产业园有限公司"
    assert tender.agency == "浙江某代理有限公司"
    assert tender.budget == "520.5万元"
    assert tender.project_no == "ZJ-2026-001"
    assert tender.contact_person == "王工"
    assert tender.contact_phone == "0571-88888888"
    assert tender.bid_deadline == "2026-07-08 09:30"
