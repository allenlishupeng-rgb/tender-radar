import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import DB_PATH, ROOT_DIR
from database.db import build_merged_rows, fetch_tenders
from exporters.excel_exporter import export_to_excel
from parsers.extractors import MIN_ACTIONABLE_DAYS_LEFT, PREPARATION_DAYS, is_open_for_tendering
from presentation.lead_row import normalize_lead_row
from scoring.project_profile import is_public_culture_without_target
from scoring.rules import NOTICE_STAGE_INVALID
from utils.date_window import DEFAULT_INTERACTIVE_SEARCH_DAYS, MAX_INTERACTIVE_SEARCH_DAYS, recent_date_window


OUTPUT_DIR = ROOT_DIR / "docs"
RESULTS_JSON = "results.json"
RESULTS_XLSX = "results.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only GitHub Pages site from local project profile radar results.")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_INTERACTIVE_SEARCH_DAYS,
        help="Publish results from the last N days. Default: 30.",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Static site output directory. Default: docs.")
    parser.add_argument("--title", default="咕咕嘎嘎", help="Public page title.")
    parser.add_argument("--no-merge", action="store_true", help="Do not merge duplicate leads across sources.")
    return parser.parse_args()


def clean_row(row: dict) -> dict:
    cleaned = normalize_lead_row(row)
    try:
        cleaned["relevance_score"] = int(cleaned.get("relevance_score") or 0)
    except (TypeError, ValueError):
        cleaned["relevance_score"] = 0
    return cleaned


def row_fit_text(row: dict) -> str:
    fields = ["title", "purchaser"]
    return " ".join(str(row.get(field, "") or "") for field in fields)


def is_publishable_target_row(row: dict) -> bool:
    if row.get("review_bucket") == "待研判":
        return False
    if not is_open_for_tendering(row):
        return False
    if row.get("notice_stage") == NOTICE_STAGE_INVALID:
        return False
    if row.get("priority") == "可能无关":
        return False
    if is_public_culture_without_target(row_fit_text(row), row.get("profile_project_type", "")):
        return False
    return True


def is_publishable_review_row(row: dict) -> bool:
    return (
        row.get("review_bucket") == "待研判"
        and is_open_for_tendering(row)
        and row.get("notice_stage") != NOTICE_STAGE_INVALID
    )


def public_row(row: dict) -> dict:
    fields = [
        "title",
        "lead_action",
        "lead_quality_score",
        "lead_risk_level",
        "lead_reason",
        "user_score",
        "priority",
        "relevance_score",
        "profile_project_type",
        "profile_client_type",
        "profile_reason",
        "notice_stage",
        "tender_status",
        "days_left",
        "design_days_left",
        "source_name",
        "merged_count",
        "merged_sources",
        "announcement_type",
        "region",
        "budget",
        "publish_date",
        "bid_deadline_date",
        "bid_deadline",
        "purchaser",
        "agency",
        "contact_person",
        "contact_phone",
        "project_no",
        "matched_keywords",
        "important_info",
        "summary",
        "source_url",
        "feedback_label",
        "remark",
        "review_bucket",
    ]
    return {field: row.get(field, "") for field in fields}


def build_html(title: str, rows: list[dict], generated_at: str, start_date: str, end_date: str) -> str:
    rows_json = json.dumps(rows, ensure_ascii=False)
    source_counts = Counter(row.get("source_name") or "未知来源" for row in rows)
    source_summary = "；".join(f"{name} {count} 条" for name, count in source_counts.items()) or "暂无数据"
    total = len(rows)
    main_count = sum(1 for row in rows if row.get("review_bucket") != "待研判")
    review_count = total - main_count
    high = sum(1 for row in rows if row.get("priority") == "高优先级")
    bid_count = sum(1 for row in rows if row.get("notice_stage") == "可投公告")
    action_now_count = sum(1 for row in rows if row.get("lead_action") == "立即跟进")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #070b10;
      --panel: #101820;
      --panel-2: #0c131a;
      --line: #1d3c3c;
      --text: #ecfff8;
      --muted: #99aaa8;
      --green: #24e0a6;
      --blue: #4fc3ff;
      --amber: #ffd166;
      --red: #ff6b7c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      background:
        linear-gradient(135deg, rgba(36,224,166,.06) 1px, transparent 1px),
        linear-gradient(45deg, rgba(79,195,255,.05) 1px, transparent 1px),
        var(--bg);
      background-size: 32px 32px;
      color: var(--text);
    }}
    header {{
      padding: 34px 5vw 24px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, rgba(36,224,166,.13), rgba(79,195,255,.08) 42%, rgba(7,11,16,.92));
    }}
    h1 {{ margin: 0 0 10px; font-size: clamp(34px, 7vw, 72px); letter-spacing: 0; }}
    .subtitle {{ color: var(--muted); font-size: 16px; line-height: 1.6; }}
    main {{ padding: 24px 5vw 48px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 22px 0; }}
    .card {{
      border: 1px solid var(--line);
      background: rgba(16,24,32,.86);
      border-radius: 8px;
      padding: 16px;
      min-height: 92px;
    }}
    .label {{ color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .value {{ font-size: 30px; font-weight: 800; }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) repeat(8, 145px) 140px;
      gap: 10px;
      margin: 20px 0;
    }}
    input, select, a.button {{
      width: 100%;
      border: 1px solid var(--line);
      background: #071016;
      color: var(--text);
      border-radius: 8px;
      padding: 11px 12px;
      font-size: 14px;
      text-decoration: none;
    }}
    a.button {{ display: inline-flex; justify-content: center; align-items: center; font-weight: 700; }}
    .table-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: 8px; background: rgba(7,12,18,.72); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1540px; }}
    th, td {{ border-bottom: 1px solid rgba(255,255,255,.08); padding: 12px 10px; text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #111922; color: #dffdf5; z-index: 1; }}
    td {{ color: #e9fff8; font-size: 13px; line-height: 1.45; }}
    .title-cell {{ min-width: 360px; font-weight: 750; }}
    .muted {{ color: var(--muted); }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 800; white-space: nowrap; }}
    .高优先级 {{ background: rgba(36,224,166,.18); color: var(--green); }}
    .中优先级 {{ background: rgba(255,209,102,.16); color: var(--amber); }}
    .低优先级 {{ background: rgba(79,195,255,.16); color: var(--blue); }}
    .可能无关 {{ background: rgba(255,107,124,.16); color: var(--red); }}
    .source-summary {{ margin: 10px 0 0; color: var(--muted); }}
    footer {{ color: var(--muted); padding-top: 22px; font-size: 13px; }}
    @media (max-width: 900px) {{
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .toolbar {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div class="subtitle">李奇的展厅项目画像雷达</div>
    <div class="source-summary">仅显示截止剩余至少{MIN_ACTIONABLE_DAYS_LEFT}天的项目（按北京时间自然日计算）。前期准备{PREPARATION_DAYS}天，再开展方案和投标。下载文件为生成时快照。</div>
    <div class="source-summary">发布时间范围：{escape(start_date)} 至 {escape(end_date)} · 生成时间：{escape(generated_at)}</div>
    <div class="source-summary">来源汇总：{escape(source_summary)}</div>
  </header>
  <main>
    <section class="stats">
      <div class="card"><div class="label">主结果</div><div class="value">{main_count}</div></div>
      <div class="card"><div class="label">待研判</div><div class="value">{review_count}</div></div>
      <div class="card"><div class="label">高优先级</div><div class="value">{high}</div></div>
      <div class="card"><div class="label">可投公告</div><div class="value">{bid_count}</div></div>
    </section>
    <section class="toolbar">
      <input id="q" placeholder="筛选项目、画像词、地区、采购人">
      <select id="pool"><option>主结果</option><option>待研判</option><option value="">全部线索</option></select>
      <select id="action"><option value="">全部动作</option><option>立即跟进</option><option>进入跟进池</option><option>机会池观察</option><option>人工筛选</option><option>情报复盘</option><option>暂不跟进</option></select>
      <select id="source"><option value="">全部来源</option></select>
      <select id="stage"><option value="">全部阶段</option><option>可投公告</option><option>情报参考</option><option>更正澄清</option><option>中标结果</option><option>无效</option></select>
      <select id="status"><option value="">全部状态</option><option>理想窗口</option><option>正常跟进</option><option>紧急跟进</option><option>观察</option><option>时间不足</option><option>待核验</option><option>已截止</option></select>
      <select id="priority"><option value="">全部优先级</option><option>高优先级</option><option>中优先级</option><option>低优先级</option><option>可能无关</option></select>
      <select id="projectType"><option value="">全部画像</option></select>
      <select id="clientType"><option value="">全部客户</option></select>
      <a class="button" href="{RESULTS_XLSX}" download>下载 Excel</a>
    </section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
              <th>分组</th><th>动作</th><th>质量</th><th>你的评分</th><th>风险</th><th>阶段</th><th>优先级</th><th>评分</th><th>画像类型</th><th>客户类型</th><th>状态</th><th>剩余</th><th>来源</th><th>标题</th><th>地区</th><th>预算</th>
            <th>发布时间</th><th>截止日期</th><th>采购人</th><th>联系电话</th><th>命中词</th><th>样本</th><th>原文</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <footer>数据来自咕咕嘎嘎本地搜索结果；原文链接指向各公开平台，请以官方页面为最终核验依据。</footer>
  </main>
  <script>
    const DATA = {rows_json};
    const tbody = document.getElementById('rows');
    const q = document.getElementById('q');
    const pool = document.getElementById('pool');
    const action = document.getElementById('action');
    const source = document.getElementById('source');
    const stage = document.getElementById('stage');
    const status = document.getElementById('status');
    const priority = document.getElementById('priority');
    const projectType = document.getElementById('projectType');
    const clientType = document.getElementById('clientType');
    const sources = [...new Set(DATA.map(row => row.source_name || '未知来源'))].sort();
    const projectTypes = [...new Set(DATA.map(row => row.profile_project_type || '未标记'))].sort();
    const clientTypes = [...new Set(DATA.map(row => row.profile_client_type || '未标记'))].sort();
    source.innerHTML += sources.map(name => `<option>${{escapeHtml(name)}}</option>`).join('');
    projectType.innerHTML += projectTypes.map(name => `<option>${{escapeHtml(name)}}</option>`).join('');
    clientType.innerHTML += clientTypes.map(name => `<option>${{escapeHtml(name)}}</option>`).join('');

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function rowText(row) {{
        return [row.title,row.region,row.purchaser,row.agency,row.summary,row.important_info,row.source_name,row.merged_sources,row.notice_stage,row.tender_status,row.lead_action,row.lead_reason,row.user_score,row.matched_keywords,row.profile_project_type,row.profile_client_type,row.profile_reason].join(' ').toLowerCase();
    }}
    function render() {{
      // Recheck against the viewing date, not the publication/export date.
      const today = new Date().toLocaleDateString('sv-SE', {{timeZone: 'Asia/Shanghai'}});
      const todayMs = Date.parse(today + 'T00:00:00+08:00');
      DATA.forEach(row => {{
        row.days_left = Math.round((Date.parse(row.bid_deadline_date + 'T00:00:00+08:00') - todayMs) / 86400000);
        row.design_days_left = Math.max(0, row.days_left - {PREPARATION_DAYS});
      }});
      const text = q.value.trim().toLowerCase();
      const bucket = pool.value;
      const a = action.value;
      const s = source.value;
      const g = stage.value;
      const t = status.value;
      const p = priority.value;
      const pt = projectType.value;
      const ct = clientType.value;
      const filtered = DATA.filter(row =>
        Number.isFinite(row.days_left) && row.days_left >= {MIN_ACTIONABLE_DAYS_LEFT} &&
        (!text || rowText(row).includes(text)) &&
        (!bucket || (bucket === '待研判' ? row.review_bucket === '待研判' : row.review_bucket !== '待研判')) &&
        (!a || row.lead_action === a) &&
        (!s || row.source_name === s) &&
        (!g || row.notice_stage === g) &&
        (!t || row.tender_status === t) &&
        (!p || row.priority === p) &&
        (!pt || row.profile_project_type === pt) &&
        (!ct || row.profile_client_type === ct)
      );
      tbody.innerHTML = filtered.map(row => `
        <tr>
            <td>${{escapeHtml(row.review_bucket || '主结果')}}</td>
            <td>${{escapeHtml(row.lead_action || '-')}}<div class="muted">${{escapeHtml(row.lead_reason || '')}}</div></td>
            <td>${{escapeHtml(row.lead_quality_score ?? '-')}}</td>
            <td>${{escapeHtml(row.user_score ?? '-')}}</td>
            <td>${{escapeHtml(row.lead_risk_level || '-')}}</td>
          <td>${{escapeHtml(row.notice_stage || '-')}}</td>
          <td><span class="pill ${{escapeHtml(row.priority || '可能无关')}}">${{escapeHtml(row.priority || '-')}}</span></td>
          <td>${{escapeHtml(row.relevance_score)}}</td>
          <td>${{escapeHtml(row.profile_project_type || '-')}}<div class="muted">${{escapeHtml(row.profile_reason || '')}}</div></td>
          <td>${{escapeHtml(row.profile_client_type || '-')}}</td>
          <td>${{escapeHtml(row.tender_status || '-')}}</td>
          <td>${{escapeHtml(row.days_left ?? '-')}}</td>
          <td>${{escapeHtml(row.merged_sources || row.source_name)}}${{Number(row.merged_count || 1) > 1 ? `<div class="muted">合并 ${{escapeHtml(row.merged_count)}} 条</div>` : ''}}</td>
          <td class="title-cell">${{escapeHtml(row.title)}}<div class="muted">${{escapeHtml(row.announcement_type || '')}}</div></td>
          <td>${{escapeHtml(row.region)}}</td>
          <td>${{escapeHtml(row.budget || '-')}}</td>
          <td>${{escapeHtml(row.publish_date || '-')}}</td>
          <td>${{escapeHtml(row.bid_deadline_date || row.bid_deadline || '-')}}</td>
          <td>${{escapeHtml(row.purchaser || '-')}}</td>
          <td>${{escapeHtml(row.contact_phone || '-')}}</td>
          <td>${{escapeHtml(row.matched_keywords || '-')}}</td>
          <td>${{escapeHtml(row.feedback_label || '-')}}</td>
          <td>${{row.source_url ? `<a href="${{escapeHtml(row.source_url)}}" target="_blank" rel="noopener">打开</a>` : '-'}}</td>
        </tr>`).join('');
    }}
    q.addEventListener('input', render);
    pool.addEventListener('change', render);
    action.addEventListener('change', render);
    source.addEventListener('change', render);
    stage.addEventListener('change', render);
    status.addEventListener('change', render);
    priority.addEventListener('change', render);
    projectType.addEventListener('change', render);
    clientType.addEventListener('change', render);
    render();
    setInterval(render, 60000);
  </script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    start, end = recent_date_window(args.days, max_days=MAX_INTERACTIVE_SEARCH_DAYS)
    source_rows = fetch_tenders(DB_PATH, start_date=start.isoformat(), end_date=end.isoformat())
    source_rows = [clean_row(row) for row in source_rows]
    main_rows = [row for row in source_rows if is_publishable_target_row(row)]
    review_rows = [row for row in source_rows if is_publishable_review_row(row)]
    if not args.no_merge:
        main_rows = [clean_row(row) for row in build_merged_rows(main_rows)]
        main_rows = [row for row in main_rows if is_publishable_target_row(row)]
        review_rows = [clean_row(row) for row in build_merged_rows(review_rows)]
        review_rows = [row for row in review_rows if is_publishable_review_row(row)]
    rows = [*main_rows, *review_rows]
    rows = [public_row(row) for row in rows]
    stage_order = {"可投公告": 0, "情报参考": 1, "更正澄清": 2, "中标结果": 3, "无效": 4}
    status_order = {"理想窗口": 0, "正常跟进": 1, "紧急跟进": 2, "观察": 3, "待核验": 4, "时间不足": 5, "已截止": 6}
    action_order = {"立即跟进": 0, "进入跟进池": 1, "机会池观察": 2, "人工筛选": 3, "情报复盘": 4, "暂不跟进": 5}
    rows.sort(
        key=lambda row: (
            1 if row.get("review_bucket") == "待研判" else 0,
            action_order.get(row.get("lead_action") or "", 99),
            stage_order.get(row.get("notice_stage") or "", 99),
            status_order.get(row.get("tender_status") or "", 99),
            -(row.get("user_score") if row.get("user_score") is not None else -99),
            -(row.get("lead_quality_score") or 0),
            -(row.get("relevance_score") or 0),
            row.get("publish_date") or "",
        )
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (output_dir / RESULTS_JSON).write_text(
        json.dumps({"generated_at": generated_at, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "index.html").write_text(
        build_html(args.title, rows, generated_at, start.isoformat(), end.isoformat()),
        encoding="utf-8",
    )
    export_to_excel(rows, output_dir / RESULTS_XLSX)
    print(f"Published {len(main_rows)} main rows and {len(review_rows)} review rows to {output_dir}")
    print(f"Open: {output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
