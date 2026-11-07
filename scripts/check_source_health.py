import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import EXPORT_DIR, KEYWORDS_PATH, SOURCES_PATH, USER_AGENT
from crawlers.registry import CRAWLER_REGISTRY
from crawlers.runner import load_yaml


DEFAULT_PROBE_QUERY = "项目"
PROBE_DAYS = 30
MAX_DETAIL_LINKS = 2


def short_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:220]


def probe_url(session: requests.Session, url: str) -> dict:
    if not url:
        return {"ok": False, "status": "", "final_url": "", "message": "未配置 base_url"}
    try:
        response = session.get(url, timeout=12, allow_redirects=True)
        return {
            "ok": 200 <= response.status_code < 400,
            "status": response.status_code,
            "final_url": response.url,
            "message": "",
        }
    except Exception as exc:
        return {"ok": False, "status": "", "final_url": "", "message": short_error(exc)}


def trim_source_config(source: dict) -> dict:
    config = deepcopy(source)
    config["max_pages"] = min(int(config.get("max_pages", 1) or 1), 1)
    config["max_items"] = min(int(config.get("max_items", 8) or 8), 8)
    config["detail_enrichment_limit"] = min(int(config.get("detail_enrichment_limit", 2)), 2)
    config["request_timeout"] = min(int(config.get("request_timeout", 6) or 6), 6)
    config["source_timeout_seconds"] = min(int(config.get("source_timeout_seconds", 20) or 20), 20)
    if isinstance(config.get("target_regions"), list) and len(config["target_regions"]) > 2:
        config["target_regions"] = config["target_regions"][:2]
    return config


def source_query(source: dict) -> str:
    return source.get("health_query") or DEFAULT_PROBE_QUERY


def probe_result_links(session: requests.Session, tenders: list) -> list[dict]:
    checked = []
    seen = set()
    for tender in tenders:
        url = tender.source_url
        if not url or url in seen:
            continue
        seen.add(url)
        status = probe_url(session, url)
        checked.append(
            {
                "title": tender.title[:80],
                "url": url,
                "ok": status["ok"],
                "status": status["status"],
                "message": status["message"],
            }
        )
        if len(checked) >= MAX_DETAIL_LINKS:
            break
    return checked


def check_source(source: dict, keywords: dict) -> dict:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": USER_AGENT})

    result = {
        "source": source.get("name", ""),
        "crawler": source.get("crawler", ""),
        "base_url": source.get("base_url", ""),
        "base": {},
        "crawl_ok": False,
        "count": 0,
        "sample_links": [],
        "status": "未检查",
        "message": "",
    }

    result["base"] = probe_url(session, source.get("base_url", ""))
    crawler_cls = CRAWLER_REGISTRY.get(source.get("crawler"))
    if not crawler_cls:
        result["status"] = "未接入"
        result["message"] = "没有找到 crawler adapter"
        return result

    try:
        probe_config = trim_source_config(source)
        crawler = crawler_cls(keywords, source_config=probe_config, request_interval=0)
        probe_days = max(PROBE_DAYS, int(source.get("lookback_days", PROBE_DAYS) or PROBE_DAYS))
        tenders = crawler.search(query=source_query(source), days=probe_days)
        result["count"] = len(tenders)
        result["crawl_ok"] = len(tenders) > 0
        result["message"] = crawler.last_error or ""
        result["sample_links"] = probe_result_links(session, tenders)
    except Exception as exc:
        result["message"] = short_error(exc)

    link_ok = all(item["ok"] for item in result["sample_links"]) if result["sample_links"] else False
    has_warning = bool(result.get("message"))
    if result["base"].get("ok") and result["crawl_ok"] and link_ok and not has_warning:
        result["status"] = "可用"
    elif result["base"].get("ok") and result["crawl_ok"]:
        result["status"] = "可抓取，部分详情需复核"
    elif result["base"].get("ok"):
        result["status"] = "官网可访问，接口无样本/需复核"
    else:
        result["status"] = "访问失败/受限"
    return result


def main() -> int:
    keywords = load_yaml(KEYWORDS_PATH)
    sources = [
        source
        for source in load_yaml(SOURCES_PATH).get("sources", [])
        if source.get("enabled", True) and source.get("crawler") != "example_public_page"
    ]

    reports = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(check_source, source, keywords): source for source in sources}
        for future in as_completed(future_map):
            report = future.result()
            reports.append(report)
            print(f"[{len(reports)}/{len(sources)}] {report['source']} | {report['status']} | count={report['count']}", flush=True)

    reports.sort(key=lambda item: item["source"])
    output = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "probe_query": DEFAULT_PROBE_QUERY,
        "probe_days": PROBE_DAYS,
        "sources": reports,
    }

    out_dir = EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "source_health.json"
    md_path = out_dir / "source_health.md"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(output), encoding="utf-8")

    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    for item in reports:
        print(f"{item['status']} | {item['source']} | base={item['base'].get('status')} | count={item['count']} | {item['message'][:80]}")
    return 0


def render_markdown(output: dict) -> str:
    lines = [
        "# 数据源健康检查",
        "",
        f"- 检查时间：{output['checked_at']}",
        f"- 抽样关键词：{output['probe_query']}",
        f"- 抽样范围：最近 {output['probe_days']} 天",
        "",
        "| 状态 | 来源 | 官网 | 样本数 | 说明 |",
        "|---|---|---:|---:|---|",
    ]
    for item in output["sources"]:
        message = (item.get("message") or "").replace("|", " ")[:120]
        lines.append(
            f"| {item['status']} | {item['source']} | {item['base'].get('status', '')} | {item['count']} | {message} |"
        )
    lines.append("")
    lines.append("## 抽样原文链接")
    for item in output["sources"]:
        lines.append(f"\n### {item['source']}")
        if not item["sample_links"]:
            lines.append("- 本次没有可抽样链接")
            continue
        for link in item["sample_links"]:
            mark = "OK" if link["ok"] else "FAIL"
            lines.append(f"- {mark} [{link['title']}]({link['url']}) HTTP {link['status']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
