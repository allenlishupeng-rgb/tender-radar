import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import DATA_DIR, DB_PATH, KEYWORDS_PATH
from database.db import fetch_tenders
from learning.feedback import apply_learning_suggestions, build_learning_suggestions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or apply keyword suggestions from feedback labels.")
    parser.add_argument("--apply", action="store_true", help="Append suggestions to config/keywords.yaml.")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "learning_suggestions.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    keywords = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))
    rows = fetch_tenders(DB_PATH)
    suggestions = build_learning_suggestions(rows, keywords)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.apply:
        updated, changed = apply_learning_suggestions(keywords, suggestions)
        if changed:
            KEYWORDS_PATH.write_text(yaml.safe_dump(updated, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"Applied {changed} keyword suggestions")
    else:
        print(f"Wrote suggestions to {args.output}")
        print(json.dumps(suggestions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
