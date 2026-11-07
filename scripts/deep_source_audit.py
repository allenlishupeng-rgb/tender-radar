import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import EXPORT_DIR, KEYWORDS_PATH, SOURCES_PATH, USER_AGENT
from crawlers.registry import CRAWLER_REGISTRY
from crawlers.runner import load_yaml
from parsers.common import clean_text
from parsers.extractors import normalize_publish_date
from scoring.rules import classify_notice_stage, is_target_exhibition_tender


GENERAL_QUERY = "项目"
RELEVANCE_QUERY = "展厅"
AUDIT_DAYS = 90
MAX_DETAIL_CHECKS = 3

GENERIC_TITLES = {
    "招标公告",
    "采购公告",
    "招标公告适用于公开招标",
    "招标公告（适用于公开招标）",
    "竞争性磋商公告",
    "中标公告",
    "结果公告",
}

OFFICIAL_HINTS = [
    "政府采购",
    "公共资源",
    "交易平台",
    "交易中心",
    "交易网",
    "公共服务平台",
]


def short_text(value: str, limit: int = 180) -> str:
    return clean_text(str(value or "")).replace("|", " ")[:limit]


def trim_source_config(source: dict) -> dict:
    config = deepcopy(source)
    config["max_pages"] = min(int(config.get("max_pages", 1) or 1), 2)
    config["max_items"] = min(int(config.get("max_items", 12) or 12), 12)
    if isinstance(config.get("target_regions"), list) and len(config["target_regions"]) > 3:
        config["target_regions"] = config["target_regions"][:3]
    if source.get("crawler") == "enterprise_tender":
        config["max_items"] = min(int(config.get("max_items", 20) or 20), 20)
    return config


def tender_to_dict(tender) -> dict:
    if is_dataclass(tender):
        return asdict(tender)
    return dict(tender)


def probe_url(session: requests.Session, url: str) -> dict:
    if not url:
        return {"ok": False, "status": "", "final_url": "", "message": "未配置 URL"}
    try:
        response = session.get(url, timeout=15, allow_redirects=True)
        return {
            "ok": 200 <= response.status_code < 400,
            "status": response.status_code,
            "final_url": response.url,
            "message": "",
            "content_length": len(response.text or ""),
        }
    except Exception as exc:
        return {"ok": False, "status": "", "final_url": "", "message": short_text(str(exc), 220), "content_length": 0}


def robots_status(session: requests.Session, base_url: str) -> dict:
    parsed = urlparse(base_url or "")
    if not parsed.scheme or not parsed.netloc:
        return {"status": "unknown", "can_fetch_base": None, "message": "base_url 无法解析"}
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = session.get(robots_url, timeout=10, allow_redirects=True)
        if response.status_code >= 400:
            return {"status": response.status_code, "can_fetch_base": True, "message": "robots.txt 不可用，按可访问处理"}
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return {
            "status": response.status_code,
            "can_fetch_base": parser.can_fetch(USER_AGENT, base_url),
            "message": "",
        }
    except Exception as exc:
        return {"status": "error", "can_fetch_base": True, "message": short_text(str(exc), 160)}


def run_crawler(source: dict, keywords: dict, query: str, days: int) -> tuple[list[dict], str]:
    crawler_cls = CRAWLER_REGISTRY.get(source.get("crawler"))
    if not crawler_cls:
        return [], "未找到 crawler adapter"
    try:
        crawler = crawler_cls(keywords, source_config=trim_source_config(source), request_interval=0)
        lookback = max(days, int(source.get("lookback_days", days) or days))
        tenders = crawler.search(query=query, days=lookback)
        return [tender_to_dict(item) for item in tenders], crawler.last_error or ""
    except Exception as exc:
        return [], short_text(str(exc), 220)


def is_generic_title(title: str) -> bool:
    normalized = re.sub(r"[\s:：,，;；。.!！?？\"'“”‘’()\[\]{}（）【】《》<>/_-]+", "", title or "")
    return not normalized or len(normalized) <= 6 or normalized in GENERIC_TITLES


def analyze_rows(rows: list[dict], source_name: str) -> dict:
    total = len(rows)
    if not total:
        return {
            "count": 0,
            "field_completeness": 0,
            "required_completeness": 0,
            "business_completeness": 0,
            "valid_publish_rate": 0,
            "target_relevance_rate": 0,
            "generic_title_rate": 0,
            "duplicate_url_count": 0,
            "stage_counts": {},
            "samples": [],
        }

    required_fields = ["title", "source_url", "publish_date", "announcement_type", "source_name"]
    business_fields = ["budget", "bid_deadline", "contact_phone", "purchaser", "agency"]
    required_hits = 0
    business_hits = 0
    valid_dates = 0
    target_hits = 0
    generic_titles = 0
    urls = []
    stage_counter: Counter[str] = Counter()
    samples = []

    for row in rows:
        row["source_name"] = row.get("source_name") or source_name
        required_hits += sum(1 for field in required_fields if row.get(field) not in {None, ""})
        business_hits += sum(1 for field in business_fields if row.get(field) not in {None, ""})
        if normalize_publish_date(row.get("publish_date", "")):
            valid_dates += 1
        if is_target_exhibition_tender(row):
            target_hits += 1
        if is_generic_title(row.get("title", "")):
            generic_titles += 1
        if row.get("source_url"):
            urls.append(row["source_url"])
        stage_counter[classify_notice_stage(row)] += 1
        if len(samples) < 5:
            samples.append(
                {
                    "title": row.get("title", ""),
                    "publish_date": row.get("publish_date", ""),
                    "notice_stage": classify_notice_stage(row),
                    "source_url": row.get("source_url", ""),
                    "budget": row.get("budget", ""),
                    "deadline": row.get("bid_deadline", ""),
                }
            )

    duplicate_url_count = len(urls) - len(set(urls))
    return {
        "count": total,
        "field_completeness": round((required_hits + business_hits) / (total * (len(required_fields) + len(business_fields))) * 100, 1),
        "required_completeness": round(required_hits / (total * len(required_fields)) * 100, 1),
        "business_completeness": round(business_hits / (total * len(business_fields)) * 100, 1),
        "valid_publish_rate": round(valid_dates / total * 100, 1),
        "target_relevance_rate": round(target_hits / total * 100, 1),
        "generic_title_rate": round(generic_titles / total * 100, 1),
        "duplicate_url_count": duplicate_url_count,
        "stage_counts": dict(stage_counter),
        "samples": samples,
    }


def detail_checks(session: requests.Session, rows: list[dict]) -> list[dict]:
    checks = []
    seen = set()
    for row in rows:
        url = row.get("source_url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        probe = probe_url(session, url)
        title = clean_text(row.get("title", ""))
        title_key = re.sub(r"\s+", "", title)[:12]
        title_hit = None
        if probe["ok"] and probe.get("content_length", 0) > 0 and title_key:
            try:
                response = session.get(url, timeout=15, allow_redirects=True)
                title_hit = title_key in re.sub(r"\s+", "", response.text or "")
            except Exception:
                title_hit = None
        checks.append(
            {
                "title": title[:80],
                "url": url,
                "ok": probe["ok"],
                "status": probe["status"],
                "title_hit": title_hit,
                "message": probe["message"],
            }
        )
        if len(checks) >= MAX_DETAIL_CHECKS:
            break
    return checks


def source_type(source: dict) -> str:
    name = source.get("name", "")
    if source.get("crawler") == "enterprise_tender":
        return "混合企业/第三方线索"
    if any(hint in name for hint in OFFICIAL_HINTS):
        return "官方公共资源/政府采购"
    return "官方区域平台"


def score_source(base: dict, robots: dict, general: dict, relevant: dict, details: list[dict], source: dict) -> dict:
    detail_ok_rate = 0
    if details:
        detail_ok_rate = sum(1 for item in details if item["ok"]) / len(details) * 100
    base_score = 20 if base.get("ok") else 0
    robots_score = 8 if robots.get("can_fetch_base") is not False else 0
    crawl_score = 20 if general["count"] > 0 else 0
    detail_score = min(15, detail_ok_rate * 0.15)
    required_score = min(17, general["required_completeness"] * 0.17)
    date_score = min(10, general["valid_publish_rate"] * 0.10)
    title_penalty = min(10, general["generic_title_rate"] * 0.10)
    duplicate_penalty = min(5, general["duplicate_url_count"])
    relevant_score = 10 if relevant["count"] > 0 else 3
    official_score = 5 if source_type(source) != "混合企业/第三方线索" else 2

    reliability = base_score + robots_score + crawl_score + detail_score + required_score + date_score + relevant_score + official_score
    accuracy = (
        general["required_completeness"] * 0.25
        + general["valid_publish_rate"] * 0.20
        + detail_ok_rate * 0.20
        + (100 - general["generic_title_rate"]) * 0.15
        + general["business_completeness"] * 0.15
        + (100 if general["duplicate_url_count"] == 0 else 70) * 0.05
    )
    reliability = max(0, min(100, reliability - title_penalty - duplicate_penalty))
    accuracy = max(0, min(100, accuracy))

    if reliability >= 85 and accuracy >= 85:
        grade = "A"
    elif reliability >= 70 and accuracy >= 70:
        grade = "B"
    elif reliability >= 55 and accuracy >= 55:
        grade = "C"
    else:
        grade = "D"

    risks = []
    if not base.get("ok"):
        risks.append("官网不可达")
    if robots.get("can_fetch_base") is False:
        risks.append("robots 限制")
    if general["count"] == 0:
        risks.append("通用抽样无结果")
    if relevant["count"] == 0:
        risks.append("展厅关键词抽样无结果")
    if detail_ok_rate < 80:
        risks.append("详情链接通过率偏低")
    if general["valid_publish_rate"] < 90:
        risks.append("发布时间解析不稳定")
    if general["generic_title_rate"] >= 20:
        risks.append("标题解析存在泛化")
    if general["business_completeness"] < 40:
        risks.append("预算/截止/联系人等业务字段不完整")
    if source_type(source) == "混合企业/第三方线索":
        risks.append("含企业官网/第三方镜像，需人工确认原始出处")

    risk_level = "低"
    if len(risks) >= 3 or grade in {"C", "D"}:
        risk_level = "高" if grade == "D" else "中"
    elif risks:
        risk_level = "中"

    return {
        "reliability_score": round(reliability, 1),
        "accuracy_score": round(accuracy, 1),
        "grade": grade,
        "risk_level": risk_level,
        "detail_ok_rate": round(detail_ok_rate, 1),
        "risks": risks,
    }


def audit_source(source: dict, keywords: dict) -> dict:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": USER_AGENT})
    base = probe_url(session, source.get("base_url", ""))
    robots = robots_status(session, source.get("base_url", ""))
    general_rows, general_error = run_crawler(source, keywords, source.get("health_query") or GENERAL_QUERY, AUDIT_DAYS)
    relevant_rows, relevant_error = run_crawler(source, keywords, RELEVANCE_QUERY, AUDIT_DAYS)
    general = analyze_rows(general_rows, source.get("name", ""))
    relevant = analyze_rows(relevant_rows, source.get("name", ""))
    details = detail_checks(session, relevant_rows or general_rows)
    score = score_source(base, robots, general, relevant, details, source)

    return {
        "source": source.get("name", ""),
        "enabled": bool(source.get("enabled", True)),
        "default_selected": bool(source.get("default_selected", False)),
        "crawler": source.get("crawler", ""),
        "base_url": source.get("base_url", ""),
        "source_type": source_type(source),
        "base": base,
        "robots": robots,
        "general_query": source.get("health_query") or GENERAL_QUERY,
        "relevance_query": RELEVANCE_QUERY,
        "general_error": general_error,
        "relevant_error": relevant_error,
        "general": general,
        "relevant": relevant,
        "detail_checks": details,
        **score,
        "recommendation": recommendation(score, general, relevant, source),
    }


def recommendation(score: dict, general: dict, relevant: dict, source: dict) -> str:
    if source.get("crawler") == "enterprise_tender":
        return "保留为情报源，但在 UI 中持续标注为需人工复核；优先确认原始企业官网。"
    if general["count"] == 0:
        return "暂不作为主源；保留监控，后续需要核验接口参数或分类入口。"
    if relevant["count"] == 0:
        return "保留为覆盖源，但不要提高权重；展厅关键词需扩大或改用分类检索。"
    if general["business_completeness"] < 40:
        return "技术可用但字段不完整；不作为自动决策唯一依据，优先补详情页解析预算、截止时间、联系人。"
    if score["grade"] == "A":
        return "可作为稳定主源，继续保留；建议定期抽样核验字段。"
    return "可用但需复核；建议连续多天监测稳定性后再提升权重。"


def render_markdown(output: dict) -> str:
    lines = [
        "# 数据源深度可靠性审计",
        "",
        f"- 审计时间：{output['checked_at']}",
        f"- 通用抽样：最近 {output['audit_days']} 天，关键词 `{GENERAL_QUERY}` 或来源自定义 health_query",
        f"- 业务抽样：最近 {output['audit_days']} 天，关键词 `{RELEVANCE_QUERY}`",
        f"- 启用数据源：{len(output['sources'])} 个",
        "",
        "## 总览",
        "",
        "| 等级 | 来源 | 类型 | 可靠性 | 准确性 | 风险 | 通用样本 | 展厅样本 | 必填完整 | 业务字段 | 详情通过 | 主要建议 |",
        "|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in output["sources"]:
        lines.append(
            "| {grade} | {source} | {source_type} | {rel} | {acc} | {risk} | {gc} | {rc} | {req}% | {biz}% | {detail}% | {rec} |".format(
                grade=item["grade"],
                source=item["source"],
                source_type=item["source_type"],
                rel=item["reliability_score"],
                acc=item["accuracy_score"],
                risk=item["risk_level"],
                gc=item["general"]["count"],
                rc=item["relevant"]["count"],
                req=item["general"]["required_completeness"],
                biz=item["general"]["business_completeness"],
                detail=item["detail_ok_rate"],
                rec=item["recommendation"],
            )
        )

    lines.extend(["", "## 风险清单", ""])
    for item in output["sources"]:
        if not item["risks"]:
            continue
        lines.append(f"### {item['source']}")
        for risk in item["risks"]:
            lines.append(f"- {risk}")
        if item.get("general_error"):
            lines.append(f"- 抓取提示：{short_text(item['general_error'])}")
        if item.get("relevant_error") and item["relevant_error"] != item.get("general_error"):
            lines.append(f"- 业务抽样提示：{short_text(item['relevant_error'])}")
        lines.append(f"- 建议：{item['recommendation']}")
        lines.append("")

    lines.extend(["", "## 抽样详情", ""])
    for item in output["sources"]:
        lines.append(f"### {item['source']}")
        lines.append(
            f"- 官网：{item['base_url']}；官网状态：{item['base'].get('status')}；robots：{item['robots'].get('status')}；can_fetch={item['robots'].get('can_fetch_base')}"
        )
        lines.append(f"- 公告阶段分布：{json.dumps(item['general']['stage_counts'], ensure_ascii=False)}")
        if item["detail_checks"]:
            lines.append("- 详情链接抽样：")
            for check in item["detail_checks"]:
                title_hit = "标题命中" if check["title_hit"] is True else ("标题未确认" if check["title_hit"] is False else "标题未核验")
                lines.append(f"  - {'OK' if check['ok'] else 'FAIL'} HTTP {check['status']} {title_hit} [{check['title']}]({check['url']})")
        else:
            lines.append("- 详情链接抽样：无")
        if item["relevant"]["samples"]:
            lines.append("- 展厅关键词样本：")
            for sample in item["relevant"]["samples"][:3]:
                lines.append(
                    f"  - {sample.get('publish_date') or '-'} `{sample.get('notice_stage') or '-'}` [{short_text(sample.get('title'), 90)}]({sample.get('source_url')})"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    keywords = load_yaml(KEYWORDS_PATH)
    sources = [
        source
        for source in load_yaml(SOURCES_PATH).get("sources", [])
        if source.get("enabled", True) and source.get("crawler") != "example_public_page"
    ]
    reports = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_map = {executor.submit(audit_source, source, keywords): source for source in sources}
        for future in as_completed(future_map):
            reports.append(future.result())
    reports.sort(key=lambda item: (-item["reliability_score"], -item["accuracy_score"], item["source"]))

    output = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "audit_days": AUDIT_DAYS,
        "sources": reports,
    }
    out_dir = EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    json_path = out_dir / f"deep_source_audit_{stamp}.json"
    md_path = out_dir / f"deep_source_audit_{stamp}.md"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(output), encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    grade_counts = Counter(item["grade"] for item in reports)
    print("Grades:", " ".join(f"{grade}={count}" for grade, count in sorted(grade_counts.items())))
    for item in reports:
        print(
            f"{item['grade']} | {item['source']} | reliability={item['reliability_score']} | accuracy={item['accuracy_score']} | risk={item['risk_level']} | samples={item['general']['count']}/{item['relevant']['count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
