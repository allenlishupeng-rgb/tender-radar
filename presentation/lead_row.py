"""Build one consistent, display-ready representation of a tender lead."""

from typing import Any

from parsers.extractors import annotate_deadline_fields
from scoring.lead_quality import annotate_lead_quality
from scoring.rules import (
    NOTICE_STAGE_INVALID,
    annotate_notice_stage,
    classify_business_priority,
    priority_from_score,
)
from scoring.user_feedback import parse_user_score
from utils.text_format import normalize_budget, normalize_matched_keywords, repair_text


TEXT_FIELDS = (
    "title",
    "announcement_type",
    "region",
    "purchaser",
    "agency",
    "budget",
    "project_no",
    "contact_person",
    "contact_phone",
    "bid_deadline",
    "bid_deadline_date",
    "tender_status",
    "notice_stage",
    "important_info",
    "summary",
    "source_name",
    "merged_sources",
    "profile_project_type",
    "profile_client_type",
    "profile_reason",
    "ai_reason",
    "ai_project_type",
    "ai_suggested_action",
    "feedback_label",
    "remark",
    "user_score_updated_at",
    "lead_action",
    "lead_risk_level",
    "lead_reason",
)

VALID_PRIORITIES = {"高优先级", "中优先级", "低优先级", "可能无关"}


def normalize_lead_row(row: dict[str, Any], *, include_display_priority: bool = False) -> dict[str, Any]:
    """Return a copy that is safe to render or export without mutating storage rows."""
    cleaned = dict(row)
    for field in TEXT_FIELDS:
        cleaned[field] = repair_text(cleaned.get(field, ""))

    cleaned["budget"] = normalize_budget(cleaned.get("budget", ""))
    cleaned["matched_keywords"] = normalize_matched_keywords(cleaned.get("matched_keywords"))
    cleaned["user_score"] = parse_user_score(cleaned.get("user_score"))
    annotate_deadline_fields(cleaned)
    annotate_notice_stage(cleaned, preserve_existing=True)

    if include_display_priority:
        _apply_display_priority(cleaned)
    annotate_lead_quality(cleaned)
    return cleaned


def _apply_display_priority(row: dict[str, Any]) -> None:
    if row.get("notice_stage") == NOTICE_STAGE_INVALID:
        priority = "可能无关"
    else:
        priority_text = " ".join(
            row.get(field, "")
            for field in ("title", "summary", "announcement_type", "purchaser", "agency")
        )
        stored_priority = repair_text(row.get("priority", ""))
        fallback_priority = stored_priority if stored_priority in VALID_PRIORITIES else priority_from_score(row.get("relevance_score"))
        priority = classify_business_priority(priority_text) or fallback_priority

    user_score = row["user_score"]
    if user_score is not None:
        if user_score >= 8:
            priority = "高优先级"
        elif user_score >= 4:
            priority = "中优先级"
        elif user_score > 0:
            priority = "低优先级"
        else:
            priority = "可能无关"

    row["display_priority"] = repair_text(priority)
    row["priority"] = row["display_priority"]
