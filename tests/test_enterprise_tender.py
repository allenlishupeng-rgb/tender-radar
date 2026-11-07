from crawlers.enterprise_tender import (
    EnterpriseTenderCrawler,
    build_company_aliases,
    parse_enterprise_lead_detail,
    parse_enterprise_tender_detail,
)


def test_parse_enterprise_tender_detail_requires_hall_and_tender_signals():
    html = """
    <html><head><title>山推企业展厅升级项目</title></head><body>
    招标公告：山推企业展厅升级项目
    山推工程机械股份有限公司现采用公开招标方式选择中标人。
    本项目为山推企业展厅升级设计施工一体化项目，包含展陈布展、多媒体与智能化系统。
    发布日期：2025.09.03
    </body></html>
    """
    tender = parse_enterprise_tender_detail(
        html,
        "https://www.shantui.com/about/tender-detail-720116.htm",
        {"company_name": "山推股份", "stock_code": "000680", "industry": "工程机械", "region": "山东济宁"},
    )

    assert tender is not None
    assert tender.title == "山推企业展厅升级项目"
    assert tender.announcement_type == "上市公司展厅招投标"
    assert tender.publish_date == "2025-09-03"
    assert tender.purchaser == "山推股份 000680"
    assert "企业展厅" in tender.important_info


def test_parse_enterprise_tender_detail_rejects_strategy_news():
    html = """
    <html><body>
    宁德时代与某地政府签署战略合作协议，共建零碳城市。
    发布日期：2026-06-12
    </body></html>
    """

    tender = parse_enterprise_tender_detail(
        html,
        "https://www.catl.com/news/example.html",
        {"company_name": "宁德时代", "stock_code": "300750"},
    )

    assert tender is None


def test_parse_enterprise_tender_detail_rejects_terminal_notice():
    html = """
    <html><head><title>南京熊猫汉达科技有限公司卫星通信展厅建设项目终止公告</title></head><body>
    南京熊猫汉达科技有限公司卫星通信展厅建设项目终止公告
    发布时间：2026-06-22
    本项目终止采购。
    </body></html>
    """

    tender = parse_enterprise_tender_detail(
        html,
        "https://www.cec-ec.com.cn/cms/channel/1xmgg1/55453.htm",
        {"company_name": "南京熊猫汉达科技有限公司（南京熊猫体系）", "stock_code": "600775"},
    )

    assert tender is None


def test_parse_enterprise_tender_detail_prefers_article_meta_title():
    html = """
    <html><head>
    <meta name="ArticleTitle" content="中国重型机械有限公司展厅建设项目公开招标公告">
    <meta name="PubDate" content="2026-06-22 09:00:00">
    </head><body>
    一、项目概况与招标范围
    中国重型机械有限公司展厅建设项目工程总承包（EPC），现对该项目进行公开招标。
    投标文件递交的截止时间：北京时间2026年07月6日9:00。
    电话：010-83921519
    </body></html>
    """
    tender = parse_enterprise_tender_detail(
        html,
        "https://epp.sinomach.com.cn/zbzq/001001/20260622/example.html",
        {"company_name": "国机重装体系（中国重机）", "stock_code": "601399", "industry": "重型装备", "region": "北京"},
    )

    assert tender is not None
    assert tender.title == "中国重型机械有限公司展厅建设项目公开招标公告"
    assert tender.publish_date == "2026-06-22"


def test_parse_enterprise_tender_detail_uses_configured_fallback_title():
    html = """
    <html><head><title>Sorry，当前栏目暂无内容!</title></head><body>
    陕西美邦药业集团股份有限公司总部展厅施工项目招标公告
    2026-06-18
    招标公告
    </body></html>
    """
    tender = parse_enterprise_tender_detail(
        html,
        "https://www.meibang.cn/news/11.html",
        {
            "company_name": "美邦股份",
            "stock_code": "605033",
            "industry": "农药制剂",
            "region": "陕西西安",
            "fallback_title": "陕西美邦药业集团股份有限公司总部展厅施工项目招标公告",
        },
    )

    assert tender is not None
    assert tender.title == "陕西美邦药业集团股份有限公司总部展厅施工项目招标公告"


def test_parse_enterprise_lead_detail_builds_suzhou_listed_company_lead():
    html = """
    <html><head><title>访企拓岗促交流</title></head><body>
    时间：2026-04-29 15:27:11
    在苏州华兴源创科技股份有限公司相关负责人的陪同下，
    先后参观了公司总部展厅、5G智能工厂及核心生产车间。
    </body></html>
    """
    tender = parse_enterprise_lead_detail(
        html,
        "https://www.uwh.edu.cn/dxxy/detail/912/16879.html",
        {
            "company_name": "苏州华兴源创科技股份有限公司",
            "stock_code": "688001",
            "industry": "半导体检测",
            "region": "江苏省苏州市工业园区",
            "fallback_title": "苏州华兴源创总部展厅与5G智能工厂参访需求线索",
        },
    )

    assert tender is not None
    assert tender.title == "苏州华兴源创总部展厅与5G智能工厂参访需求线索"
    assert tender.announcement_type == "江浙沪上市公司展厅需求线索"
    assert tender.publish_date == "2026-04-29"


def test_parse_enterprise_lead_detail_accepts_service_tender_signal():
    html = """
    <html><head><title>中标候选人公示</title></head><body>
    玉环市未来城市之窗项目-展陈工程总承包（EPC）中标候选人公示
    中标候选人：苏州金螳螂文化发展股份有限公司。
    发布日期：2026-01-23
    </body></html>
    """
    tender = parse_enterprise_lead_detail(
        html,
        "https://ggzy.tzztb.zjtz.gov.cn/jyxx/002001/002001005/20260123/example.html",
        {
            "company_name": "苏州金螳螂文化发展股份有限公司（金螳螂体系）",
            "stock_code": "002081",
            "industry": "文博展陈/展览展示设计施工",
            "region": "江苏省苏州市",
            "fallback_title": "苏州金螳螂文化参与玉环市未来城市之窗展陈工程总承包投标",
            "lead_type": "江浙沪上市公司公开招投标服务线索",
            "lead_note": "公开资源交易页面显示江浙沪上市公司体系企业参与展陈工程总承包投标。",
        },
    )

    assert tender is not None
    assert tender.title == "苏州金螳螂文化参与玉环市未来城市之窗展陈工程总承包投标"
    assert tender.announcement_type == "江浙沪上市公司公开招投标服务线索"
    assert tender.publish_date == "2026-01-23"
    assert "展陈工程" in tender.important_info


def test_public_record_to_tender_requires_company_alias_and_hall_signal():
    source_config = {
        "name": "江浙沪上市公司展厅招投标",
        "monitored_companies": [
            {
                "company_name": "吉利汽车",
                "stock_code": "0175.HK",
                "region": "浙江省杭州市",
                "aliases": ["极氪", "极氪智能科技"],
            }
        ],
    }
    crawler = EnterpriseTenderCrawler({}, source_config=source_config)
    aliases = build_company_aliases(source_config)
    record = {
        "titlenew": "极氪直营展厅2025-2026年度装饰装修施工年框项目招标公告",
        "content": "项目地点：浙江杭州。项目内容包括直营展厅装饰装修施工。",
        "webdate": "2025-02-13",
        "linkurl": "/sample.html",
        "_category": {"announcement_type": "招标公告"},
    }

    tender = crawler.public_record_to_tender(
        record,
        {"name": "浙江省公共资源交易服务平台", "base_url": "https://ggzy.zj.gov.cn/"},
        "展厅",
        aliases,
    )

    assert tender is not None
    assert tender.title == "极氪直营展厅2025-2026年度装饰装修施工年框项目招标公告"
    assert tender.purchaser == "吉利汽车 0175.HK"
    assert tender.region == "浙江省杭州市"
    assert "江浙沪上市公司公开平台线索" in tender.important_info
