"""Project-type profile learned from Allen's recent exhibition/design portfolio."""

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_PROFILE_PATH = ROOT / "config" / "historical_project_profile.yaml"

BASE_EXHIBITION_TERMS = [
    "展厅",
    "展馆",
    "展陈",
    "布展",
    "展示中心",
    "数字展厅",
    "企业展厅",
    "品牌展厅",
    "科技展厅",
    "规划馆",
    "主题馆",
]

PUBLIC_CULTURE_PROFILE_TYPE = "公共文化展陈"

PUBLIC_CULTURE_TERMS = [
    "博物馆",
    "博物院",
    "文物",
    "遗址",
    "文化馆",
    "科技馆",
    "科普馆",
    "纪念馆",
    "陈列馆",
    "研学基地",
    "科普基地",
    "校史馆",
    "院史馆",
    "校史展厅",
    "院史展厅",
    "史志馆",
    "档案馆",
    "烈士纪念",
    "廉洁教育",
    "艺术馆",
    "校园文化",
    "民族共同体",
    "自然遗产",
    "古生物",
    "化石标本",
    "活动中心",
    "党群服务中心",
]

PUBLIC_CULTURE_SEARCH_TERMS = [
    "博物馆",
    "博物院",
    "文化馆",
    "科技馆",
    "科普馆",
    "纪念馆",
    "陈列馆",
    "研学基地",
    "科普基地",
    "校史馆",
    "院史馆",
    "校史展厅",
    "院史展厅",
    "档案馆",
    "文化中心",
    "活动中心",
]

PRIMARY_TARGET_TERMS = [
    "企业展厅",
    "企业馆",
    "总部展厅",
    "总部展示中心",
    "企业总部展示中心",
    "企业文化展厅",
    "品牌馆",
    "品牌展厅",
    "品牌体验中心",
    "产品展示中心",
    "客户接待中心",
    "产业展示中心",
    "产业展厅",
    "产业馆",
    "产业博览馆",
    "产业园",
    "科技产业园",
    "低碳产业园",
    "硅基产业园",
    "产业社区",
    "科技城",
    "开发区",
    "高新区",
    "经开区",
    "自贸区",
    "园区",
    "科技展厅",
    "创新馆",
    "人工智能",
    "机器人",
    "智能制造",
    "低空经济",
    "车联网",
    "数字经济",
    "新能源",
    "云计算",
    "具身机器人",
    "银行展厅",
    "金融科技",
    "酒业展厅",
    "智能制造展示中心",
    "人工智能展厅",
    "机器人展厅",
    "低空经济展厅",
    "车联网展示中心",
]

PROJECT_VENUE_TERMS = [
    "发展馆",
    "展示馆",
    "展示体验中心",
    "体验中心",
    "未来中心",
    "创新中心",
    "国际创新中心",
    "创新创业服务中心",
    "产业服务中心",
    "企业服务中心",
    "文化交流中心",
    "科普展陈",
    "科普基地",
    "研学基地",
    "产业博览馆",
    "产业馆",
    "企业馆",
    "产品展示中心",
    "客户接待中心",
]

PROJECT_CONTEXT_TERMS = [
    "产业园",
    "科技产业园",
    "低碳产业园",
    "硅基产业园",
    "科技城",
    "开发区",
    "高新区",
    "经开区",
    "自贸区",
    "产业社区",
    "高铁新城",
    "低空经济",
    "人工智能",
    "机器人",
    "智能制造",
    "智能交通",
    "车联网",
    "ESG",
    "银行",
    "酒业",
    "康养",
    "血液学",
    "文旅",
    "景区",
]

PROJECT_DELIVERY_TERMS = [
    "设计施工",
    "设计施工一体化",
    "EPC",
    "工程总承包",
    "策展",
    "展陈设计",
    "展陈施工",
    "布展设计",
    "陈列布展",
    "深化设计",
    "多媒体",
    "互动装置",
    "展项",
    "数字化",
    "改造",
    "升级改造",
    "提升改造",
    "局部修改",
    "建设",
    "装修",
]

HIGH_INTENT_SEARCH_TERMS = [
    "企业展厅",
    "总部展厅",
    "品牌展厅",
    "企业文化展厅",
    "产品展示中心",
    "客户接待中心",
    "产业展示中心",
    "产业展厅",
    "产业馆",
    "产业博览馆",
    "科技展厅",
    "智能制造展示中心",
    "人工智能展厅",
    "机器人展厅",
    "低空经济展厅",
    "车联网展示中心",
    "银行展厅",
    "酒业展厅",
    "数字展厅",
    "智慧展厅",
    "展示体验中心",
    "展厅设计",
    "展厅装修",
    "展厅建设",
    "展陈设计",
    "展陈施工",
    "布展设计",
    "布展施工",
    "设计施工一体化",
]

PROJECT_SEARCH_TERMS = [
    "产业园",
    "科技城",
    "开发区",
    "高新区",
    "经开区",
    "自贸区",
    "创新中心",
    "未来中心",
    "体验中心",
    "人工智能",
    "机器人",
    "智能制造",
    "低空经济",
    "车联网",
    "银行展厅",
    "酒业展厅",
    "展示中心",
    "展厅",
    "发展馆",
    "规划馆",
]


def dedupe_terms(terms: list[str]) -> list[str]:
    return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))


def remove_public_culture_search_terms(terms: list[str]) -> list[str]:
    blocked = set(PUBLIC_CULTURE_SEARCH_TERMS)
    return [term for term in dedupe_terms(terms) if term not in blocked]


def load_historical_profile(path: Path = HISTORICAL_PROFILE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


HISTORICAL_PROFILE = load_historical_profile()
BASE_EXHIBITION_TERMS = dedupe_terms(BASE_EXHIBITION_TERMS + HISTORICAL_PROFILE.get("venue_terms", []))
PROJECT_VENUE_TERMS = dedupe_terms(PROJECT_VENUE_TERMS + HISTORICAL_PROFILE.get("venue_terms", []))
PROJECT_CONTEXT_TERMS = dedupe_terms(
    PROJECT_CONTEXT_TERMS
    + HISTORICAL_PROFILE.get("context_terms", [])
    + HISTORICAL_PROFILE.get("technology_terms", [])
)
PROJECT_CLIENT_TERMS = dedupe_terms(HISTORICAL_PROFILE.get("client_terms", []))
PROJECT_DELIVERY_TERMS = dedupe_terms(PROJECT_DELIVERY_TERMS + HISTORICAL_PROFILE.get("delivery_terms", []))
PRIMARY_TARGET_CONTEXT_EXCLUDE = {"文旅", "景区", "康养", "血液学"}
PRIMARY_TARGET_TERMS = dedupe_terms(
    PRIMARY_TARGET_TERMS
    + [term for term in PROJECT_CONTEXT_TERMS if term not in PRIMARY_TARGET_CONTEXT_EXCLUDE]
)
PROJECT_SEARCH_TERMS = remove_public_culture_search_terms(
    HIGH_INTENT_SEARCH_TERMS + PROJECT_SEARCH_TERMS + HISTORICAL_PROFILE.get("search_terms", [])
)
PROJECT_DOWNRANK_TERMS = dedupe_terms(HISTORICAL_PROFILE.get("downrank_terms", []))


def compact_text(item: dict[str, Any]) -> str:
    fields = [
        "title",
        "summary",
        "important_info",
        "announcement_type",
        "purchaser",
        "agency",
        "region",
        "source_name",
    ]
    return " ".join(str(item.get(field, "") or "") for field in fields)


def client_text(item: dict[str, Any]) -> str:
    purchaser = str(item.get("purchaser", "") or "").strip()
    if purchaser:
        return " ".join([purchaser, str(item.get("title", "") or ""), str(item.get("source_name", "") or "")])
    fields = ["title", "summary", "important_info", "source_name"]
    return " ".join(str(item.get(field, "") or "") for field in fields)


def first_hit(text: str, words: list[str]) -> str:
    return next((word for word in words if word and word in text), "")


def has_public_culture_signal(text: str) -> bool:
    return first_hit(text, PUBLIC_CULTURE_TERMS) != ""


def has_target_business_signal(text: str) -> bool:
    normalized = "".join(str(text or "").split())
    if first_hit(normalized, PRIMARY_TARGET_TERMS):
        return True
    target_pairs = [
        (["企业", "总部", "品牌", "产品", "客户", "股份有限公司", "有限公司", "集团"], ["展厅", "展示中心", "体验中心", "企业馆", "品牌馆"]),
        (["产业", "园区", "科技城", "开发区", "高新区", "经开区", "自贸区"], ["展厅", "展示中心", "展示馆", "发展馆", "规划馆"]),
        (["人工智能", "机器人", "智能制造", "低空经济", "车联网", "数字经济"], ["展厅", "展示中心", "体验中心", "展馆"]),
        (["银行", "金融", "酒业"], ["展厅", "展示中心", "体验中心", "展馆"]),
    ]
    return any(any(left in normalized for left in left_words) and any(right in normalized for right in right_words) for left_words, right_words in target_pairs)


def is_public_culture_without_target(text: str, project_type: str = "") -> bool:
    normalized = "".join(str(text or "").split())
    public_hit = project_type == PUBLIC_CULTURE_PROFILE_TYPE or has_public_culture_signal(normalized)
    return public_hit and not has_target_business_signal(normalized)


def infer_profile_project_type(text: str) -> tuple[str, str]:
    rules = [
        (
            "企业品牌展厅",
            ["企业展厅", "企业馆", "品牌展厅", "品牌馆", "总部展厅", "企业文化展厅", "产品展示中心", "客户接待中心", "展示体验中心"],
            "企业/品牌展示空间",
        ),
        (
            "金融科技展厅",
            ["银行展厅", "银行", "金融科技", "金控", "基金", "保险", "证券"],
            "金融机构或金融科技场景",
        ),
        (
            "园区产业展示",
            ["产业展示中心", "产业展厅", "产业馆", "产业博览馆", "产业园", "科技产业园", "低碳产业园", "硅基产业园", "产业社区", "科技城", "开发区", "高新区", "经开区", "自贸区", "园区"],
            "园区/开发区产业展示",
        ),
        (
            "科技主题展厅",
            ["科技展厅", "创新馆", "人工智能", "机器人", "智能制造", "低空经济", "车联网", "数字经济", "新能源", "云计算", "具身机器人"],
            "科技产业主题",
        ),
        (
            "规划馆/发展馆",
            ["规划馆", "发展馆", "城市规划馆", "国土空间规划馆"],
            "规划发展展示载体",
        ),
        (
            PUBLIC_CULTURE_PROFILE_TYPE,
            PUBLIC_CULTURE_TERMS,
            "公共文化/科普展陈",
        ),
        (
            "文旅主题空间",
            ["文旅", "景区", "游客中心", "旅游", "非遗", "酒业", "文化交流中心"],
            "文旅或主题体验空间",
        ),
        (
            "城市更新/展示中心",
            ["城市之窗", "城市展厅", "城市展示", "展示中心", "城市更新", "提升改造", "升级改造", "局部修改"],
            "城市展示或改造提升",
        ),
    ]
    for project_type, words, reason in rules:
        hit = first_hit(text, words)
        if hit:
            return project_type, f"{reason}：命中“{hit}”"
    return "未知项目", "未命中明确历史项目类型"


def infer_profile_client_type(text: str) -> tuple[str, str]:
    rules = [
        (
            "银行/金融机构",
            ["银行", "金控", "基金", "证券", "保险", "农商行", "农信", "金融"],
            "金融采购主体",
        ),
        (
            "平台公司/城投产投",
            ["城投", "产投", "文旅集团", "交通投资", "建设投资", "城市建设", "开发建设", "产业投资"],
            "平台公司/城投产投主体",
        ),
        (
            "政府/管委会",
            ["人民政府", "管委会", "管理委员会", "商务局", "发改委", "文旅局", "宣传部", "政务服务", "机关事务"],
            "政府或园区管委会主体",
        ),
        (
            "事业单位/公共文化",
            ["博物馆", "文化馆", "科技馆", "学校", "学院", "大学", "医院", "研究院", "事业单位"],
            "事业单位或公共文化主体",
        ),
        (
            "国企/集团",
            ["国有", "国企", "集团有限公司", "控股集团", "发展集团", "投资集团"],
            "国企/集团主体",
        ),
        (
            "上市公司/民企",
            ["股份有限公司", "科技股份", "上市公司", "民营"],
            "企业采购主体",
        ),
        (
            "文旅/商业运营",
            ["景区", "旅游", "文旅", "商业", "酒店", "运营管理"],
            "文旅或商业运营主体",
        ),
    ]
    for client_type, words, reason in rules:
        hit = first_hit(text, words)
        if hit:
            return client_type, f"{reason}：命中“{hit}”"
    return "未知", "未命中明确客户类型"


def classify_project_profile(item: dict[str, Any]) -> dict[str, str]:
    normalized = "".join(compact_text(item).split())
    normalized_client = "".join(client_text(item).split())
    project_type, project_reason = infer_profile_project_type(normalized)
    client_type, client_reason = infer_profile_client_type(normalized_client)
    reason_parts = [project_reason, client_reason]
    downrank_hit = first_hit(normalized, PROJECT_DOWNRANK_TERMS)
    if downrank_hit:
        reason_parts.append(f"历史降噪词：命中“{downrank_hit}”")
    return {
        "profile_project_type": project_type,
        "profile_client_type": client_type,
        "profile_reason": "；".join(part for part in reason_parts if part),
    }


def expand_project_query_terms(query: str = "", extra_terms: list[str] | None = None, limit: int | None = None) -> list[str]:
    query = (query or "").strip()
    terms = [query] if query else []
    if query in {"展厅", "展馆", "展陈", "布展", "展示"} or any(word in query for word in ["展", "馆"]):
        terms.extend(remove_public_culture_search_terms(BASE_EXHIBITION_TERMS))
    if any(word in query for word in ["产业园", "科技城", "开发区", "高新区", "经开区"]):
        terms.extend(["产业园", "科技产业园", "展示中心", "发展馆", "规划馆", "创新中心"])
    if any(word in query for word in ["人工智能", "机器人", "智能制造", "低空经济", "车联网"]):
        terms.extend(["人工智能", "机器人", "智能制造", "低空经济", "车联网", "展示中心", "体验中心"])
    terms.extend(extra_terms or [])
    terms.extend(PROJECT_SEARCH_TERMS)
    terms = dedupe_terms(terms)
    return terms[:limit] if limit else terms
