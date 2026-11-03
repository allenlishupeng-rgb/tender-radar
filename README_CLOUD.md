# 招标雷达团队测试版

完整 Streamlit 后端保留搜索、筛选、评分、Excel导出和20天硬门槛。部署成功后，Render 分配固定 HTTPS 网址，可在同事的电脑和手机使用，无需本机持续开机。当前文件只是部署配置，不代表线上服务已经创建。

## 部署

1. 在 GitHub 建立专用私有仓库，将 `build/tender-radar-cloud.zip` 解压后的内容上传到仓库根目录；不要上传本地数据库、日志、历史快照、密钥或公司项目样本。
2. 在 Render 连接这个仓库，用根目录 `render.yaml` 创建 Blueprint。默认仅免费测试服务；密码由平台生成，在服务的 Environment 页面查看 `RADAR_TEAM_PASSWORD`，单独告知测试同事。
3. 等待构建和 `/_stcore/health` 检查成功，使用平台实际返回的固定网址。先验证登录、搜索、评分与导出，再分发。
4. 免费环境的SQLite会在休眠、重启和重新部署时清空，不适合长期保存评分。需要长期保存时，经费用确认后使用 `deploy/render.persistent.yaml`（付费服务和1GB持久化磁盘）。磁盘用于 `/var/radar`，覆盖数据、导出和日志；应另外定期备份。

## 环境变量

| 变量 | 用途 |
| --- | --- |
| `RADAR_REQUIRE_LOGIN=true` | 云端必须启用；口令未设置时拒绝进入工作台 |
| `RADAR_TEAM_PASSWORD` | 团队共享访问口令，不能提交到代码仓库 |
| `RADAR_DATA_DIR` | SQLite和搜索诊断目录，容器默认 `/var/radar/data` |
| `RADAR_EXPORT_DIR` | 导出目录，容器默认 `/var/radar/exports` |
| `RADAR_LOG_DIR` | 日志目录，容器默认 `/var/radar/logs` |
| `RADAR_EPHEMERAL=true` | 免费实例显示数据会重置的提醒 |
| `PORT` | 托管平台自动设置，监听 `0.0.0.0` |

无需配置AI密钥也可运行。可选AI判断沿用 `OPENAI_API_KEY`，仅在平台环境变量中配置。团队测试版共用评分和备注；同一时刻只执行一个搜索，避免多人重复请求来源网站。更换口令会要求现有会话重新登录。

部署包刻意不包含私人历史样本；云端启动时使用默认行业画像，已有本地数据不受影响。实际来源覆盖需要从部署地区再做实搜验证，不能用本地结果代替云端验收。

## 本地验证

```powershell
python -m pytest -q
python scripts/prepare_cloud_bundle.py
```

资料：[Render Web Services](https://render.com/docs/web-services)、[免费实例限制](https://render.com/docs/free)、[持久化磁盘](https://render.com/docs/disks)。
