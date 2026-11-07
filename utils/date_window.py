from datetime import date, datetime, timedelta
from typing import Any

import config.settings  # noqa: F401  Applies the Beijing business timezone.


STRICT_RECENT_DAYS = 7
DEFAULT_INTERACTIVE_SEARCH_DAYS = 30
MAX_INTERACTIVE_SEARCH_DAYS = 30


def parse_iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def clamp_recent_days(days: Any, max_days: int = STRICT_RECENT_DAYS) -> int:
    try:
        requested_days = int(days)
    except (TypeError, ValueError):
        requested_days = max_days
    return min(max(requested_days, 1), max_days)


def recent_date_window(
    days: Any = STRICT_RECENT_DAYS,
    start_date: Any = None,
    end_date: Any = None,
    today: date | None = None,
    max_days: int = STRICT_RECENT_DAYS,
) -> tuple[date, date]:
    end = parse_iso_date(end_date) or today or date.today()
    strict_start = end - timedelta(days=clamp_recent_days(days, max_days=max_days) - 1)
    requested_start = parse_iso_date(start_date)
    start = max(requested_start, strict_start) if requested_start else strict_start
    return start, end


def date_in_window(value: Any, start: date, end: date) -> bool:
    parsed = parse_iso_date(value)
    if not parsed:
        return False
    return start <= parsed <= end
