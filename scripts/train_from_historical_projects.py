import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_INPUT = ROOT / "data" / "historical_projects.csv"
DEFAULT_OUTPUT = ROOT / "config" / "historical_project_profile.yaml"
DEFAULT_REPORT = ROOT / "docs" / "historical_project_training_report.md"

POSITIVE_LEVELS = {"核心正样本", "次级正样本"}
OBSERVE_LEVELS = {"观察样本"}
NEGATIVE_LEVELS = {"排除样本"}

TERM_GROUPS = {
    "venue_terms": [
        "展厅",
        "展馆",
        "展示中心",
        "展示馆",
        "展示体验中心",
        "体验馆",
        "体验中心",
        "发展馆",
        "规划馆",
        "博物馆",
        "科技馆",
        "科普馆",
        "科普基地",
        "研学基地",
        "陈列馆",
        "文化中心",
        "企业展厅",
        "科技展厅",
        "品牌馆",
        "未来中心",
        "创新中心",
        "服务中心",
    ],
    "context_terms": [
        "产业园",
        "科技产业园",
        "低碳产业",
        "数字经济产业园",
        "硅基产业园",
        "科技城",
        "开发区",
        "高新区",
        "经开区",
        "自贸区",
        "产业社区",
        "高铁新城",
        "基金小镇",
        "科技小镇",
        "创新创业服务中心",
        "企业创新中心",
        "国际创新中心",
        "城市文化中心",
        "港城经济区",
        "新区",
        "新城",
    ],
    "technology_terms": [
        "人工智能",
        "机器人",
        "具身机器人",
        "具身智能",
        "协同机器人",
        "低空经济",
        "车联网",
        "智能制造",
        "智能交通",
        "新基建",
        "数字经济",
        "光子",
        "硅基",
        "ESG",
        "低碳",
        "元宇宙",
        "云计算",
        "新能源",
        "金融科技",
        "知识产权",
    ],
    "client_terms": [
        "银行",
        "金控",
        "基金",
        "集团",
        "上市公司",
        "国企",
        "城投",
        "产投",
        "管委会",
        "轨道交通",
        "交通投资",
        "能源",
        "钢铁",
        "酒业",
    ],
    "delivery_terms": [
        "展陈",
        "布展",
        "陈列",
        "设计施工",
        "设计施工一体化",
        "EPC",
        "工程总承包",
        "改造",
        "升级改造",
        "局部修改",
        "提升",
        "科普展陈",
    ],
    "downrank_terms": [
        "排水",
        "市政",
        "环境整治",
        "广场环境",
        "立面改造",
        "海绵城市",
        "活动",
        "会展活动",
        "练习题",
        "内部资料",
        "物业",
        "安防",
        "监理",
        "设备采购",
        "广告",
        "标识标牌",
    ],
}

PUBLIC_CULTURE_SEARCH_EXCLUDE = {
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
    "档案馆",
    "文化中心",
    "活动中心",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Project Profile Radar profile from Allen's historical project samples.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def row_text(row: dict[str, str]) -> str:
    fields = [
        "project_name",
        "client_type",
        "project_type",
        "industry_theme",
        "stage",
        "reason",
        "notes",
    ]
    return "".join(str(row.get(field) or "") for field in fields)


def row_level(row: dict[str, str]) -> str:
    return (row.get("fit_level") or "").strip()


def extract_terms(rows: list[dict[str, str]], group: str, levels: set[str]) -> Counter[str]:
    counter: Counter[str] = Counter()
    candidates = TERM_GROUPS[group]
    for row in rows:
        if row_level(row) not in levels:
            continue
        text = row_text(row)
        counter.update(term for term in candidates if term in text)
    return counter


def count_field(rows: list[dict[str, str]], field: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        value = (row.get(field) or "").strip()
        if value:
            counter[value] += 1
    return counter


def terms_from_counter(counter: Counter[str], min_count: int = 1) -> list[str]:
    return [term for term, count in counter.most_common() if count >= min_count]


def build_profile(rows: list[dict[str, str]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if row_level(row) in POSITIVE_LEVELS]
    observe_rows = [row for row in rows if row_level(row) in OBSERVE_LEVELS]
    negative_rows = [row for row in rows if row_level(row) in NEGATIVE_LEVELS]

    venue_terms = terms_from_counter(extract_terms(rows, "venue_terms", POSITIVE_LEVELS))
    context_terms = terms_from_counter(extract_terms(rows, "context_terms", POSITIVE_LEVELS))
    technology_terms = terms_from_counter(extract_terms(rows, "technology_terms", POSITIVE_LEVELS))
    client_terms = terms_from_counter(extract_terms(rows, "client_terms", POSITIVE_LEVELS))
    delivery_terms = terms_from_counter(extract_terms(rows, "delivery_terms", POSITIVE_LEVELS))
    downrank_terms = terms_from_counter(extract_terms(rows, "downrank_terms", NEGATIVE_LEVELS | OBSERVE_LEVELS))

    search_terms = []
    for group_terms in [venue_terms, context_terms, technology_terms, client_terms]:
        search_terms.extend(group_terms[:20])
    search_terms = [term for term in dict.fromkeys(search_terms) if term not in PUBLIC_CULTURE_SEARCH_EXCLUDE]

    return {
        "generated_from": str(DEFAULT_INPUT.relative_to(ROOT)),
        "sample_count": len(rows),
        "positive_sample_count": len(positive_rows),
        "observe_sample_count": len(observe_rows),
        "negative_sample_count": len(negative_rows),
        "search_terms": search_terms,
        "venue_terms": venue_terms,
        "context_terms": context_terms,
        "technology_terms": technology_terms,
        "client_terms": client_terms,
        "delivery_terms": delivery_terms,
        "downrank_terms": downrank_terms,
        "project_type_counts": dict(count_field(rows, "project_type").most_common()),
        "client_type_counts": dict(count_field(rows, "client_type").most_common()),
        "stage_counts": dict(count_field(rows, "stage").most_common()),
        "reason_counts": dict(count_field(rows, "reason").most_common()),
        "result_counts": dict(count_field(rows, "result").most_common()),
    }


def markdown_table(counter_map: dict[str, int], limit: int = 12) -> str:
    lines = ["| 项 | 数量 |", "|---|---:|"]
    for key, value in list(counter_map.items())[:limit]:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def build_report(profile: dict[str, Any]) -> str:
    return f"""# 历史项目样本训练报告

样本来源：`{profile['generated_from']}`

- 样本总数：{profile['sample_count']}
- 核心/次级正样本：{profile['positive_sample_count']}
- 观察样本：{profile['observe_sample_count']}
- 排除样本：{profile['negative_sample_count']}

## 项目类型分布

{markdown_table(profile['project_type_counts'])}

## 客户类型分布

{markdown_table(profile['client_type_counts'])}

## 阶段分布

{markdown_table(profile['stage_counts'])}

## 未推进原因分布

{markdown_table(profile['reason_counts'])}

## 已反向训练的搜索词

{', '.join(profile['search_terms'])}

## 已反向训练的降噪词

{', '.join(profile['downrank_terms'])}
"""


def main() -> None:
    args = parse_args()
    rows = load_rows(args.input)
    profile = build_profile(rows)
    profile["generated_from"] = str(args.input.relative_to(ROOT) if args.input.is_absolute() else args.input)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(build_report(profile), encoding="utf-8")

    print(f"trained {profile['sample_count']} samples")
    print(f"profile: {args.output}")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
