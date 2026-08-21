# 港银行信用卡活动每日监控

定时抓取多家香港银行信用卡活动，增量入库（SQLite），发现新活动自动点开详情页抓取**条款细则 / 活动要求 / 奖励内容**。

## 目录结构

```
hk_card_promo/
├── main.py            # 主入口：抓取→增量对比→详情入库→报告
├── config.py          # 全局配置：路径、超时、礼貌延时、启用银行
├── db.py              # SQLite 访问层（promotions / run_log 两张表）
├── banks/
│   ├── __init__.py    # 银行适配器注册表（新增银行在此挂载）
│   ├── bea.py         # 东亚银行（BEA）适配器
│   └── icbcasia.py    # 工银亚洲（ICBC Asia）适配器
├── notify.py          # 通知推送：Server酱(方糖)推微信 / 邮件 / Webhook
├── utils.py           # 通用工具：重试会话、PDF 文本提取
├── run_daily.bat      # 每日定时任务入口
├── data/
│   ├── hk_card_promos.db          # SQLite 数据库
│   ├── promotions_snapshot.json   # 全量活动本地快照（增量对比基准之一）
│   ├── report_latest.md           # 最近一次增量报告
│   └── details/<bank>_<slug>.txt  # 每个新活动的详情+条款文本
└── logs/                          # 运行日志
```

## 工作原理

1. **抓列表**：直接请求活动列表页 HTML，解析 7 个分类的隐藏源容器
   `div.update-discover-offer-list-source[data-tag]`，一次拿全部分类，
   无需模拟下拉控件点击（前端只是把卡片搬进可见区）。
2. **增量对比**：以 `归一化详情页URL + Banner图文件名` 为唯一键 `promo_key`。
   - 库里没有 → **新活动**，立即抓详情页；
   - 库里已有 → 刷新 `last_seen_at`；
   - 库里有、本次消失 → 标记 `offline`。
3. **新活动详情**：抓详情页 `<title>`/主视觉、正文文本，
   收集全部 `.pdf` 链接并优先解析文件名含 `tnc/terms/条款` 的 PDF 提取条款全文。
4. **落库与产出**：写入 SQLite，导出 JSON 快照，生成 Markdown 增量报告，
   每个新活动另存一份可读 txt。

## 反爬与稳定性

- 站点为 Incapsula WAF，偶发 SSL EOF / 连接重置：
  `urllib3 Retry`(4 次指数退避) + 外层手动重试 3 次兜底。
- `config.POLITE_DELAY` 控制请求间隔，避免触发限流。
- 编码：列表页按字节交给 lxml 解析，避免 requests 误判 ISO-8859-1 乱码。

## 手动运行

```powershell
python hk_card_promo\main.py
```

## 手动验证效果（演示模式，不污染正式数据）

数据目录可用环境变量 `HKP_DATA_DIR` 覆盖，借此在隔离目录里完整重演一遍：

```powershell
# 第 1 步：空库首跑 —— 34 个活动全部被识别为"新增"，逐个点开抓条款
$env:HKP_DATA_DIR = "hk_card_promo\data_demo"
python hk_card_promo\main.py
# 看 data_demo\report_latest.md（全部活动+条款摘录）和 data_demo\details\*.txt

# 第 2 步：再跑一次 —— 验证增量对比，应输出"新增 0"
python hk_card_promo\main.py

# 验证完清理演示数据
Remove-Item hk_card_promo\data_demo -Recurse
$env:HKP_DATA_DIR = $null
```

日常想看正式库的最新报告，直接打开 `data\report_latest.md` 即可。

## 新增活动如何提醒我

脚本每次运行后：
- **始终落地**：`data\report_latest.md`（最新报告）+ `data\report_<时间戳>.md`（历史归档）。
- **Server酱（方糖）推微信**（当前默认渠道，已启用）：发现新增/下线活动时，
  报告自动推送到微信（无新增不打扰）。SendKey 配在 `config.py` 的
  `NOTIFY["serverchan_key"]`，也可用环境变量 `HKP_SCKEY` 覆盖。

可选附加渠道：

```powershell
# 邮件（QQ 邮箱示例，需先在邮箱设置开启 SMTP 获取授权码）
$env:HKP_NOTIFY_EMAIL = "on"
$env:SMTP_HOST = "smtp.qq.com"; $env:SMTP_PORT = "465"
$env:SMTP_USER = "你的QQ邮箱"; $env:SMTP_PASS = "授权码"
$env:MAIL_TO = "接收提醒的邮箱"

# 通用 Webhook（钉钉/飞书/ntfy 等）
$env:HKP_WEBHOOK_URL = "https://你的webhook地址"
```

> 定时任务场景：把上述环境变量配进任务计划（任务属性→环境变量）或 GitHub Actions 的 Secrets/Vars。

## 存储便携性（Docker / Mac / 云服务器）

- SQLite 是**单文件数据库**（`data/hk_card_promos.db`），无需安装数据库服务，
  整个 `data/` 目录拷到哪都能用，Mac/Linux/Windows 全平台兼容。
- 依赖仅 `requirements.txt` 里 4 个纯 Python 库，`pip install -r requirements.txt` 即装好。
- Docker：仓库根目录已带 `Dockerfile`：

  ```bash
  docker build -t hk-card-promo .
  docker run --rm -v hkp-data:/app/data hk-card-promo
  ```

- 若未来要多实例/远程访问数据，再迁移 PostgreSQL，只需改 `db.py` 连接层，业务代码不动。

## 免费 24 小时云端部署（GitHub Actions）

无需服务器、电脑关机照跑，公开/私有仓库均有免费额度（私有仓库每月 2000 分钟，本项目单次约 3 分钟）。

1. 在 GitHub 建仓库，把本项目（含 `.github/workflows/daily-scan.yml`）推上去；
2. 仓库 Settings → Secrets and variables → Actions，按需配置
   `SMTP_PASS`、`HKP_WEBHOOK_URL`（Secrets）与 `SMTP_HOST/SMTP_USER/MAIL_TO/HKP_NOTIFY_EMAIL` 等（Variables）；
3. 完事。工作流每天 08:30（港时）自动运行：抓数据 → 增量对比 → 推送通知 →
   把更新后的 db/快照 commit 回仓库（数据持久化）→ 报告同时上传为 artifact 可下载。
4. 想随时手动跑一次：仓库 Actions 页面 → daily-card-promo-scan → Run workflow。

> 注意：GitHub Actions 的 cron 调度有几分钟~几十分钟的延迟，属正常现象。


## 配置每日定时（Windows 任务计划程序）

以管理员身份运行 PowerShell：

```powershell
schtasks /Create /TN "HK_Bank_Card_Promo" /SC DAILY /ST 08:00 `
  /TR "C:\Users\Mr.Cao\Documents\Qoder\2026-08-18\chat-1\hk_card_promo\run_daily.bat"
```

- `/ST 08:00` 每天 08:00 运行，可自行改时间。
- 查看：`schtasks /Query /TN "HK_Bank_Card_Promo" /V /FO LIST`
- 删除：`schtasks /Delete /TN "HK_Bank_Card_Promo"`

## 新增一家银行

1. 在 `banks/` 下新建 `<code>.py`，实现两个函数：
   - `fetch_promotions()` → 返回 `[{promo_key, category, title, detail_url, banner_img}]`
   - `fetch_detail(promo)` → 原地填充 `title/detail_text/terms_pdf_urls/terms_text`
2. 在 `banks/__init__.py` 的 `ADAPTERS` 注册。
3. 在 `config.py` 的 `ENABLED_BANKS` 加入银行代码。

## 依赖

```
requests beautifulsoup4 lxml pdfplumber
```
