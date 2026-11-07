"""Regression tests for the team/cloud build: 20-day rule, access gate, shared search."""

import os
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from exporters.excel_exporter import export_to_excel
from parsers.extractors import (
    MIN_ACTIONABLE_DAYS_LEFT,
    PREPARATION_DAYS,
    annotate_deadline_fields,
    extract_deadline,
    is_open_for_tendering,
    radar_today,
)
from presentation.search_report import build_search_report, load_search_report, save_search_report
from ui import team_access
from utils import shared_search


ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 7)


def row_with_days(days: int | None) -> dict:
    deadline = "" if days is None else (TODAY + timedelta(days=days)).isoformat() + " 09:30"
    return {"title": "企业展厅设计施工", "bid_deadline": deadline}


# --- 20-day hard rule -------------------------------------------------------

def test_policy_constants_match_team_rule():
    assert MIN_ACTIONABLE_DAYS_LEFT == 20
    assert PREPARATION_DAYS == 10


@pytest.mark.parametrize(
    "days, expected",
    [(None, False), (-1, False), (0, False), (19, False), (20, True), (45, True)],
)
def test_only_known_deadlines_with_twenty_days_are_open(days, expected):
    assert is_open_for_tendering(row_with_days(days), today=TODAY) is expected


def test_design_days_left_subtracts_preparation_and_never_goes_negative():
    assert annotate_deadline_fields(row_with_days(25), today=TODAY)["design_days_left"] == 15
    assert annotate_deadline_fields(row_with_days(5), today=TODAY)["design_days_left"] == 0
    assert annotate_deadline_fields(row_with_days(None), today=TODAY)["design_days_left"] is None


def test_excel_export_drops_rows_below_twenty_days(tmp_path):
    keep = row_with_days(30)
    keep["bid_deadline"] = (radar_today() + timedelta(days=30)).isoformat()
    short = {"title": "时间不足的展厅项目", "bid_deadline": (radar_today() + timedelta(days=5)).isoformat()}
    unknown = {"title": "日期不明的展厅项目", "bid_deadline": ""}
    output = export_to_excel([keep, short, unknown], tmp_path / "out.xlsx")

    df = pd.read_excel(output)

    assert df["标题"].tolist() == ["企业展厅设计施工"]


# --- Deadline extraction ----------------------------------------------------

def test_deadline_from_split_table_heading():
    text = "投标文件提交 | 截止时间 | 2026年12月01日 09时30分 | 地点：线上"
    assert extract_deadline(text).startswith("2026年12月01日")


def test_deadline_from_prose_sentence():
    text = "响应文件递交截止时间为2026-12-03 14:00。其他事项另行通知。"
    assert extract_deadline(text).startswith("2026-12-03")


def test_deadline_from_ccgp_intro_sentence():
    text = "请于2026年11月20日至2026年11月27日获取采购文件，并于 2026年12月10日 09点30分（北京时间）前提交响应文件。"
    assert extract_deadline(text).startswith("2026年12月10日")


def test_document_purchase_deadline_is_not_a_submission_deadline():
    assert extract_deadline("获取招标文件截止时间：2026年11月20日 17:00") == ""


# --- Search coverage report -------------------------------------------------

def test_search_report_counts_and_round_trip(tmp_path):
    tenders = [
        {"bid_deadline": (radar_today() + timedelta(days=30)).isoformat()},
        {"bid_deadline": (radar_today() + timedelta(days=3)).isoformat()},
        {"bid_deadline": ""},
    ]
    statuses = [
        {"source": "甲", "status": "成功", "detail_recovered_count": 2},
        {"source": "乙", "status": "访问失败/受限"},
        {"source": "丙", "status": "失败"},
    ]
    report = build_search_report(tenders, statuses, days=14, depth="deep")

    assert (report["returned"], report["eligible"], report["short"], report["unknown"]) == (3, 1, 1, 1)
    assert (report["sources"], report["failed_sources"], report["detail_recovered"]) == (3, 2, 2)
    assert report["run_at"].endswith("+08:00")

    path = tmp_path / "nested" / "report.json"
    save_search_report(report, path)
    assert load_search_report(path) == report
    assert list(path.parent.glob("*.tmp")) == []


def test_missing_or_corrupt_search_report_loads_empty(tmp_path):
    assert load_search_report(tmp_path / "missing.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_search_report(broken) == {}


# --- Shared search lock -----------------------------------------------------

def test_second_concurrent_search_is_rejected_and_lock_is_released(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow_search(**_kwargs):
        started.set()
        release.wait(5)
        return [], []

    monkeypatch.setattr(shared_search, "run_search_with_status", slow_search)
    worker = threading.Thread(target=shared_search.run_shared_search)
    worker.start()
    assert started.wait(5)
    with pytest.raises(shared_search.SearchBusyError):
        shared_search.run_shared_search()
    release.set()
    worker.join(5)

    assert shared_search.run_shared_search() == ([], [])


def test_lock_is_released_when_search_raises(monkeypatch):
    def broken_search(**_kwargs):
        raise RuntimeError("source crashed")

    monkeypatch.setattr(shared_search, "run_search_with_status", broken_search)
    with pytest.raises(RuntimeError):
        shared_search.run_shared_search()
    monkeypatch.setattr(shared_search, "run_search_with_status", lambda **_kwargs: ([], []))
    assert shared_search.run_shared_search() == ([], [])


# --- Team access gate -------------------------------------------------------

class StopApp(Exception):
    pass


class FakeForm:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeStreamlit:
    def __init__(self, supplied="", submitted=False):
        self.session_state = {}
        self.supplied, self.submitted = supplied, submitted
        self.errors = []
        self.reran = False

    def title(self, *_a, **_k): pass
    def caption(self, *_a, **_k): pass
    def form(self, *_a, **_k): return FakeForm()
    def text_input(self, *_a, **_k): return self.supplied
    def form_submit_button(self, *_a, **_k): return self.submitted
    def error(self, message): self.errors.append(message)

    def stop(self):
        raise StopApp

    def rerun(self):
        self.reran = True
        raise StopApp


def test_check_password_rejects_empty_expected_and_wrong_value():
    assert team_access.check_password("", "") is False
    assert team_access.check_password("x", "secret") is False
    assert team_access.check_password("secret", "secret") is True


def test_local_run_without_password_is_open(monkeypatch):
    monkeypatch.delenv("RADAR_TEAM_PASSWORD", raising=False)
    monkeypatch.delenv("RADAR_REQUIRE_LOGIN", raising=False)
    team_access.require_team_access(FakeStreamlit())


def test_cloud_without_password_refuses_to_open(monkeypatch):
    monkeypatch.delenv("RADAR_TEAM_PASSWORD", raising=False)
    monkeypatch.setenv("RADAR_REQUIRE_LOGIN", "true")
    st = FakeStreamlit()
    with pytest.raises(StopApp):
        team_access.require_team_access(st)
    assert st.errors


def test_wrong_password_stops_and_correct_password_authenticates(monkeypatch):
    monkeypatch.setenv("RADAR_TEAM_PASSWORD", "secret")
    wrong = FakeStreamlit("nope", submitted=True)
    with pytest.raises(StopApp):
        team_access.require_team_access(wrong)
    assert wrong.errors and "_radar_authenticated" not in wrong.session_state

    right = FakeStreamlit("secret", submitted=True)
    with pytest.raises(StopApp):
        team_access.require_team_access(right)
    assert right.reran
    team_access.require_team_access(right)  # Authenticated session passes through.


def test_changing_password_invalidates_existing_sessions(monkeypatch):
    monkeypatch.setenv("RADAR_TEAM_PASSWORD", "old")
    st = FakeStreamlit("old", submitted=True)
    with pytest.raises(StopApp):
        team_access.require_team_access(st)
    monkeypatch.setenv("RADAR_TEAM_PASSWORD", "new")
    st.submitted = False
    with pytest.raises(StopApp):
        team_access.require_team_access(st)


# --- Business timezone and storage paths -----------------------------------

def run_python(code: str, **env) -> str:
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("RADAR_")}
    child_env.update(env)
    child_env["TZ"] = "UTC"
    child_env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=child_env, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps the machine's local zone")
def test_utc_host_uses_beijing_calendar_day():
    out = run_python(
        "import config.settings, time;"
        "from datetime import date;"
        "from parsers.extractors import radar_today;"
        "print(time.strftime('%z'), date.today() == radar_today())"
    )
    assert out == "+0800 True"


def test_storage_directories_follow_environment(tmp_path):
    out = run_python(
        "from config import settings; print(settings.DB_PATH); print(settings.EXPORT_DIR)",
        RADAR_DATA_DIR=str(tmp_path / "d"),
        RADAR_EXPORT_DIR=str(tmp_path / "e"),
    )
    assert out.splitlines() == [str(tmp_path / "d" / "tender_radar.db"), str(tmp_path / "e")]


def test_public_repository_does_not_ship_private_profile_data():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config/historical_project_profile.yaml" in ignored
    assert "data/" in ignored
