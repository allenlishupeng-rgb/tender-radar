"""Verify and restore the Markdown source snapshot using only the standard library."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


SNAPSHOT_MARKER = "<!-- RADAR_SNAPSHOT "
FILE_MARKER = "<!-- RADAR_FILE "


def marker_metadata(line: str, marker: str) -> dict:
    value = line.strip()
    if not value.endswith(" -->"):
        raise ValueError("Incomplete snapshot metadata")
    return json.loads(value[len(marker):-4])


def read_snapshot(snapshot: Path) -> list[tuple[str, bytes]]:
    lines = snapshot.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    expected = None
    records = []
    seen = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(SNAPSHOT_MARKER):
            expected = marker_metadata(line, SNAPSHOT_MARKER)["file_count"]
        if not line.startswith(FILE_MARKER):
            index += 1
            continue
        meta = marker_metadata(line, FILE_MARKER)
        name = meta["path"]
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                or not path.parts or ":" in path.parts[0] or name != path.as_posix()):
            raise ValueError(f"Invalid relative file path: {name}")
        if name.casefold() in seen:
            raise ValueError(f"Duplicate file path: {name}")
        seen.add(name.casefold())
        fence = meta["fence"]
        if len(fence) < 3 or set(fence) != {"`"}:
            raise ValueError(f"Invalid code fence: {name}")
        index += 1
        if index >= len(lines) or lines[index].rstrip("\r\n") != fence + meta["language"]:
            raise ValueError(f"Missing opening code fence: {name}")
        index += 1
        chunks = []
        while index < len(lines) and lines[index].rstrip("\r\n") != fence:
            chunks.append(lines[index])
            index += 1
        if index == len(lines):
            raise ValueError(f"Missing closing code fence: {name}")
        content = "".join(chunks)
        if not meta["ends_with_newline"]:
            if not content.endswith("\n"):
                raise ValueError(f"Missing payload separator: {name}")
            content = content[:-1]
        payload = content.encode("utf-8")
        if len(payload) != meta["bytes"] or hashlib.sha256(payload).hexdigest() != meta["sha256"]:
            raise ValueError(f"Checksum mismatch: {name}")
        records.append((name, payload))
        index += 1
    if expected is None or len(records) != expected or not records:
        raise ValueError(f"Incomplete snapshot: expected {expected}, parsed {len(records)} files")
    return records


def restore_snapshot(snapshot: Path, destination: Path) -> int:
    records = read_snapshot(snapshot)
    root = destination.resolve()
    if root.exists():
        raise FileExistsError(f"Destination must be a new directory: {root}")
    targets = [(root / name, payload) for name, payload in records]
    if any(not path.resolve().is_relative_to(root) for path, _ in targets):
        raise ValueError("A file path escapes the destination")
    root.mkdir(parents=True)
    for path, payload in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        print(f"Verified {len(read_snapshot(args.snapshot))} files")
    elif args.destination is None:
        parser.error("destination is required unless --verify-only is used")
    else:
        print(f"Restored {restore_snapshot(args.snapshot, args.destination)} files to {args.destination.resolve()}")


if __name__ == "__main__":
    main()
