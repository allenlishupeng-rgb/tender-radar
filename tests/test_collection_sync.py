import json
import os
import subprocess
from datetime import timedelta

import pytest

from collection_sync import bundle as sync
from database.db import fetch_tenders, update_remark, update_user_score, upsert_many
from database.models import Tender
from parsers.extractors import radar_today
from scripts import collect_and_sync


TODAY = radar_today()


def sample(url="https://example.com/a", **extra):
    values = dict(
        title="企业总部展厅设计施工项目招标公告",
        publish_date=TODAY.isoformat(),
        source_url=url,
        source_name="江苏省公共资源交易平台",
        budget="300万元",
        bid_deadline=(TODAY + timedelta(days=30)).isoformat() + " 09:30",
        matched_keywords=["展厅", "设计施工"],
        relevance_score=88,
        priority="高优先级",
        notice_stage="可投公告",
    )
    values.update(extra)
    return Tender(**values)


def raw(bundle):
    return json.dumps(bundle, ensure_ascii=False).encode("utf-8")


@pytest.fixture(autouse=True)
def no_sync_env(monkeypatch):
    for name in ("RADAR_SYNC_URL", "RADAR_SYNC_TOKEN", "RADAR_SYNC_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_bundle_never_contains_personal_fields():
    local = sample(remark="私人备注", user_score=9, feedback_label="这是我的菜", is_read=True)
    row = sync.build_bundle([local])["rows"][0]

    assert not sync.PERSONAL_FIELDS & set(row)
    assert row["title"] == local.title and row["budget"] == "300万元"


def test_round_trip_from_database_rows(tmp_path):
    db = tmp_path / "local.db"
    upsert_many(db, [sample()])
    rows = fetch_tenders(db)

    tenders, meta = sync.parse_bundle(raw(sync.build_bundle(rows, window=("2026-10-09", "2026-11-07"))))

    assert meta["row_count"] == 1 and meta["window"] == {"start": "2026-10-09", "end": "2026-11-07"}
    assert tenders[0].matched_keywords == ["展厅", "设计施工"]
    assert tenders[0].days_left == 30


def test_import_keeps_team_scores_and_remarks(tmp_path):
    cloud = tmp_path / "cloud.db"
    upsert_many(cloud, [sample(budget="")])
    row_id = fetch_tenders(cloud)[0]["id"]
    update_user_score(cloud, row_id, 9)
    update_remark(cloud, row_id, "王工已联系采购人")

    result = sync.import_bundle(cloud, raw(sync.build_bundle([sample()])), state_path=tmp_path / "s.json")

    row = fetch_tenders(cloud)[0]
    assert result["imported"] == 1
    assert (row["user_score"], row["remark"], row["budget"]) == (9, "王工已联系采购人", "300万元")
    assert len(fetch_tenders(cloud)) == 1


def test_same_bundle_is_imported_once(tmp_path):
    data = raw(sync.build_bundle([sample()]))
    state = tmp_path / "s.json"
    assert sync.import_bundle(tmp_path / "c.db", data, state_path=state)["skipped"] is False
    assert sync.import_bundle(tmp_path / "c.db", data, state_path=state)["skipped"] is True


def test_signature_is_required_and_checked_when_key_is_set():
    signed = sync.build_bundle([sample()], key="k1")
    assert sync.parse_bundle(raw(signed), key="k1")[1]["signed"] is True

    tampered = dict(signed, rows=[dict(signed["rows"][0], budget="9999万元")])
    with pytest.raises(sync.BundleError, match="签名"):
        sync.parse_bundle(raw(tampered), key="k1")
    with pytest.raises(sync.BundleError, match="签名"):
        sync.parse_bundle(raw(sync.build_bundle([sample()], key="")), key="k1")
    with pytest.raises(sync.BundleError, match="签名"):
        sync.parse_bundle(raw(signed), key="other")


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "", "ftp://example.com/x"])
def test_rows_with_unsafe_links_are_rejected(bad_url):
    bundle = sync.build_bundle([sample(url=bad_url)])
    with pytest.raises(sync.BundleError, match="链接"):
        sync.parse_bundle(raw(bundle))


@pytest.mark.parametrize("payload", [b"not json", b"[]", json.dumps({"format": "x"}).encode()])
def test_non_bundles_are_rejected(payload):
    with pytest.raises(sync.BundleError):
        sync.parse_bundle(payload)


def test_wrong_types_are_coerced_not_crashing():
    bundle = sync.build_bundle([sample()])
    bundle["rows"][0].update({"relevance_score": "abc", "days_left": "x", "publish_date": "昨天",
                              "matched_keywords": "展厅", "summary": 123})
    tender = sync.parse_bundle(raw(bundle))[0][0]
    assert (tender.relevance_score, tender.days_left, tender.publish_date) == (0, None, "")
    assert tender.matched_keywords == [] and tender.summary == "123"


def test_pull_is_throttled_and_failures_are_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_SYNC_URL", "https://api.github.com/repos/o/r/contents/collection_bundle.json")
    state = tmp_path / "s.json"
    calls = []
    data = raw(sync.build_bundle([sample()]))

    def fetcher(url, token):
        calls.append(url)
        return data

    first = sync.pull_and_import(tmp_path / "c.db", state_path=state, fetcher=fetcher, now=1000)
    assert first["imported"] == 1
    assert sync.pull_and_import(tmp_path / "c.db", state_path=state, fetcher=fetcher, now=1000 + 60) is None
    assert len(calls) == 1
    forced = sync.pull_and_import(tmp_path / "c.db", force=True, state_path=state, fetcher=fetcher, now=1000 + 60)
    assert forced["skipped"] is True

    def broken(url, token):
        raise sync.BundleError("同步地址返回 HTTP 404")

    later = 1000 + 60 + sync.AUTO_PULL_INTERVAL_SECONDS + 1  # forced pull reset the clock
    assert "404" in sync.pull_and_import(tmp_path / "c.db", state_path=state, fetcher=broken, now=later)["error"]
    assert "404" in sync.load_sync_state(state)["last_result"]


def test_no_url_means_no_pull(tmp_path):
    assert sync.pull_and_import(tmp_path / "c.db", state_path=tmp_path / "s.json") is None


def test_collector_bundles_local_inventory_without_searching(tmp_path, monkeypatch):
    db = tmp_path / "local.db"
    upsert_many(db, [sample(), sample(url="https://example.com/old", publish_date="2020-01-01")])
    monkeypatch.setattr(collect_and_sync, "DB_PATH", db)
    output = tmp_path / "bundle.json"

    assert collect_and_sync.main(["--skip-search", "--days", "30", "--output", str(output)]) == 0

    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert [row["source_url"] for row in bundle["rows"]] == ["https://example.com/a"]


def test_collector_refuses_to_publish_into_the_public_source_repo(tmp_path):
    with pytest.raises(SystemExit, match="公开仓库"):
        collect_and_sync.check_publish_dir(collect_and_sync.ROOT / "config")


def test_collector_commits_into_private_data_clone(tmp_path):
    repo = tmp_path / "data-repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    bundle_path = sync.write_bundle(sync.build_bundle([sample()]), tmp_path / "b.json")

    assert collect_and_sync.publish(bundle_path, repo, push=False) == "已提交到本地数据仓库（未推送）"
    assert collect_and_sync.publish(bundle_path, repo, push=False) == "采集包与上次相同，无需提交"
    assert (repo / "collection_bundle.json").is_file()


# --- One-time setup on the collecting computer -------------------------------

def make_clone(tmp_path, remote_url="https://github.com/allen/tender-radar-data.git"):
    repo = tmp_path / "data-repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote_url], check=True)
    return repo


def test_github_remote_parsing(tmp_path):
    assert collect_and_sync.github_remote(make_clone(tmp_path)) == ("allen", "tender-radar-data")
    ssh = make_clone(tmp_path / "ssh", "git@github.com:allen/data.git")
    assert collect_and_sync.github_remote(ssh) == ("allen", "data")


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def test_visibility_reads_anonymous_github_api():
    assert collect_and_sync.github_visibility("a", "b", getter=lambda *a, **k: FakeResponse(404)) == "private"
    assert collect_and_sync.github_visibility("a", "b", getter=lambda *a, **k: FakeResponse(200, {"private": False})) == "public"
    assert collect_and_sync.github_visibility("a", "b", getter=lambda *a, **k: FakeResponse(403)) == "unknown"


def test_publishing_to_a_public_data_repo_is_refused(tmp_path, monkeypatch):
    repo = make_clone(tmp_path)
    monkeypatch.setattr(collect_and_sync, "github_visibility", lambda owner, name: "public")
    with pytest.raises(SystemExit, match="公开"):
        collect_and_sync.check_publish_dir(repo)


def test_setup_saves_key_and_prints_cloud_secrets(tmp_path, monkeypatch, capsys):
    repo = make_clone(tmp_path)
    # parse_args() writes os.environ; register the variables so monkeypatch
    # removes them again after this test.
    for name in ("RADAR_SYNC_KEY", "RADAR_COLLECTOR_NAME"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    config_path = tmp_path / "sync.local.yaml"
    monkeypatch.setattr(collect_and_sync, "LOCAL_CONFIG_PATH", config_path)
    monkeypatch.setattr(collect_and_sync, "github_visibility", lambda owner, name: "private")

    assert collect_and_sync.main(["--setup", str(repo)]) == 0

    saved = collect_and_sync.load_local_config()
    out = capsys.readouterr().out
    assert saved["publish_dir"] == str(repo.resolve()) and len(saved["sync_key"]) >= 40
    assert 'RADAR_SYNC_URL = "https://api.github.com/repos/allen/tender-radar-data/contents/collection_bundle.json"' in out
    assert f'RADAR_SYNC_KEY = "{saved["sync_key"]}"' in out

    # Running setup again keeps the same key, so the cloud secret stays valid.
    collect_and_sync.main(["--setup", str(repo)])
    assert collect_and_sync.load_local_config()["sync_key"] == saved["sync_key"]

    # Later runs pick up the saved directory and sign with the saved key.
    args = collect_and_sync.parse_args([])
    assert args.publish_dir == repo.resolve()
    assert os.environ["RADAR_SYNC_KEY"] == saved["sync_key"]


def test_missing_git_gives_install_hint(tmp_path, monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(collect_and_sync.subprocess, "run", no_git)
    with pytest.raises(SystemExit, match="Git for Windows"):
        collect_and_sync.git(tmp_path, "status")


def test_git_timeout_is_reported_not_raised(tmp_path, monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(collect_and_sync.subprocess, "run", slow)
    result = collect_and_sync.git(tmp_path, "ls-remote", timeout=5)
    assert result.returncode == 124
    assert "超过 5 秒" in collect_and_sync.git_error(result)


def test_git_output_is_decoded_as_utf8_without_prompting(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 128, "", "致命错误：认证失败\n")

    monkeypatch.setattr(collect_and_sync.subprocess, "run", fake_run)
    result = collect_and_sync.git(tmp_path, "ls-remote")
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert collect_and_sync.git_error(result) == "致命错误：认证失败"


def test_check_reports_unreachable_remote_with_git_reason(tmp_path, monkeypatch, capsys):
    repo = make_clone(tmp_path, "https://github.com/allen/tender-radar-data.git")
    for name in ("RADAR_SYNC_KEY", "RADAR_SYNC_REPO_DIR"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("RADAR_SYNC_KEY", "k")
    monkeypatch.setattr(collect_and_sync, "LOCAL_CONFIG_PATH", tmp_path / "none.yaml")
    monkeypatch.setattr(collect_and_sync, "github_visibility", lambda owner, name: "private")
    real_git = collect_and_sync.git

    def fake_git(repo_path, *args, **kwargs):
        if args[:1] == ("ls-remote",):
            return subprocess.CompletedProcess(args, 128, "", "fatal: Authentication failed\n")
        return real_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(collect_and_sync, "git", fake_git)
    assert collect_and_sync.main(["--check", "--publish-dir", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "[通过] 数据仓库 allen/tender-radar-data：私有" in out
    assert "[问题] 连不上数据仓库：fatal: Authentication failed" in out
