from typing import Any

from parsers.extractors import annotate_deadline_fields, MIN_ACTIONABLE_DAYS_LEFT
from scoring.project_profile import is_public_culture_without_target
from scoring.rules import (
    NOTICE_STAGE_BID,
    NOTICE_STAGE_CHANGE,
    NOTICE_STAGE_INTEL,
    NOTICE_STAGE_INVALID,
    NOTICE_STAGE_RESULT,
    annotate_notice_stage,
)
from scoring.user_feedback import parse_user_score, user_score_display


ACTION_NOW = "立即跟进"
ACTION_PIPELINE = "进入跟进池"
ACTION_OBSERVE = "机会池观察"
ACTION_REVIEW = "人工筛选"
ACTION_INTEL = "情报复盘"
ACTION_IGNORE = "暂不跟进"

RISK_LOW = "低"
RISK_MEDIUM = "中"
RISK_HIGH = "高"

PRIORITY_SCORE = {
    "高优先级": 35,
    "中优先级": 26,
    "低优先级": 14,
    "可能无关": 0,
}

STAGE_SCORE = {
    NOTICE_STAGE_BID: 28,
    NOTICE_STAGE_INTEL: 16,
    NOTICE_STAGE_CHANGE: 8,
    NOTICE_STAGE_RESULT: 6,
    NOTICE_STAGE_INVALID: -30,
}

STATUS_SCORE = {
    "理想窗口": 20,
    "正常跟进": 16,
    "紧急跟进": 12,
    "观察": 8,
    "待核验": 5,
    "时间不足": -8,
    "已截止": -20,
}


def item_get(item: dict[str, Any] | Any, field: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def item_set(item: dict[str, Any] | Any, field: str, value: Any) -> None:
    if isinstance(item, dict):
        item[field] = value
    else:
        setattr(item, field, value)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def has_value(item: dict[str, Any] | Any, field: str) -> bool:
    value = item_get(item, field, "")
    if value is None:
        return False
    return bool(str(value).strip())


def clamp(value: int, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, value))


def assess_lead_quality(item: dict[str, Any] | Any) -> dict[str, Any]:
    annotate_deadline_fields(item)
    annotate_notice_stage(item, preserve_existing=True)

    priority = str(item_get(item, "display_priority", "") or item_get(item, "priority", "") or "可能无关")
    stage = str(item_get(item, "notice_stage", "") or NOTICE_STAGE_INTEL)
    status = str(item_get(item, "tender_status", "") or "待核验")
    source_name = str(item_get(item, "source_name", "") or "")
    score = clamp(safe_int(item_get(item, "relevance_score", 0)))
    user_score = parse_user_score(item_get(item, "user_score", None))

    quality = int(round(score * 0.25))
    quality += PRIORITY_SCORE.get(priority, 0)
    quality += STAGE_SCORE.get(stage, 0)
    quality += STATUS_SCORE.get(status, 0)

    reasons: list[str] = []
    risks: list[str] = []

    if stage == NOTICE_STAGE_BID:
        reasons.append("正式可投公告")
    elif stage == NOTICE_STAGE_INTEL:
        reasons.append("前期/需求线索")
    elif stage == NOTICE_STAGE_RESULT:
        reasons.append("结果类公告")
    elif stage == NOTICE_STAGE_CHANGE:
        reasons.append("更正澄清类公告")
    elif stage == NOTICE_STAGE_INVALID:
        reasons.append("已识别为无效/非目标")

    if priority in {"高优先级", "中优先级"}:
        reasons.append(priority)
    elif priority == "低优先级":
        reasons.append("低优先级，需人工筛选")
    else:
        risks.append("相关性低")

    days_left = item_get(item, "days_left", None)
    if days_left is not None:
        days = safe_int(days_left, 0)
        if days < 0:
            risks.append("已截止")
        elif days < MIN_ACTIONABLE_DAYS_LEFT:
            risks.append(f"截止期不足 {MIN_ACTIONABLE_DAYS_LEFT} 天")
        elif days <= 30:
            reasons.append(f"剩余 {days} 天")
        else:
            reasons.append(f"剩余 {days} 天，可观察")
    else:
        risks.append("截止时间待核验")

    if has_value(item, "budget"):
        reasons.append("预算已提取")
    else:
        risks.append("预算缺失")

    if has_value(item, "contact_phone") or has_value(item, "contact_person"):
        reasons.append("联系方式已提取")
    else:
        risks.append("联系方式缺失")

    profile_type = str(item_get(item, "profile_project_type", "") or item_get(item, "ai_project_type", "") or "")
    if profile_type and profile_type != "未知项目":
        reasons.append(f"画像：{profile_type}")
    else:
        risks.append("项目画像不明确")

    public_text = " ".join(
        str(item_get(item, field, "") or "")
        for field in ["title", "purchaser"]
    )
    public_culture_only = is_public_culture_without_target(public_text, profile_type)
    if public_culture_only:
        risks.append("公共文化/博物馆类，默认不作为主攻项目")
        quality -= 28

    if user_score is not None:
        reasons.append(f"你的评分：{user_score_display(user_score)}")
        if user_score >= 8:
            quality = max(quality + user_score * 4, 85)
            reasons.append("人工高分样本优先")
        elif user_score >= 4:
            quality += user_score * 3
            reasons.append("人工观察样本")
        elif user_score <= 0:
            quality = min(quality + user_score * 4, 20)
            risks.append("人工低分/负分样本")

    merged_count = safe_int(item_get(item, "merged_count", 1), 1)
    if merged_count > 1:
        reasons.append(f"跨来源合并 {merged_count} 条")
        quality += 6

    if "上市公司展厅招投标" in source_name or "上市民企" in source_name:
        reasons.append("企业/第三方线索需复核原始出处")
        quality -= 4

    if status in {"时间不足", "已截止"}:
        quality -= 12
    if stage in {NOTICE_STAGE_RESULT, NOTICE_STAGE_CHANGE}:
        quality -= 8
    if priority == "可能无关" or stage == NOTICE_STAGE_INVALID:
        quality = min(quality, 25)
    if public_culture_only:
        quality = min(quality, 54)
    if user_score is not None and user_score <= 0:
        quality = min(quality, 20)

    quality = clamp(quality)

    if user_score is not None and user_score <= 0:
        action = ACTION_IGNORE
    elif stage == NOTICE_STAGE_INVALID or priority == "可能无关":
        action = ACTION_IGNORE
    elif status in {"已截止", "时间不足"}:
        action = ACTION_INTEL
    elif stage == NOTICE_STAGE_BID and priority == "高优先级" and quality >= 70:
        action = ACTION_NOW
    elif stage == NOTICE_STAGE_BID and priority in {"高优先级", "中优先级"}:
        action = ACTION_PIPELINE
    elif stage == NOTICE_STAGE_INTEL and priority in {"高优先级", "中优先级"}:
        action = ACTION_OBSERVE
    elif stage in {NOTICE_STAGE_RESULT, NOTICE_STAGE_CHANGE}:
        action = ACTION_INTEL
    else:
        action = ACTION_REVIEW

    if public_culture_only and action in {ACTION_NOW, ACTION_PIPELINE, ACTION_OBSERVE}:
        action = ACTION_REVIEW if stage == NOTICE_STAGE_BID else ACTION_INTEL

    if action in {ACTION_IGNORE, ACTION_INTEL} or "已截止" in risks:
        risk_level = RISK_HIGH
    elif risks or quality < 60:
        risk_level = RISK_MEDIUM
    else:
        risk_level = RISK_LOW

    reason_text = "；".join(dict.fromkeys(reasons + risks))
    return {
        "lead_action": action,
        "lead_quality_score": quality,
        "lead_risk_level": risk_level,
        "lead_reason": reason_text,
    }


def annotate_lead_quality(item: dict[str, Any] | Any):
    assessment = assess_lead_quality(item)
    for field, value in assessment.items():
        item_set(item, field, value)
    return item
