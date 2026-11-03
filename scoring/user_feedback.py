from typing import Any


POSITIVE_USER_SCORE = 8
OBSERVE_USER_SCORE = 4
NEGATIVE_USER_SCORE = 0

POSITIVE_FEEDBACK_LABEL = "这是我的菜"
OBSERVE_FEEDBACK_LABEL = "待观察"
NEGATIVE_FEEDBACK_LABEL = "误报"


def parse_user_score(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        score = int(float(text))
    except (TypeError, ValueError):
        return None
    return max(-10, min(10, score))


def feedback_label_from_user_score(value: Any) -> str:
    score = parse_user_score(value)
    if score is None:
        return ""
    if score >= POSITIVE_USER_SCORE:
        return POSITIVE_FEEDBACK_LABEL
    if score <= NEGATIVE_USER_SCORE:
        return NEGATIVE_FEEDBACK_LABEL
    return OBSERVE_FEEDBACK_LABEL


def user_score_weight(value: Any) -> int:
    score = parse_user_score(value)
    if score is None:
        return 0
    return score * 4


def user_score_display(value: Any) -> str:
    score = parse_user_score(value)
    if score is None:
        return "未评分"
    if score >= POSITIVE_USER_SCORE:
        return f"{score} / 我的菜"
    if score <= NEGATIVE_USER_SCORE:
        return f"{score} / 排除"
    return f"{score} / 观察"
