from learning.feedback import build_learning_suggestions


def test_learning_uses_numeric_user_scores():
    rows = [
        {
            "title": "企业总部展厅设计施工一体化项目招标公告",
            "matched_keywords": ["总部展厅", "设计施工一体化"],
            "user_score": 10,
        },
        {
            "title": "展会展位搭建及会务服务项目采购公告",
            "matched_keywords": ["展位", "会务服务"],
            "user_score": -5,
        },
        {
            "title": "产业园展示中心前期需求线索",
            "matched_keywords": ["展示中心"],
            "user_score": 5,
        },
    ]

    suggestions = build_learning_suggestions(rows, {})

    assert suggestions["positive_count"] == 1
    assert suggestions["negative_count"] == 1
    assert suggestions["observe_count"] == 1
    assert suggestions["scored_count"] == 3
    assert "设计施工一体化" in suggestions["positive_terms"]
    assert "展位" in suggestions["negative_terms"]
