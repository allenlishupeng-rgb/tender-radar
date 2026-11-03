from pathlib import Path

import pandas as pd

from utils.text_format import normalize_budget, normalize_matched_keywords, repair_text
from parsers.extractors import annotate_deadline_fields, is_open_for_tendering
from scoring.lead_quality import annotate_lead_quality
from scoring.rules import annotate_notice_stage


EXPORT_COLUMNS = {
    "lead_action": "建议动作",
    "lead_quality_score": "质量分",
    "lead_risk_level": "风险",
    "lead_reason": "判断依据",
    "user_score": "你的评分",
    "priority": "优先级",
    "relevance_score": "评分",
    "profile_project_type": "画像项目类型",
    "profile_client_type": "画像客户类型",
    "profile_reason": "画像理由",
    "notice_stage": "公告阶段",
    "tender_status": "可投状态",
    "days_left": "剩余天数",
    "merged_count": "合并条数",
    "merged_sources": "合并来源",
    "source_name": "来源",
    "announcement_type": "公告类型",
    "title": "标题",
    "region": "地区",
    "budget": "预算",
    "publish_date": "发布时间",
    "bid_deadline_date": "截止日期",
    "bid_deadline": "投标/响应截止",
    "purchaser": "采购人",
    "agency": "代理机构",
    "contact_person": "联系人",
    "contact_phone": "联系电话",
    "matched_keywords": "命中关键词",
    "ai_suggested_action": "AI建议",
    "ai_project_type": "AI项目类型",
    "ai_score_adjustment": "AI评分调整",
    "ai_reason": "AI判断原因",
    "important_info": "重要信息",
    "summary": "摘要",
    "source_url": "原文链接",
    "feedback_label": "样本标记",
    "remark": "备注",
    "design_days_left": "准备10天后可用天数",
}

PRIORITY_ORDER = {
    "高优先级": 0,
    "中优先级": 1,
    "低优先级": 2,
    "可能无关": 3,
}

TENDER_STATUS_ORDER = {
    "紧急跟进": 0,
    "正常跟进": 1,
    "观察": 2,
    "待核验": 3,
    "时间不足": 4,
    "已截止": 5,
}

NOTICE_STAGE_ORDER = {
    "可投公告": 0,
    "情报参考": 1,
    "更正澄清": 2,
    "中标结果": 3,
    "无效": 4,
}

ACTION_ORDER = {
    "立即跟进": 0,
    "进入跟进池": 1,
    "机会池观察": 2,
    "人工筛选": 3,
    "情报复盘": 4,
    "暂不跟进": 5,
}


def export_to_excel(rows: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row for row in rows if is_open_for_tendering(row)])
    if df.empty:
        df = pd.DataFrame(columns=EXPORT_COLUMNS.keys())

    for col in EXPORT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = pd.DataFrame([annotate_lead_quality(annotate_notice_stage(annotate_deadline_fields(row))) for row in df.to_dict("records")])
    for col in EXPORT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    for col in df.columns:
        if col == "budget":
            df[col] = df[col].apply(normalize_budget)
        elif col == "matched_keywords":
            df[col] = df[col].apply(normalize_matched_keywords)
        elif df[col].dtype == "object":
            df[col] = df[col].apply(repair_text)

    if "display_priority" in df.columns:
        df["priority"] = df["display_priority"].where(df["display_priority"].astype(str).str.len() > 0, df["priority"])

    df["priority_sort"] = df["priority"].map(PRIORITY_ORDER).fillna(99)
    df["action_sort"] = df["lead_action"].map(ACTION_ORDER).fillna(99)
    df["user_score_sort"] = pd.to_numeric(df["user_score"], errors="coerce").fillna(-99)
    df["notice_stage_sort"] = df["notice_stage"].map(NOTICE_STAGE_ORDER).fillna(99)
    df["tender_status_sort"] = df["tender_status"].map(TENDER_STATUS_ORDER).fillna(99)
    df["days_left_sort"] = pd.to_numeric(df["days_left"], errors="coerce").fillna(9999)
    df = df.sort_values(
        ["action_sort", "notice_stage_sort", "tender_status_sort", "priority_sort", "user_score_sort", "days_left_sort", "lead_quality_score", "relevance_score", "publish_date"],
        ascending=[True, True, True, True, False, True, False, False, False],
    )
    df = df[list(EXPORT_COLUMNS.keys())].rename(columns=EXPORT_COLUMNS)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="搜索结果")
        worksheet = writer.sheets["搜索结果"]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        widths = {
            "建议动作": 14,
            "质量分": 8,
            "风险": 8,
            "判断依据": 54,
            "你的评分": 10,
            "优先级": 12,
            "评分": 8,
            "画像项目类型": 18,
            "画像客户类型": 18,
            "画像理由": 46,
            "公告阶段": 12,
            "可投状态": 12,
            "剩余天数": 10,
            "合并条数": 10,
            "合并来源": 30,
            "来源": 24,
            "公告类型": 18,
            "标题": 60,
            "地区": 16,
            "预算": 18,
            "发布时间": 14,
            "截止日期": 14,
            "投标/响应截止": 20,
            "采购人": 30,
            "代理机构": 30,
            "联系人": 14,
            "联系电话": 18,
            "命中关键词": 28,
            "AI建议": 28,
            "AI项目类型": 18,
            "AI评分调整": 12,
            "AI判断原因": 50,
            "重要信息": 50,
            "摘要": 60,
            "原文链接": 60,
            "样本标记": 12,
            "备注": 30,
        }
        for cell in worksheet[1]:
            worksheet.column_dimensions[cell.column_letter].width = widths.get(cell.value, 16)
    return output_path
