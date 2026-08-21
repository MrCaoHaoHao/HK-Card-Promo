# -*- coding: utf-8 -*-
"""主入口：每日定时运行 —— 抓取各银行信用卡活动，增量对比，详情入库

流程：
1. 逐银行抓取活动列表
2. 与数据库已有记录对比：新 promo_key = 增量新活动；已知活动刷新 last_seen；
   本次未出现的在架活动标记为 offline
3. 对每个新活动抓取详情页：标题、正文、条款 PDF 及其文本
4. 写入 SQLite，导出 JSON 快照，生成 Markdown 增量报告
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime

import config
import db
import notify
from banks import ADAPTERS


def _write_report(results, run_at):
    """生成本次运行的 Markdown 增量报告"""
    lines = [f"# 银行信用卡活动增量报告", f"", f"运行时间：{run_at}", ""]
    any_new = False
    for r in results:
        lines.append(f"## {r['bank'].upper()}（本次见到 {r['total']} 个，"
                     f"新增 {len(r['new'])}，下线 {len(r['offline'])}）")
        if r["error"]:
            lines.append(f"- 抓取失败：{r['error']}")
        if r["new"]:
            any_new = True
            lines.append("")
            lines.append("### 新增活动")
            for p in r["new"]:
                lines.append(f"- **{p['title']}**（分类：{p['category']}）")
                lines.append(f"  - 详情页: {p['detail_url']}")
                if p.get("terms_pdf_urls"):
                    lines.append(f"  - 条款 PDF: {'; '.join(p['terms_pdf_urls'][:3])}")
                if p.get("terms_text"):
                    snippet = p["terms_text"][:200].replace("\n", " ")
                    lines.append(f"  - 条款摘录: {snippet} ...")
        if r["offline"]:
            lines.append("")
            lines.append("### 本次未出现（已标记下线）")
            for key in r["offline"]:
                lines.append(f"- {key}")
        lines.append("")
    if not any_new:
        lines.append("> 本次运行未发现新增活动。")
    content = "\n".join(lines)
    with open(config.REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    # 归档一份带时间戳的报告，便于回溯（云端部署时作为产物下载）
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = os.path.join(config.DATA_DIR, f"report_{stamp}.md")
    with open(archive, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def run_bank(conn, bank):
    adapter = ADAPTERS[bank]
    result = {"bank": bank, "total": 0, "new": [], "offline": [], "error": None}

    print(f"[{bank}] 抓取活动列表 ...")
    try:
        promos = adapter.fetch_promotions()
    except Exception as e:
        result["error"] = f"{e}"
        traceback.print_exc()
        db.log_run(conn, bank, 0, 0, 0, f"ERROR: {e}")
        return result

    result["total"] = len(promos)
    print(f"[{bank}] 本次见到 {len(promos)} 个活动卡片")

    known = db.load_known(conn, bank)
    fetched_keys = {p["promo_key"] for p in promos}

    # 新活动 → 抓详情
    new_promos = [p for p in promos if p["promo_key"] not in known]
    detail_cache = {}
    for i, p in enumerate(new_promos, 1):
        print(f"[{bank}] 新活动 {i}/{len(new_promos)}: {p['detail_url']}")
        if p["detail_url"] not in detail_cache:
            adapter.fetch_detail(p)
            detail_cache[p["detail_url"]] = True
        else:
            # 同一详情页多卡片：复用已抓取的详情字段
            for done in result["new"]:
                if done["detail_url"] == p["detail_url"]:
                    for k in ("title", "detail_text", "terms_pdf_urls", "terms_text"):
                        p[k] = done.get(k)
                    break
        db.insert_promotion(conn, bank, p)
        result["new"].append(p)
        time.sleep(config.POLITE_DELAY)

    # 已知活动刷新出现时间
    for key in fetched_keys & known.keys():
        db.touch_promotion(conn, bank, key)

    # 补抓历史遗留的详情失败记录（无正文且无条款链接）
    for row in db.find_incomplete(conn, bank):
        print(f"[{bank}] 补抓详情: {row['detail_url']}")
        adapter.fetch_detail(row)
        db.update_detail(conn, bank, row["promo_key"], row)
        time.sleep(config.POLITE_DELAY)

    # 之前在架、本次消失 → 标记下线
    for key, row in known.items():
        if key not in fetched_keys and row["status"] == "active":
            db.mark_offline(conn, bank, key)
            result["offline"].append(key)
            print(f"[{bank}] 下线: {key}")

    db.log_run(conn, bank, result["total"], len(result["new"]), len(result["offline"]))
    return result


def main():
    # 开关：--reset 清空数据库全量重抓；--no-notify 本次运行不推送
    reset = "--reset" in sys.argv
    no_notify = "--no-notify" in sys.argv

    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"===== 运行开始 {run_at} =====")
    conn = db.connect()
    if reset:
        conn.execute("DELETE FROM promotions")
        conn.execute("DELETE FROM run_log")
        conn.commit()
        print("[reset] 已清空数据库，本次全部活动将视为新增并重新抓取详情")
    results = []
    try:
        for bank in config.ENABLED_BANKS:
            results.append(run_bank(conn, bank))
            conn.commit()
        n = db.export_snapshot(conn)
        report = _write_report(results, run_at)
        total_new = sum(len(r["new"]) for r in results)
        total_offline = sum(len(r["offline"]) for r in results)
        # 运行摘要：云端工作流据此决定是否需要把数据提交回仓库
        with open(os.path.join(config.DATA_DIR, "_run_summary.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"new": total_new, "offline": total_offline,
                       "errors": sum(1 for r in results if r["error"])}, f)
        if no_notify:
            print("[no-notify] 跳过推送（可用 push_all.py --send 手动全量推送）")
        else:
            notify.notify_new_activities(report, total_new, total_offline)
            notify.notify_run_errors(results)
        print(f"===== 运行结束：快照共 {n} 条，新增 {total_new} 条，"
              f"报告 -> {config.REPORT_PATH} =====")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
