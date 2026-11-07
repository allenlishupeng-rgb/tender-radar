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

## 开发与测试

接手开发先读 `AGENTS.md`（业务规则、隐私边界、修改入口）。离线测试：

```bash
python -m pip install -r requirements-tested.txt
python -m pytest -q
```

GitHub Actions 在每次推送时运行同一套离线测试，不访问真实招采网站。
