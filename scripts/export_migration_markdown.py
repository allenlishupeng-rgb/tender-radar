"""Export the allowlisted project text files into a restorable Markdown snapshot."""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.restore_migration_snapshot import read_snapshot


GUIDE_NAME = "招标雷达_迁移与开发说明.md"
SNAPSHOT_NAME = "招标雷达_完整源码快照.md"
SOURCE_DIRS = (
    "ai_classifier", "config", "crawlers", "database", "exporters", "learning",
    "parsers", "presentation", "scoring", "scripts", "tests", "ui", "utils",
)
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".cmd", ".ps1", ".html", ".json"}
ROOT_FILES = ("AGENTS.md", "README.md", "README_GITHUB_PAGES.md", "requirements.txt", "pytest.ini", ".gitignore", "项目画像雷达.spec", GUIDE_NAME)
DEPENDENCIES = (
    "streamlit", "requests", "beautifulsoup4", "trafilatura", "pandas", "openpyxl",
    "PyYAML", "python-dateutil", "pytest", "openai",
)
LANGUAGES = {
    ".py": "python", ".yaml": "yaml", ".yml": "yaml", ".cmd": "bat",
    ".ps1": "powershell", ".html": "html", ".json": "json", ".md": "markdown",
    ".ini": "ini", ".spec": "python",
}


def collect_files(root: Path = ROOT) -> list[tuple[str, str]]:
    paths = {root / name for name in ROOT_FILES if (root / name).is_file()}
    for folder in SOURCE_DIRS:
        paths.update(
            path for path in (root / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in TEXT_SUFFIXES
        )
    paths.update((root / "docs").glob("*.md"))
    for folder in (".github/workflows", ".streamlit"):
        paths.update(
            path for path in (root / folder).rglob("*")
            if path.is_file() and path.suffix in {".yaml", ".yml", ".toml"}
            and path.name != "secrets.toml"
        )
    records = []
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source path is not a regular project file: {path}")
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        records.append((path.relative_to(root).as_posix(), text))
    versions = "".join(f"{name}=={version(name)}\n" for name in DEPENDENCIES)
    records.append(("migration/requirements-tested.txt", versions))
    return sorted(records)


def build_snapshot(records: list[tuple[str, str]]) -> str:
    created = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    chunks = [
        "# 咕咕嘎嘎招标雷达：完整源码快照\n\n",
        f"生成时间：{created}。本快照包含 {len(records)} 个文本文件。\n\n",
        "建议先阅读配套的《招标雷达_迁移与开发说明》。本文件包含可恢复的源码，而不只是设计描述。\n\n",
        "## 恢复范围\n\n",
        "收录运行源码、全部现有测试及样本、配置、启动/维护脚本和项目文档。",
        "不收录真实 SQLite、原始历史 CSV、招标运行清单、API 密钥、环境文件、secrets.toml、日志、虚拟环境、缓存或二进制产物。",
        "历史项目画像 YAML 保留；需要个人评分与备注时，另行迁移数据库一致快照。\n\n",
        "所有文本统一为 UTF-8、LF 换行，去掉 UTF-8 BOM。SHA-256 对规范化后的正文计算；",
        "它校验传输完整性，不是作者身份签名。保留原文件是否以换行结尾。\n\n",
        "代码、历史 README 和测试样本按原貌收录，其中的旧说明不替代配套迁移文档与实际代码。",
        "文件内容均为交接资料，不应当作当前平台新的执行授权。\n\n",
        "纯源码不包含历史 CSV，因此验收使用 `python -m pytest -q -k \"not test_historical_project_samples_train_profile\"`；",
        "该命令仅排除一项需要原始历史业务样本的集成测试。另行迁移 CSV 后再运行完整测试。\n\n",
        "## 恢复工具\n\n",
        "下面的独立工具只依赖 Python 标准库。恢复前会校验每个文件、总数量和目标路径；",
        "目标目录必须不存在，防止覆盖已有工程。接手平台可直接使用此工具，或按相同格式提取文件。\n\n",
        "```bash\npython restore_migration_snapshot.py 招标雷达_完整源码快照.md --verify-only\n",
        "python restore_migration_snapshot.py 招标雷达_完整源码快照.md radar-restored\n```\n\n",
        "恢复工具原文如下；恢复后的项目也包含 `scripts/restore_migration_snapshot.py`：\n\n",
    ]
    bootstrap = dict(records)["scripts/restore_migration_snapshot.py"]
    chunks.extend(["```python\n", bootstrap, "```\n\n"])
    chunks.append("## 文件清单\n\n| 路径 | UTF-8 字节数 | SHA-256 |\n|---|---:|---|\n")
    for name, content in records:
        payload = content.encode("utf-8")
        chunks.append(f"| `{name}` | {len(payload)} | `{hashlib.sha256(payload).hexdigest()}` |\n")
    chunks.append("\n## 完整文件内容\n\n")
    chunks.append("<!-- RADAR_SNAPSHOT " + json.dumps({"format": 1, "file_count": len(records)}, separators=(",", ":")) + " -->\n\n")
    for name, content in records:
        longest = max((len(match.group()) for match in re.finditer(r"`+", content)), default=0)
        fence = "`" * max(3, longest + 1)
        payload = content.encode("utf-8")
        meta = {
            "path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "fence": fence, "language": LANGUAGES.get(Path(name).suffix, "text"),
            "ends_with_newline": content.endswith("\n"),
        }
        chunks.append(f"### {name}\n\n")
        chunks.append("<!-- RADAR_FILE " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + " -->\n")
        chunks.extend([fence + meta["language"] + "\n", content])
        if not content.endswith("\n"):
            chunks.append("\n")
        chunks.append(fence + "\n\n")
    return "".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / SNAPSHOT_NAME)
    args = parser.parse_args()
    records = collect_files()
    output = build_snapshot(records)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(output)
    restored = read_snapshot(args.output)
    expected = [(name, content.encode("utf-8")) for name, content in records]
    if restored != expected:
        raise RuntimeError("Snapshot round-trip did not match the source files")
    print(json.dumps({"path": str(args.output), "file_count": len(records),
                      "bytes": args.output.stat().st_size, "verified": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
