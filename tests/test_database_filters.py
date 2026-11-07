from database.db import build_merged_rows, build_region_terms, connect, fetch_tenders, init_db, update_user_score, upsert_many
from database.models import Tender


def test_build_region_terms_expands_jiangsu():
    terms = build_region_terms("江苏省")

    assert "江苏" in terms
    assert "江苏省" in terms
    assert "苏州" in terms
    assert "南京" in terms


def test_init_db_creates_hot_path_indexes(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    with connect(db_path) as conn:
        index_names = {row["name"] for row in conn.execute("PRAGMA index_list(tenders)").fetchall()}

    assert "idx_tenders_source_name" in index_names
    assert "idx_tenders_recent_order" in index_names


def test_fetch_tenders_region_filter_excludes_other_provinces(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(
                title="苏州市规划馆展陈设计施工项目",
                publish_date="2026-06-05",
                region="江苏省苏州市",
                source_url="https://example.com/jiangsu",
            ),
            Tender(
                title="安徽创新馆展厅更新项目",
                publish_date="2026-06-05",
                region="安徽省合肥市",
                source_url="https://example.com/anhui",
            ),
            Tender(
                title="汤河镇农产品销售展厅招标公告",
                publish_date="2026-06-05",
                region="辽宁省辽阳市",
                source_url="https://example.com/liaoning",
            ),
        ],
    )

    rows = fetch_tenders(db_path, region="江苏省")

    assert len(rows) == 1
    assert rows[0]["title"] == "苏州市规划馆展陈设计施工项目"


def test_fetch_tenders_source_filter_excludes_other_sources(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(
                title="浙江展厅项目",
                publish_date="2026-06-05",
                source_url="https://ggzy.zj.gov.cn/1",
                source_name="浙江省公共资源交易服务平台",
            ),
            Tender(
                title="政府采购网展厅项目",
                publish_date="2026-06-05",
                source_url="https://www.ccgp.gov.cn/1",
                source_name="中国政府采购网",
            ),
        ],
    )

    rows = fetch_tenders(db_path, source_names=["浙江省公共资源交易服务平台"])

    assert len(rows) == 1
    assert rows[0]["source_name"] == "浙江省公共资源交易服务平台"


def test_explicit_empty_sources_does_not_show_unselected_inventory(tmp_path):
    db_path = tmp_path / "test.db"
    upsert_many(db_path, [Tender(title="展厅项目", source_url="https://example.com/one")])

    assert len(fetch_tenders(db_path, source_names=None)) == 1
    assert fetch_tenders(db_path, source_names=[]) == []


def test_detail_title_changes_update_same_notice_and_preserve_user_score(tmp_path):
    db_path = tmp_path / "test.db"
    original = Tender(
        title="某企业 展厅 改造项目招标公告", publish_date="2026-10-01",
        source_url="https://example.com/same-notice",
    )
    upsert_many(db_path, [original])
    saved = fetch_tenders(db_path)[0]
    update_user_score(db_path, saved["id"], 8)
    enriched = Tender(
        title="某企业展厅改造项目招标公告", publish_date="2026-10-01",
        source_url=original.source_url, budget="260000元", bid_deadline="2026-09-30",
    )
    upsert_many(db_path, [enriched])
    rows = fetch_tenders(db_path)
    assert len(rows) == 1
    assert rows[0]["id"] == saved["id"]
    assert rows[0]["user_score"] == 8
    assert rows[0]["bid_deadline_date"] == "2026-09-30"
    assert rows[0]["tender_status"] == "已截止"
    assert rows[0]["budget"] == "260000元"

    upsert_many(db_path, [original])
    retained = fetch_tenders(db_path)[0]
    assert retained["bid_deadline_date"] == "2026-09-30"
    assert retained["budget"] == "260000元"
    assert retained["user_score"] == 8


def test_fetch_tenders_date_filter_excludes_old_and_empty_dates(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(title="近期展厅项目", publish_date="2026-06-05", source_url="https://example.com/current"),
            Tender(title="旧展厅项目", publish_date="2022-07-21", source_url="https://example.com/old"),
            Tender(title="空日期展厅项目", publish_date="", source_url="https://example.com/empty"),
        ],
    )

    rows = fetch_tenders(db_path, start_date="2026-06-01", end_date="2026-06-09")

    assert [row["title"] for row in rows] == ["近期展厅项目"]


def test_fetch_tenders_source_filter_includes_ccgp_regional_alias(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(
                title="\u6e56\u5357\u5c55\u5385\u8bbe\u8ba1\u670d\u52a1\u516c\u5f00\u62db\u6807\u516c\u544a",
                publish_date="2026-06-05",
                region="\u6e56\u5357\u7701",
                source_url="https://www.ccgp.gov.cn/hunan",
                source_name="\u4e2d\u56fd\u653f\u5e9c\u91c7\u8d2d\u7f51",
            ),
            Tender(
                title="\u4e0a\u6d77\u5c55\u5385\u8bbe\u8ba1\u670d\u52a1\u516c\u5f00\u62db\u6807\u516c\u544a",
                publish_date="2026-06-05",
                region="\u4e0a\u6d77\u5e02",
                source_url="https://www.ccgp.gov.cn/shanghai",
                source_name="\u4e2d\u56fd\u653f\u5e9c\u91c7\u8d2d\u7f51",
            ),
        ],
    )

    rows = fetch_tenders(db_path, source_names=["\u6e56\u5357\u7701\u653f\u5e9c\u91c7\u8d2d\u6570\u636e"])

    assert len(rows) == 1
    assert rows[0]["region"] == "\u6e56\u5357\u7701"


def test_upsert_tender_persists_deadline_metadata(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(
                title="苏州企业展厅设计施工项目",
                publish_date="2026-06-29",
                bid_deadline="2026年07月08日 09:30",
                source_url="https://example.com/deadline",
            )
        ],
    )

    rows = fetch_tenders(db_path)

    assert rows[0]["bid_deadline_date"] == "2026-07-08"
    assert rows[0]["tender_status"] in {"理想窗口", "紧急跟进", "正常跟进", "观察", "时间不足", "已截止"}


def test_upsert_tender_persists_notice_stage(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(
                title="苏州企业展厅设计施工项目中标公告",
                announcement_type="中标公告",
                publish_date="2026-06-29",
                source_url="https://example.com/result",
            )
        ],
    )

    rows = fetch_tenders(db_path)

    assert rows[0]["notice_stage"] == "中标结果"


def test_build_merged_rows_groups_same_project_across_sources():
    rows = [
        {
            "id": 1,
            "title": "苏派盆景历史文化陈列馆展陈项目采购公告",
            "source_name": "中国政府采购网",
            "source_url": "https://example.com/1",
            "notice_stage": "可投公告",
            "tender_status": "正常跟进",
            "priority": "高优先级",
            "relevance_score": 90,
        },
        {
            "id": 2,
            "title": "苏派盆景历史文化陈列馆展陈项目",
            "source_name": "江苏省公共资源交易平台",
            "source_url": "https://example.com/2",
            "notice_stage": "可投公告",
            "tender_status": "正常跟进",
            "priority": "高优先级",
            "relevance_score": 88,
        },
    ]

    merged = build_merged_rows(rows)

    assert len(merged) == 1
    assert merged[0]["merged_count"] == 2
    assert "中国政府采购网" in merged[0]["merged_sources"]
    assert "江苏省公共资源交易平台" in merged[0]["merged_sources"]


def test_build_merged_rows_prefers_same_normalized_title_over_conflicting_project_numbers():
    rows = [
        {
            "title": "徐圩新区廉洁教育展馆内容更新升级（三次）采购公告",
            "project_no": "JSZC-ONE",
            "source_name": "来源一",
            "source_url": "https://example.com/one",
        },
        {
            "title": "徐圩新区廉洁教育 展馆 内容更新升级（三次）采购公告",
            "project_no": "JSZC-TWO",
            "source_name": "来源二",
            "source_url": "https://example.com/two",
        },
    ]

    merged = build_merged_rows(rows)

    assert len(merged) == 1
    assert merged[0]["merged_count"] == 2


def test_build_merged_rows_prefers_main_result_over_review_candidate():
    rows = [
        {
            "title": "企业总部数字展厅建设项目采购公告",
            "source_name": "待研判来源",
            "source_url": "https://example.com/review",
            "notice_stage": "可投公告",
            "tender_status": "理想窗口",
            "priority": "高优先级",
            "relevance_score": 95,
            "review_bucket": "待研判",
        },
        {
            "title": "企业总部数字展厅建设项目",
            "source_name": "主结果来源",
            "source_url": "https://example.com/main",
            "notice_stage": "情报参考",
            "tender_status": "待核验",
            "priority": "中优先级",
            "relevance_score": 70,
            "review_bucket": "主结果",
        },
    ]

    merged = build_merged_rows(rows)

    assert len(merged) == 1
    assert merged[0]["source_name"] == "主结果来源"
    assert merged[0]["review_bucket"] == "主结果"
    assert merged[0]["merged_count"] == 2


def test_user_score_persists_and_clamps(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    upsert_many(
        db_path,
        [
            Tender(
                title="企业总部展厅设计施工项目招标公告",
                publish_date="2026-06-29",
                source_url="https://example.com/score",
            )
        ],
    )

    row = fetch_tenders(db_path)[0]
    update_user_score(db_path, row["id"], 99)
    scored = fetch_tenders(db_path)[0]

    assert scored["user_score"] == 10
    assert scored["user_score_updated_at"]
