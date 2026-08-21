# -*- coding: utf-8 -*-
"""通知模块：发现新增/下线活动时推送提醒

支持两个通道（可同时开启）：
1. 邮件（SMTP/SSL）：适合 QQ/163/Gmail 等，正文为 HTML 格式增量报告
2. 通用 Webhook：POST {"text": 报告} —— 钉钉、飞书、Server酱、ntfy 均可对接

所有敏感信息从环境变量读取（见 config.NOTIFY），不落代码仓库。
"""
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import config


def _md_to_simple_html(md_text):
    """极简 Markdown→HTML：标题、加粗、列表、换行（不引第三方库）"""
    import re
    lines, out = md_text.splitlines(), []
    for ln in lines:
        if ln.startswith("### "):
            out.append(f"<h3>{ln[4:]}</h3>")
        elif ln.startswith("## "):
            out.append(f"<h2>{ln[3:]}</h2>")
        elif ln.startswith("# "):
            out.append(f"<h1>{ln[2:]}</h1>")
        elif ln.startswith("- "):
            out.append(f"<p style='margin:2px 0'>• {ln[2:]}</p>")
        elif ln.strip():
            out.append(f"<p>{ln}</p>")
    html = "\n".join(out)
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    return html


def _send_email(subject, md_body):
    n = config.NOTIFY
    if not (n["smtp_user"] and n["smtp_pass"] and n["mail_to"]):
        print("[通知] 邮件配置不完整（需 SMTP_USER/SMTP_PASS/MAIL_TO），跳过")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = n["mail_from"] or n["smtp_user"]
    msg["To"] = n["mail_to"]
    msg.attach(MIMEText(md_body, "plain", "utf-8"))
    msg.attach(MIMEText(_md_to_simple_html(md_body), "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        if int(n["smtp_port"]) == 465:
            with smtplib.SMTP_SSL(n["smtp_host"], 465, context=ctx, timeout=30) as s:
                s.login(n["smtp_user"], n["smtp_pass"])
                s.sendmail(msg["From"], n["mail_to"].split(","), msg.as_string())
        else:
            with smtplib.SMTP(n["smtp_host"], int(n["smtp_port"]), timeout=30) as s:
                s.starttls(context=ctx)
                s.login(n["smtp_user"], n["smtp_pass"])
                s.sendmail(msg["From"], n["mail_to"].split(","), msg.as_string())
        print(f"[通知] 邮件已发送至 {n['mail_to']}")
        return True
    except Exception as e:
        print(f"[通知] 邮件发送失败: {e}")
        return False


def _send_serverchan(subject, md_body):
    """Server酱（方糖）推送：标题 + Markdown 正文，送达微信"""
    key = config.NOTIFY["serverchan_key"]
    if not key:
        return False
    try:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            json={"title": subject[:100], "desp": md_body},
            timeout=20,
        )
        data = resp.json()
        if data.get("code") == 0:
            print(f"[通知] Server酱已推送至微信: {subject}")
            return True
        print(f"[通知] Server酱返回异常: {data}")
        return False
    except Exception as e:
        print(f"[通知] Server酱推送失败: {e}")
        return False


def _send_webhook(md_body):
    url = config.NOTIFY["webhook_url"]
    if not url:
        return False
    try:
        resp = requests.post(url, json={"text": md_body}, timeout=15)
        print(f"[通知] Webhook 推送完成: {resp.status_code} {resp.text[:200]}")
        return resp.ok
    except Exception as e:
        print(f"[通知] Webhook 推送失败: {e}")
        return False


def notify_run_errors(results):
    """抓取失败告警：避免网络/WAF 故障被误当成"无新增"而漏报"""
    failed = [r for r in results if r["error"]]
    if not failed:
        return
    lines = ["以下银行本次抓取失败，本轮结果不完整，请关注：", ""]
    for r in failed:
        lines.append(f"- **{r['bank'].upper()}**: {r['error'][:200]}")
    lines.append("")
    lines.append("（常见原因：网络波动或站点防火墙临时拦截，下一轮运行会自动重试）")
    _send_serverchan("[港卡活动监控] 抓取失败告警", "\n".join(lines))


def notify_new_activities(report_md, total_new, total_offline=0):
    """对外入口：有新活动/下线活动时调用；无新增则不打扰"""
    if total_new <= 0 and total_offline <= 0:
        print("[通知] 无新增/下线活动，跳过推送")
        return
    subject = f"[港卡活动监控] 新增 {total_new} 个信用卡活动"
    if total_offline:
        subject += f"，下线 {total_offline} 个"
    n = config.NOTIFY
    if n["serverchan_key"]:
        _send_serverchan(subject, report_md)
    if n["email_enabled"]:
        _send_email(subject, report_md)
    if n["webhook_url"]:
        _send_webhook(report_md)
    if not (n["serverchan_key"] or n["email_enabled"] or n["webhook_url"]):
        print("[通知] 未配置通知渠道，仅落地报告文件。"
              "开启方式见 README「新增活动提醒」一节。")
