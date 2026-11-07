import os
from datetime import timedelta
from pathlib import Path

from database.db import (
    fetch_tenders,
    is_pending_deadline_verification,
    update_verified_deadline,
    upsert_many,
)
from database.models import Tender
from parsers.extractors import is_open_for_tendering, radar_today


ROOT = Path(__file__).resolve().parents[1]
TODAY = radar_today()


def bid(**extra):
    values = dict(
        title="企业总部展厅设计施工项目招标公告",
        publish_date=TODAY.isoformat(),
        source_url="https://example.com/verify",
        source_name="江苏省公共资源交易平台",
        relevance_score=88,
        priority="高优先级",
        notice_stage="可投公告",
    )
    values.update(extra)
    return Tender(**values)


def only_row(db):
    rows = fetch_tenders(db)
    assert len(rows) == 1
    return rows[0]


def test_pending_rule_covers_only_relevant_open_bids_without_deadline():
    base = {"days_left": None, "notice_stage": "可投公告", "review_bucket": "主结果", "priority": "高优先级"}
    assert is_pending_deadline_verification(base)
    assert not is_pending_deadline_verification({**base, "days_left": 25})
    assert not is_pending_deadline_verification({**base, "notice_stage": "中标结果"})
    assert not is_pending_deadline_verification({**base, "review_bucket": "待研判"})
    assert not is_pending_deadline_verification({**base, "priority": "可能无关"})
    assert not is_pending_deadline_verification({**base, "display_priority": "可能无关"})


def test_verified_deadline_makes_bid_open_and_survives_later_crawls(tmp_path):
    db = tmp_path / "t.db"
    upsert_many(db, [bid()])
    row = only_row(db)
    assert is_pending_deadline_verification(row)

    update_verified_deadline(db, row["id"], TODAY + timedelta(days=25))
    row = only_row(db)
    assert row["days_left"] == 25 and row["deadline_verified_at"]
    assert is_open_for_tendering(row) and not is_pending_deadline_verification(row)

    # A later crawl without a deadline, or with a misread one, keeps the human value.
    upsert_many(db, [bid()])
    upsert_many(db, [bid(bid_deadline=(TODAY + timedelta(days=3)).isoformat())])
    assert only_row(db)["days_left"] == 25


def test_unverified_rows_still_take_crawled_deadlines(tmp_path):
    db = tmp_path / "t.db"
    upsert_many(db, [bid()])
    upsert_many(db, [bid(bid_deadline=(TODAY + timedelta(days=22)).isoformat())])
    assert only_row(db)["days_left"] == 22


def test_clearing_verification_returns_row_to_pending(tmp_path):
    db = tmp_path / "t.db"
    upsert_many(db, [bid()])
    row_id = only_row(db)["id"]
    update_verified_deadline(db, row_id, TODAY + timedelta(days=25))
    update_verified_deadline(db, row_id, None)
    row = only_row(db)
    assert row["deadline_verified_at"] == "" and is_pending_deadline_verification(row)


def test_workbench_moves_verified_bid_into_main_list(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from config import settings

    db = tmp_path / "ui.db"
    upsert_many(db, [bid()])
    monkeypatch.setattr(settings, "DB_PATH", db)
    for name in ("RADAR_TEAM_PASSWORD", "RADAR_REQUIRE_LOGIN", "RADAR_SYNC_URL", "RADAR_COLLECTION_MODE"):
        monkeypatch.delenv(name, raising=False)

    at = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("待核验：截止日期不明（1）" in e.label for e in at.expander)
    key = f"verify_deadline_{only_row(db)['id']}"
    at.date_input(key).set_value(TODAY + timedelta(days=26)).run()
    next(b for b in at.button if b.label == "保存日期").click().run()

    assert not at.exception
    assert not any("待核验" in e.label for e in at.expander)
    assert any("剩余 26 天，已进入主列表" in s.value for s in at.success)
    assert "（人工核验）" in " ".join(m.value for m in at.markdown)
