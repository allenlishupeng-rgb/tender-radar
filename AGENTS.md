# AGENTS.md

本仓库是“咕咕嘎嘎招标雷达”团队测试版的唯一源码仓库（公开仓库）。接手的开发者或 AI 平台先读本文件。

## 协作循环

ALLEN 只输入“继续 / 继续优化 / 继续完善”时，直接执行：计划 → 执行 → 验证 → 复盘，再进入下一轮必要迭代。除非遇到必须由 ALLEN 决定的产品取舍，不先反问。每轮小步修改，并报告验证结果。

## 公开仓库的隐私边界

不得提交：`config/historical_project_profile.yaml`、`data/`（SQLite、历史 CSV、运行摘要）、评分与备注、公司历史项目分析文档、日志、`.env`、`secrets.toml`、API 密钥、迁移快照 Markdown。`.gitignore` 已列出这些路径；新增私有文件时同步补充。缺少私有画像时程序使用默认行业词库，依赖私有数据的测试自动跳过。

## 不可回归的业务规则

- 硬门槛：截止剩余至少 20 天（`MIN_ACTIONABLE_DAYS_LEFT`），日期不明不展示；前期准备 10 天（`PREPARATION_DAYS`）。UI、Excel、静态页、巡检均以 `parsers.extractors.is_open_for_tendering()` 为准，不要各写一套阈值。
- 日期按北京时间自然日计算。`config/settings.py` 在类 Unix 主机上把进程时区设为 `CST-8`（可用 `RADAR_TIMEZONE` 覆盖），避免 UTC 云主机在北京时间 0–8 点算错一天。
- 企业/总部/品牌/科技展厅、产业展示中心、设计施工一体化优先；泛博物馆、文化馆、纯文旅公共文化默认降噪。
- 公告阶段、截止窗口、业务相关度、用户评分是四个独立字段；结果类公告不能当作可投。
- 刷新不能覆盖已读、备注、反馈标签、用户评分；后续抓取的空预算/空截止日期不能擦除已有值。
- 显式空来源列表 `[]` 不能扩展成全量搜索。
- 采集包只含公开公告字段（`PERSONAL_FIELDS` 之外）；导入走 `upsert_many`，不能覆盖云端团队的评分、备注、已读。
- 截止日期补全先搜索、后补全：按优先级、相关度、发布日期排序，有候选时才预留来源时间预算。
- 只访问公开信息，遵守 robots，不绕过登录、验证码或反爬。
- 每日自动巡检已关闭：不创建定时任务、不发送通知、不发布站点，除非 ALLEN 另行要求。

## 运行与验证

```bash
python -m pip install -r requirements-tested.txt
python -m pytest -q                      # 离线测试，CI 同样运行
python -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
curl http://127.0.0.1:8501/_stcore/health   # 应返回 ok
```

云端部署见 `README.md`（Streamlit Community Cloud）与 `README_CLOUD.md`（Render/Docker）。存储目录由 `RADAR_DATA_DIR`、`RADAR_EXPORT_DIR`、`RADAR_LOG_DIR` 控制，维护脚本与 UI 使用同一目录。

## 修改入口

| 想改什么 | 先读 |
|---|---|
| 来源与搜索范围 | `config/sources.yaml`、`crawlers/runner.py`、`crawlers/registry.py` |
| 关键词与画像 | `config/keywords.yaml`、`scoring/project_profile.py` |
| 相关度与优先级 | `scoring/rules.py`、`presentation/lead_row.py` |
| 截止日期提取与门槛 | `parsers/extractors.py` |
| 存储、去重、用户字段 | `database/db.py` |
| 团队访问与并发搜索 | `ui/team_access.py`、`utils/shared_search.py` |
| 搜索覆盖报告 | `presentation/search_report.py` |
| 本机采集 → 云端同步 | `collection_sync/bundle.py`、`scripts/collect_and_sync.py` |
| 详情补全优先级 | `crawlers/runner.py` 的 `select_recovery_candidates()` |
| 静态页 / Excel | `scripts/generate_static_site.py`、`exporters/excel_exporter.py` |

新增来源适配器：继承 `BaseCrawler`，实现 `search(query, days, start_date, end_date, regions)` 返回 `list[Tender]`，用 `last_error` 表达失败，在注册表和 YAML 中登记，并用 `tests/fixtures/` 的脱网样本测试解析。
