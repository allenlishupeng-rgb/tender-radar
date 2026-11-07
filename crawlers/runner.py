from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time

import yaml

from ai_classifier.relevance import AIRelevanceClassifier, apply_ai_classification
from config.settings import KEYWORDS_PATH, SOURCES_PATH
from crawlers.registry import CRAWLER_REGISTRY
from crawlers.source_health import (
    FAILURE_STATE_PATH,
    apply_source_failure_alerts,
    load_source_failure_state,
    save_source_failure_state,
    source_status_failed,
)
from parsers.extractors import annotate_deadline_fields, is_open_for_tendering
from scoring.project_profile import PROJECT_SEARCH_TERMS, expand_project_query_terms, is_public_culture_without_target
from scoring.rules import (
    NOTICE_STAGE_BID,
    NOTICE_STAGE_INTEL,
    annotate_notice_stage,
    is_target_exhibition_tender,
)
from utils.date_window import (
    MAX_INTERACTIVE_SEARCH_DAYS,
    STRICT_RECENT_DAYS,
    date_in_window,
    parse_iso_date as parse_result_date,
    recent_date_window,
)


DEFAULT_PROFILE_QUERY_LIMIT = 32
DEFAULT_SOURCE_QUERY_LIMIT = 8
DEFAULT_SOURCE_RESULT_LIMIT = 18
DEFAULT_SOURCE_MIN_RELEVANCE_SCORE = 20
DEFAULT_SOURCE_TIMEOUT_SECONDS = 60
DEFAULT_DETAIL_RECOVERY_LIMIT = 12
# Share of a source's time budget held back for deadline recovery while
# relevant bids without a deadline are waiting.
DETAIL_RECOVERY_RESERVE_RATIO = 0.25
# Rough cost of one detail page (request interval plus fetch).
DETAIL_RECOVERY_SECONDS_PER_ITEM = 4
PRIORITY_RANK = {"高优先级": 0, "中优先级": 1, "低优先级": 2, "可能无关": 3}


def result_date_window(days, start_date=None, end_date=None):
    return recent_date_window(
        days,
        start_date,
        end_date,
        max_days=MAX_INTERACTIVE_SEARCH_DAYS,
    )


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def split_query_terms(
    query: str,
    keywords: dict | None = None,
    limit: int = DEFAULT_PROFILE_QUERY_LIMIT,
) -> list[str]:
    text = (query or "").strip()
    seed_terms = [term.strip() for term in re.split(r"[、,，;；?？\s]+", text) if term.strip()]
    if not seed_terms and keywords:
        configured_terms = [
            *(keywords.get("query_priority_terms") or []),
            *(keywords.get("default_search_terms") or []),
        ]
        seed_terms = list(dict.fromkeys(term.strip() for term in configured_terms if term and term.strip()))
    if not seed_terms:
        seed_terms = PROJECT_SEARCH_TERMS

    expanded_terms = list(seed_terms)
    for term in seed_terms:
        expanded_terms.extend(expand_project_query_terms(term))
    expanded_terms.extend(PROJECT_SEARCH_TERMS)
    return list(dict.fromkeys(term for term in expanded_terms if term))[:limit]


def source_query_terms(source: dict, query_terms: list[str]) -> list[str]:
    if source.get("query_strategy") == "crawler_managed":
        # Some public APIs expand a query internally. Replaying the complete
        # profile term list from the runner duplicates requests and exhausts
        # the source deadline before later terms can run.
        return [""]
    if source.get("broad_match"):
        return [""]
    raw_limit = source.get("max_terms", source.get("query_limit", DEFAULT_SOURCE_QUERY_LIMIT))
    try:
        max_terms = int(raw_limit or DEFAULT_SOURCE_QUERY_LIMIT)
    except (TypeError, ValueError):
        max_terms = DEFAULT_SOURCE_QUERY_LIMIT
    return query_terms[: max(max_terms, 1)]


def source_result_limit(source: dict) -> int:
    raw_limit = source.get("result_limit", source.get("max_results", source.get("max_items", DEFAULT_SOURCE_RESULT_LIMIT)))
    try:
        limit = int(raw_limit or DEFAULT_SOURCE_RESULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_SOURCE_RESULT_LIMIT
    return max(limit, 1)


def detail_recovery_limit(source: dict) -> int:
    try:
        return max(int(source.get("detail_recovery_limit", DEFAULT_DETAIL_RECOVERY_LIMIT)), 0)
    except (TypeError, ValueError):
        return DEFAULT_DETAIL_RECOVERY_LIMIT


def needs_deadline_recovery(tender) -> bool:
    return tender.days_left is None and tender.notice_stage == NOTICE_STAGE_BID


def select_recovery_candidates(tenders, limit: int) -> list:
    """Most valuable first: priority, then relevance, then newest notice."""
    pending = [tender for tender in tenders if needs_deadline_recovery(tender)]
    pending.sort(key=lambda tender: tender.publish_date or "", reverse=True)
    pending.sort(key=lambda tender: (
        PRIORITY_RANK.get(tender.priority, len(PRIORITY_RANK)),
        -int(tender.relevance_score or 0),
    ))
    return pending[:max(limit, 0)]


def recovery_reserve_seconds(total_seconds: float, pending_count: int, limit: int) -> float:
    if pending_count <= 0 or limit <= 0:
        return 0.0
    wanted = min(pending_count, limit) * DETAIL_RECOVERY_SECONDS_PER_ITEM
    return min(float(wanted), total_seconds * DETAIL_RECOVERY_RESERVE_RATIO)


def source_min_relevance_score(source: dict) -> int:
    raw_score = source.get("min_relevance_score", DEFAULT_SOURCE_MIN_RELEVANCE_SCORE)
    try:
        return max(int(raw_score or 0), 0)
    except (TypeError, ValueError):
        return DEFAULT_SOURCE_MIN_RELEVANCE_SCORE


def source_timeout_seconds(source: dict) -> int:
    raw_seconds = source.get("source_timeout_seconds", DEFAULT_SOURCE_TIMEOUT_SECONDS)
    try:
        seconds = int(raw_seconds or DEFAULT_SOURCE_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        seconds = DEFAULT_SOURCE_TIMEOUT_SECONDS
    return max(seconds, 1)


def build_source_diagnostic_message(stats: dict, base_message: str = "") -> str:
    parts = []
    if base_message:
        parts.append(base_message)
    parts.append(
        "过滤链路："
        f"查询词 {stats.get('query_count', 0)}/{stats.get('query_total', 0)} 个，"
        f"候选 {stats.get('raw_count', 0)} 条，"
        f"时间窗内 {stats.get('date_count', 0)} 条，"
        f"画像命中 {stats.get('target_count', 0)} 条，"
        f"质量通过 {stats.get('quality_count', 0)} 条"
    )
    duplicate_count = int(stats.get("duplicate_count", 0) or 0)
    if duplicate_count:
        parts.append(f"去重 {duplicate_count} 条")
    non_target_count = int(stats.get("non_target_count", 0) or 0)
    if non_target_count:
        parts.append(f"画像排除 {non_target_count} 条")
    quality_rejected_count = int(stats.get("quality_rejected_count", 0) or 0)
    if quality_rejected_count:
        parts.append(f"质量门槛排除 {quality_rejected_count} 条")
    parts.append(f"20天可用 {stats.get('actionable_count', 0)} 条，日期缺失 {stats.get('deadline_unknown_count', 0)} 条，时间不足 {stats.get('deadline_short_count', 0)} 条")
    return "；".join(part for part in parts if part)


def source_diagnostic_fields(stats: dict) -> dict:
    return {
        "query_count": int(stats.get("query_count", 0) or 0),
        "query_total": int(stats.get("query_total", 0) or 0),
        "raw_count": int(stats.get("raw_count", 0) or 0),
        "date_count": int(stats.get("date_count", 0) or 0),
        "target_count": int(stats.get("target_count", 0) or 0),
        "quality_count": int(stats.get("quality_count", 0) or 0),
        "duplicate_count": int(stats.get("duplicate_count", 0) or 0),
        "non_target_count": int(stats.get("non_target_count", 0) or 0),
        "quality_rejected_count": int(stats.get("quality_rejected_count", 0) or 0),
        "review_count": int(stats.get("review_count", 0) or 0),
        "executed_terms": list(stats.get("executed_terms", [])),
        "actionable_count": int(stats.get("actionable_count", 0)),
        "deadline_unknown_count": int(stats.get("deadline_unknown_count", 0)),
        "deadline_short_count": int(stats.get("deadline_short_count", 0)),
        "detail_recovered_count": int(stats.get("detail_recovered_count", 0)),
        "detail_recovery_attempted": int(stats.get("detail_recovery_attempted", 0)),
        "elapsed_seconds": stats.get("elapsed_seconds", 0),
    }


def passes_source_quality_gate(tender, source: dict) -> bool:
    try:
        score = int(getattr(tender, "relevance_score", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    priority = getattr(tender, "priority", "") or "可能无关"
    if priority == "可能无关" and score < source_min_relevance_score(source):
        return False
    if source.get("require_header_target"):
        header_only = {
            "title": getattr(tender, "title", ""),
            "announcement_type": getattr(tender, "announcement_type", ""),
            "purchaser": getattr(tender, "purchaser", ""),
            "agency": getattr(tender, "agency", ""),
            "summary": "",
            "important_info": "",
        }
        if not is_target_exhibition_tender(header_only):
            return False
    if source.get("drop_public_culture", True):
        title_purchaser = f"{getattr(tender, 'title', '')} {getattr(tender, 'purchaser', '')}"
        if is_public_culture_without_target(title_purchaser, getattr(tender, "profile_project_type", "")):
            return False
    return True


def retains_quality_rejected_candidate(source: dict) -> bool:
    return bool(source.get("keep_quality_rejected_as_review"))


def split_region_terms(region_text: str | None) -> list[str] | None:
    terms = [term.strip() for term in re.split(r"[、,，;；\s]+", region_text or "") if term.strip()]
    expanded = []
    for term in terms:
        if term in {"东三省", "东北三省", "东北"}:
            expanded.extend(["辽宁", "吉林", "黑龙江"])
        else:
            expanded.append(term)
    terms = expanded
    return list(dict.fromkeys(terms)) or None


def tender_in_result_date_window(tender, start, end) -> bool:
    return date_in_window(getattr(tender, "publish_date", ""), start, end)


def close_crawler(crawler) -> None:
    close = getattr(crawler, "close", None)
    if callable(close):
        close()
        return
    session = getattr(crawler, "session", None)
    session_close = getattr(session, "close", None)
    if callable(session_close):
        session_close()


def is_ai_candidate_tender(tender) -> bool:
    annotate_deadline_fields(tender)
    annotate_notice_stage(tender)
    if getattr(tender, "ai_classified", False):
        return False
    if getattr(tender, "tender_status", "") == "已截止":
        return False
    if getattr(tender, "notice_stage", "") not in {NOTICE_STAGE_BID, NOTICE_STAGE_INTEL}:
        return False
    if not getattr(tender, "title", "") or not getattr(tender, "source_url", ""):
        return False
    return is_target_exhibition_tender(tender.__dict__)


def apply_ai_to_candidates(
    tenders: list,
    classifier: AIRelevanceClassifier | None = None,
    max_items: int | None = None,
) -> dict[str, int]:
    classifier = classifier or AIRelevanceClassifier()
    if not classifier.enabled:
        return {}

    counts: dict[str, int] = {}
    classified_total = 0
    for tender in tenders:
        if max_items is not None and classified_total >= max_items:
            break
        if not is_ai_candidate_tender(tender):
            continue
        before = getattr(tender, "ai_classified", False)
        apply_ai_classification(tender, classifier)
        if getattr(tender, "ai_classified", False) and not before:
            classified_total += 1
            source_name = getattr(tender, "source_name", "") or "未知来源"
            counts[source_name] = counts.get(source_name, 0) + 1
    return counts


def run_search(
    selected_sources: list[str] | None = None,
    query: str = "展陈",
    days: int = 7,
    start_date: str | None = None,
    end_date: str | None = None,
    regions: list[str] | None = None,
    enable_ai: bool = True,
    max_ai_candidates: int | None = None,
):
    results, _statuses = run_search_with_status(
        selected_sources,
        query,
        days,
        start_date,
        end_date,
        regions,
        enable_ai=enable_ai,
        max_ai_candidates=max_ai_candidates,
    )
    return results


def run_search_with_status(
    selected_sources: list[str] | None = None,
    query: str = "展陈",
    days: int = 7,
    start_date: str | None = None,
    end_date: str | None = None,
    regions: list[str] | None = None,
    enable_ai: bool = True,
    max_ai_candidates: int | None = None,
    search_depth: str = "standard",
    progress_callback=None,
):
    keywords = load_yaml(KEYWORDS_PATH)
    query_terms = split_query_terms(query, keywords)
    sources = load_yaml(SOURCES_PATH).get("sources", [])
    results = []
    statuses_by_index = {}
    runnable = []

    def status_from_error(message: str) -> str:
        if any(marker in (message or "") for marker in ["超时", "频繁", "HTTP", "robots.txt", "中断", "重置", "不可用"]):
            return "访问失败/受限"
        return "无结果"

    def run_one_source(source: dict):
        source = dict(source)
        if search_depth == "deep":
            # Increase bounded coverage only for real structured adapters.
            # Slow static homepage scanners keep their small original budget.
            if source.get("crawler") not in {"regional_static", "example_public_page"}:
                if source.get("crawler") != "ccgp_public":
                    source["max_pages"] = min(max(int(source.get("max_pages", 1)), 2), 4)
                source["detail_enrichment_limit"] = max(int(source.get("detail_enrichment_limit", 8)), 30)
                source["source_timeout_seconds"] = min(source_timeout_seconds(source) * 2, 120)
        if source.get("query_strategy") == "crawler_managed" and not source.get("broad_match"):
            source["search_terms"] = list(dict.fromkeys([*query_terms, *(source.get("search_terms") or [])]))
        crawler_cls = CRAWLER_REGISTRY.get(source.get("crawler"))
        source_results = []
        errors = []
        crawler = None
        try:
            seen_urls = set()
            source_terms = source_query_terms(source, query_terms)
            stats = {
                "query_count": 0,
                "query_total": len(source_terms),
                "raw_count": 0,
                "date_count": 0,
                "target_count": 0,
                "quality_count": 0,
                "duplicate_count": 0,
                "non_target_count": 0,
                "quality_rejected_count": 0,
                "review_count": 0,
                "executed_terms": [],
            }
            max_results = source_result_limit(source)
            review_limit = max(int(source.get("review_candidate_limit", 8) or 8), 1)
            review_results = []
            source_budget = source_timeout_seconds(source)
            source_deadline = time.monotonic() + source_budget
            enrich = getattr(crawler_cls, "enrich_from_detail", None)
            recovery_limit = detail_recovery_limit(source) if callable(enrich) else 0
            result_start, result_end = result_date_window(days, start_date, end_date)
            source_days = (result_end - result_start).days + 1
            effective_start = result_start.isoformat()
            effective_end = result_end.isoformat()
            stop_source = False
            crawler = crawler_cls(keywords, source_config=source)
            crawler.execution_deadline = source_deadline
            def search_deadline() -> float:
                pending = sum(1 for item in source_results if needs_deadline_recovery(item))
                return source_deadline - recovery_reserve_seconds(source_budget, pending, recovery_limit)

            for term in source_terms:
                if time.monotonic() >= search_deadline():
                    errors.append("单来源总运行超时，已切换下一个来源")
                    stop_source = True
                    break
                crawler.execution_deadline = search_deadline()
                crawler.last_error = ""
                term_results = crawler.search(
                    query=term,
                    days=source_days,
                    start_date=effective_start,
                    end_date=effective_end,
                    regions=regions,
                )
                stats["query_count"] += 1
                stats["executed_terms"].append(term or "全量机会扫描")
                stats["raw_count"] += len(term_results)
                if crawler.last_error:
                    errors.append(crawler.last_error)
                for tender in term_results:
                    annotate_notice_stage(tender)
                    if not tender_in_result_date_window(tender, result_start, result_end):
                        continue
                    stats["date_count"] += 1
                    key = tender.source_url or f"{tender.title}|{tender.publish_date}"
                    if key in seen_urls:
                        stats["duplicate_count"] += 1
                        continue
                    if not is_target_exhibition_tender(tender.__dict__):
                        stats["non_target_count"] += 1
                        continue
                    stats["target_count"] += 1
                    seen_urls.add(key)
                    if not passes_source_quality_gate(tender, source):
                        stats["quality_rejected_count"] += 1
                        if retains_quality_rejected_candidate(source) and len(review_results) < review_limit:
                            tender.review_bucket = "待研判"
                            reason = "未通过自动质量门槛，保留在待研判候选池"
                            tender.profile_reason = "；".join(
                                part for part in [getattr(tender, "profile_reason", ""), reason] if part
                            )
                            review_results.append(tender)
                            stats["review_count"] += 1
                        continue
                    stats["quality_count"] += 1
                    annotate_deadline_fields(tender)
                    source_results.append(tender)
                    if len(source_results) >= max_results:
                        stop_source = True
                        break
                if stop_source:
                    break
                if time.monotonic() >= search_deadline():
                    errors.append("单来源总运行超时，已切换下一个来源")
                    break
            # Phase 2: spend the reserved budget on the most valuable bids whose
            # deadline the adapter's own detail quota did not reach.
            crawler.execution_deadline = source_deadline
            recovery_candidates = select_recovery_candidates(source_results, recovery_limit)
            stats["detail_recovery_attempted"] = 0
            for tender in recovery_candidates:
                if time.monotonic() >= source_deadline:
                    break
                stats["detail_recovery_attempted"] += 1
                try:
                    crawler.enrich_from_detail(tender)
                except Exception as exc:  # One broken detail page must not drop the source.
                    errors.append(f"详情补全失败：{exc}")
                    continue
                annotate_deadline_fields(tender)
                if tender.days_left is not None:
                    stats["detail_recovered_count"] = stats.get("detail_recovered_count", 0) + 1
            for tender in source_results:
                deadline_key = "actionable_count" if is_open_for_tendering(tender) else ("deadline_unknown_count" if tender.days_left is None else "deadline_short_count")
                stats[deadline_key] = stats.get(deadline_key, 0) + 1
            all_source_results = [*source_results, *review_results]
            stats["elapsed_seconds"] = round(source_budget - max(0, source_deadline - time.monotonic()), 2)
            if all_source_results:
                limit_note = f"已按来源上限保留 {len(source_results)} 条" if len(source_results) >= max_results else ""
                review_note = f"待研判候选 {len(review_results)} 条" if review_results else ""
                completion_note = "；".join(note for note in [*errors, limit_note] if note)
                return all_source_results, {
                    "source": source["name"],
                    "status": "成功",
                    "count": len(all_source_results),
                    "message": build_source_diagnostic_message(stats, "；".join(note for note in [completion_note, review_note] if note)),
                    **source_diagnostic_fields(stats),
                }
            message = next((error for error in errors if error), "") or "本次未返回匹配公告"
            return source_results, {
                "source": source["name"],
                "status": status_from_error(message),
                "count": 0,
                "message": build_source_diagnostic_message(stats, message),
                **source_diagnostic_fields(stats),
            }
        except Exception as exc:
            return source_results, {"source": source["name"], "status": "部分成功" if source_results else "失败", "count": len(source_results), "message": str(exc)}

        finally:
            if crawler is not None:
                close_crawler(crawler)

    for index, source in enumerate(sources):
        # None means "all configured sources"; an explicit empty list means
        # "run nothing". This prevents a failed health-filter lookup from
        # accidentally turning into a full wide scan.
        if selected_sources is not None and source["name"] not in selected_sources:
            continue
        if not source.get("enabled", True):
            statuses_by_index[index] = {"source": source["name"], "status": "已禁用", "count": 0, "message": source.get("notes", "")}
            continue
        crawler_cls = CRAWLER_REGISTRY.get(source.get("crawler"))
        if not crawler_cls:
            statuses_by_index[index] = {"source": source["name"], "status": "未接入", "count": 0, "message": "没有找到 crawler adapter"}
            continue
        if source.get("crawler") == "example_public_page":
            statuses_by_index[index] = {"source": source["name"], "status": "示例源跳过", "count": 0, "message": "未接入真实公开页面适配器"}
            continue
        runnable.append((index, source))

    if runnable:
        max_workers = min(4, len(runnable))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(run_one_source, source): (index, source) for index, source in runnable}
            for future in as_completed(future_map):
                index, source = future_map[future]
                try:
                    source_results, status = future.result()
                except Exception as exc:
                    source_results = []
                    status = {
                        "source": source["name"],
                        "status": "失败",
                        "count": 0,
                        "message": f"来源执行异常：{exc}",
                    }
                results.extend(source_results)
                statuses_by_index[index] = status
                if progress_callback is not None:
                    progress_callback(status, sum(1 for i, _ in runnable if i in statuses_by_index), len(runnable))

    ai_counts = apply_ai_to_candidates(results, max_items=max_ai_candidates) if enable_ai else {}
    if ai_counts:
        for status in statuses_by_index.values():
            source_ai_count = ai_counts.get(status.get("source", ""), 0)
            if status.get("status") == "成功" and source_ai_count:
                suffix = f"AI 已二次判断 {source_ai_count} 条候选线索"
                status["message"] = f"{status.get('message', '')}；{suffix}".strip("；")

    statuses = [statuses_by_index[index] for index in sorted(statuses_by_index)]
    statuses = apply_source_failure_alerts(statuses, sources)
    return results, statuses
