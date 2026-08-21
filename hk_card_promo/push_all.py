# -*- coding: utf-8 -*-
"""一次性工具：全量活动推送（无视增量），用于查看最终推送效果

用法：
  python push_all.py            # 干跑：只生成全量报告文件，不推送（默认）
  python push_all.py --send     # 真正调用 Server酱 推送到微信（仅一次）
"""
import json
import os
import re
import sys

import config
import db
import notify

REPORT_FULL_PATH = os.path.join(config.DATA_DIR, "report_full_push.md")


def build_full_report(conn):
    """从数据库读取全部在架活动，生成全量 Markdown 报告"""
    rows = conn.execute(
        """SELECT bank, category, title, detail_url, terms_pdf_urls, terms_text
           FROM promotions WHERE status = 'active'
           ORDER BY bank, category, title"""
    ).fetchall()

    bank_names = {"bea": "东亚银行 BEA", "icbcasia": "工银亚洲 ICBC Asia"}
    lines = ["# 港银行信用卡活动 · 全量总览", ""]

    cur_bank, cur_cat = None, None
    bank_counts = {}
    for r in rows:
        bank_counts[r["bank"]] = bank_counts.get(r["bank"], 0) + 1
        if r["bank"] != cur_bank:
            cur_bank, cur_cat = r["bank"], None
            lines.append(f"## {bank_names.get(cur_bank, cur_bank)}")
            lines.append("")
        if r["category"] != cur_cat:
            cur_cat = r["category"]
            lines.append(f"### {cur_cat}")
            lines.append("")
        lines.append(f"- **{r['title']}**")
        lines.append(f"  - 详情页: {r['detail_url']}")
        pdfs = json.loads(r["terms_pdf_urls"] or "[]")
        # 过滤全站通用文件（利率表/隐私政策）：精确匹配文件名特征，
        # 避免误伤文件名恰好含 interest 的真实条款 PDF
        real_pdfs = [
            u for u in pdfs
            if not re.search(r"mkd_interest|interest(%20|\s|_|-)?rates|privacy.?policy",
                             u, re.I)
        ] or pdfs
        if real_pdfs:
            lines.append(f"  - 条款 PDF（{len(pdfs)} 份）: {real_pdfs[0]}")
        if r["terms_text"]:
            snippet = re.sub(r"={5,}\s*条款文件:.*?={5,}", " ", r["terms_text"])
            snippet = snippet.replace("\n", " ").strip()
            lines.append(f"  - 条款摘录: {snippet[:120]} …")
        lines.append("")

    summary = "、".join(f"{bank_names.get(b, b)} {n} 个" for b, n in bank_counts.items())
    lines.insert(2, f"> 在架活动共 {len(rows)} 个（{summary}）")
    lines.insert(3, "")
    return "\n".join(lines), len(rows), bank_counts


def main():
    send = "--send" in sys.argv
    conn = db.connect()
    try:
        report, total, counts = build_full_report(conn)
    finally:
        conn.close()

    with open(REPORT_FULL_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"全量报告已生成：{total} 个活动 -> {REPORT_FULL_PATH}")

    if not send:
        print("[干跑模式] 未调用推送。确认报告无误后用 --send 真实推送。")
        return 0

    summary = "、".join(f"{b.upper()} {n}" for b, n in counts.items())
    subject = f"[港卡活动监控] 全量活动总览：共 {total} 个（{summary}）"
    ok = notify._send_serverchan(subject, report)
    print("推送成功" if ok else "推送失败，请查看上方日志")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
