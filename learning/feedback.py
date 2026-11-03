import json
import re
from collections import Counter
from typing import Any

from scoring.user_feedback import (
    NEGATIVE_USER_SCORE,
    POSITIVE_USER_SCORE,
    parse_user_score,
)


POSITIVE_LABEL = "这是我的菜"
NEGATIVE_LABEL = "误报"
OBSERVE_LABEL = "待观察"

POSITIVE_TERM_POOL = [
    "展厅",
    "展馆",
    "展陈",
    "布展",
    "陈列",
    "展示中心",
    "规划馆",
    "博物馆",
    "文化馆",
    "科技馆",
    "纪念馆",
    "主题馆",
    "品牌馆",
    "企业展厅",
    "企业文化展厅",
    "产业园",
    "产业展示中心",
    "数字展厅",
    "智慧展厅",
    "多媒体展项",
    "互动装置",
    "设计施工一体化",
    "深化设计",
    "EPC",
]

NEGATIVE_TERM_POOL = [
    "会展服务",
    "会务服务",
    "展会服务",
    "展位",
    "展台",
    "舞台搭建",
    "广告印刷",
    "广告制作",
    "宣传片",
    "发布会",
    "推介会",
    "博览会",
    "交易会",
    "标识标牌",
    "办公家具",
    "物业服务",
    "保洁服务",
    "安保服务",
    "文物预防性保护",
]


def normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return normalize_keywords(parsed)
        except Exception:
            pass
        return [item.strip() for item in re.split(r"[、,，;；\s]+", text) if item.strip()]
    return []


def row_text(row: dict) -> str:
    fields = ["title", "announcement_type", "summary", "important_info", "purchaser", "agency", "source_name"]
    return re.sub(r"\s+", "", " ".join(str(row.get(field) or "") for field in fields))


def matched_terms(row: dict, pool: list[str]) -> list[str]:
    text = row_text(row)
    terms = [term for term in pool if term in text]
    terms.extend(normalize_keywords(row.get("matched_keywords")))
    return list(dict.fromkeys(term for term in terms if term))


def existing_keyword_set(keywords: dict[str, list[str]]) -> set[str]:
    existing = set()
    for values in keywords.values():
        existing.update(str(item).strip() for item in values or [] if str(item).strip())
    return existing


def build_learning_suggestions(rows: list[dict], keywords: dict[str, list[str]]) -> dict[str, Any]:
    positive_counter: Counter[str] = Counter()
    negative_counter: Counter[str] = Counter()
    positive_count = 0
    negative_count = 0
    observe_count = 0
    scored_count = 0

    for row in rows:
        label = str(row.get("feedback_label") or "").strip()
        user_score = parse_user_score(row.get("user_score"))
        if user_score is not None:
            scored_count += 1
        is_positive = label == POSITIVE_LABEL or (user_score is not None and user_score >= POSITIVE_USER_SCORE)
        is_negative = label == NEGATIVE_LABEL or (user_score is not None and user_score <= NEGATIVE_USER_SCORE)
        is_observe = label == OBSERVE_LABEL or (user_score is not None and NEGATIVE_USER_SCORE < user_score < POSITIVE_USER_SCORE)

        if is_positive:
            positive_count += 1
            positive_counter.update(matched_terms(row, POSITIVE_TERM_POOL))
        elif is_negative:
            negative_count += 1
            negative_counter.update(matched_terms(row, NEGATIVE_TERM_POOL))
        elif is_observe:
            observe_count += 1

    existing = existing_keyword_set(keywords)
    positive_terms = [term for term, count in positive_counter.most_common(20) if term not in existing and count >= 1]
    negative_terms = [term for term, count in negative_counter.most_common(20) if term not in existing and count >= 1]

    return {
        "sample_count": positive_count + negative_count,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "observe_count": observe_count,
        "scored_count": scored_count,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
        "top_positive_terms": positive_counter.most_common(10),
        "top_negative_terms": negative_counter.most_common(10),
    }


def apply_learning_suggestions(keywords: dict[str, list[str]], suggestions: dict[str, Any]) -> tuple[dict[str, list[str]], int]:
    updated = {key: list(values or []) for key, values in keywords.items()}
    updated.setdefault("extended_keywords", [])
    updated.setdefault("downrank_keywords", [])
    changed = 0

    for term in suggestions.get("positive_terms", []):
        if term not in updated["extended_keywords"]:
            updated["extended_keywords"].append(term)
            changed += 1
    for term in suggestions.get("negative_terms", []):
        if term not in updated["downrank_keywords"]:
            updated["downrank_keywords"].append(term)
            changed += 1
    return updated, changed
