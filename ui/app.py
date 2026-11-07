import re
import os
import sys
import time
from datetime import date, datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import DB_PATH, EXPORT_DIR, KEYWORDS_PATH, SOURCES_PATH, DATA_DIR
from crawlers.runner import run_search_with_status
from utils.shared_search import run_shared_search, SearchBusyError
from database.db import (
    build_merged_rows,
    connect,
    fetch_tenders,
    init_db,
    update_feedback_label,
    update_read_status,
    update_remark,
    update_user_score,
    upsert_many,
)
from exporters.excel_exporter import export_to_excel
from learning.feedback import apply_learning_suggestions, build_learning_suggestions
from parsers.extractors import is_open_for_tendering, radar_today
from presentation.lead_row import normalize_lead_row
from presentation.refresh_status import load_refresh_status
from presentation.search_report import build_search_report, save_search_report, load_search_report
from ui.team_access import require_team_access
from scoring.project_profile import HISTORICAL_PROFILE_PATH, PROJECT_SEARCH_TERMS, remove_public_culture_search_terms
from scoring.rules import (
    NOTICE_STAGE_BID,
    NOTICE_STAGE_CHANGE,
    NOTICE_STAGE_INTEL,
    NOTICE_STAGE_INVALID,
    NOTICE_STAGE_RESULT,
    annotate_notice_stage,
)
from scoring.user_feedback import feedback_label_from_user_score, parse_user_score, user_score_display
from utils.date_window import (
    DEFAULT_INTERACTIVE_SEARCH_DAYS,
    MAX_INTERACTIVE_SEARCH_DAYS,
    recent_date_window,
)
from utils.text_format import repair_text


st.set_page_config(page_title="咕咕嘎嘎", page_icon=":material/radar:", layout="wide")
require_team_access(st)
if os.getenv("RADAR_EPHEMERAL", "").lower() == "true":
    st.warning("免费云端测试环境：服务休眠或重启后，搜索记录和团队评分会重置。需要长期保留时，请启用持久化存储。")


TENDER_STATUS_ORDER = {
    "理想窗口": 0,
    "正常跟进": 1,
    "紧急跟进": 2,
    "观察": 3,
    "待核验": 4,
    "时间不足": 5,
    "已截止": 6,
}

NOTICE_STAGE_ORDER = {
    NOTICE_STAGE_BID: 0,
    NOTICE_STAGE_INTEL: 1,
    NOTICE_STAGE_CHANGE: 2,
    NOTICE_STAGE_RESULT: 3,
    NOTICE_STAGE_INVALID: 4,
}

PRIORITY_ORDER = {
    "高优先级": 0,
    "中优先级": 1,
    "低优先级": 2,
    "可能无关": 3,
}

ACTION_ORDER = {
    "立即跟进": 0,
    "进入跟进池": 1,
    "机会池观察": 2,
    "人工筛选": 3,
    "情报复盘": 4,
    "暂不跟进": 5,
}

VIEW_ACTION = "行动优先"
VIEW_INTEL = "机会情报"
VIEW_ALL = "全部库存"
NOTICE_STAGE_VIEW_DEFAULT = "视图默认"
SOURCE_SCOPE_CORE = "核心来源"
SOURCE_SCOPE_BALANCED = "均衡拓源"
SOURCE_SCOPE_WIDE = "广域扫描"
USER_SCORE_OPTIONS = ["未评分"] + list(range(10, -11, -1))


def load_yaml(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def build_profile_search_terms(historical_profile: dict, keywords: dict) -> list[str]:
    broad_first_terms = ["展厅", "展示中心", "展陈", "布展", "数字展厅", "展馆", "展厅设计", "展陈设计"]
    return remove_public_culture_search_terms(
        list(keywords.get("query_priority_terms") or [])
        + broad_first_terms
        + list(PROJECT_SEARCH_TERMS or [])
        + list(historical_profile.get("search_terms") or [])
        + list(keywords.get("default_search_terms") or [])
        + ["展陈"]
    )


def source_can_join_balanced_scope(source: dict) -> bool:
    if not source.get("enabled", True):
        return False
    if source.get("crawler") == "example_public_page":
        return False
    return source.get("risk_level") != "高"


def balanced_backfill_source_names(sources: list[dict]) -> list[str]:
    return [
        source.get("name", "")
        for source in sources
        if source.get("name") and source_can_join_balanced_scope(source)
    ]


def build_scope_source_names(
    sources: list[dict],
    selected_sources: list[str],
    scope: str,
) -> list[str]:
    selected = set(selected_sources or [])
    if scope == SOURCE_SCOPE_CORE:
        return []
    balanced_source_names = set(balanced_backfill_source_names(sources))
    candidates = []
    for source in sources:
        name = source.get("name", "")
        if not name or name in selected:
            continue
        if not source.get("enabled", True) or source.get("crawler") == "example_public_page":
            continue
        if scope == SOURCE_SCOPE_BALANCED and name not in balanced_source_names:
            continue
        if source.get("risk_level") == "高" and scope != SOURCE_SCOPE_WIDE:
            continue
        candidates.append(name)
    return candidates


def top_count_items(values: dict | None, limit: int = 5) -> str:
    if not isinstance(values, dict):
        return ""
    sorted_items = sorted(
        values.items(),
        key=lambda item: int(item[1] or 0) if str(item[1] or "").isdigit() else 0,
        reverse=True,
    )
    return "；".join(f"{repair_text(str(name))} {count}" for name, count in sorted_items[:limit])


def split_region_terms(region_text: str | None) -> list[str] | None:
    terms = [term.strip() for term in re.split(r"[、,，;；\s]+", region_text or "") if term.strip()]
    expanded = []
    for term in terms:
        if term in {"东三省", "东北三省", "东北"}:
            expanded.extend(["辽宁", "吉林", "黑龙江"])
        else:
            expanded.append(term)
    terms = expanded
    return list(dict.fromkeys(terms)) or None


def has_open_deadline(row: dict, search_date: date) -> bool:
    return is_open_for_tendering(row, today=search_date)


def has_actionable_deadline(row: dict, search_date: date) -> bool:
    return is_open_for_tendering(row, today=search_date)


def days_left_text(value) -> str:
    if value is None or value == "":
        return "-"
    try:
        days = int(value)
    except (TypeError, ValueError):
        return "-"
    if days == 0:
        return "今天截止"
    if days < 0:
        return "已截止"
    return f"{days} 天"


def row_sort_key(row: dict):
    stage = row.get("notice_stage") or NOTICE_STAGE_INTEL
    status = row.get("tender_status") or "待核验"
    priority = row.get("display_priority") or row.get("priority") or "可能无关"
    action = row.get("lead_action") or ""
    try:
        score = int(row.get("relevance_score") or 0)
    except (TypeError, ValueError):
        score = 0
    try:
        quality = int(row.get("lead_quality_score") or 0)
    except (TypeError, ValueError):
        quality = 0
    user_score = parse_user_score(row.get("user_score"))
    try:
        days = int(row.get("days_left")) if row.get("days_left") is not None else 9999
    except (TypeError, ValueError):
        days = 9999
    return (
        ACTION_ORDER.get(action, 99),
        NOTICE_STAGE_ORDER.get(stage, 99),
        TENDER_STATUS_ORDER.get(status, 99),
        PRIORITY_ORDER.get(priority, 99),
        -(user_score if user_score is not None else -99),
        -quality,
        days,
        -score,
        row.get("publish_date") or "",
    )


def priority_from_score(score) -> str:
    try:
        value = int(score or 0)
    except (TypeError, ValueError):
        value = 0
    if value >= 80:
        return "高优先级"
    if value >= 60:
        return "中优先级"
    if value >= 40:
        return "低优先级"
    return "可能无关"


def display_priority(row: dict) -> str:
    raw = repair_text(row.get("priority", ""))
    if raw in {"高优先级", "中优先级", "低优先级", "可能无关"}:
        return raw
    return priority_from_score(row.get("relevance_score"))


def priority_class(priority: str) -> str:
    return {
        "高优先级": "high",
        "中优先级": "medium",
        "低优先级": "low",
        "可能无关": "muted",
    }.get(priority, "muted")


def score_option_label(value) -> str:
    if value == "未评分":
        return "未评分"
    return user_score_display(value)


def score_option_index(value) -> int:
    score = parse_user_score(value)
    if score is None:
        return 0
    try:
        return USER_SCORE_OPTIONS.index(score)
    except ValueError:
        return 0


def score_value_from_option(value):
    return None if value == "未评分" else int(value)


def resolve_feedback_label(score_value, explicit_label: str = "") -> str:
    explicit_label = (explicit_label or "").strip()
    return explicit_label or feedback_label_from_user_score(score_value)


def match_user_score_filter(row: dict, score_filter: str) -> bool:
    score = parse_user_score(row.get("user_score"))
    if score_filter == "全部":
        return True
    if score_filter == "未评分":
        return score is None
    if score_filter == "我的菜(8-10)":
        return score is not None and score >= 8
    if score_filter == "观察(1-7)":
        return score is not None and 1 <= score <= 7
    if score_filter == "排除(0/负分)":
        return score is not None and score <= 0
    return True


def clean_row(row: dict) -> dict:
    cleaned = normalize_lead_row(row, include_display_priority=True)
    cleaned["is_read"] = bool(cleaned.get("is_read"))
    return cleaned


def metric_card(title: str, value, icon: str, tone: str = "blue") -> str:
    return f"""
    <div class="apple-card metric-card tone-{tone}">
        <div class="metric-icon">{icon}</div>
        <div>
            <div class="metric-label">{escape(title)}</div>
            <div class="metric-value">{escape(str(value))}</div>
        </div>
    </div>
    """


def line_icon(name: str) -> str:
    icons = {
        "radar": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 12 19 8"/><path d="M12 4v16"/><path d="M4 12h16"/></svg>',
        "target": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>',
        "bolt": '<svg viewBox="0 0 24 24"><path d="m13 2-9 12h7l-1 8 10-13h-7l0-7z"/></svg>',
        "eye": '<svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/></svg>',
        "source": '<svg viewBox="0 0 24 24"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h10"/><circle cx="18" cy="17" r="2"/></svg>',
        "spark": '<svg viewBox="0 0 24 24"><path d="M12 2v6"/><path d="M12 16v6"/><path d="m4.9 4.9 4.2 4.2"/><path d="m14.9 14.9 4.2 4.2"/><path d="M2 12h6"/><path d="M16 12h6"/><path d="m4.9 19.1 4.2-4.2"/><path d="m14.9 9.1 4.2-4.2"/></svg>',
    }
    return icons.get(name, icons["radar"])


def render_searching(query_text: str, source_count: int) -> str:
    safe_query = escape(query_text or "展陈")
    return f"""
    <div class="searching-panel">
        <div class="searching-visual">
            <div class="soft-radar">
                <div class="soft-sweep"></div>
                <span></span>
            </div>
        </div>
        <div>
            <div class="eyebrow small">{line_icon("spark")} Searching project profiles</div>
            <h3>正在按项目画像扫描公开线索</h3>
            <p>项目画像 <strong>{safe_query}</strong> 已进入检索队列。系统会同步匹配历史样本特征、业务场景、来源状态、预算、截止时间与原文链接。</p>
            <div class="status-pills">
                <span>{source_count} 个公开来源</span>
                <span>合规访问</span>
                <span>线索评分</span>
                <span>本地入库</span>
            </div>
        </div>
    </div>
    """


def primary_source_url(item: dict) -> str:
    return item.get("source_url") or item.get("open_url") or open_url(item)


def render_workbench_summary(
    total: int,
    high_count: int,
    urgent_count: int,
    start_date: date,
    end_date: date,
    inventory_total: int | None = None,
) -> None:
    window_days = (end_date - start_date).days + 1
    inventory_stat = ""
    if inventory_total is not None:
        inventory_stat = f"<span><small>{window_days}天库存</small><strong>{inventory_total}</strong></span>"
    st.markdown(
        f"""
        <section class="workbench-summary">
            <div class="brand-lockup">
                <div class="summary-kicker"><span class="status-dot"></span>最近 {window_days} 天 · 展厅项目线索</div>
                <div class="brand-line">
                    <h1>咕咕嘎嘎</h1>
                    <span class="brand-subtitle">李奇的展厅项目画像雷达</span>
                </div>
            </div>
            <div class="summary-strip">
                <span><small>当前结果</small><strong>{total}</strong></span>
                {inventory_stat}
                <span><small>高优先</small><strong>{high_count}</strong></span>
                <span><small>理想窗口</small><strong>{urgent_count}</strong></span>
                <span><small>日期</small><strong>{start_date.isoformat()} - {end_date.isoformat()}</strong></span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_tender_card(item: dict) -> None:
    priority = item["display_priority"]
    title = escape(item.get("title") or "未命名项目")
    source = escape(item.get("source_name") or "未知来源")
    budget = escape(item.get("budget") or "-")
    publish_date = escape(item.get("publish_date") or "-")
    deadline = escape(item.get("bid_deadline_date") or item.get("bid_deadline") or "-")
    tender_status = escape(item.get("tender_status") or "待核验")
    profile_project_type = escape(item.get("profile_project_type") or item.get("ai_project_type") or "-")
    days_left = escape(days_left_text(item.get("days_left")))
    source_url = escape(primary_source_url(item), quote=True)
    source_label = "打开原文"
    merged_count = int(item.get("merged_count") or 1)
    merge_text = f" · 跨来源 {merged_count} 条" if merged_count > 1 else ""
    st.markdown(
        f"""
        <div class="tender-card">
            <div class="tender-head">
                <div>
                    <div class="tender-kicker">{source} · {publish_date}{merge_text}</div>
                    <h3>{title}</h3>
                    <div class="tender-subline">{profile_project_type} · {tender_status}</div>
                </div>
                <div class="lead-actions">
                    <a class="source-link" href="{source_url}" target="_blank" rel="noopener">{source_label}</a>
                    <span class="priority-pill {priority_class(priority)}">{escape(priority)}</span>
                </div>
            </div>
            <div class="decision-grid">
                <span class="deadline-cell"><small>截止日期</small><strong>{deadline}</strong><em>{days_left} · 准备10天后余 {item.get('design_days_left', '-')} 天</em></span>
                <span class="budget-cell"><small>预算</small><strong>{budget}</strong></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


LOCAL_DETAIL_SOURCES = {"湖南省公共资源交易数据", "长沙市公共资源交易数据"}


def is_local_detail_source(item: dict) -> bool:
    return repair_text(item.get("source_name", "")) in LOCAL_DETAIL_SOURCES


def open_url(item: dict) -> str:
    if is_local_detail_source(item) and item.get("id"):
        return f"?lead_id={int(item['id'])}"
    return item.get("source_url") or ""


def fetch_tender_by_id(tender_id: int) -> dict | None:
    with connect(DB_PATH) as conn:
        row = conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()
    return dict(row) if row else None


def render_local_detail_page(item: dict) -> None:
    cleaned = clean_row(item)
    st.title(cleaned.get("title") or "线索详情")
    st.caption(f"{cleaned.get('source_name') or '-'} · {cleaned.get('publish_date') or '-'}")
    detail_cols = st.columns(3)
    detail_cols[0].write(f"地区：{cleaned.get('region') or '-'}")
    detail_cols[1].write(f"预算：{cleaned.get('budget') or '-'}")
    detail_cols[2].write(f"评分：{cleaned.get('relevance_score') or 0}")
    st.write(f"采购人/招标人：{cleaned.get('purchaser') or '-'}")
    st.write(f"代理机构：{cleaned.get('agency') or '-'}")
    st.write(f"投标/响应截止：{cleaned.get('bid_deadline') or '-'}")
    st.write(f"公告阶段：{cleaned.get('notice_stage') or '-'}")
    st.write(f"可投状态：{cleaned.get('tender_status') or '-'}；剩余：{days_left_text(cleaned.get('days_left'))}")
    st.write(f"建议动作：{cleaned.get('lead_action') or '-'}；质量分：{cleaned.get('lead_quality_score') or 0}；风险：{cleaned.get('lead_risk_level') or '-'}")
    st.write(f"判断依据：{cleaned.get('lead_reason') or '-'}")
    st.write(f"画像项目类型：{cleaned.get('profile_project_type') or cleaned.get('ai_project_type') or '-'}")
    st.write(f"画像客户类型：{cleaned.get('profile_client_type') or '-'}")
    st.write(f"画像理由：{cleaned.get('profile_reason') or '-'}")
    st.write(f"命中关键词：{cleaned.get('matched_keywords') or '-'}")
    st.write(f"重要信息：{cleaned.get('important_info') or '-'}")
    st.write(f"摘要：{cleaned.get('summary') or '-'}")
    st.link_button("尝试打开官网链接", cleaned.get("source_url") or "", icon=":material/open_in_new:")
    st.code(cleaned.get("source_url") or "-", language=None)
    st.link_button("返回线索列表", "/", icon=":material/arrow_back:")


init_db(DB_PATH)
keywords = load_yaml(KEYWORDS_PATH)
sources_config = load_yaml(SOURCES_PATH)
historical_profile = load_yaml(HISTORICAL_PROFILE_PATH) if HISTORICAL_PROFILE_PATH.exists() else {}
profile_search_terms = build_profile_search_terms(historical_profile, keywords)
default_query = "、".join(profile_search_terms[:18])
enabled_source_names = {
    item["name"]
    for item in sources_config.get("sources", [])
    if item.get("enabled", True) and item.get("crawler") != "example_public_page"
}

lead_id = st.query_params.get("lead_id")
if lead_id:
    try:
        local_item = fetch_tender_by_id(int(lead_id))
    except (TypeError, ValueError):
        local_item = None
    if local_item:
        render_local_detail_page(local_item)
    else:
        st.error("没有找到这条线索，可能已经被清理或更新。")
        st.link_button("返回线索列表", "/", icon=":material/arrow_back:")
    st.stop()

st.markdown(
    """
    <style>
    :root {
        --page-bg: #05070b;
        --surface: rgba(11, 17, 25, 0.86);
        --surface-strong: rgba(14, 23, 34, 0.96);
        --surface-raised: rgba(13, 22, 32, 0.92);
        --text: #e8fff7;
        --muted: #8ca3a3;
        --line: rgba(40, 255, 191, 0.22);
        --line-strong: rgba(83, 217, 255, 0.34);
        --blue: #53d9ff;
        --blue-soft: rgba(83, 217, 255, 0.14);
        --green: #28ffbf;
        --amber: #ffd166;
        --red: #ff4b5c;
        --shadow: 0 0 46px rgba(40, 255, 191, 0.12), 0 24px 54px rgba(0, 0, 0, 0.42);
        --shadow-soft: 0 0 24px rgba(40, 255, 191, 0.1), 0 14px 34px rgba(0, 0, 0, 0.32);
        --radius: 8px;
    }

    .stApp {
        color: var(--text);
        background:
            linear-gradient(180deg, rgba(10, 15, 22, 0.98) 0%, rgba(5, 7, 11, 1) 46%, rgba(4, 7, 11, 1) 100%),
            linear-gradient(135deg, rgba(40, 255, 191, 0.055) 1px, transparent 1px),
            linear-gradient(45deg, rgba(83, 217, 255, 0.045) 1px, transparent 1px),
            var(--page-bg);
        background-size: auto, 34px 34px, 34px 34px, auto;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "Microsoft YaHei", sans-serif;
    }

    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background:
            linear-gradient(rgba(255, 255, 255, 0.026) 50%, transparent 50%),
            linear-gradient(90deg, rgba(255, 75, 92, 0.022), rgba(83, 217, 255, 0.024), rgba(40, 255, 191, 0.024));
        background-size: 100% 4px, 100% 100%;
        mix-blend-mode: screen;
        opacity: 0.32;
        z-index: 0;
    }

    [data-testid="stHeader"] {
        background: rgba(5, 7, 11, 0.84) !important;
        backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(40,255,191,0.12);
    }

    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    #MainMenu,
    footer {
        visibility: hidden;
    }

    .block-container {
        max-width: 1440px;
        padding-top: 4rem;
        padding-bottom: 4rem;
        position: relative;
        z-index: 1;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #090d14 0%, #0c131d 58%, #081018 100%);
        backdrop-filter: blur(18px);
        border-right: 1px solid var(--line);
        box-shadow: 12px 0 34px rgba(0, 0, 0, 0.42);
    }

    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-top: 1.5rem;
    }

    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] label,
    h1, h2, h3, p, span, label {
        color: var(--text);
        letter-spacing: 0 !important;
    }

    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        font-size: 0.92rem !important;
        font-weight: 700 !important;
        margin-top: 1.1rem !important;
    }

    .stCaption,
    [data-testid="stCaptionContainer"],
    small {
        color: var(--muted) !important;
    }

    .hero-shell {
        position: relative;
        display: grid;
        grid-template-columns: minmax(0, 1fr) 390px;
        align-items: center;
        gap: 34px;
        min-height: 320px;
        margin: 0 0 26px;
        padding: 44px 46px;
        overflow: hidden;
        border: 1px solid rgba(40,255,191,0.34);
        border-radius: var(--radius);
        background:
            radial-gradient(circle at 78% 18%, rgba(83,217,255,0.18), transparent 30%),
            radial-gradient(circle at 18% 78%, rgba(40,255,191,0.11), transparent 28%),
            linear-gradient(135deg, rgba(6,13,18,0.98), rgba(4,8,13,0.94));
        box-shadow: var(--shadow);
    }

    .hero-shell::after {
        content: "";
        position: absolute;
        right: -120px;
        bottom: -180px;
        width: 520px;
        height: 520px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(83,217,255,0.16), transparent 62%);
        pointer-events: none;
    }

    .hero-shell::before {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
            linear-gradient(rgba(40, 255, 191, 0.045) 1px, transparent 1px),
            linear-gradient(90deg, rgba(83, 217, 255, 0.035) 1px, transparent 1px);
        background-size: 22px 22px;
        mask-image: linear-gradient(90deg, rgba(0,0,0,0.95), rgba(0,0,0,0.45));
    }

    .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: var(--blue);
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.02em !important;
    }

    .eyebrow.small {
        font-size: 0.78rem;
        margin-bottom: 8px;
    }

    .eyebrow svg,
    .metric-icon svg,
    .orbit-core svg {
        width: 18px;
        height: 18px;
        fill: none;
        stroke: currentColor;
        stroke-width: 1.8;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .hero-copy h1 {
        margin: 10px 0 8px;
        color: var(--text) !important;
        font-size: clamp(3.2rem, 6vw, 6.6rem) !important;
        line-height: 0.96 !important;
        font-weight: 760 !important;
        text-shadow: 0 0 18px rgba(40, 255, 191, 0.38), 0 0 42px rgba(83, 217, 255, 0.2);
    }

    .hero-copy p {
        max-width: 680px;
        margin: 0;
        color: var(--muted);
        font-size: 1.12rem;
        line-height: 1.7;
    }

    .hero-panel {
        position: relative;
        z-index: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 18px;
    }

    .orbital {
        position: relative;
        width: 220px;
        height: 220px;
        border-radius: 50%;
        background:
            radial-gradient(circle, rgba(40,255,191,0.95) 0 2px, transparent 3px),
            repeating-radial-gradient(circle, transparent 0 34px, rgba(40,255,191,0.24) 35px, transparent 36px),
            linear-gradient(90deg, transparent 49.5%, rgba(40,255,191,0.28) 50%, transparent 50.5%),
            linear-gradient(0deg, transparent 49.5%, rgba(40,255,191,0.28) 50%, transparent 50.5%),
            rgba(5, 22, 18, 0.88);
        border: 1px solid rgba(40,255,191,0.52);
        box-shadow: 0 0 30px rgba(40,255,191,0.22), inset 0 0 38px rgba(40,255,191,0.1);
    }

    .orbit {
        position: absolute;
        inset: 26px;
        border: 1px solid rgba(40,255,191,0.28);
        border-radius: 50%;
    }

    .orbit-two {
        inset: 58px;
        border-color: rgba(83,217,255,0.2);
    }

    .orbit-dot {
        position: absolute;
        left: 50%;
        top: 18px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--green);
        box-shadow: 0 0 18px rgba(40,255,191,0.75), 0 0 0 7px rgba(40,255,191,0.1);
        animation: orbitMove 5.6s linear infinite;
        transform-origin: 0 92px;
    }

    .orbit-core {
        position: absolute;
        inset: 82px;
        display: grid;
        place-items: center;
        color: var(--blue);
        border-radius: 50%;
        background: rgba(5, 22, 18, 0.94);
        border: 1px solid rgba(40,255,191,0.38);
        box-shadow: var(--shadow-soft);
    }

    .hero-stats,
    .status-pills {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 8px;
    }

    .hero-stats span,
    .status-pills span {
        display: inline-flex;
        align-items: center;
        min-height: 30px;
        padding: 0 11px;
        color: rgba(232,255,247,0.84);
        border: 1px solid rgba(83,217,255,0.25);
        border-radius: 999px;
        background: rgba(83,217,255,0.08);
        font-size: 0.82rem;
    }

    .apple-card,
    [data-testid="stExpander"],
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: linear-gradient(180deg, rgba(16,23,34,0.94), rgba(7,11,17,0.92));
        box-shadow: var(--shadow-soft);
        backdrop-filter: blur(14px);
    }

    .metric-card {
        display: flex;
        align-items: center;
        gap: 15px;
        min-height: 112px;
        padding: 20px;
        margin-bottom: 16px;
    }

    .metric-icon {
        display: grid;
        place-items: center;
        flex: 0 0 42px;
        width: 42px;
        height: 42px;
        color: var(--blue);
        border-radius: 50%;
        background: rgba(83,217,255,0.12);
        box-shadow: inset 0 0 18px rgba(83,217,255,0.08);
    }

    .metric-label {
        color: var(--muted);
        font-size: 0.86rem;
        font-weight: 650;
    }

    .metric-value {
        margin-top: 4px;
        color: var(--text);
        font-size: 2rem;
        line-height: 1;
        font-weight: 760;
    }

    .tone-green .metric-icon { color: var(--green); background: rgba(40,255,191,0.13); }
    .tone-amber .metric-icon { color: var(--amber); background: rgba(255,209,102,0.14); }
    .tone-slate .metric-icon { color: #d8f6ff; background: rgba(216,246,255,0.12); }

    .stTextInput input,
    .stNumberInput input,
    .stDateInput input,
    .stTextArea textarea,
    .stSelectbox [data-baseweb="select"],
    .stMultiSelect [data-baseweb="select"] {
        min-height: 42px;
        color: var(--text) !important;
        background: rgba(6,10,15,0.96) !important;
        border: 1px solid var(--line-strong) !important;
        border-radius: var(--radius) !important;
        box-shadow: none !important;
    }

    .stSelectbox [data-baseweb="select"] > div,
    .stMultiSelect [data-baseweb="select"] > div,
    .stNumberInput button {
        color: var(--text) !important;
        background: rgba(6,10,15,0.96) !important;
        border-color: var(--line-strong) !important;
    }

    .stSelectbox [data-baseweb="select"] svg,
    .stMultiSelect [data-baseweb="select"] svg,
    .stNumberInput button svg {
        color: var(--text) !important;
        fill: var(--text) !important;
    }

    .stTextArea textarea {
        line-height: 1.65;
    }

    [data-baseweb="tag"] {
        border-radius: 999px !important;
        background: rgba(40,255,191,0.16) !important;
        color: var(--text) !important;
    }

    [data-baseweb="tag"] span,
    [data-baseweb="tag"] svg {
        color: var(--text) !important;
        fill: var(--text) !important;
    }

    [data-baseweb="popover"],
    [data-baseweb="menu"],
    [role="listbox"] {
        border: 1px solid var(--line) !important;
        border-radius: var(--radius) !important;
        background: #071019 !important;
        box-shadow: 0 20px 42px rgba(0,0,0,0.5) !important;
    }

    .stButton button,
    .stLinkButton a {
        min-height: 44px;
        border-radius: var(--radius) !important;
        border: 1px solid var(--line) !important;
        font-weight: 680 !important;
        box-shadow: none !important;
        transition: transform 180ms ease, border-color 180ms ease, filter 180ms ease, background 180ms ease;
    }

    .stButton button[kind="primary"],
    .stButton button[data-testid="baseButton-primary"],
    .stLinkButton a[data-testid="stBaseButton-primary"] {
        color: #03110d !important;
        background: linear-gradient(135deg, var(--green), #7de7ff) !important;
        border-color: rgba(40,255,191,0.82) !important;
        box-shadow: 0 0 22px rgba(40,255,191,0.16) !important;
    }

    .stButton button:hover,
    .stLinkButton a:hover {
        transform: translateY(-1px);
        border-color: rgba(0,113,227,0.42) !important;
    }

    [data-testid="stExpander"] {
        overflow: hidden;
        margin-bottom: 10px;
    }

    [data-testid="stExpander"] summary {
        color: var(--text);
        min-height: 44px;
        background: linear-gradient(90deg, rgba(40,255,191,0.11), rgba(83,217,255,0.06)) !important;
        border-bottom: 1px solid rgba(40,255,191,0.12);
        font-weight: 680;
    }

    .stAlert {
        border-radius: var(--radius) !important;
        border: 1px solid var(--line) !important;
        background: rgba(13, 22, 32, 0.82) !important;
    }

    .searching-panel {
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 26px;
        align-items: center;
        min-height: min(72vh, 760px);
        margin: 0 0 28px;
        padding: 42px 34px;
        border: 1px solid rgba(40,255,191,0.35);
        border-radius: var(--radius);
        background:
            radial-gradient(circle at 50% 42%, rgba(40,255,191,0.2), transparent 34%),
            radial-gradient(circle at 74% 20%, rgba(83,217,255,0.16), transparent 28%),
            linear-gradient(135deg, rgba(6,13,18,0.96), rgba(4,8,13,0.94));
        box-shadow: var(--shadow-soft);
        text-align: center;
        overflow: hidden;
        position: relative;
    }

    .searching-panel::before {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
            linear-gradient(rgba(40,255,191,0.046) 1px, transparent 1px),
            linear-gradient(90deg, rgba(83,217,255,0.04) 1px, transparent 1px);
        background-size: 28px 28px;
        mask-image: radial-gradient(circle at center, rgba(0,0,0,0.98), transparent 72%);
    }

    .searching-panel > * {
        position: relative;
        z-index: 1;
    }

    .searching-panel h3 {
        margin: 0 0 8px;
        color: var(--text) !important;
        font-size: clamp(1.55rem, 3vw, 2.35rem);
        text-shadow: 0 0 18px rgba(40,255,191,0.28);
    }

    .searching-panel p {
        max-width: 780px;
        margin: 0 0 16px;
        color: rgba(232,255,247,0.72);
        line-height: 1.75;
    }

    .soft-radar {
        position: relative;
        width: min(52vw, 420px);
        height: min(52vw, 420px);
        min-width: 280px;
        min-height: 280px;
        margin: auto;
        border-radius: 50%;
        border: 1px solid rgba(40,255,191,0.52);
        background:
            radial-gradient(circle, rgba(40,255,191,0.95) 0 2px, transparent 3px),
            repeating-radial-gradient(circle, transparent 0 58px, rgba(40,255,191,0.24) 59px, transparent 60px),
            linear-gradient(90deg, transparent 49.75%, rgba(40,255,191,0.26) 50%, transparent 50.25%),
            linear-gradient(0deg, transparent 49.75%, rgba(40,255,191,0.26) 50%, transparent 50.25%),
            rgba(5,22,18,0.88);
        overflow: hidden;
        box-shadow: 0 0 44px rgba(40,255,191,0.22), inset 0 0 54px rgba(40,255,191,0.12);
    }

    .soft-sweep {
        position: absolute;
        inset: 0;
        background: conic-gradient(from 0deg, rgba(40,255,191,0.72), rgba(40,255,191,0.18) 18deg, transparent 72deg);
        animation: radarSweep 1.8s linear infinite;
    }

    .soft-radar span {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 12px;
        height: 12px;
        margin: -6px 0 0 -6px;
        border-radius: 50%;
        background: var(--green);
        box-shadow:
            0 0 22px var(--green),
            96px -76px 0 -3px rgba(83,217,255,0.95),
            -118px 66px 0 -4px rgba(40,255,191,0.88),
            58px 122px 0 -4px rgba(255,255,255,0.78),
            -68px -112px 0 -5px rgba(255,209,102,0.82);
    }

    .tender-card {
        position: relative;
        margin: 12px 0;
        padding: 18px 20px 18px 22px;
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background:
            linear-gradient(180deg, rgba(13,22,32,0.96), rgba(8,13,20,0.92)),
            var(--surface-raised);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.30);
        overflow: hidden;
        transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
    }

    .tender-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        background: linear-gradient(180deg, var(--green), var(--blue), var(--amber));
    }

    .tender-card:hover {
        transform: translateY(-1px);
        border-color: rgba(40,255,191,0.46);
        box-shadow: 0 18px 38px rgba(0, 0, 0, 0.34), 0 0 22px rgba(40,255,191,0.08);
    }

    .tender-head {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 16px;
        align-items: start;
    }

    .tender-kicker {
        color: var(--muted);
        font-size: 0.8rem;
        font-weight: 650;
    }

    .tender-card h3 {
        max-width: 980px;
        margin: 6px 0 0;
        color: var(--text) !important;
        font-size: 1.16rem;
        line-height: 1.45;
        font-weight: 780;
    }

    .tender-subline {
        margin-top: 6px;
        color: rgba(232,255,247,0.62);
        font-size: 0.82rem;
    }

    .lead-actions {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 10px;
        min-width: 268px;
    }

    .priority-pill {
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        padding: 0 9px;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 720;
    }

    .priority-pill.high { color: #03110d; background: var(--green); box-shadow: 0 0 16px rgba(40,255,191,0.24); }
    .priority-pill.medium { color: #100a00; background: var(--amber); box-shadow: 0 0 16px rgba(255,209,102,0.2); }
    .priority-pill.low { color: #d8f6ff; background: rgba(83,217,255,0.15); border: 1px solid rgba(83,217,255,0.22); }
    .priority-pill.muted { color: #ffd7d5; background: rgba(255,75,92,0.16); border: 1px solid rgba(255,75,92,0.24); }

    .source-link {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 48px;
        padding: 0 22px;
        color: #02110c !important;
        text-decoration: none !important;
        border-radius: var(--radius);
        background: linear-gradient(135deg, var(--green), #7de7ff 82%);
        border: 1px solid rgba(40,255,191,0.82);
        font-size: 1rem;
        font-weight: 820;
        box-shadow: 0 0 22px rgba(40,255,191,0.20);
        transition: transform 180ms ease, filter 180ms ease, box-shadow 180ms ease;
    }

    .source-link:hover {
        transform: translateY(-1px);
        filter: brightness(1.04);
        box-shadow: 0 0 28px rgba(40,255,191,0.28);
    }

    .decision-grid {
        display: grid;
        grid-template-columns: minmax(190px, 250px) minmax(200px, 300px);
        gap: 12px;
        margin-top: 14px;
    }

    .decision-grid span {
        min-height: 72px;
        padding: 13px 15px;
        color: var(--muted);
        border: 1px solid rgba(83,217,255,0.16);
        border-radius: var(--radius);
        background: rgba(83,217,255,0.055);
        font-size: 0.84rem;
    }

    .decision-grid small,
    .decision-grid em {
        display: block;
        color: var(--muted);
        font-style: normal;
        font-size: 0.76rem;
    }

    .decision-grid strong {
        display: block;
        margin-top: 4px;
        color: var(--text);
        font-size: 1.08rem;
        font-weight: 820;
        overflow-wrap: anywhere;
    }

    .budget-cell strong {
        color: var(--amber);
    }

    a {
        color: var(--blue) !important;
    }

    .workbench-summary {
        position: relative;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 24px;
        margin: 0 0 28px;
        padding: 24px 26px;
        border: 1px solid rgba(40,255,191,0.30);
        border-radius: var(--radius);
        background:
            linear-gradient(120deg, rgba(10,17,25,0.98), rgba(7,12,18,0.94) 48%, rgba(11,23,29,0.92)),
            var(--surface);
        box-shadow: 0 20px 42px rgba(0,0,0,0.32), inset 0 1px 0 rgba(255,255,255,0.04);
        overflow: hidden;
    }

    .workbench-summary::before {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
            linear-gradient(90deg, rgba(40,255,191,0.22), transparent 36%, rgba(83,217,255,0.14) 72%, transparent),
            linear-gradient(rgba(40,255,191,0.035) 1px, transparent 1px);
        background-size: 100% 100%, 100% 12px;
        opacity: 0.7;
    }

    .brand-lockup,
    .summary-strip {
        position: relative;
        z-index: 1;
    }

    .brand-lockup {
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 14px;
        min-width: 0;
        padding: 4px 0;
    }

    .workbench-summary h1 {
        display: block;
        margin: 0;
        color: #f2fffb !important;
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
        font-size: clamp(3.9rem, 5.6vw, 5.8rem) !important;
        line-height: 0.98 !important;
        font-weight: 900 !important;
        letter-spacing: 0;
        text-shadow:
            0 0 18px rgba(40,255,191,0.30),
            0 0 36px rgba(83,217,255,0.12);
    }

    .brand-line {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 20px;
    }

    .brand-line .brand-subtitle {
        max-width: 24rem;
        padding: 8px 0 8px 18px;
        color: rgba(232,255,247,0.78);
        border-left: 1px solid rgba(40,255,191,0.42);
        font-size: 1.05rem;
        line-height: 1.35;
        font-weight: 700;
    }

    .summary-kicker {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 0;
        color: var(--muted);
        font-size: 0.86rem;
        font-weight: 760;
    }

    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--green);
        box-shadow: 0 0 14px rgba(40,255,191,0.78);
    }

    .summary-strip {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 10px;
        max-width: 560px;
    }

    .summary-strip span {
        display: inline-flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-width: 96px;
        min-height: 58px;
        padding: 8px 12px;
        color: rgba(232,255,247,0.82);
        border: 1px solid rgba(83,217,255,0.16);
        border-radius: var(--radius);
        background: rgba(83,217,255,0.06);
        font-size: 0.82rem;
    }

    .summary-strip strong {
        color: var(--green);
        font-size: 1.08rem;
        line-height: 1.2;
    }

    .summary-strip small {
        color: var(--muted) !important;
        font-size: 0.72rem;
        font-weight: 700;
    }

    .section-heading {
        display: flex;
        align-items: end;
        gap: 12px;
        margin: 6px 0 14px;
    }

    .section-heading span {
        color: var(--text);
        font-size: 1.75rem;
        font-weight: 850;
        line-height: 1.2;
    }

    .section-heading em {
        color: var(--muted);
        font-size: 0.88rem;
        font-style: normal;
        font-weight: 650;
    }

    @keyframes orbitMove {
        to { transform: rotate(360deg); }
    }

    @keyframes radarSweep {
        to { transform: rotate(360deg); }
    }

    @media (max-width: 980px) {
        .hero-shell,
        .searching-panel {
            grid-template-columns: 1fr;
        }

        .hero-shell {
            min-height: auto;
            padding: 28px 26px;
        }

        .hero-panel {
            display: none;
        }

        .hero-copy h1 {
            font-size: 3.1rem !important;
        }

        .hero-copy p {
            font-size: 0.98rem;
        }

        .decision-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .workbench-summary {
            align-items: flex-start;
            flex-direction: column;
        }

        .brand-lockup {
            min-width: 0;
        }

        .summary-strip {
            justify-content: flex-start;
            max-width: none;
        }
    }

    @media (max-width: 640px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }

        .hero-shell {
            padding: 24px 20px;
        }

        .hero-copy h1 {
            font-size: 2.55rem !important;
        }

        .tender-head,
        .decision-grid,
        .workbench-summary {
            grid-template-columns: 1fr;
        }

        .workbench-summary {
            display: grid;
        }

        .brand-line {
            align-items: flex-start;
            flex-direction: column;
            gap: 10px;
        }

        .workbench-summary h1 {
            font-size: clamp(3rem, 16vw, 4.4rem) !important;
            line-height: 1 !important;
        }

        .brand-line .brand-subtitle {
            padding-left: 0;
            padding-top: 0;
            padding-bottom: 0;
            border-left: 0;
            font-size: 0.96rem;
        }

        .summary-strip,
        .lead-actions {
            justify-content: flex-start;
        }

        .section-heading {
            align-items: flex-start;
            flex-direction: column;
            gap: 6px;
        }

        .section-heading span {
            white-space: nowrap;
        }

        .lead-actions {
            min-width: 0;
            flex-wrap: wrap;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

radar_wait_slot = st.empty()

with st.sidebar:
    st.header("画像搜索")
    query = st.text_input("项目画像词", value=default_query, placeholder="例如：产业园、低空经济、展示中心、展陈")
    with st.expander("当前项目画像", expanded=False):
        st.caption(
            f"历史样本 {historical_profile.get('sample_count', 0)} 条；"
            f"正样本 {historical_profile.get('positive_sample_count', 0)} 条；"
            f"观察 {historical_profile.get('observe_sample_count', 0)} 条；"
            f"排除 {historical_profile.get('negative_sample_count', 0)} 条"
        )
        project_type_summary = top_count_items(historical_profile.get("project_type_counts"))
        client_type_summary = top_count_items(historical_profile.get("client_type_counts"))
        if project_type_summary:
            st.write("项目类型：" + project_type_summary)
        if client_type_summary:
            st.write("客户类型：" + client_type_summary)
        if historical_profile.get("search_terms"):
            st.write("画像词：" + "、".join(repair_text(term) for term in historical_profile["search_terms"][:12]))
        if historical_profile.get("downrank_terms"):
            st.write("降噪词：" + "、".join(repair_text(term) for term in historical_profile["downrank_terms"][:8]))
    days = st.selectbox(
        "时间范围",
        [7, 14, DEFAULT_INTERACTIVE_SEARCH_DAYS],
        index=2,
        format_func=lambda value: f"最近 {value} 天",
        help="工作台默认覆盖最近 30 天；新项目提醒仍只使用最近 7 天。",
    )
    region_filter = st.text_input("地区包含", value="", placeholder="例如：苏州、江苏、上海")
    search_depth_label = st.selectbox("搜索深度", ["标准搜索", "深度搜索"], index=1,
        help="深度搜索扩大分页和详情补全额度；结构化来源最多运行120秒，各来源并行执行。20天门槛保持不变。")
    search_depth = "deep" if search_depth_label == "深度搜索" else "standard"

    source_names = [
        item["name"]
        for item in sources_config.get("sources", [])
        if item.get("enabled", True) and item.get("crawler") != "example_public_page"
    ]
    default_sources = [
        item["name"]
        for item in sources_config.get("sources", [])
        if item.get("enabled", True)
        and item.get("crawler") != "example_public_page"
        and item.get("default_selected", False)
    ]
    source_config_by_name = {item["name"]: item for item in sources_config.get("sources", [])}
    source_labels = {}
    for name in source_names:
        config = source_config_by_name.get(name, {})
        label = repair_text(name)
        if config.get("risk_level") == "高":
            label = f"{label}（高风险/降权）"
        source_labels[name] = label
    selected_labels = st.multiselect(
        "数据源",
        list(source_labels.values()),
        default=[source_labels[name] for name in (default_sources or source_names)],
        key="source_selector_with_enterprise_hall_v5",
    )
    reverse_source_labels = {label: name for name, label in source_labels.items()}
    selected_sources = [reverse_source_labels[label] for label in selected_labels if label in reverse_source_labels]
    source_scope = st.selectbox(
        "搜寻范围",
        [SOURCE_SCOPE_BALANCED, SOURCE_SCOPE_CORE, SOURCE_SCOPE_WIDE],
        index=2,
        help="均衡拓源会自动补充已启用的非高风险来源；核心来源只跑手动勾选源；广域扫描会尝试所有启用来源。",
    )
    scope_source_names = build_scope_source_names(
        sources_config.get("sources", []),
        selected_sources,
        source_scope,
    )
    active_source_names = ordered_unique(selected_sources + scope_source_names)
    if scope_source_names:
        st.caption("自动拓源：" + "、".join(repair_text(name) for name in scope_source_names))
    balanced_candidates = balanced_backfill_source_names(sources_config.get("sources", []))
    paused_backfill_sources = [
        name
        for name in balanced_candidates
        if name not in selected_sources and name not in scope_source_names
    ]
    if source_scope != SOURCE_SCOPE_CORE and paused_backfill_sources:
        st.caption("暂停补源：" + "、".join(repair_text(name) for name in paused_backfill_sources))

    ai_ready = bool(os.getenv("OPENAI_API_KEY"))
    with st.expander("高级设置", expanded=False):
        enable_ai = st.checkbox("AI 二次判断", value=ai_ready, disabled=not ai_ready)
        max_ai_candidates = st.number_input("AI最多判断候选数", min_value=1, max_value=200, value=30, step=5)
        if not ai_ready:
            st.caption("未配置 OPENAI_API_KEY，AI 二次判断会自动跳过。")
        else:
            st.caption("AI 只会处理可投公告/情报参考中的候选线索。")

    if st.button("开始画像搜索", type="primary", icon=":material/search:", width="stretch"):
        radar_wait_slot.markdown(
            render_searching(query, len(active_source_names or [])),
            unsafe_allow_html=True,
        )
        time.sleep(1.4)
        search_regions = split_region_terms(region_filter)
        search_progress = st.progress(0.0, text="正在连接各来源…")
        def update_search_progress(status, completed, total):
            search_progress.progress(completed / max(total, 1), text=f"{completed}/{total} 来源完成：{status['source']} · {status['count']} 条候选")
        try:
            tenders, source_statuses = run_shared_search(
                selected_sources=active_source_names,
                query=query,
                days=int(days),
                regions=search_regions,
                enable_ai=enable_ai,
                max_ai_candidates=int(max_ai_candidates),
                search_depth=search_depth,
                progress_callback=update_search_progress,
            )
        except SearchBusyError as exc:
            search_progress.empty()
            radar_wait_slot.empty()
            st.warning(str(exc))
            st.stop()
        search_progress.empty()
        report = build_search_report(tenders, source_statuses, days=days, depth=search_depth)
        save_search_report(report)
        deadline_limited_count = sum(1 for tender in tenders if not has_actionable_deadline(tender, radar_today()))
        st.session_state["search_deadline_hidden_count"] = deadline_limited_count
        count = upsert_many(DB_PATH, tenders)
        st.session_state["source_statuses"] = source_statuses
        st.session_state["last_active_source_names"] = active_source_names
        per_source = {}
        for tender in tenders:
            source_name = repair_text(tender.source_name or "未知来源")
            per_source[source_name] = per_source.get(source_name, 0) + 1
        st.session_state["last_search_counts"] = per_source
        st.session_state["last_search_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        radar_wait_slot.empty()
        st.caption(f"本次已写入或更新 {count} 条线索。")
        if st.session_state.get("search_deadline_hidden_count"):
            st.caption(f"{st.session_state['search_deadline_hidden_count']} 条不足20天、已截止或日期不明，保留原始数据但不展示。")

    if st.session_state.get("source_statuses"):
        with st.expander("本次搜索状态", expanded=False):
            if st.session_state.get("last_search_counts"):
                st.caption("返回来源：" + "；".join(f"{name} {num} 条" for name, num in st.session_state["last_search_counts"].items()))
            for status in st.session_state["source_statuses"]:
                label = f"{repair_text(status['source'])}：{repair_text(status['status'])}（{status['count']} 条）"
                status_text = repair_text(status["status"])
                if status_text == "成功":
                    st.success(label)
                elif status_text in {"已禁用", "示例源跳过"}:
                    st.info(label)
                else:
                    st.warning(label)
                if status.get("message"):
                    st.caption(repair_text(status["message"]))
                if status.get("executed_terms"):
                    st.caption("本轮关键词：" + "、".join(repair_text(term) for term in status["executed_terms"]))
                if status.get("alert"):
                    st.warning(repair_text(status["alert"]))

    st.header("筛选")
    view_mode = st.selectbox("工作台视图", [VIEW_ACTION, VIEW_INTEL, VIEW_ALL], index=2)
    start_date, end_date = recent_date_window(days, max_days=MAX_INTERACTIVE_SEARCH_DAYS)
    st.date_input("开始日期", value=start_date, disabled=True)
    st.date_input("结束日期", value=end_date, disabled=True)
    st.caption(f"当前显示发布日期 {start_date.isoformat()} 至 {end_date.isoformat()} 的结果。")
    priority_filter = st.selectbox("优先级", ["全部", "高优先级", "中优先级", "低优先级", "可能无关"])
    user_score_filter = st.selectbox("你的评分", ["全部", "我的菜(8-10)", "观察(1-7)", "排除(0/负分)", "未评分"])
    notice_stage_filter = st.selectbox(
        "公告阶段",
        [
            NOTICE_STAGE_VIEW_DEFAULT,
            NOTICE_STAGE_BID,
            NOTICE_STAGE_INTEL,
            NOTICE_STAGE_CHANGE,
            NOTICE_STAGE_RESULT,
            NOTICE_STAGE_INVALID,
            "全部",
        ],
    )
    tender_status_filter = st.selectbox("可投状态", ["全部", "理想窗口", "正常跟进", "紧急跟进", "观察", "时间不足", "待核验", "已截止"])
    profile_project_options = ["全部"] + list((historical_profile.get("project_type_counts") or {}).keys())
    profile_client_options = ["全部"] + list((historical_profile.get("client_type_counts") or {}).keys())
    profile_project_filter = st.selectbox("画像项目类型", profile_project_options)
    profile_client_filter = st.selectbox("画像客户类型", profile_client_options)
    st.caption("硬性门槛：截止剩余至少20天；前期准备10天后，再开展方案和投标。日期不明不展示。")
    show_unrelated_tenders = st.checkbox("显示可能无关线索", value=view_mode == VIEW_ALL)
    merge_duplicate_rows = st.checkbox("合并跨来源重复线索", value=True)

    st.header("画像词配置")
    with st.expander("编辑画像词/规则词"):
        edited_keywords = {}
        for key, values in keywords.items():
            display_key = repair_text(key)
            text = st.text_area(display_key, value="\n".join(repair_text(item) for item in values), height=120)
            edited_keywords[key] = [line.strip() for line in text.splitlines() if line.strip()]
        if st.button("保存画像词配置", icon=":material/save:", width="stretch"):
            save_yaml(KEYWORDS_PATH, edited_keywords)
            st.success("画像词已保存，重新搜索后生效")

    st.header("自动学习")
    with st.expander("从样本标记学习"):
        learning_rows = fetch_tenders(DB_PATH)
        suggestions = build_learning_suggestions(learning_rows, keywords)
        st.caption(
            f"已标记样本 {suggestions['sample_count']} 条；"
            f"正样本 {suggestions['positive_count']} 条，误报 {suggestions['negative_count']} 条，"
            f"观察 {suggestions.get('observe_count', 0)} 条；已评分 {suggestions.get('scored_count', 0)} 条。"
        )
        if suggestions["positive_terms"]:
            st.write("建议扩展词：" + "、".join(suggestions["positive_terms"][:10]))
        if suggestions["negative_terms"]:
            st.write("建议降噪词：" + "、".join(suggestions["negative_terms"][:10]))
        if not suggestions["positive_terms"] and not suggestions["negative_terms"]:
            st.caption("先在工作台标记几条“这是我的菜”或“误报”，这里才会出现可学习的建议。")
        if st.button("应用学习建议", icon=":material/psychology:", width="stretch"):
            updated_keywords, changed_count = apply_learning_suggestions(keywords, suggestions)
            save_yaml(KEYWORDS_PATH, updated_keywords)
            st.success(f"已追加 {changed_count} 个画像词建议，重新搜索后生效。")

rows = fetch_tenders(
    DB_PATH,
    start_date=start_date.isoformat(),
    end_date=end_date.isoformat(),
    region="、".join(split_region_terms(region_filter) or []) or None,
    priority=None,
    source_names=active_source_names,
)

rows = [clean_row(row) for row in rows]
inventory_row_count = len(rows)
closed_deadline_count = sum(1 for row in rows if not is_open_for_tendering(row))
rows = [row for row in rows if is_open_for_tendering(row)]
review_rows = [row for row in rows if repair_text(row.get("review_bucket")) == "待研判"]
rows = [row for row in rows if repair_text(row.get("review_bucket")) != "待研判"]
review_hidden_count = len(review_rows)
raw_row_count = len(rows)
hidden_deadline_count = closed_deadline_count
before_unrelated_filter_count = len(rows)
if not show_unrelated_tenders and priority_filter != "可能无关":
    rows = [row for row in rows if repair_text(row["display_priority"]) != "可能无关"]
hidden_unrelated_count = before_unrelated_filter_count - len(rows)
if notice_stage_filter == NOTICE_STAGE_VIEW_DEFAULT:
    if view_mode == VIEW_ACTION:
        rows = [row for row in rows if row.get("notice_stage") == NOTICE_STAGE_BID]
    elif view_mode == VIEW_INTEL:
        rows = [
            row
            for row in rows
            if row.get("notice_stage") in {NOTICE_STAGE_BID, NOTICE_STAGE_INTEL}
        ]
elif notice_stage_filter != "全部":
    rows = [row for row in rows if row.get("notice_stage") == notice_stage_filter]
if priority_filter != "全部":
    rows = [row for row in rows if repair_text(row["display_priority"]) == priority_filter]
if user_score_filter != "全部":
    rows = [row for row in rows if match_user_score_filter(row, user_score_filter)]
if tender_status_filter != "全部":
    rows = [row for row in rows if row.get("tender_status") == tender_status_filter]
if profile_project_filter != "全部":
    rows = [
        row
        for row in rows
        if (row.get("profile_project_type") or row.get("ai_project_type") or "") == profile_project_filter
    ]
if profile_client_filter != "全部":
    rows = [row for row in rows if (row.get("profile_client_type") or "") == profile_client_filter]
filtered_row_count = len(rows)
if merge_duplicate_rows:
    rows = build_merged_rows(rows)
    merged_hidden_count = filtered_row_count - len(rows)
else:
    merged_hidden_count = 0
for row in rows:
    row["open_url"] = open_url(row)
rows = sorted(rows, key=row_sort_key)

df = pd.DataFrame(rows)

total_count = len(rows)
high_count = sum(1 for row in rows if row["display_priority"] == "高优先级")
urgent_count = sum(1 for row in rows if row.get("tender_status") == "理想窗口")

render_workbench_summary(total_count, high_count, urgent_count, start_date, end_date, inventory_row_count)
search_report = load_search_report()
if search_report:
    with st.expander("搜索覆盖与过滤原因", expanded=total_count <= 1):
        st.caption(f"最近搜索：{search_report.get('run_at', '-')}；本次统计为搜索候选，列表还会按你的视图和地区筛选、去重。")
        st.write(f"返回 {search_report.get('returned', 0)} 条 · 满足20天 {search_report.get('eligible', 0)} 条 · 日期不明 {search_report.get('unknown', 0)} 条 · 时间不足/已截止 {search_report.get('short', 0)} 条")
        st.write(f"尝试 {search_report.get('sources', 0)} 个来源 · 访问失败 {search_report.get('failed_sources', 0)} 个 · 二次补全截止日期 {search_report.get('detail_recovered', 0)} 条")
        details = [{"来源": s.get('source'), "状态": s.get('status'), "候选": s.get('count', 0), "20天可用": s.get('actionable_count', 0), "日期缺失": s.get('deadline_unknown_count', 0), "耗时(秒)": s.get('elapsed_seconds', 0), "说明": s.get('message', '')} for s in search_report.get('source_statuses', [])]
        if details:
            st.dataframe(pd.DataFrame(details), hide_index=True, width="stretch")
refresh_status = load_refresh_status(
    DATA_DIR / "manual_runs" / "last_manual_refresh.json",
    search_at=st.session_state.get("last_search_at") or search_report.get("run_at"),
)
if refresh_status["stale"]:
    st.warning(refresh_status["text"])
else:
    st.caption(refresh_status["text"])

visibility_notes = []
if review_hidden_count:
    visibility_notes.append(f"{review_hidden_count} 条待研判候选已折叠到下方")
if hidden_deadline_count:
    visibility_notes.append(f"{hidden_deadline_count} 条截止期不足20天、已截止或日期不明")
if hidden_unrelated_count:
    visibility_notes.append(f"{hidden_unrelated_count} 条可能无关线索")
if merged_hidden_count:
    visibility_notes.append(f"{merged_hidden_count} 条跨来源重复线索已合并")
if visibility_notes:
    st.caption("当前视图口径：" + "；".join(visibility_notes) + "。")
if raw_row_count > filtered_row_count:
    st.caption(f"当前视图已隐藏 {raw_row_count - filtered_row_count} 条低价值、非当前阶段或已过时线索，可切换到“全部库存”查看。")

if rows:
    st.markdown(
        '<div class="section-heading"><span>线索列表</span><em>按项目画像、截止时间和预算优先扫描</em></div>',
        unsafe_allow_html=True,
    )
    for item in rows[:30]:
        render_tender_card(item)
        with st.expander("查看详情", expanded=False):
            detail_cols = st.columns(3)
            detail_cols[0].write(f"地区：{item.get('region') or '-'}")
            detail_cols[1].write(f"预算：{item.get('budget') or '-'}")
            detail_cols[2].write(f"发布时间：{item.get('publish_date') or '-'}")
            st.write(f"采购人/招标人：{item.get('purchaser') or '-'}")
            st.write(f"代理机构：{item.get('agency') or '-'}")
            st.write(f"联系人：{item.get('contact_person') or '-'}")
            st.write(f"联系电话：{item.get('contact_phone') or '-'}")
            st.write(f"投标/响应截止：{item.get('bid_deadline') or '-'}")
            st.write(f"公告阶段：{item.get('notice_stage') or '-'}")
            st.write(f"可投状态：{item.get('tender_status') or '-'}；剩余：{days_left_text(item.get('days_left'))}")
            st.write(f"画像项目类型：{item.get('profile_project_type') or item.get('ai_project_type') or '-'}")
            st.write(f"画像客户类型：{item.get('profile_client_type') or '-'}")
            st.write(f"画像理由：{item.get('profile_reason') or '-'}")
            if int(item.get("merged_count") or 1) > 1:
                st.write(f"合并来源：{item.get('merged_sources') or '-'}")
            st.write(f"重要信息：{item.get('important_info') or '-'}")
            score_cols = st.columns([2, 1, 3])
            score_choice = score_cols[0].selectbox(
                "你的评分",
                USER_SCORE_OPTIONS,
                index=score_option_index(item.get("user_score")),
                format_func=score_option_label,
                key=f"quick_user_score_{item['id']}",
            )
            if score_cols[1].button("保存评分", key=f"save_user_score_{item['id']}", icon=":material/thumb_up:"):
                score_value = score_value_from_option(score_choice)
                update_user_score(DB_PATH, int(item["id"]), score_value)
                auto_label = feedback_label_from_user_score(score_value)
                if auto_label:
                    update_feedback_label(DB_PATH, int(item["id"]), auto_label)
                st.success("评分已保存，列表会按你的偏好重新排序。")
                st.rerun()
            st.link_button("打开原文", primary_source_url(item), icon=":material/open_in_new:")

    table_expander = st.expander("表格视图（高级）", expanded=False)
    display_cols = [
        "lead_action",
        "lead_quality_score",
        "lead_risk_level",
        "user_score",
        "display_priority",
        "relevance_score",
        "ai_suggested_action",
        "profile_project_type",
        "profile_client_type",
        "ai_project_type",
        "notice_stage",
        "source_name",
        "merged_count",
        "merged_sources",
        "title",
        "region",
        "budget",
        "publish_date",
        "tender_status",
        "days_left",
        "bid_deadline_date",
        "bid_deadline",
        "purchaser",
        "contact_phone",
        "matched_keywords",
        "lead_reason",
        "feedback_label",
        "open_url",
    ]
    safe_display_cols = [col for col in display_cols if col in df.columns]
    table_expander.dataframe(
        df[safe_display_cols],
        width="stretch",
        hide_index=True,
        column_config={
            "open_url": st.column_config.LinkColumn("打开链接"),
            "lead_action": "建议动作",
            "lead_quality_score": "质量分",
            "lead_risk_level": "风险",
            "user_score": st.column_config.NumberColumn("你的评分", min_value=-10, max_value=10, step=1),
            "display_priority": "优先级",
            "relevance_score": "评分",
            "ai_suggested_action": "AI建议",
            "profile_project_type": "画像项目类型",
            "profile_client_type": "画像客户类型",
            "ai_project_type": "AI项目类型",
            "notice_stage": "公告阶段",
            "title": "标题",
            "source_name": "来源",
            "merged_count": "合并条数",
            "merged_sources": "合并来源",
            "region": "地区",
            "budget": "预算",
            "publish_date": "发布时间",
            "tender_status": "可投状态",
            "days_left": "剩余天数",
            "bid_deadline_date": "截止日期",
            "bid_deadline": "截止时间",
            "purchaser": "采购人",
            "contact_phone": "联系电话",
            "matched_keywords": "命中关键词",
            "lead_reason": "判断依据",
            "feedback_label": "样本标记",
        },
    )

    workbench_expander = st.expander("状态与备注（高级）", expanded=False)
    selected_title = workbench_expander.selectbox("选择线索", [f"{row['id']} · {row['title']}" for row in rows])
    selected_id = int(selected_title.split(" · ", 1)[0])
    selected = next(item for item in rows if item["id"] == selected_id)

    workbench_expander.markdown(f"### {selected['title']}")
    detail_cols = workbench_expander.columns(3)
    detail_cols[0].write(f"建议动作：{selected.get('lead_action') or '-'}")
    detail_cols[1].write(f"质量分：{selected.get('lead_quality_score') or 0}")
    detail_cols[2].write(f"发布时间：{selected['publish_date'] or '-'}")
    workbench_expander.write(f"你的评分：{user_score_display(selected.get('user_score'))}")
    workbench_expander.write(f"优先级：{selected['display_priority']}；规则评分：{selected['relevance_score']}；风险：{selected.get('lead_risk_level') or '-'}")
    workbench_expander.write(f"判断依据：{selected.get('lead_reason') or '-'}")
    workbench_expander.write(f"公告阶段：{selected.get('notice_stage') or '-'}")
    if int(selected.get("merged_count") or 1) > 1:
        workbench_expander.write(f"合并来源：{selected.get('merged_sources') or '-'}")
    ai_text = "未启用/未判断"
    if selected.get("ai_classified"):
        relevant = "相关" if selected.get("ai_is_relevant") else "不相关"
        ai_text = (
            f"{relevant} · 调整 {selected.get('ai_score_adjustment', 0)} · "
            f"{selected.get('ai_project_type') or '-'} · {selected.get('ai_suggested_action') or '-'}"
        )
    workbench_expander.write(f"AI判断：{ai_text}")
    if selected.get("ai_reason"):
        workbench_expander.write(f"AI原因：{selected.get('ai_reason')}")
    workbench_expander.write(f"画像项目类型：{selected.get('profile_project_type') or selected.get('ai_project_type') or '-'}")
    workbench_expander.write(f"画像客户类型：{selected.get('profile_client_type') or '-'}")
    workbench_expander.write(f"画像理由：{selected.get('profile_reason') or '-'}")
    workbench_expander.write(f"地区：{selected.get('region') or '-'}")
    workbench_expander.write(f"采购人/招标人：{selected.get('purchaser') or '-'}")
    workbench_expander.write(f"代理机构：{selected.get('agency') or '-'}")
    workbench_expander.write(f"预算/最高限价：{selected.get('budget') or '-'}")
    workbench_expander.write(f"项目编号：{selected.get('project_no') or '-'}")
    workbench_expander.write(f"联系人：{selected.get('contact_person') or '-'}")
    workbench_expander.write(f"联系电话：{selected.get('contact_phone') or '-'}")
    workbench_expander.write(f"投标/响应截止：{selected.get('bid_deadline') or '-'}")
    workbench_expander.write(f"可投状态：{selected.get('tender_status') or '-'}；剩余：{days_left_text(selected.get('days_left'))}；结构化截止：{selected.get('bid_deadline_date') or '-'}")
    workbench_expander.write(f"命中关键词：{selected.get('matched_keywords') or '-'}")
    workbench_expander.write(f"重要信息：{selected.get('important_info') or '-'}")
    workbench_expander.write(f"摘要：{selected.get('summary') or '-'}")
    workbench_expander.link_button("打开原文链接", primary_source_url(selected), icon=":material/open_in_new:")

    read_value = workbench_expander.checkbox("已读", value=bool(selected["is_read"]))
    feedback_options = ["", "这是我的菜", "误报", "待观察"]
    current_feedback = selected.get("feedback_label") or ""
    feedback_index = feedback_options.index(current_feedback) if current_feedback in feedback_options else 0
    selected_score_choice = workbench_expander.selectbox(
        "你的评分",
        USER_SCORE_OPTIONS,
        index=score_option_index(selected.get("user_score")),
        format_func=score_option_label,
        key=f"workbench_user_score_{selected_id}",
    )
    feedback_value = workbench_expander.selectbox("样本标记", feedback_options, index=feedback_index, format_func=lambda value: value or "未标记")
    remark_value = workbench_expander.text_area("备注", value=selected.get("remark") or "")
    action_cols = workbench_expander.columns([1, 1, 4])
    if action_cols[0].button("保存状态", icon=":material/check_circle:"):
        update_read_status(DB_PATH, selected_id, read_value)
        update_remark(DB_PATH, selected_id, remark_value)
        selected_score_value = score_value_from_option(selected_score_choice)
        update_user_score(DB_PATH, selected_id, selected_score_value)
        update_feedback_label(DB_PATH, selected_id, resolve_feedback_label(selected_score_value, feedback_value))
        st.success("已保存")
        st.rerun()

    export_path = EXPORT_DIR / f"tender_leads_{date.today().isoformat()}.xlsx"
    if action_cols[1].button("导出 Excel", icon=":material/download:"):
        output = export_to_excel(rows, export_path)
        st.success(f"已导出：{output}")
else:
    st.info("暂无线索。点击左侧“开始画像搜索”生成第一批结果。")

if review_rows:
    review_rows = sorted(review_rows, key=row_sort_key)
    with st.expander(f"待研判候选（{len(review_rows)}）", expanded=False):
        st.caption("这些项目已命中展厅画像，但未通过自动质量门槛；不会进入主列表或自动提醒，可直接打开原文并评分。")
        for item in review_rows[:20]:
            summary_cols = st.columns([5, 2, 2, 2])
            summary_cols[0].write(item.get("title") or "未命名项目")
            summary_cols[1].write(item.get("source_name") or "未知来源")
            summary_cols[2].write(item.get("budget") or "预算待核")
            summary_cols[3].link_button("打开原文", primary_source_url(item), icon=":material/open_in_new:", key=f"review_open_{item['id']}")
            st.caption(item.get("profile_reason") or "自动质量门槛待人工复核")
            score_cols = st.columns([2, 1, 6])
            choice = score_cols[0].selectbox(
                "你的评分",
                USER_SCORE_OPTIONS,
                index=score_option_index(item.get("user_score")),
                format_func=score_option_label,
                key=f"review_user_score_{item['id']}",
            )
            if score_cols[1].button("保存评分", key=f"review_save_score_{item['id']}", icon=":material/thumb_up:"):
                score_value = score_value_from_option(choice)
                update_user_score(DB_PATH, int(item["id"]), score_value)
                auto_label = feedback_label_from_user_score(score_value)
                if auto_label:
                    update_feedback_label(DB_PATH, int(item["id"]), auto_label)
                st.success("评分已保存")
                st.rerun()
