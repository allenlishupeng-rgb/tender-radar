import json
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from database.models import Tender
from parsers.extractors import annotate_deadline_fields, extract_contact_person, extract_project_no
from parsers.common import clean_text
from scoring.rules import annotate_notice_stage


REGION_ALIASES = {
    "江苏": ["江苏", "江苏省", "南京", "苏州", "无锡", "常州", "镇江", "扬州", "南通", "泰州", "盐城", "淮安", "宿迁", "徐州", "连云港"],
    "上海": ["上海", "上海市"],
    "浙江": ["浙江", "浙江省", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水"],
    "安徽": ["安徽", "安徽省", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城"],
    "湖北": ["湖北", "湖北省", "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施"],
    "湖南": ["湖南", "湖南省", "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西"],
    "贵州": ["贵州", "贵州省", "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南"],
    "新疆": ["新疆", "新疆维吾尔自治区", "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰"],
    "西藏": ["西藏", "西藏自治区", "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"],
    "内蒙古": ["内蒙古", "内蒙古自治区", "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "兴安", "锡林郭勒", "阿拉善"],
    "辽宁": ["辽宁", "辽宁省", "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛"],
    "吉林": ["吉林", "吉林省", "长春", "吉林市", "四平", "辽源", "通化", "白山", "松原", "白城", "延边"],
    "黑龙江": ["黑龙江", "黑龙江省", "哈尔滨", "齐齐哈尔", "牡丹江", "佳木斯", "大庆", "鸡西", "双鸭山", "伊春", "七台河", "鹤岗", "黑河", "绥化", "大兴安岭"],
}


SOURCE_REGION_ALIASES = {
    "湖南省政府采购数据": ["湖南", "湖南省"],
    "长沙市政府采购数据": ["长沙", "长沙市"],
    "贵州省政府采购数据": ["贵州", "贵州省"],
    "贵阳市政府采购数据": ["贵阳", "贵阳市"],
    "湖南省公共资源交易数据": ["湖南", "湖南省"],
    "长沙市公共资源交易数据": ["长沙", "长沙市"],
    "贵州省公共资源交易数据": ["贵州", "贵州省"],
    "贵阳市公共资源交易数据": ["贵阳", "贵阳市"],
    "新疆维吾尔自治区公共资源交易数据": ["新疆", "新疆维吾尔自治区"],
    "西藏自治区公共资源交易数据": ["西藏", "西藏自治区"],
    "内蒙古自治区公共资源交易数据": ["内蒙古", "内蒙古自治区"],
    "辽宁省公共资源交易数据": ["辽宁", "辽宁省"],
    "吉林省公共资源交易数据": ["吉林", "吉林省"],
    "黑龙江省公共资源交易数据": ["黑龙江", "黑龙江省"],
}

SOURCE_ALIAS_BACKENDS = {
    "中国政府采购网",
    "全国公共资源交易平台",
}

MERGE_NOTICE_SUFFIXES = [
    "公开招标公告",
    "竞争性磋商公告",
    "竞争性谈判公告",
    "询价公告",
    "询比公告",
    "比选公告",
    "采购公告",
    "招标公告",
    "中标结果公告",
    "中标公告",
    "成交结果公告",
    "成交公告",
    "结果公告",
    "更正公告",
    "变更公告",
    "澄清公告",
]

MERGE_PRIORITY_ORDER = {
    "高优先级": 0,
    "中优先级": 1,
    "低优先级": 2,
    "可能无关": 3,
}

MERGE_STATUS_ORDER = {
    "理想窗口": 0,
    "正常跟进": 1,
    "紧急跟进": 2,
    "观察": 3,
    "待核验": 4,
    "时间不足": 5,
    "已截止": 6,
}

MERGE_STAGE_ORDER = {
    "可投公告": 0,
    "情报参考": 1,
    "更正澄清": 2,
    "中标结果": 3,
    "无效": 4,
}

TEXT_FIELDS = [
    "title",
    "announcement_type",
    "publish_date",
    "region",
    "purchaser",
    "agency",
    "budget",
    "project_no",
    "contact_person",
    "contact_phone",
    "bid_deadline",
    "bid_deadline_date",
    "tender_status",
    "notice_stage",
    "important_info",
    "summary",
    "priority",
    "profile_project_type",
    "profile_client_type",
    "profile_reason",
    "ai_reason",
    "ai_project_type",
    "ai_suggested_action",
    "remark",
    "feedback_label",
    "user_score_updated_at",
    "source_name",
    "review_bucket",
]


SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    announcement_type TEXT,
    publish_date TEXT,
    region TEXT,
    purchaser TEXT,
    agency TEXT,
    budget TEXT,
    project_no TEXT,
    contact_person TEXT DEFAULT '',
    contact_phone TEXT DEFAULT '',
    bid_deadline TEXT DEFAULT '',
    bid_deadline_date TEXT DEFAULT '',
    days_left INTEGER,
    tender_status TEXT DEFAULT '待核验',
    notice_stage TEXT DEFAULT '情报参考',
    important_info TEXT DEFAULT '',
    source_url TEXT NOT NULL,
    summary TEXT,
    matched_keywords TEXT,
    relevance_score INTEGER DEFAULT 0,
    priority TEXT DEFAULT '可能无关',
    profile_project_type TEXT DEFAULT '',
    profile_client_type TEXT DEFAULT '',
    profile_reason TEXT DEFAULT '',
    ai_is_relevant INTEGER,
    ai_score_adjustment INTEGER DEFAULT 0,
    ai_reason TEXT DEFAULT '',
    ai_project_type TEXT DEFAULT '',
    ai_suggested_action TEXT DEFAULT '',
    ai_classified INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 0,
    remark TEXT DEFAULT '',
    feedback_label TEXT DEFAULT '',
    user_score INTEGER,
    user_score_updated_at TEXT DEFAULT '',
    source_name TEXT,
    review_bucket TEXT DEFAULT '主结果',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(title, publish_date, source_url)
);

CREATE INDEX IF NOT EXISTS idx_tenders_publish_date ON tenders(publish_date);
CREATE INDEX IF NOT EXISTS idx_tenders_priority ON tenders(priority);
CREATE INDEX IF NOT EXISTS idx_tenders_region ON tenders(region);
CREATE INDEX IF NOT EXISTS idx_tenders_source_name ON tenders(source_name);
CREATE INDEX IF NOT EXISTS idx_tenders_source_url_date ON tenders(source_url, publish_date);
CREATE INDEX IF NOT EXISTS idx_tenders_recent_order ON tenders(publish_date DESC, relevance_score DESC, id DESC);
"""


EXTRA_COLUMNS = {
    "contact_person": "TEXT DEFAULT ''",
    "contact_phone": "TEXT DEFAULT ''",
    "bid_deadline": "TEXT DEFAULT ''",
    "bid_deadline_date": "TEXT DEFAULT ''",
    "days_left": "INTEGER",
    "tender_status": "TEXT DEFAULT '待核验'",
    "notice_stage": "TEXT DEFAULT '情报参考'",
    "important_info": "TEXT DEFAULT ''",
    "profile_project_type": "TEXT DEFAULT ''",
    "profile_client_type": "TEXT DEFAULT ''",
    "profile_reason": "TEXT DEFAULT ''",
    "ai_is_relevant": "INTEGER",
    "ai_score_adjustment": "INTEGER DEFAULT 0",
    "ai_reason": "TEXT DEFAULT ''",
    "ai_project_type": "TEXT DEFAULT ''",
    "ai_suggested_action": "TEXT DEFAULT ''",
    "ai_classified": "INTEGER DEFAULT 0",
    "feedback_label": "TEXT DEFAULT ''",
    "user_score": "INTEGER",
    "user_score_updated_at": "TEXT DEFAULT ''",
    "review_bucket": "TEXT DEFAULT '主结果'",
}


class ManagedConnection(sqlite3.Connection):
    """Commit/rollback on context exit and release the database handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, factory=ManagedConnection)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        ensure_columns(conn)


def ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(tenders)").fetchall()}
    for column, definition in EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE tenders ADD COLUMN {column} {definition}")


def sanitize_tender(tender: Tender) -> Tender:
    for field in TEXT_FIELDS:
        if hasattr(tender, field):
            setattr(tender, field, clean_text(getattr(tender, field, "") or ""))
    if tender.project_no:
        tender.project_no = extract_project_no(f"项目编号:{tender.project_no}")
    if tender.contact_person:
        tender.contact_person = extract_contact_person(f"联系人:{tender.contact_person}") or tender.contact_person
    return tender


def sanitize_row(row: dict) -> dict:
    cleaned = dict(row)
    for field in TEXT_FIELDS:
        if field in cleaned:
            cleaned[field] = clean_text(cleaned.get(field) or "")
    if cleaned.get("project_no"):
        cleaned["project_no"] = extract_project_no(f"项目编号:{cleaned['project_no']}")
    if cleaned.get("contact_person"):
        cleaned["contact_person"] = extract_contact_person(f"联系人:{cleaned['contact_person']}") or cleaned["contact_person"]
    return cleaned


def build_region_terms(region: str) -> list[str]:
    value = (region or "").strip()
    if not value or value == "全部":
        return []
    if value in {"东三省", "东北三省", "东北"}:
        value = "辽宁、吉林、黑龙江"
    short = value.replace("省", "").replace("市", "")
    raw_terms = [term.strip() for term in value.replace("，", "、").replace(",", "、").split("、") if term.strip()]
    if not raw_terms:
        raw_terms = [value]
    terms = [value, short]
    for term in raw_terms:
        terms.extend([term, term.replace("省", "").replace("市", "")])
    for province, aliases in REGION_ALIASES.items():
        if province in value or province in short or any(province in term or term in province for term in raw_terms):
            terms.extend(aliases)
    return sorted(set(term for term in terms if term))


def normalize_merge_key(row: dict) -> str:
    title = str(row.get("title") or "").lower()
    title = re.sub(r"\s+", "", title)
    title = re.sub(r"[:：,，;；。.!！?？\"'“”‘’()\[\]{}（）【】《》<>/_-]+", "", title)
    for suffix in MERGE_NOTICE_SUFFIXES:
        title = title.replace(suffix.lower(), "")
    title = re.sub(r"(第?[一二三四五六七八九十\d]+次|二次|重新招标)$", "", title)
    if title:
        return f"title:{title[:100]}"
    project_no = re.sub(r"[\s:：,，;；。()\[\]{}（）【】《》<>/_-]+", "", str(row.get("project_no") or "")).lower()
    if len(project_no) >= 6:
        return f"no:{project_no}"
    return f"url:{row.get('source_url') or id(row)}"


def merge_pick_key(row: dict):
    try:
        score = int(row.get("relevance_score") or 0)
    except (TypeError, ValueError):
        score = 0
    try:
        days_left = int(row.get("days_left")) if row.get("days_left") is not None else 9999
    except (TypeError, ValueError):
        days_left = 9999
    return (
        1 if row.get("review_bucket") == "待研判" else 0,
        MERGE_STAGE_ORDER.get(row.get("notice_stage") or "", 99),
        MERGE_STATUS_ORDER.get(row.get("tender_status") or "", 99),
        MERGE_PRIORITY_ORDER.get(row.get("display_priority") or row.get("priority") or "", 99),
        days_left,
        -score,
        str(row.get("publish_date") or ""),
    )


def build_merged_rows(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(normalize_merge_key(row), []).append(dict(row))

    merged = []
    for group_rows in groups.values():
        group_rows.sort(key=merge_pick_key)
        representative = dict(group_rows[0])
        sources = []
        urls = []
        seen_sources = set()
        seen_urls = set()
        for item in group_rows:
            source = item.get("source_name") or "未知来源"
            if source not in seen_sources:
                seen_sources.add(source)
                sources.append(source)
            url = item.get("source_url") or ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)
        scores = []
        for item in group_rows:
            try:
                if item.get("user_score") is not None and str(item.get("user_score")).strip() != "":
                    scores.append(int(item.get("user_score")))
            except (TypeError, ValueError):
                pass
        if scores and (representative.get("user_score") is None or str(representative.get("user_score")).strip() == ""):
            representative["user_score"] = max(scores) if any(score > 0 for score in scores) else min(scores)
        representative["merged_count"] = len(group_rows)
        representative["merged_sources"] = "、".join(sources)
        representative["merged_source_urls"] = json.dumps(urls, ensure_ascii=False)
        merged.append(representative)
    return merged


def upsert_tender(conn: sqlite3.Connection, tender: Tender) -> None:
    sanitize_tender(tender)
    annotate_deadline_fields(tender)
    annotate_notice_stage(tender)
    existing = conn.execute(
        "SELECT title FROM tenders WHERE source_url=? AND publish_date=? ORDER BY id LIMIT 1",
        (tender.source_url, tender.publish_date),
    ).fetchone()
    # List-page highlighting and detail-page titles can differ for the same notice.
    if existing is not None:
        tender.title = existing["title"]
    conn.execute(
        """
        INSERT INTO tenders (
            title, announcement_type, publish_date, region, purchaser, agency,
            budget, project_no, contact_person, contact_phone, bid_deadline,
            bid_deadline_date, days_left, tender_status,
            notice_stage, important_info, source_url, summary, matched_keywords,
            relevance_score, priority, profile_project_type, profile_client_type,
            profile_reason, ai_is_relevant, ai_score_adjustment, ai_reason,
            ai_project_type, ai_suggested_action, ai_classified,
            is_read, remark, feedback_label, user_score, user_score_updated_at, source_name, review_bucket
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(title, publish_date, source_url) DO UPDATE SET
            announcement_type=excluded.announcement_type,
            region=excluded.region,
            purchaser=excluded.purchaser,
            agency=excluded.agency,
            budget=COALESCE(NULLIF(excluded.budget, ''), tenders.budget),
            project_no=excluded.project_no,
            contact_person=excluded.contact_person,
            contact_phone=excluded.contact_phone,
            bid_deadline=COALESCE(NULLIF(excluded.bid_deadline, ''), tenders.bid_deadline),
            bid_deadline_date=COALESCE(NULLIF(excluded.bid_deadline_date, ''), tenders.bid_deadline_date),
            days_left=CASE WHEN excluded.bid_deadline_date='' THEN tenders.days_left ELSE excluded.days_left END,
            tender_status=CASE WHEN excluded.bid_deadline_date='' THEN tenders.tender_status ELSE excluded.tender_status END,
            notice_stage=excluded.notice_stage,
            important_info=excluded.important_info,
            summary=excluded.summary,
            matched_keywords=excluded.matched_keywords,
            relevance_score=excluded.relevance_score,
            priority=excluded.priority,
            profile_project_type=excluded.profile_project_type,
            profile_client_type=excluded.profile_client_type,
            profile_reason=excluded.profile_reason,
            ai_is_relevant=excluded.ai_is_relevant,
            ai_score_adjustment=excluded.ai_score_adjustment,
            ai_reason=excluded.ai_reason,
            ai_project_type=excluded.ai_project_type,
            ai_suggested_action=excluded.ai_suggested_action,
            ai_classified=excluded.ai_classified,
            source_name=excluded.source_name,
            review_bucket=excluded.review_bucket,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            tender.title,
            tender.announcement_type,
            tender.publish_date,
            tender.region,
            tender.purchaser,
            tender.agency,
            tender.budget,
            tender.project_no,
            tender.contact_person,
            tender.contact_phone,
            tender.bid_deadline,
            tender.bid_deadline_date,
            tender.days_left,
            tender.tender_status,
            tender.notice_stage,
            tender.important_info,
            tender.source_url,
            tender.summary,
            json.dumps(tender.matched_keywords, ensure_ascii=False),
            tender.relevance_score,
            tender.priority,
            tender.profile_project_type,
            tender.profile_client_type,
            tender.profile_reason,
            None if tender.ai_is_relevant is None else int(tender.ai_is_relevant),
            tender.ai_score_adjustment,
            tender.ai_reason,
            tender.ai_project_type,
            tender.ai_suggested_action,
            int(tender.ai_classified),
            int(tender.is_read),
            tender.remark,
            tender.feedback_label,
            tender.user_score,
            tender.user_score_updated_at,
            tender.source_name,
            tender.review_bucket,
        ),
    )


def upsert_many(db_path: Path, tenders: Iterable[Tender]) -> int:
    init_db(db_path)
    count = 0
    with connect(db_path) as conn:
        for tender in tenders:
            upsert_tender(conn, tender)
            count += 1
        conn.commit()
    return count


def fetch_tenders(
    db_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str | None = None,
    priority: str | None = None,
    source_names: list[str] | None = None,
) -> list[dict]:
    init_db(db_path)
    if source_names is not None and not source_names:
        return []
    where = []
    params = []
    if start_date:
        where.append("(publish_date IS NOT NULL AND publish_date != '' AND publish_date >= ?)")
        params.append(start_date)
    if end_date:
        where.append("(publish_date IS NOT NULL AND publish_date != '' AND publish_date <= ?)")
        params.append(end_date)
    region_terms = build_region_terms(region or "")
    if region_terms:
        searchable_fields = ["region", "title", "summary", "important_info", "purchaser", "agency"]
        clauses = []
        for term in region_terms:
            for field in searchable_fields:
                clauses.append(f"{field} LIKE ?")
                params.append(f"%{term}%")
        where.append("(" + " OR ".join(clauses) + ")")
    if priority and priority != "全部":
        where.append("priority = ?")
        params.append(priority)
    if source_names:
        source_clauses = []
        exact_source_names = []
        searchable_fields = ["region", "title", "summary", "important_info", "purchaser", "agency"]
        for source_name in source_names:
            if source_name in SOURCE_REGION_ALIASES:
                source_clauses.append("source_name = ?")
                params.append(source_name)
                region_clauses = []
                alias_params = []
                for term in SOURCE_REGION_ALIASES[source_name]:
                    for field in searchable_fields:
                        region_clauses.append(f"{field} LIKE ?")
                        alias_params.append(f"%{term}%")
                backend_placeholders = ", ".join("?" for _ in SOURCE_ALIAS_BACKENDS)
                source_clauses.append(f"(source_name IN ({backend_placeholders}) AND ({' OR '.join(region_clauses)}))")
                params.extend(SOURCE_ALIAS_BACKENDS)
                params.extend(alias_params)
            else:
                exact_source_names.append(source_name)
        if exact_source_names:
            placeholders = ", ".join("?" for _ in exact_source_names)
            source_clauses.append(f"source_name IN ({placeholders})")
            params.extend(exact_source_names)
        if source_clauses:
            where.append("(" + " OR ".join(source_clauses) + ")")

    sql = "SELECT * FROM tenders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY publish_date DESC, relevance_score DESC, id DESC"

    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [annotate_notice_stage(annotate_deadline_fields(sanitize_row(dict(row))), preserve_existing=True) for row in rows]


def fetch_source_counts(db_path: Path) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(source_name, ''), '未知来源') AS source_name,
                   COUNT(*) AS count
            FROM tenders
            GROUP BY COALESCE(NULLIF(source_name, ''), '未知来源')
            ORDER BY count DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def update_read_status(db_path: Path, tender_id: int, is_read: bool) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE tenders SET is_read=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (int(is_read), tender_id),
        )
        conn.commit()


def update_remark(db_path: Path, tender_id: int, remark: str) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE tenders SET remark=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (remark, tender_id),
        )
        conn.commit()


def update_feedback_label(db_path: Path, tender_id: int, feedback_label: str) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE tenders SET feedback_label=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (feedback_label, tender_id),
        )
        conn.commit()


def update_user_score(db_path: Path, tender_id: int, user_score: int | None) -> None:
    init_db(db_path)
    if user_score is not None:
        user_score = max(-10, min(10, int(user_score)))
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE tenders
            SET user_score=?,
                user_score_updated_at=CASE WHEN ? IS NULL THEN '' ELSE CURRENT_TIMESTAMP END,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (user_score, user_score, tender_id),
        )
        conn.commit()
