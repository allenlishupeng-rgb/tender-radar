from datetime import date, datetime

from utils.date_window import (
    MAX_INTERACTIVE_SEARCH_DAYS,
    STRICT_RECENT_DAYS,
    clamp_recent_days,
    date_in_window,
    parse_iso_date,
    recent_date_window,
)


def test_recent_date_window_uses_inclusive_seven_day_boundary():
    start, end = recent_date_window(days=STRICT_RECENT_DAYS, end_date="2026-06-25")

    assert start.isoformat() == "2026-06-19"
    assert end.isoformat() == "2026-06-25"
    assert date_in_window("2026-06-19", start, end)
    assert date_in_window("2026-06-25", start, end)
    assert not date_in_window("2026-06-18", start, end)


def test_recent_date_window_clamps_requested_days_to_strict_limit():
    start, end = recent_date_window(days=90, start_date="2026-01-01", end_date="2026-06-25")

    assert start.isoformat() == "2026-06-19"
    assert end.isoformat() == "2026-06-25"


def test_recent_date_window_supports_thirty_day_interactive_window():
    start, end = recent_date_window(
        days=30,
        end_date="2026-06-25",
        max_days=MAX_INTERACTIVE_SEARCH_DAYS,
    )

    assert start.isoformat() == "2026-05-27"
    assert end.isoformat() == "2026-06-25"


def test_recent_date_window_accepts_today_for_deterministic_ui_and_exports():
    start, end = recent_date_window(today=date(2026, 7, 9))

    assert start.isoformat() == "2026-07-03"
    assert end.isoformat() == "2026-07-09"


def test_parse_iso_date_and_clamp_recent_days_are_defensive():
    assert parse_iso_date("2026-07-09 10:30:00").isoformat() == "2026-07-09"
    assert parse_iso_date(datetime(2026, 7, 9, 10, 30)).isoformat() == "2026-07-09"
    assert parse_iso_date("not-a-date") is None
    assert clamp_recent_days(None) == STRICT_RECENT_DAYS
    assert clamp_recent_days(0) == 1
    assert clamp_recent_days(30) == STRICT_RECENT_DAYS
