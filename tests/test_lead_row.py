from presentation.lead_row import normalize_lead_row


def test_normalize_lead_row_preserves_shared_export_fields():
    row = normalize_lead_row(
        {
            "title": "企业展厅设计采购",
            "budget": "1000000元",
            "matched_keywords": '["企业展厅"]',
            "publish_date": "2026-07-16",
            "source_url": "https://example.com/tender/1",
            "priority": "中优先级",
            "user_score": "8",
        },
        include_display_priority=True,
    )

    assert row["user_score"] == 8
    assert row["matched_keywords"] == "企业展厅"
    assert row["display_priority"] == "高优先级"
    assert row["priority"] == "高优先级"


def test_normalize_lead_row_keeps_static_priority_unchanged():
    row = normalize_lead_row(
        {
            "title": "普通项目",
            "priority": "中优先级",
            "publish_date": "2026-07-16",
            "source_url": "https://example.com/tender/2",
        }
    )

    assert row["priority"] == "中优先级"
    assert "display_priority" not in row
