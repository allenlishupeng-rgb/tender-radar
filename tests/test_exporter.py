import pandas as pd
from datetime import timedelta

from exporters.excel_exporter import export_to_excel
from utils.text_format import normalize_budget
from parsers.extractors import radar_today


FUTURE_DEADLINE = radar_today() + timedelta(days=25)


def test_normalize_budget_repairs_wrong_yuan_symbol():
    assert normalize_budget("2941550.00呎") == "2941550元"
    assert normalize_budget("600000.00円") == "600000元"
    assert normalize_budget("118.000000万元") == "118万元"
    assert normalize_budget("￥160.000000万元（人民币）") == "160万元"


def test_export_to_excel_cleans_budget_and_includes_submission_columns(tmp_path):
    output = tmp_path / "leads.xlsx"
    export_to_excel(
        [
            {
                "display_priority": "低优先级",
                "priority": "可能无关",
                "relevance_score": 70,
                "user_score": 8,
                "source_name": "苏州市公共资源交易平台",
                "announcement_type": "中标公告",
                "title": "展示中心布展服务",
                "region": "苏州市吴江区",
                "budget": "2941550.00呎",
                "publish_date": "2026-05-25",
                "bid_deadline": FUTURE_DEADLINE.strftime("%Y年%m月%d日 09:30"),
                "purchaser": "",
                "agency": "",
                "contact_person": "",
                "contact_phone": "",
                "matched_keywords": ["展厅", "布展"],
                "source_url": "https://example.com/detail",
            }
        ],
        output,
    )

    df = pd.read_excel(output)

    assert list(df.columns[:15]) == [
        "建议动作",
        "质量分",
        "风险",
        "判断依据",
        "你的评分",
        "优先级",
        "评分",
        "画像项目类型",
        "画像客户类型",
        "画像理由",
        "公告阶段",
        "可投状态",
        "剩余天数",
        "合并条数",
        "合并来源",
    ]
    assert df.loc[0, "你的评分"] == 8
    assert df.loc[0, "建议动作"] in {"情报复盘", "人工筛选", "暂不跟进"}
    assert df.loc[0, "质量分"] >= 0
    assert df.loc[0, "公告阶段"] == "中标结果"
    assert df.loc[0, "预算"] == "2941550元"
    assert df.loc[0, "命中关键词"] == "展厅、布展"
    assert df.loc[0, "截止日期"] == FUTURE_DEADLINE.isoformat()
