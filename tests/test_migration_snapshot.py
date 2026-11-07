from pathlib import Path

import pytest

from scripts.export_migration_markdown import build_snapshot
from scripts.restore_migration_snapshot import read_snapshot, restore_snapshot


def write_snapshot(tmp_path: Path, extra_records=None) -> tuple[Path, list[tuple[str, str]]]:
    records = [
        ("scripts/restore_migration_snapshot.py", "# Restore helper fixture\n"),
        ("module.py", "print('radar')\n"),
        ("说明.md", "中文及嵌套代码块\n````python\nprint('example')\n````"),
        ("empty.txt", ""),
    ] + (extra_records or [])
    snapshot = tmp_path / "snapshot.md"
    snapshot.write_text(build_snapshot(records), encoding="utf-8")
    return snapshot, records


def test_snapshot_round_trip_handles_unicode_fences_and_missing_final_newline(tmp_path):
    snapshot, records = write_snapshot(tmp_path)
    destination = tmp_path / "restored"

    assert restore_snapshot(snapshot, destination) == len(records)
    for name, content in records:
        assert (destination / name).read_bytes() == content.encode("utf-8")


def test_corrupted_content_is_rejected_before_creating_destination(tmp_path):
    snapshot, _ = write_snapshot(tmp_path)
    snapshot.write_text(snapshot.read_text(encoding="utf-8").replace("print('radar')", "print('changed')"), encoding="utf-8")
    destination = tmp_path / "restored"

    with pytest.raises(ValueError, match="Checksum mismatch"):
        restore_snapshot(snapshot, destination)
    assert not destination.exists()


def test_relative_path_escape_is_rejected(tmp_path):
    snapshot, _ = write_snapshot(tmp_path, [("../outside.py", "pass\n")])

    with pytest.raises(ValueError, match="Invalid relative file path"):
        read_snapshot(snapshot)
    assert not (tmp_path.parent / "outside.py").exists()


def test_case_collisions_are_rejected_for_windows_portability(tmp_path):
    snapshot, _ = write_snapshot(tmp_path, [("MODULE.py", "pass\n")])

    with pytest.raises(ValueError, match="Duplicate file path"):
        read_snapshot(snapshot)


def test_restoration_refuses_to_overwrite_an_existing_project(tmp_path):
    snapshot, _ = write_snapshot(tmp_path)
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "user.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    with pytest.raises(FileExistsError):
        restore_snapshot(snapshot, destination)
    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_truncated_snapshot_cannot_pass_checksum_and_count_validation(tmp_path):
    snapshot, _ = write_snapshot(tmp_path)
    text = snapshot.read_text(encoding="utf-8")
    snapshot.write_text(text[:text.rfind("<!-- RADAR_FILE ")], encoding="utf-8")

    with pytest.raises(ValueError, match="Incomplete snapshot"):
        read_snapshot(snapshot)
