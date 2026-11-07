from pathlib import Path

import yaml

from scoring.rules import classify_notice_stage, is_target_exhibition_tender, score_tender
from crawlers.base import BaseCrawler
from database.models import Tender


def test_score_high_priority_sample():
    keywords = {
        "strong_keywords": ["展厅", "展示中心"],
        "business_keywords": ["设计施工一体化", "多媒体展项"],
        "extended_keywords": ["产业服务中心"],
        "downrank_keywords": ["广告印刷"],
        "preferred_regions": ["江苏"],
    }
    tender = {
        "title": "江苏产业展示中心展厅设计施工一体化招标公告",
        "summary": "项目包含多媒体展项、数字沙盘及深化设计。",
        "budget": "1500万元",
        "region": "江苏省苏州市",
        "publish_date": "2026-06-05",
        "announcement_type": "公开招标公告",
    }
    scored = score_tender(tender, keywords)
    assert scored["relevance_score"] >= 60
    assert "展厅" in scored["matched_keywords"]
    assert scored["notice_stage"] == "可投公告"
    assert scored["profile_project_type"] == "园区产业展示"
    assert scored["profile_client_type"] in {"事业单位/公共文化", "未知"}
    assert "画像" not in scored["profile_reason"]


def test_source_weight_downranks_high_risk_source():
    crawler = BaseCrawler(
        {
            "strong_keywords": ["展厅"],
            "business_keywords": ["设计施工一体化"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "preferred_regions": ["江苏"],
        },
        source_config={"source_weight": 0.35},
        request_interval=0,
    )
    tender = Tender(
        title="江苏产业展示中心展厅设计施工一体化招标公告",
        summary="项目包含展陈设计、数字展厅和布展施工。",
        budget="1500万元",
        region="江苏省苏州市",
        publish_date="2026-06-05",
        announcement_type="公开招标公告",
        source_url="https://example.com/high-risk",
    )

    scored = crawler.apply_scoring(tender)

    assert scored.relevance_score < 40
    assert scored.priority == "可能无关"


def test_classify_notice_stage_splits_result_and_intel():
    assert classify_notice_stage({"title": "某企业文化展厅项目中标公告", "announcement_type": "中标公告"}) == "中标结果"
    assert classify_notice_stage({"title": "产业园数字展厅装修展示工程合同公示"}) == "中标结果"
    assert classify_notice_stage({"title": "产业园展示中心项目采购意向公开", "announcement_type": "采购意向"}) == "情报参考"
    assert classify_notice_stage({"title": "徐圩新区廉洁教育展馆内容更新升级（二次）废标(终止)公告"}) == "无效"


def test_selected_supplier_notice_overrides_stale_bid_stage():
    from scoring.rules import annotate_notice_stage

    row = {
        "title": "自动化研究所展厅改造工程中选公告",
        "announcement_type": "比选公告",
        "notice_stage": "可投公告",
    }
    assert classify_notice_stage(row) == "中标结果"
    assert annotate_notice_stage(row, preserve_existing=True)["notice_stage"] == "中标结果"


def test_score_downranks_museum_exhibition_fit():
    keywords = {
        "strong_keywords": ["博物馆", "展馆", "展陈"],
        "business_keywords": ["布展", "深化设计"],
        "extended_keywords": [],
        "downrank_keywords": [],
        "preferred_regions": ["安徽"],
    }
    tender = {
        "title": "亳州市博物馆布展项目展陈大纲编写及展陈深化设计项目招标公告",
        "summary": "",
        "budget": "",
        "region": "安徽省",
        "publish_date": "2026-06-05",
        "announcement_type": "招标公告",
    }
    scored = score_tender(tender, keywords)
    assert scored["relevance_score"] < 60
    assert scored["priority"] == "低优先级"
    assert scored["profile_project_type"] == "公共文化展陈"


def test_public_museum_exhibition_is_not_high_priority_even_with_delivery_terms():
    scored = score_tender(
        {
            "title": "山东博物馆东夷文化展陈列布展项目公开招标公告",
            "summary": "项目包含展陈大纲、陈列布展和多媒体展项。",
            "budget": "1200万元",
            "region": "山东",
            "publish_date": "2026-07-02",
            "announcement_type": "公开招标公告",
        },
        {
            "strong_keywords": ["博物馆", "展陈", "布展"],
            "business_keywords": ["陈列布展", "多媒体展项"],
            "extended_keywords": [],
            "downrank_keywords": ["博物馆", "文物"],
            "preferred_regions": ["山东"],
        },
    )

    assert scored["profile_project_type"] == "公共文化展陈"
    assert scored["priority"] == "低优先级"
    assert scored["relevance_score"] < 60


def test_school_history_hall_is_public_culture_even_with_epc_delivery_terms():
    keywords = yaml.safe_load(Path("config/keywords.yaml").read_text(encoding="utf-8"))
    scored = score_tender(
        {
            "title": "大连理工大学化工学院院史展厅改造项目总承包（EPC）竞争性磋商公告",
            "purchaser": "大连理工大学",
            "summary": "包括展厅设计、装修施工、多媒体展项和布展服务。",
            "announcement_type": "竞争性磋商公告",
        },
        keywords,
    )

    assert scored["profile_project_type"] == "公共文化展陈"
    assert scored["priority"] == "低优先级"
    assert scored["relevance_score"] < 60


def test_enterprise_and_industrial_halls_stay_high_priority():
    enterprise = score_tender(
        {
            "title": "某集团总部展厅设计施工一体化项目招标公告",
            "summary": "包含企业文化展厅、品牌展示、数字展厅和多媒体展项。",
            "budget": "800万元",
            "region": "江苏",
            "publish_date": "2026-07-02",
            "announcement_type": "公开招标公告",
        },
        {
            "strong_keywords": ["总部展厅", "企业文化展厅", "数字展厅"],
            "business_keywords": ["设计施工一体化", "多媒体展项"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "preferred_regions": ["江苏"],
        },
    )
    industrial = score_tender(
        {
            "title": "低空经济产业园展示中心设计施工一体化项目招标公告",
            "summary": "包含低空经济产业展示、展陈深化、互动装置和布展施工。",
            "budget": "1000万元",
            "region": "江苏",
            "publish_date": "2026-07-02",
            "announcement_type": "公开招标公告",
        },
        {
            "strong_keywords": ["展示中心", "展陈"],
            "business_keywords": ["设计施工一体化", "互动装置", "布展施工"],
            "extended_keywords": ["产业园", "低空经济"],
            "downrank_keywords": [],
            "preferred_regions": ["江苏"],
        },
    )

    assert enterprise["priority"] == "高优先级"
    assert industrial["priority"] == "高优先级"


def test_business_priority_classifies_planning_hall_as_high():
    scored = score_tender(
        {
            "title": "苏州高新区产业园区规划馆改造翻新工程招标公告",
            "summary": "包含规划馆展陈更新、布展设计和施工。",
            "budget": "300万元",
            "region": "苏州",
            "publish_date": "2026-06-08",
            "announcement_type": "招标公告",
        },
        {
            "strong_keywords": ["规划馆"],
            "business_keywords": ["展陈", "布展设计"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "preferred_regions": ["苏州"],
        },
    )

    assert scored["priority"] == "高优先级"
    assert scored["relevance_score"] >= 85


def test_business_priority_classifies_scenic_theme_hall_as_medium():
    scored = score_tender(
        {
            "title": "景区内文旅主题馆设计施工工程采购公告",
            "summary": "建设主题展馆，包含展陈设计和布展施工。",
            "budget": "260万元",
            "region": "浙江",
            "publish_date": "2026-06-08",
            "announcement_type": "采购公告",
        },
        {
            "strong_keywords": ["主题馆", "展馆"],
            "business_keywords": ["设计施工", "展陈设计"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "preferred_regions": ["浙江"],
        },
    )

    assert scored["priority"] == "中优先级"
    assert 60 <= scored["relevance_score"] < 80


def test_business_priority_classifies_state_owned_display_hall_as_low():
    scored = score_tender(
        {
            "title": "大型国企展示中心展厅设计施工项目招标公告",
            "summary": "企业成果展示馆和形象展示中心更新。",
            "budget": "1200万元",
            "region": "湖北",
            "publish_date": "2026-06-08",
            "announcement_type": "招标公告",
        },
        {
            "strong_keywords": ["展示中心", "展厅"],
            "business_keywords": ["设计施工"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "preferred_regions": ["湖北"],
        },
    )

    assert scored["priority"] == "低优先级"
    assert 40 <= scored["relevance_score"] < 60


def test_enterprise_culture_hall_is_high_priority_for_enterprise_source():
    scored = score_tender(
        {
            "title": "信泰保险企业文化展厅项目结果公示",
            "summary": "项目为企业文化展厅设计、布置和多媒体施工。",
            "budget": "",
            "region": "浙江省杭州市",
            "publish_date": "2025-10-17",
            "announcement_type": "上市公司展厅招投标",
            "source_name": "江浙沪上市公司展厅招投标",
        },
        {
            "strong_keywords": ["展厅", "企业文化展厅"],
            "business_keywords": ["设计", "施工"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "enterprise_hall_keywords": ["企业文化展厅"],
            "enterprise_expansion_keywords": [],
            "enterprise_downrank_keywords": [],
            "preferred_regions": ["浙江"],
        },
    )

    assert scored["priority"] == "高优先级"
    assert scored["relevance_score"] >= 85


def test_relevance_gate_rejects_generic_digital_project():
    tender = {
        "title": "某单位数字化管理平台建设项目采购公告",
        "summary": "包含数据治理、系统集成和运维服务。",
        "announcement_type": "采购公告",
    }

    scored = score_tender(
        tender,
        {
            "strong_keywords": ["数字化", "展示"],
            "business_keywords": ["系统集成"],
            "extended_keywords": [],
            "downrank_keywords": [],
            "preferred_regions": [],
        },
    )

    assert not is_target_exhibition_tender(tender)
    assert scored["relevance_score"] == 0
    assert scored["priority"] == "可能无关"


def test_relevance_gate_rejects_trade_show_booth_service():
    tender = {
        "title": "第八届展会展位搭建及会务服务项目采购公告",
        "summary": "服务内容为展位设计、展台搭建、会务执行和物料制作。",
        "announcement_type": "采购公告",
    }

    scored = score_tender(
        tender,
        {
            "strong_keywords": ["展示"],
            "business_keywords": ["设计"],
            "extended_keywords": [],
            "downrank_keywords": ["展位", "展台搭建", "会务服务"],
            "preferred_regions": [],
        },
    )

    assert not is_target_exhibition_tender(tender)
    assert scored["relevance_score"] == 0


def test_relevance_gate_keeps_real_exhibition_hall_project():
    tender = {
        "title": "城市文化馆数字展厅展陈布展设计施工一体化项目招标公告",
        "summary": "包含展陈深化设计、多媒体展项、互动装置和布展施工。",
        "announcement_type": "招标公告",
    }

    assert is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_asset_transfer_with_display_center_name():
    tender = {
        "title": "思南县展示中心一区部分商业用房资产转让招标公告",
        "summary": "本项目为商业用房资产转让。",
        "announcement_type": "招标公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_activity_materials_in_memorial_hall():
    tender = {
        "title": "陈列馆端午节文化惠民活动物料设计制作服务项目",
        "summary": "服务内容为活动物料和宣传设计。",
        "announcement_type": "采购公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_does_not_reject_real_project_from_noisy_summary():
    tender = {
        "title": "同济大学校史馆展陈采购项目公开招标公告",
        "summary": "网页侧栏包含物业服务、食堂、超市等无关导航文字。",
        "announcement_type": "公开招标公告",
    }

    assert is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_museum_security_service():
    tender = {
        "title": "城市博物馆安保服务项目公开招标公告",
        "summary": "服务内容为场馆保安、巡逻和值守。",
        "announcement_type": "公开招标公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_museum_collection_protection():
    tender = {
        "title": "自然博物馆馆藏文物预防性保护项目公开招标公告",
        "summary": "采购内容为储藏柜、恒湿设备和文物库房配套设备。",
        "announcement_type": "公开招标公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_advertising_display_service():
    tender = {
        "title": "党群服务中心广告布展服务项目招标公告",
        "summary": "服务内容为广告制作、喷绘写真、标识标牌和物料安装。",
        "announcement_type": "招标公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_municipal_navigation_light_project():
    tender = {
        "title": "2025年航标灯维护改造工程公开招标公告",
        "summary": "本项目为航标灯维护、市政设施巡检和改造。",
        "announcement_type": "公开招标公告",
        "purchaser": "福州市市政工程中心",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_hospital_property_management():
    tender = {
        "title": "福州市第二总医院物业管理服务项目公开招标公告",
        "summary": "服务内容为医院保洁、秩序维护和物业管理。",
        "announcement_type": "公开招标公告",
        "purchaser": "福州市第二总医院",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_keeps_industrial_park_hall_epc():
    tender = {
        "title": "空天产业园一体化展厅建设项目设计施工一体化询比公告",
        "summary": "包含展陈设计、数字展厅、多媒体展项、互动装置和布展施工。",
        "announcement_type": "询比公告",
    }

    assert is_target_exhibition_tender(tender)


def test_portfolio_profile_keeps_low_carbon_industrial_expo_hall():
    tender = {
        "title": "昆山低碳产业博览馆布展设计施工一体化项目公开招标公告",
        "summary": "建设内容包含产业展示、展陈深化、数字内容和互动展项。",
        "announcement_type": "公开招标公告",
        "region": "江苏省昆山市",
    }

    scored = score_tender(
        tender,
        {
            "strong_keywords": ["产业博览馆", "展示中心", "展厅"],
            "business_keywords": ["布展设计", "设计施工一体化", "数字内容"],
            "extended_keywords": ["低碳产业园", "产业园"],
            "downrank_keywords": [],
            "preferred_regions": ["江苏", "昆山"],
        },
    )

    assert is_target_exhibition_tender(tender)
    assert scored["priority"] == "高优先级"


def test_portfolio_profile_keeps_ai_industrial_community_showroom():
    tender = {
        "title": "西太湖常州人工智能国际产业社区展示体验中心设计施工项目招标公告",
        "summary": "项目包含人工智能产业展示、体验中心空间设计、多媒体展项和布展施工。",
        "announcement_type": "招标公告",
        "region": "江苏省常州市",
    }

    assert is_target_exhibition_tender(tender)


def test_project_profile_classifies_portfolio_like_examples():
    keywords = {
        "strong_keywords": ["展厅", "科技展厅"],
        "business_keywords": ["布展", "展陈"],
        "extended_keywords": ["园区"],
        "downrank_keywords": [],
        "preferred_regions": ["江苏"],
    }

    park = score_tender(
        {
            "title": "临港园区展厅展廊项目工程总承包公开招标公告",
            "summary": "包含园区展厅展廊建设和展陈施工。",
            "announcement_type": "公开招标公告",
            "region": "上海",
        },
        keywords,
    )
    tech = score_tender(
        {
            "title": "南京大学无锡滨湖大气前沿技术与高端装备创新研究院科技展厅布展项目采购公告",
            "summary": "项目包含科技展厅布展与展陈内容制作。",
            "announcement_type": "采购公告",
            "region": "江苏",
        },
        keywords,
    )

    assert park["profile_project_type"] == "园区产业展示"
    assert tech["profile_project_type"] == "科技主题展厅"
    assert tech["profile_client_type"] == "事业单位/公共文化"


def test_portfolio_profile_rejects_plain_drainage_in_industrial_zone():
    tender = {
        "title": "高新区排水管网改造工程公开招标公告",
        "summary": "项目内容为雨污水管网和市政道路配套施工。",
        "announcement_type": "公开招标公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_ignores_opening_location_in_display_hall():
    tender = {
        "title": "福州市电子证照治理提升服务项目公开招标公告",
        "summary": "项目内容为电子证照数据治理、平台升级和系统运维服务。",
        "announcement_type": "公开招标公告",
        "important_info": "开标地点：福州市城市规划展示馆3楼公共资源交易服务中心。",
    }

    assert not is_target_exhibition_tender(tender)


def test_relevance_gate_rejects_multimedia_equipment_project():
    tender = {
        "title": "上海市静安区文化馆海上多媒体设备项目公开招标公告",
        "summary": "采购内容为多媒体设备供货、安装和运维。",
        "announcement_type": "公开招标公告",
    }

    assert not is_target_exhibition_tender(tender)


def test_profile_search_rejects_context_without_exhibition_carrier():
    examples = [
        "2026-2027年度开发区地下空间探测检测项目招标公告",
        "国际先进技术应用推进中心（大湾区）暨场景创新中心项目招标公告",
        "中国中医科学院眼科医院国家中医药传承创新中心建设项目--设备第二批公开招标公告",
        "山东水利职业学院具身智能机器人训练场项目(二次)公开招标公告",
        "中国长城博物馆观众服务配套物资采购公开招标公告",
        "贵州省坝陵河桥梁博物馆研学基地提升项目工程监理（二次）中标结果公告",
        "2026年南博开放运行基础网络智能化、终端设备、多媒体展览展示设备运维及运营项目采购公告",
        "博大大厦一、二号展厅运营服务公开招标公告",
        "吉林省供销合作社-第25届长春农博会供销展馆搭建运营及产销对接活动项目公开招标公告",
        "五莲县博物馆馆藏文物数字化保护项目招标公告",
        "六合文庙消防系统设备及安装采购公告",
        "清华大学科学博物馆网络建设项目公开招标公告",
        "中国科学家博物馆藏品管理平台维护与藏品数字化项目公开招标公告",
        "首都博物馆东馆展柜、灯具购置01包展柜购置公开招标公告",
        "高质量发展-学科建设-职业教育博物馆文化育人智能体建设与应用-AI智能体开发项目公开招标公告",
        "中国科学家博物馆采集工程业务交流活动项目公开招标公告",
        "苏州碑刻博物馆关于苏州文庙及石刻防雷工程项目的采购公告",
    ]

    for title in examples:
        assert not is_target_exhibition_tender({"title": title, "announcement_type": "公开招标公告"})
