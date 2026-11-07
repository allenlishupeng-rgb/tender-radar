from pathlib import Path

from database.db import connect, fetch_tenders, init_db
from parsers.common import clean_text
from parsers.extractors import build_important_info, extract_contact_person, extract_project_no


def test_clean_text_strips_encoded_html_fragments():
    text = "项目编号：&lt;span id='1' data-tag-id='1'&gt;JSZC-320211-SXZT-G2026-0011&lt;/span&gt;"

    cleaned = clean_text(text)

    assert "<span" not in cleaned
    assert "data-tag" not in cleaned
    assert "JSZC-320211-SXZT-G2026-0011" in cleaned


def test_clean_text_strips_truncated_tag_tail():
    assert clean_text("招标公告 <span...") == "招标公告"


def test_extract_labeled_fields_ignore_html_and_next_labels():
    text = (
        "项目编号：&lt;span id='1' title='项目编号' data-tag-id='1'&gt;"
        "JSZC-320211-SXZT-G2026-0011&lt;/span&gt; 招标项目 "
        "项目联系人：朱才俊&lt;/p&gt;&lt;p&gt;联系电话:0510-85598692"
    )

    assert extract_project_no(text) == "JSZC-320211-SXZT-G2026-0011"
    assert extract_contact_person(text) == "朱才俊"


def test_extract_project_no_rejects_project_name_leakage():
    text = "项目编号：2.项目名称:苏地2024-WG-Z22号地块项目物料制作、宣传及展厅配套服务"

    assert extract_project_no(text) == ""


def test_important_info_drops_markup_artifacts():
    text = (
        "预算金额：&lt;span data-tag-type='span'&gt;119.169101万元&lt;/span&gt;；"
        "项目编号：&lt;span id='1'&gt;JSZC-320211-SXZT-G2026-0011&lt;/span&gt;"
    )

    important_info = build_important_info(text)

    assert "<" not in important_info
    assert "data-tag" not in important_info
    assert "119.169101万元" in important_info
    assert "JSZC-320211-SXZT-G2026-0011" in important_info


def test_fetch_tenders_sanitizes_existing_dirty_rows(tmp_path: Path):
    db_path = tmp_path / "dirty.db"
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tenders (
                title, publish_date, source_url, project_no, contact_person, important_info, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "科技展厅布展项目",
                "2026-07-01",
                "https://example.com/dirty",
                "&lt;span data-tag-id='1'&gt;JSZC-001&lt;/span&gt;",
                "朱才俊&lt;/p&gt;&lt;p&gt;联系电话:0510-85598692",
                "项目编号：&lt;span data-tag-id='1'&gt;JSZC-001&lt;/span&gt;",
                "正文&lt;span class='x'&gt;内容&lt;/span&gt;",
            ),
        )
        conn.commit()

    row = fetch_tenders(db_path)[0]

    assert row["project_no"] == "JSZC-001"
    assert row["contact_person"] == "朱才俊"
    assert "<" not in row["important_info"]
    assert "data-tag" not in row["important_info"]
