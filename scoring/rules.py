import re
from datetime import date, datetime
from typing import Any

import yaml
from dateutil import parser as date_parser

import config.settings  # noqa: F401  Applies the Beijing business timezone.

from scoring.project_profile import (
    PRIMARY_TARGET_TERMS,
    PROJECT_CONTEXT_TERMS,
    PROJECT_DELIVERY_TERMS,
    PROJECT_DOWNRANK_TERMS,
    PROJECT_VENUE_TERMS,
    PUBLIC_CULTURE_PROFILE_TYPE,
    PUBLIC_CULTURE_TERMS,
    classify_project_profile,
    has_target_business_signal,
    is_public_culture_without_target,
)


WEAK_PROFILE_VENUE_TERMS = {
    "未来中心",
    "创新中心",
    "国际创新中心",
    "创新创业服务中心",
    "产业服务中心",
    "企业服务中心",
    "服务中心",
    "文化中心",
    "文化交流中心",
    "客户接待中心",
}
PROFILE_EXHIBITION_VENUE_TERMS = [
    word for word in PROJECT_VENUE_TERMS if word not in WEAK_PROFILE_VENUE_TERMS and word not in PUBLIC_CULTURE_TERMS
]


def load_keywords(path) -> dict[str, list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    text_lower = (text or "").lower()
    hits = []
    for keyword in keywords:
        if keyword.lower() in text_lower:
            hits.append(keyword)
    return hits


def parse_budget_amount(text: str) -> float:
    """Return budget in RMB yuan when possible."""
    if not text:
        return 0
    normalized = text.replace(",", "").replace("，", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(亿元|亿|万元|万|元)?", normalized)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2) or "元"
    if unit in {"亿元", "亿"}:
        return value * 100_000_000
    if unit in {"万元", "万"}:
        return value * 10_000
    return value


def freshness_score(publish_date: str) -> int:
    if not publish_date:
        return 0
    try:
        dt = date_parser.parse(publish_date).date()
    except Exception:
        return 0
    days = max((date.today() - dt).days, 0)
    if days <= 3:
        return 10
    if days <= 7:
        return 8
    if days <= 14:
        return 6
    if days <= 30:
        return 4
    return 1


def stage_score(announcement_type: str, title: str) -> int:
    stage = classify_notice_stage({"announcement_type": announcement_type, "title": title})
    if stage == NOTICE_STAGE_BID:
        return 10
    if stage == NOTICE_STAGE_INTEL:
        return 7
    if stage == NOTICE_STAGE_CHANGE:
        return 4
    if stage == NOTICE_STAGE_RESULT:
        return 2
    if stage == NOTICE_STAGE_INVALID:
        return 0
    return 5


def budget_score(budget_text: str) -> int:
    amount = parse_budget_amount(budget_text)
    if amount >= 20_000_000:
        return 15
    if amount >= 10_000_000:
        return 12
    if amount >= 5_000_000:
        return 10
    if amount >= 1_000_000:
        return 7
    if amount > 0:
        return 4
    return 0


def contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def contains_pair(text: str, left_words: list[str], right_words: list[str]) -> bool:
    return contains_any(text, left_words) and contains_any(text, right_words)


NOTICE_STAGE_BID = "可投公告"
NOTICE_STAGE_CHANGE = "更正澄清"
NOTICE_STAGE_RESULT = "中标结果"
NOTICE_STAGE_INTEL = "情报参考"
NOTICE_STAGE_INVALID = "无效"
NOTICE_STAGE_OPTIONS = [
    NOTICE_STAGE_BID,
    NOTICE_STAGE_INTEL,
    NOTICE_STAGE_CHANGE,
    NOTICE_STAGE_RESULT,
    NOTICE_STAGE_INVALID,
]

INVALID_NOTICE_TERMS = [
    "终止公告",
    "废标公告",
    "流标公告",
    "失败公告",
    "暂停公告",
    "取消公告",
    "终止采购",
    "采购失败",
    "招标失败",
]

INVALID_PRIMARY_TERMS = ["废标", "流标", "采购终止", "项目终止"]

CHANGE_NOTICE_TERMS = [
    "更正公告",
    "变更公告",
    "澄清公告",
    "答疑公告",
    "补遗公告",
    "延期公告",
    "修改通知",
    "补充公告",
]

RESULT_NOTICE_TERMS = [
    "中选公告",
    "中选结果",
    "中选公示",
    "中选候选人",
    "中标公告",
    "中标结果",
    "中标候选人",
    "成交公告",
    "成交结果",
    "结果公告",
    "结果公示",
    "定标候选人",
    "合同公告",
    "合同公示",
    "交易证明书",
]

INTEL_NOTICE_TERMS = [
    "意向公开",
    "采购意向",
    "需求公示",
    "需求调查",
    "招标计划",
    "采购计划",
    "项目预告",
    "征集公告",
    "征求意见",
    "市场调研",
    "企业机会",
    "需求线索",
    "服务线索",
    "公开平台线索",
]

BID_NOTICE_TERMS = [
    "招标公告",
    "采购公告",
    "公开招标",
    "竞争性磋商",
    "竞争性谈判",
    "询价公告",
    "询比公告",
    "比选公告",
    "磋商公告",
    "投标邀请",
    "资格预审",
]


def item_text(item: dict[str, Any] | Any, fields: list[str]) -> str:
    if isinstance(item, dict):
        values = [item.get(field, "") for field in fields]
    else:
        values = [getattr(item, field, "") for field in fields]
    return " ".join(str(value or "") for value in values)


def classify_notice_stage(item: dict[str, Any] | Any) -> str:
    """Split notices into bid workflow, secondary intelligence, results, and invalid notices."""
    primary_text = re.sub(r"\s+", "", item_text(item, ["announcement_type", "title"]))
    full_text = re.sub(
        r"\s+",
        "",
        item_text(
            item,
            [
                "announcement_type",
                "title",
                "summary",
                "important_info",
                "source_name",
            ],
        ),
    )
    if not full_text:
        return NOTICE_STAGE_INTEL
    if (
        contains_any(primary_text, INVALID_PRIMARY_TERMS)
        or contains_any(primary_text, INVALID_NOTICE_TERMS)
        or contains_any(full_text, INVALID_NOTICE_TERMS)
    ):
        return NOTICE_STAGE_INVALID
    if contains_any(primary_text, CHANGE_NOTICE_TERMS):
        return NOTICE_STAGE_CHANGE
    if contains_any(primary_text, RESULT_NOTICE_TERMS):
        return NOTICE_STAGE_RESULT
    if contains_any(full_text, INTEL_NOTICE_TERMS):
        return NOTICE_STAGE_INTEL
    if contains_any(primary_text, BID_NOTICE_TERMS):
        return NOTICE_STAGE_BID
    return NOTICE_STAGE_INTEL


def annotate_notice_stage(item: dict[str, Any] | Any, preserve_existing: bool = False):
    existing = item.get("notice_stage", "") if isinstance(item, dict) else getattr(item, "notice_stage", "")
    stage = classify_notice_stage(item)
    if preserve_existing and existing in NOTICE_STAGE_OPTIONS and stage not in {
        NOTICE_STAGE_INVALID, NOTICE_STAGE_CHANGE, NOTICE_STAGE_RESULT
    }:
        return item
    if isinstance(item, dict):
        item["notice_stage"] = stage
    else:
        item.notice_stage = stage
    return item


CORE_EXHIBITION_TERMS = [
    "展厅",
    "展馆",
    "展陈",
    "布展",
    "陈列馆",
    "陈列布展",
    "陈列展览",
    "博物馆",
    "规划馆",
    "文化馆",
    "科技馆",
    "纪念馆",
    "展示馆",
    "展示中心",
    "数字展厅",
    "智慧展厅",
    "企业展厅",
    "企业文化展厅",
    "总部展厅",
    "主题馆",
    "品牌馆",
    "党建馆",
    "校史馆",
    "院史馆",
    "厂史馆",
    "多媒体展项",
]

CORE_EXHIBITION_TERMS = list(dict.fromkeys(CORE_EXHIBITION_TERMS + PROFILE_EXHIBITION_VENUE_TERMS))

VENUE_ONLY_TERMS = [
    "博物馆",
    "博物院",
    "文化馆",
    "科技馆",
    "科普馆",
    "纪念馆",
    "陈列馆",
]

VENUE_ONLY_TERMS = list(dict.fromkeys(VENUE_ONLY_TERMS + PUBLIC_CULTURE_TERMS))

DIRECT_TARGET_TERMS = [word for word in CORE_EXHIBITION_TERMS if word not in VENUE_ONLY_TERMS]

HALL_CONTEXT_TERMS = [
    "展览展示",
    "文化展示",
    "成果展示",
    "历史陈列",
    "专题陈列",
    "展示空间",
    "展示体验",
    "展示工程",
]

HALL_CONTEXT_TERMS = list(dict.fromkeys(HALL_CONTEXT_TERMS + PROFILE_EXHIBITION_VENUE_TERMS))

PROJECT_ACTION_TERMS = [
    "设计",
    "施工",
    "建设",
    "装修",
    "改造",
    "提升",
    "升级",
    "更新",
    "深化",
    "一体化",
    "EPC",
    "采购",
    "招标",
    "磋商",
    "中标",
    "成交",
    "服务",
]

PROJECT_ACTION_TERMS = list(dict.fromkeys(PROJECT_ACTION_TERMS + PROJECT_DELIVERY_TERMS))

EXHIBITION_ACTION_TERMS = [
    "展陈",
    "布展",
    "陈列",
    "展览",
    "展品",
    "展项",
    "展柜深化",
    "展厅",
    "数字展厅",
    "多媒体",
    "互动装置",
    "设计施工",
    "设计施工一体化",
    "EPC",
    "深化设计",
]

NON_TARGET_TERMS = [
    "展会服务",
    "会务服务",
    "会展服务",
    "展位",
    "展台",
    "摊位",
    "舞台搭建",
    "广告印刷",
    "宣传片",
    "发布会",
    "推介会",
    "博览会",
    "交易会",
    "展销会",
    "西洽会",
    "文博会",
    "参展",
    "广告制作",
    "广告服务",
    "广告布展",
    "标识标牌",
    "标牌制作",
    "导视牌",
    "办公家具",
    "家具采购",
    "展柜采购",
    "展柜更换",
    "展柜购置",
    "灯具购置",
    "耗材采购",
    "储藏柜",
    "密集柜",
    "安保",
    "保安服务",
    "安防系统",
    "文物预防性保护",
    "馆藏文物预防性保护",
    "馆藏可移动文物",
    "馆藏文物数字化",
    "珍贵文物数字化",
    "文物数字化保护",
    "藏品数字化",
    "藏品管理平台",
    "设备采购",
    "电梯设备",
    "消防系统",
    "消防设施",
    "安防工程",
    "防雷工程",
    "网络建设",
    "信息系统",
    "软件开发",
    "系统开发",
    "智能体开发",
    "图形工作站",
    "标本库房",
    "库房设施",
    "考古钻探",
    "业务交流活动",
    "开放运行服务",
    "公共服务项目",
    "运行保障",
    "硬件采购",
    "耗材采购",
    "资料制作",
    "软件耗材",
]

NON_TARGET_TERMS = list(dict.fromkeys(NON_TARGET_TERMS + PROJECT_DOWNRANK_TERMS))

FATAL_NON_TARGET_TERMS = [
    "资产转让",
    "商业用房",
    "房屋租赁",
    "承租权",
    "场地租赁",
    "活动物料",
    "文化惠民活动",
    "档案著录",
    "多媒体设备",
    "设备项目",
    "物资采购",
    "配套物资",
    "仪器采购",
    "设备更新",
    "运维服务",
    "设备运维",
    "运维及运营",
    "运维运营",
    "运营服务",
    "工程监理",
    "施工监理",
    "监理服务",
    "全过程咨询",
    "造价咨询",
    "审计服务",
    "训练场",
    "探测检测",
    "检测项目",
    "物业服务",
    "物业管理",
    "物业管理服务",
    "保洁服务",
    "餐饮服务",
    "食堂",
    "超市",
    "保险采购",
    "广告印刷",
    "广告制作",
    "广告服务",
    "广告布展",
    "会展服务",
    "会务服务",
    "农博会",
    "产销对接活动",
    "搭建运营",
    "舞台搭建",
    "展馆搭建",
    "展台搭建",
    "展位搭建",
    "展位设计",
    "标识标牌",
    "标牌制作",
    "办公家具",
    "家具采购",
    "安保",
    "安保服务",
    "保安服务",
    "文物预防性保护",
    "馆藏文物预防性保护",
    "馆藏可移动文物",
    "馆藏文物数字化",
    "珍贵文物数字化",
    "文物数字化保护",
    "藏品数字化",
    "藏品管理平台",
    "文物保护修复",
    "文物修复",
    "储藏柜采购",
    "密集柜采购",
    "展柜购置",
    "灯具购置",
    "耗材采购",
    "标本库房",
    "库房设施",
    "消防系统",
    "消防设施",
    "安防工程",
    "防雷工程",
    "网络建设",
    "信息系统",
    "软件开发",
    "系统开发",
    "智能体开发",
    "图形工作站",
    "考古钻探",
    "业务交流活动",
    "开放运行服务",
    "公共服务项目",
    "运行保障",
    "硬件采购",
    "耗材采购",
    "资料制作",
    "软件耗材",
    "市政工程",
    "市政工程中心",
    "市政设施",
    "航标灯",
    "航标维护",
    "道路工程",
    "道路改造",
    "桥梁工程",
    "排水管网",
    "污水管网",
    "雨污水",
    "路灯",
    "交通设施",
]


def is_target_exhibition_text(text: str, check_fatal: bool = True) -> bool:
    text = re.sub(r"\s+", "", text or "")
    if not text:
        return False
    if check_fatal and contains_any(text, FATAL_NON_TARGET_TERMS):
        return False
    has_direct_core = contains_any(text, DIRECT_TARGET_TERMS)
    has_venue_project = contains_pair(text, VENUE_ONLY_TERMS, EXHIBITION_ACTION_TERMS)
    has_core = has_direct_core or has_venue_project
    has_context_project = contains_pair(text, HALL_CONTEXT_TERMS, PROJECT_ACTION_TERMS)
    if not (has_core or has_context_project):
        return False
    has_non_target = contains_any(text, NON_TARGET_TERMS)
    has_hall_anchor = contains_any(
        text,
        [
            "展厅",
            "展馆",
            "展陈",
            "布展",
            "博物馆",
            "规划馆",
            "文化馆",
            "展示馆",
            "展示中心",
            "陈列馆",
            "主题馆",
            "品牌馆",
        ],
    )
    if has_non_target and not has_hall_anchor:
        return False
    return True


def is_target_exhibition_tender(tender: dict[str, Any]) -> bool:
    header_text = " ".join(
        [
            tender.get("title", ""),
            tender.get("announcement_type", ""),
            tender.get("purchaser", ""),
            tender.get("agency", ""),
        ]
    )
    project_text = f"{header_text} {tender.get('summary', '')}"
    fatal_text = f"{header_text} {tender.get('important_info', '')}"
    if contains_any(re.sub(r"\s+", "", fatal_text or ""), FATAL_NON_TARGET_TERMS):
        return False
    return is_target_exhibition_text(project_text, check_fatal=False)


def classify_business_priority(text: str) -> str | None:
    """Classify by Allen's target project types before numeric scoring."""
    text = re.sub(r"\s+", "", text or "")
    renovation_words = ["改造", "翻新", "更新", "提升", "升级", "改陈", "布展", "展陈", "装修", "工程"]
    planning_hall_words = ["规划馆", "城市规划馆", "城乡规划馆", "国土空间规划馆"]
    portfolio_context_words = PROJECT_CONTEXT_TERMS + ["产业园区", "园区", "科技园", "双创中心", "金融科技", "科技金融"]
    portfolio_venue_words = PROFILE_EXHIBITION_VENUE_TERMS + [
        "展厅",
        "展馆",
        "展示中心",
        "科技展厅",
        "银行展厅",
        "酒业展厅",
        "企业展厅",
        "品牌展厅",
    ]
    strategic_context_words = [word for word in portfolio_context_words if word not in ["文旅", "景区"]]

    if is_public_culture_without_target(text):
        if contains_pair(text, PUBLIC_CULTURE_TERMS, EXHIBITION_ACTION_TERMS):
            return "低优先级"
        return None

    low_rules = [
        contains_pair(text, ["大型国企", "央企", "中央企业", "国企", "国有企业"], ["展示馆", "展示中心", "展厅", "企业馆"]),
        contains_pair(text, ["事业单位", "机关", "单位"], ["党建馆", "党建展厅", "党建阵地"]),
        contains_any(text, ["党建馆", "党建展厅", "党建阵地", "党群服务中心", "廉政教育基地"]),
    ]
    if any(low_rules):
        return "低优先级"

    high_rules = [
        contains_any(text, ["企业展厅", "总部展厅", "品牌展厅", "企业文化展厅", "产品展示中心", "客户接待中心"]),
        contains_pair(text, PRIMARY_TARGET_TERMS, ["展厅", "展示中心", "展示馆", "发展馆", "规划馆", "体验中心"]),
        contains_pair(text, strategic_context_words, portfolio_venue_words),
        contains_pair(text, ["人工智能", "机器人", "智能制造", "低空经济", "车联网", "ESG", "低碳"], portfolio_venue_words),
        contains_pair(text, ["产业园区", "产业园", "园区"], planning_hall_words + ["展示馆", "展厅"]),
        contains_pair(text, ["省级", "省域", "省"], planning_hall_words),
        contains_pair(text, ["市级", "市域", "城市"], planning_hall_words),
        contains_pair(text, ["新区", "开发区", "高新区", "经开区"], planning_hall_words),
        contains_pair(text, planning_hall_words, renovation_words),
    ]
    if any(high_rules):
        return "高优先级"

    medium_rules = [
        contains_any(text, ["文旅主题馆", "文化旅游主题馆"]),
        contains_any(text, ["主题馆"]),
        contains_pair(text, ["景区", "旅游区", "度假区", "文旅"], ["展馆", "展示馆", "主题展馆"]),
        contains_pair(text, ["景区", "旅游区", "度假区", "文旅"], ["设计施工", "设计", "施工", "布展", "展陈", "新建"]),
    ]
    if any(medium_rules):
        return "中优先级"

    return None


def classify_enterprise_opportunity(text: str) -> str | None:
    text = re.sub(r"\s+", "", text or "")
    enterprise_context = ["企业展厅", "企业文化展厅", "总部展厅", "企业总部展示中心", "品牌馆", "品牌展厅", "品牌体验中心"]
    hall_words = ["展厅", "展示中心", "体验中心", "企业馆", "品牌馆", "企业文化馆", "数字化展厅", "智慧展厅"]
    build_words = ["建设", "装修", "设计", "施工", "改造", "启用", "开放", "投产", "竣工", "落成"]
    expansion_words = ["总部基地", "全球总部", "中国总部", "研发中心", "产业园", "智能制造基地", "未来工厂", "新基地"]

    if contains_any(text, enterprise_context) or contains_pair(text, hall_words, build_words):
        return "高优先级"
    if contains_pair(text, expansion_words, ["开工", "启用", "投产", "签约", "落成", "客户参观", "参观"]) or contains_any(text, expansion_words):
        return "中优先级"
    return None


def priority_from_score(score: int) -> str:
    if score >= 80:
        return "高优先级"
    if score >= 60:
        return "中优先级"
    if score >= 40:
        return "低优先级"
    return "可能无关"


def score_tender(tender: dict[str, Any], keywords: dict[str, list[str]]) -> dict[str, Any]:
    title = tender.get("title", "")
    tender.update(classify_project_profile(tender))
    tender["notice_stage"] = classify_notice_stage(tender)
    body = " ".join(
        [
            tender.get("summary", ""),
            tender.get("announcement_type", ""),
            tender.get("purchaser", ""),
            tender.get("agency", ""),
        ]
    )
    is_enterprise_source = (
        "企业机会" in tender.get("announcement_type", "")
        or "上市民企" in tender.get("source_name", "")
        or "上市公司展厅招投标" in tender.get("source_name", "")
        or "上市公司展厅招投标" in tender.get("announcement_type", "")
        or "江浙沪上市公司" in tender.get("source_name", "")
        or "江浙沪上市公司" in tender.get("announcement_type", "")
        or "苏州上市公司展厅" in tender.get("source_name", "")
        or "苏州上市公司展厅" in tender.get("announcement_type", "")
    )

    strong_hits = find_keywords(title, keywords.get("strong_keywords", []))
    title_business_hits = find_keywords(title, keywords.get("business_keywords", []))
    body_business_hits = find_keywords(body, keywords.get("business_keywords", []))
    extended_hits = find_keywords(f"{title} {body}", keywords.get("extended_keywords", []))
    enterprise_hall_hits = find_keywords(f"{title} {body}", keywords.get("enterprise_hall_keywords", []))
    enterprise_expansion_hits = find_keywords(f"{title} {body}", keywords.get("enterprise_expansion_keywords", []))
    enterprise_downrank_hits = find_keywords(f"{title} {body}", keywords.get("enterprise_downrank_keywords", []))
    downrank_hits = find_keywords(f"{title} {body}", keywords.get("downrank_keywords", []))
    region_hits = find_keywords(tender.get("region", ""), keywords.get("preferred_regions", []))

    title_score = min(len(strong_hits) * 10, 30)
    business_score = min(len(title_business_hits) * 10 + len(body_business_hits) * 8 + len(extended_hits) * 3, 25)
    enterprise_score = min(len(enterprise_hall_hits) * 12 + len(enterprise_expansion_hits) * 5, 30) if is_enterprise_source else 0
    region_score = 10 if region_hits else 0
    total = (
        title_score
        + business_score
        + enterprise_score
        + budget_score(tender.get("budget", ""))
        + region_score
        + freshness_score(tender.get("publish_date", ""))
        + stage_score(tender.get("announcement_type", ""), title)
    )

    high_intent_pairs = [
        ("企业展厅", "设计"),
        ("总部展厅", "设计"),
        ("品牌展厅", "设计"),
        ("企业文化展厅", "设计"),
        ("产品展示中心", "设计"),
        ("产业展示中心", "设计"),
        ("产业园", "展示中心"),
        ("产业园", "展厅"),
        ("科技城", "展示中心"),
        ("高新区", "展示中心"),
        ("开发区", "展示中心"),
        ("人工智能", "展示中心"),
        ("机器人", "展示中心"),
        ("智能制造", "展示中心"),
        ("低空经济", "展示中心"),
        ("展馆", "布展"),
        ("展馆", "展陈"),
        ("展馆", "设计"),
        ("展馆", "搭建"),
        ("展馆", "装修"),
        ("展馆", "展出"),
        ("展厅", "设计"),
        ("展厅", "搭建"),
        ("展陈", "设计"),
        ("非遗", "展馆"),
        ("深化设计", "展陈"),
    ]
    title_body = f"{title} {body}"
    public_culture_only = is_public_culture_without_target(
        f"{title} {tender.get('purchaser', '')}",
        tender.get("profile_project_type", ""),
    )
    if tender["notice_stage"] == NOTICE_STAGE_INVALID or not is_target_exhibition_tender(tender):
        tender["notice_stage"] = NOTICE_STAGE_INVALID
        tender["matched_keywords"] = []
        tender["relevance_score"] = 0
        tender["priority"] = "可能无关"
        return tender

    if any(left in title_body and right in title_body for left, right in high_intent_pairs):
        total += 25

    if downrank_hits or enterprise_downrank_hits:
        total -= min((len(downrank_hits) + len(enterprise_downrank_hits)) * 8, 24)

    total = max(0, min(int(total), 100))
    matched = sorted(
        set(
            strong_hits
            + title_business_hits
            + body_business_hits
            + extended_hits
            + enterprise_hall_hits
            + enterprise_expansion_hits
            + region_hits
            + downrank_hits
            + enterprise_downrank_hits
        )
    )
    enterprise_priority = classify_enterprise_opportunity(title_body) if is_enterprise_source else None
    business_priority = enterprise_priority or classify_business_priority(title_body)
    if business_priority == "高优先级":
        total = max(total, 85)
    elif business_priority == "中优先级":
        total = min(max(total, 65), 79)
    elif business_priority == "低优先级":
        total = min(max(total, 45), 59)

    if public_culture_only:
        total = min(total, 49)
        business_priority = "低优先级" if total >= 40 else None

    tender["matched_keywords"] = matched
    tender["relevance_score"] = total
    tender["priority"] = business_priority or priority_from_score(total)
    return tender
