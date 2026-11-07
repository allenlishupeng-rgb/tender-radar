# 招标雷达 · 团队测试

完整Python工作台：多来源搜索、截止剩余至少20天筛选、团队评分和Excel导出。

## Streamlit Community Cloud

在 https://share.streamlit.io/ 登录并创建应用：

- Repository: `allenlishupeng-rgb/tender-radar`
- Branch: `main`
- Main file path: `streamlit_app.py`
- Python: `3.12`
- App URL: 可选择尚未被占用的固定子域名，实际网址以部署成功后的返回值为准。

在 Advanced settings → Secrets 中配置（实际口令不要提交GitHub）：

```toml
RADAR_TEAM_PASSWORD = "替换为你自己的长随机口令"
```

未配置口令时，入口拒绝显示工作台。应用可分享给同事，口令单独传递。同事共用数据库、评分与备注；一次只允许一个搜索任务，避免重复抓取。

免费托管的本地文件不应作为长期存储；服务重建或重启后数据可能丢失，请导出重要记录。上线后需从云端再验证来源可访问性、登录、搜索和评分，不能以本地测试代替线上验证。

本仓库只包含部署代码与公开来源配置，不包含本地数据库、公司历史样本、评分、日志和密钥。行业画像使用默认词库。

[Streamlit部署文档](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)

## 云端访问不了国内招采网站时：本机采集，云端展示

Streamlit Community Cloud 的服务器在海外，国内政府采购站点可能限流或拒绝访问。这时改由国内电脑采集，云端只负责展示和团队评分：

```text
国内电脑：scripts/collect_and_sync.py  →  私有数据仓库 collection_bundle.json
云端工作台：每 10 分钟最多检查一次同步地址 → 校验签名 → 导入（不覆盖团队评分/备注）
```

一次性设置：

1. 在 GitHub 新建**私有**仓库（例如 `tender-radar-data`），克隆到国内电脑。不要用本源码仓库，它是公开的；脚本也会拒绝。
2. 为这个数据仓库创建 fine-grained token，只授予该仓库的 Contents: Read-only 权限。
3. 生成一个长随机字符串作为签名密钥，两端都配置为 `RADAR_SYNC_KEY`。
4. 云端 Secrets 增加：

```toml
RADAR_COLLECTION_MODE = "local"   # 隐藏云端直接搜索
RADAR_SYNC_URL = "https://api.github.com/repos/<你的账号>/tender-radar-data/contents/collection_bundle.json"
RADAR_SYNC_TOKEN = "<只读 token>"
RADAR_SYNC_KEY = "<签名密钥>"
```

5. 国内电脑设置环境变量 `RADAR_SYNC_KEY`（同一个值）和 `RADAR_SYNC_REPO_DIR`（数据仓库克隆目录）。

日常使用：双击 `scripts/collect_and_sync.cmd`，或运行

```bash
python scripts/collect_and_sync.py                # 搜索 → 写本机库 → 生成采集包 → 提交并推送到数据仓库
python scripts/collect_and_sync.py --skip-search  # 不搜索，只把本机现有 30 天库存同步上去
```

云端页面侧栏“本机采集同步”会显示最近一次导入，也可以手动“立即拉取”，或者直接上传采集包 JSON（没有数据仓库时的备用办法）。采集包只含公开公告字段，个人评分、备注、已读状态不会上传。免费云端重启后数据库会清空，下次打开页面时会自动从同步地址恢复公告；团队评分仍需持久化存储才能保留。

脚本不会创建定时任务。需要定时采集时，由你自己决定后再配置 Windows 任务计划。

## 开发与测试

接手开发先读 `AGENTS.md`（业务规则、隐私边界、修改入口）。离线测试：

```bash
python -m pip install -r requirements-tested.txt
python -m pytest -q
```

GitHub Actions 在每次推送时运行同一套离线测试，不访问真实招采网站。
