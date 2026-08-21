# -*- coding: utf-8 -*-
"""全局配置：路径、请求参数、银行列表"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_local_secrets():
    """读取本地密钥文件 .local_secrets（每行 KEY=VALUE，已 gitignore），
    不覆盖已有环境变量；云端部署改用仓库 Secrets 注入同名变量"""
    path = os.path.join(BASE_DIR, ".local_secrets")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_local_secrets()

# 可用环境变量 HKP_DATA_DIR 覆盖数据目录（演示模式 / Docker 卷挂载用）
DATA_DIR = os.environ.get("HKP_DATA_DIR") or os.path.join(BASE_DIR, "data")
DETAIL_DIR = os.path.join(DATA_DIR, "details")      # 详情页/PDF 提取文本存放处
LOG_DIR = os.path.join(BASE_DIR, "logs")

DB_PATH = os.path.join(DATA_DIR, "hk_card_promos.db")      # SQLite 数据库
SNAPSHOT_PATH = os.path.join(DATA_DIR, "promotions_snapshot.json")  # 本地快照文件
REPORT_PATH = os.path.join(DATA_DIR, "report_latest.md")   # 最近一次增量报告

for _d in (DATA_DIR, DETAIL_DIR, LOG_DIR):
    os.makedirs(_d, exist_ok=True)

# 请求参数
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,zh-HK;q=0.8,en;q=0.7",
}
REQUEST_TIMEOUT = 30        # 单请求超时（秒）
POLITE_DELAY = 0.8          # 相邻请求间隔（秒），礼貌爬取
MAX_PDF_PAGES = 30          # 条款 PDF 最多解析页数，防止超长文件

# 启用的银行适配器（后续新增银行在此注册）
ENABLED_BANKS = ["bea", "icbcasia"]

# ---------------------------------------------------------------- 通知配置
# 发现新增/下线活动时推送。敏感信息优先读环境变量，其次用此处默认值。
NOTIFY = {
    # Server酱（方糖）推送到微信：https://sct.ftqq.com 获取 SendKey
    # 本地放 .local_secrets（HKP_SCKEY=SCT...），云端放仓库 Secrets，勿写进代码
    "serverchan_key": os.environ.get("HKP_SCKEY", ""),
    # 邮件通知（SMTP）。QQ/163 需开启 SMTP 并获取"授权码"作为密码；
    # Gmail 需开启两步验证后使用"应用专用密码"。
    "email_enabled": os.environ.get("HKP_NOTIFY_EMAIL", "off") == "on",
    "smtp_host": os.environ.get("SMTP_HOST", "smtp.qq.com"),
    "smtp_port": int(os.environ.get("SMTP_PORT", "465")),   # 465=SSL, 587=STARTTLS
    "smtp_user": os.environ.get("SMTP_USER", ""),
    "smtp_pass": os.environ.get("SMTP_PASS", ""),          # 授权码/应用密码，勿硬编码
    "mail_from": os.environ.get("MAIL_FROM", ""),
    "mail_to": os.environ.get("MAIL_TO", ""),              # 多个收件人用逗号分隔
    # 通用 Webhook（钉钉/飞书/Server酱/ntfy 等）：POST {"text": 报告}
    "webhook_url": os.environ.get("HKP_WEBHOOK_URL", ""),
}
