from datetime import date

from parsers.extractors import (
    annotate_deadline_fields,
    extract_deadline,
    is_open_for_tendering,
    normalize_deadline_date,
    normalize_publish_date,
)


def test_normalize_deadline_date_repairs_spaced_digits():
    assert normalize_deadline_date("202 6 年 7 月 13 日 8 点 30 分") == "2026-07-13"


def test_normalize_publish_date_rejects_noise_and_reads_url_date():
    assert normalize_publish_date(":") == ""
    assert normalize_publish_date("http://www.ccgp.gov.cn/cggg/dfgg/gkzb/202606/t20260616_26759510.htm") == "2026-06-16"
    assert normalize_publish_date("2026-94-08") == ""
    assert normalize_publish_date("2026-13-40 2026-07-02") == "2026-07-02"


def test_annotate_deadline_fields_marks_tender_status():
    row = {"bid_deadline": "2026年07月06日9:00"}

    annotate_deadline_fields(row, today=date(2026, 6, 29))

    assert row["bid_deadline_date"] == "2026-07-06"
    assert row["days_left"] == 7
    assert row["tender_status"] == "时间不足"
    assert not is_open_for_tendering(row, today=date(2026, 6, 29))


def test_annotate_deadline_fields_marks_insufficient_time_and_closed():
    insufficient = {"bid_deadline": "2026-07-02 09:30"}
    closed = {"bid_deadline": "2026-06-28 09:30"}

    annotate_deadline_fields(insufficient, today=date(2026, 6, 29))
    annotate_deadline_fields(closed, today=date(2026, 6, 29))

    assert insufficient["tender_status"] == "时间不足"
    assert closed["tender_status"] == "已截止"


def test_annotate_deadline_fields_marks_ideal_window():
    row = {"bid_deadline": "2026-07-21 09:30"}

    annotate_deadline_fields(row, today=date(2026, 7, 1))

    assert row["days_left"] == 20
    assert row["tender_status"] == "理想窗口"
    assert is_open_for_tendering(row, today=date(2026, 7, 1))


def test_annotate_deadline_fields_uses_structured_deadline_fallback():
    row = {"bid_deadline": "", "bid_deadline_date": "2026-07-10"}

    annotate_deadline_fields(row, today=date(2026, 7, 1))

    assert row["days_left"] == 9
    assert row["tender_status"] == "时间不足"
    assert not is_open_for_tendering(row, today=date(2026, 7, 1))


def test_extract_deadline_returns_compact_date_from_long_notice():
    text = "提交投标文件截止时间：202 6 年 7 月 13 日 8 点 30 分（北京时间）开标地点：政采云平台"

    assert extract_deadline(text) == "2026 年 7 月 13 日 8 点 30"


def test_extract_deadline_keeps_time_after_dash_date():
    assert extract_deadline("投标截止时间：2026-07-08 09:30") == "2026-07-08 09:30"
