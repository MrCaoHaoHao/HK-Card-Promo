# 💳 港卡活动雷达 · HK Card Promo Monitor

> 🤖 全自动监控香港银行信用卡优惠活动 —— 云端智能频率巡检（月初高发期 10 分钟一轮），新活动上线**分钟级感知**，条款细则自动提取，微信即时推送。

[![monitor](https://github.com/MrCaoHaoHao/HK-Card-Promo/actions/workflows/daily-scan.yml/badge.svg)](https://github.com/MrCaoHaoHao/HK-Card-Promo/actions/workflows/daily-scan.yml)
![Python](https://img.shields.io/badge/Python-3.12+-3776ab?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-单文件数据库-003b57?logo=sqlite&logoColor=white)
![Schedule](https://img.shields.io/badge/巡检频率-10_/_30_分钟智能调度-success)

---

## ✨ 项目亮点

| | 能力 | 说明 |
|---|---|---|
| 🕵️ | **增量监控** | 每次抓取与 SQLite 基线对比，精准识别「新增 / 下线 / 持续在架」三种状态 |
| 📄 | **条款深挖** | 新活动自动点开详情页，下载并解析条款 PDF 全文（pdfplumber），达标要求 / 奖励内容一目了然 |
| 📲 | **微信推送** | 检测到新活动立即通过 [Server酱（方糖）](https://sct.ftqq.com) 推送到微信，附带条款摘录与 PDF 链接 |
| ☁️ | **云端 24h 运行** | GitHub Actions 定时调度，电脑关机照跑；数据自动提交回仓库持久化 |
| 🔌 | **银行适配器架构** | 新增一家银行 = 新增一个适配器文件，实现两个函数即可接入 |
| 🛡️ | **抗封锁设计** | 会话复用 + 指数退避重试，从容应对 WAF 偶发拦截；抓取失败自动推送告警，绝不误报"无新增" |

## 🏦 已接入银行

| 银行 | 活动页 | 在架活动 | 抓取方式 |
|---|---|---|---|
| 🇭🇰 东亚银行 BEA | [热门优惠](https://www.hkbea.com/html/sc/bea-credit-card-hot-promotions.html) | 35 个 · 7 大分类 | 静态 HTML 隐藏容器解析 |
| 🇭🇰 工银亚洲 ICBC Asia | [最新优惠](https://www.icbcasia.com/hk/tc/personal/credit-cards/latest-promotions/default.html) | 6 个 | 列表链接 + 推广期正则提取 |

> 📊 活动数据基线随仓库 `hk_card_promo/data/` 目录持久化，clone 即拥有完整历史。

## ⚙️ 工作原理

```
GitHub Actions 智能调度（北京时间）
  · 每月 1-5 号：8:00-20:00 每 10 分钟 + 凌晨 0:00-2:00 每 10 分钟
  · 每月 6-月底：8:00-20:00 每 30 分钟
        │
        ▼
┌──────────────────┐    ┌──────────────────┐
│ 抓取各行活动列表   │ ─▶ │ 与 SQLite 基线对比 │
└──────────────────┘    └────────┬─────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        🆕 新活动           ♻️ 已知活动          👻 消失活动
     抓详情页+条款PDF      刷新 last_seen       标记 offline
     全文提取入库
              │
              ▼
     📲 Server酱 → 微信推送（含条款摘录）
```

## 🚀 快速开始

### 云端部署（推荐，零运维）

1. Fork 或克隆本仓库
2. 在仓库 **Settings → Secrets and variables → Actions** 添加：
   - `HKP_SCKEY`：你的 Server酱 SendKey（[点此申请](https://sct.ftqq.com)）
3. 完成！工作流 `hk-card-promo-monitor` 按智能频率自动巡检（月初 10 分钟 / 平日 30 分钟）
   - 也可在 **Actions** 页面点击 `Run workflow` 手动触发

### 本地运行

```bash
pip install -r hk_card_promo/requirements.txt

# 写入本地密钥（文件已 gitignore）
echo "HKP_SCKEY=你的SendKey" > hk_card_promo/.local_secrets

# 跑一轮（增量逻辑：无新增不推送）
python hk_card_promo/main.py

# 清空数据库全量重抓
python hk_card_promo/main.py --reset --no-notify

# 全量活动目录推送到微信
python hk_card_promo/push_all.py --send
```

## 📁 项目结构

```
├── .github/workflows/daily-scan.yml   # 云端调度（每 30 分钟 + 按需回写数据）
└── hk_card_promo/
    ├── main.py        # 主流程：抓取 → 增量对比 → 详情入库 → 报告 → 推送
    ├── config.py      # 全局配置（支持环境变量 / .local_secrets 覆盖）
    ├── db.py          # SQLite 存储层（promotions + run_log）
    ├── notify.py      # 通知层（Server酱 / 邮件 / Webhook）
    ├── utils.py       # 重试会话、PDF 文本提取等公共工具
    ├── push_all.py    # 一次性工具：全量活动推送（默认干跑，--send 真推）
    └── banks/         # 🏦 银行适配器（新增银行在此扩展）
        ├── bea.py         # 东亚银行
        └── icbcasia.py    # 工银亚洲
```

## 🔌 如何接入新银行

在 `banks/` 下新建适配器，实现两个函数并注册：

```python
def fetch_promotions():
    """返回列表页所有活动卡片：promo_key / title / category / detail_url"""

def fetch_detail(promo):
    """就地填充详情字段：detail_text / terms_pdf_urls / terms_text"""
```

然后在 `banks/__init__.py` 的 `ADAPTERS` 与 `config.ENABLED_BANKS` 中登记即可。

## 📬 通知策略

- 🆕 有新活动 / 活动下线 → 推送增量报告（标题、详情页、条款 PDF、条款摘录）
- 🚨 抓取失败 → 推送告警（避免网络故障被误当成"无新增"）
- 😴 无变化 → 静默跳过，绝不打扰

## ⚠️ 免责声明

本项目仅供个人学习与技术研究，数据版权归各银行所有；请控制抓取频率、遵守目标网站的 robots 协议与服务条款，勿用于商业用途。

---

⭐ 如果这个项目对你有帮助，欢迎点星收藏；也欢迎 PR 接入更多银行！
