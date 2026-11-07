# 招标雷达团队版：给同事一个网址

两条路线。先用 A 免费拿到网址试用；如果国内同事打开慢或打不开，或者需要长期保存评分，改用 B。

| | A. Streamlit Community Cloud | B. 自己的香港/国内服务器 |
|---|---|---|
| 费用 | 免费 | 轻量服务器月租（以云厂商报价为准） |
| 网址 | `https://<自选名>.streamlit.app` | 你的域名（自动 HTTPS），或 `http://服务器IP:8501` |
| 国内同事访问 | 海外服务器，速度和稳定性需实测 | 香港/国内节点更稳 |
| 采集招采网站 | 大概率受限，配合本机采集同步 | 国内服务器可直接采集；香港需实测 |
| 评分/备注保存 | 重启会丢 | Docker 数据卷长期保存 |

## A. Streamlit Community Cloud（约 5 分钟）

1. 打开 https://share.streamlit.io ，用 GitHub 账号 `allenlishupeng-rgb` 登录，点 **Create app → Deploy a public app from GitHub**。
2. Repository：`allenlishupeng-rgb/tender-radar`；Branch：`main`（新功能合并前可直接选 `claude/focused-lovelace-j8jlef`）；Main file path：`streamlit_app.py`；App URL：填一个好记的名字。
3. Advanced settings：Python 选 3.12；Secrets 填：

```toml
RADAR_TEAM_PASSWORD = "一段长随机口令"
# 云端连不上招采网站时，再加上本机采集同步四项（见 README.md）：
# RADAR_COLLECTION_MODE = "local"
# RADAR_SYNC_URL = "https://api.github.com/repos/<账号>/tender-radar-data/contents/collection_bundle.json"
# RADAR_SYNC_TOKEN = "<只读 token>"
# RADAR_SYNC_KEY = "<签名密钥>"
```

4. Deploy。完成后把网址和口令分别发给同事（口令不要和网址放在同一条消息里）。
5. 验收：同事用手机流量和公司网络各打开一次；在页面里点一次搜索，看“搜索覆盖与过滤原因”里有多少来源访问失败。大部分失败就打开 local 模式，由你的电脑采集。

## B. 自己的服务器（Docker）

适合团队长期使用。香港节点不需要备案；国内节点要用域名，必须先完成 ICP 备案。

```bash
# 服务器上（已安装 Docker）
git clone https://github.com/allenlishupeng-rgb/tender-radar.git && cd tender-radar/deploy
cp radar.env.example radar.env && nano radar.env        # 设置口令；有域名就填 RADAR_DOMAIN
docker compose --env-file radar.env --profile https up -d --build     # 有域名：https://你的域名
# 或
docker compose --env-file radar.env --profile ip-only up -d --build   # 无域名：http://服务器IP:8501
```

- 有域名时，先把域名的 A 记录指向服务器，并在安全组放行 80/443；证书由 Caddy 自动申请和续期。
- 无域名的 `http://IP:8501` 能在所有浏览器打开，但会显示“不安全”，口令以明文传输，只适合短期试用。
- 部署后在服务器上运行 `docker compose exec radar python scripts/check_source_health.py`，确认这台服务器能访问哪些招采来源。国内服务器通常可以直接采集，不需要本机同步。
- 数据在 Docker 数据卷 `radar-data`，更新代码不会清空。备份：
  `docker compose cp radar:/var/radar/data/tender_radar.db ./backup-$(date +%F).db`
- 更新版本：`git pull && docker compose --env-file radar.env --profile https up -d --build`

---

## 附：Render 部署（原方案）

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
| `RADAR_COLLECTION_MODE=local` | 云端不直接抓取，只导入本机采集包（海外主机访问不了国内站点时使用） |
| `RADAR_SYNC_URL` / `RADAR_SYNC_TOKEN` | 私有数据仓库中采集包的地址与只读 token，见 `README.md` |
| `RADAR_SYNC_KEY` | 采集包签名密钥，本机与云端必须一致 |
| `RADAR_TIMEZONE` | 业务时区，默认 `CST-8`（北京时间） |

无需配置AI密钥也可运行。可选AI判断沿用 `OPENAI_API_KEY`，仅在平台环境变量中配置。团队测试版共用评分和备注；同一时刻只执行一个搜索，避免多人重复请求来源网站。更换口令会要求现有会话重新登录。

部署包刻意不包含私人历史样本；云端启动时使用默认行业画像，已有本地数据不受影响。实际来源覆盖需要从部署地区再做实搜验证，不能用本地结果代替云端验收。

## 本地验证

```powershell
python -m pytest -q
python scripts/prepare_cloud_bundle.py
```

资料：[Render Web Services](https://render.com/docs/web-services)、[免费实例限制](https://render.com/docs/free)、[持久化磁盘](https://render.com/docs/disks)。
