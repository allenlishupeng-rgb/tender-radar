import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import DB_PATH, KEYWORDS_PATH, SOURCES_PATH
from database.db import connect, init_db
from parsers.extractors import annotate_deadline_fields, normalize_publish_date
from scoring.rules import annotate_notice_stage, load_keywords, priority_from_score, score_tender


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild derived Project Profile Radar fields for historical rows.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite database path.")
    parser.add_argument("--limit", type=int, default=0, help="Limit rows for a trial run. Default: all rows.")
    parser.add_argument("--dry-run", action="store_true", help="Calculate and print a summary without writing changes.")
    return parser.parse_args()


def load_source_weights() -> dict[str, float]:
    config = load_keywords(SOURCES_PATH)
    return {
        source.get("name", ""): float(source.get("source_weight", 1) or 1)
        for source in config.get("sources", [])
        if source.get("name")
    }


def apply_source_weight(row: dict, source_weights: dict[str, float]) -> dict:
    weight = source_weights.get(row.get("source_name", ""), 1)
    if 0 < weight < 1 and int(row.get("relevance_score") or 0) > 0:
        row["relevance_score"] = max(1, int(round(int(row.get("relevance_score") or 0) * weight)))
        row["priority"] = priority_from_score(row["relevance_score"])
    return row


def rebuild_row(row: dict, keywords: dict, source_weights: dict[str, float]) -> dict:
    scored = score_tender(dict(row), keywords)
    apply_source_weight(scored, source_weights)
    scored["publish_date"] = normalize_publish_date(scored.get("publish_date", "")) or normalize_publish_date(scored.get("source_url", ""))
    annotate_deadline_fields(scored)
    annotate_notice_stage(scored, preserve_existing=True)
    return scored


def main() -> None:
    args = parse_args()
    init_db(args.db)
    keywords = load_keywords(KEYWORDS_PATH)
    source_weights = load_source_weights()
    limit_clause = " LIMIT ?" if args.limit else ""
    params = (args.limit,) if args.limit else ()

    with connect(args.db) as conn:
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM tenders ORDER BY id{limit_clause}", params).fetchall()]
        rebuilt = [rebuild_row(row, keywords, source_weights) for row in rows]
        stage_counts = Counter(row.get("notice_stage") or "未标记" for row in rebuilt)
        status_counts = Counter(row.get("tender_status") or "待核验" for row in rebuilt)

        if not args.dry_run:
            for row in rebuilt:
                conn.execute(
                    """
                    UPDATE tenders
                    SET publish_date=?,
                        notice_stage=?,
                        bid_deadline_date=?,
                        days_left=?,
                        tender_status=?,
                        matched_keywords=?,
                        relevance_score=?,
                        priority=?,
                        profile_project_type=?,
                        profile_client_type=?,
                        profile_reason=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        row.get("publish_date", ""),
                        row.get("notice_stage", ""),
                        row.get("bid_deadline_date", ""),
                        row.get("days_left"),
                        row.get("tender_status", ""),
                        json.dumps(row.get("matched_keywords") or [], ensure_ascii=False),
                        int(row.get("relevance_score") or 0),
                        row.get("priority", ""),
                        row.get("profile_project_type", ""),
                        row.get("profile_client_type", ""),
                        row.get("profile_reason", ""),
                        row["id"],
                    ),
                )
            conn.commit()

    action = "Dry run" if args.dry_run else "Updated"
    print(f"{action} {len(rebuilt)} rows")
    print("公告阶段：" + "；".join(f"{name} {count}" for name, count in stage_counts.items()))
    print("可投状态：" + "；".join(f"{name} {count}" for name, count in status_counts.items()))


if __name__ == "__main__":
    main()
