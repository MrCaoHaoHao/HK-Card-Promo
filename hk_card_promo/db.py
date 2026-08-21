# -*- coding: utf-8 -*-
"""SQLite 数据库访问层：活动表 + 运行日志表"""
import json
import sqlite3
from datetime import datetime

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS promotions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bank          TEXT NOT NULL,               -- 银行代码，如 bea
    promo_key     TEXT NOT NULL,               -- 归一化唯一键（详情页URL+Banner图）
    category      TEXT,                        -- 分类（迎新优惠/餐饮优惠/...）
    title         TEXT,                        -- 活动标题（来自详情页 h1，缺失时用 slug）
    detail_url    TEXT,                        -- 活动详情页 URL
    banner_img    TEXT,                        -- Banner 图片 URL
    first_seen_at TEXT NOT NULL,               -- 首次发现时间
    last_seen_at  TEXT NOT NULL,               -- 最近一次在列表中出现的时间
    status        TEXT NOT NULL DEFAULT 'active',  -- active / offline
    offline_at    TEXT,                        -- 下线时间
    detail_text   TEXT,                        -- 详情页正文文本
    terms_pdf_urls TEXT,                       -- 条款 PDF 链接列表（JSON 数组）
    terms_text    TEXT,                        -- 条款 PDF 提取文本
    UNIQUE(bank, promo_key)
);
CREATE INDEX IF NOT EXISTS idx_promo_status ON promotions(bank, status);

CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bank       TEXT NOT NULL,
    run_at     TEXT NOT NULL,
    total_seen INTEGER,
    new_count  INTEGER,
    offline_count INTEGER,
    message    TEXT
);
"""


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_known(conn, bank):
    """读取某银行全部已知活动，返回 {promo_key: row_dict}"""
    rows = conn.execute(
        "SELECT * FROM promotions WHERE bank = ?", (bank,)
    ).fetchall()
    return {r["promo_key"]: dict(r) for r in rows}


def insert_promotion(conn, bank, promo):
    conn.execute(
        """INSERT INTO promotions
           (bank, promo_key, category, title, detail_url, banner_img,
            first_seen_at, last_seen_at, status,
            detail_text, terms_pdf_urls, terms_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
        (
            bank, promo["promo_key"], promo["category"], promo["title"],
            promo["detail_url"], promo["banner_img"],
            now(), now(),
            promo.get("detail_text"),
            json.dumps(promo.get("terms_pdf_urls", []), ensure_ascii=False),
            promo.get("terms_text"),
        ),
    )


def update_detail(conn, bank, promo_key, promo):
    """补抓详情成功后，回填标题/正文/条款字段"""
    conn.execute(
        """UPDATE promotions
           SET title = ?, detail_text = ?, terms_pdf_urls = ?, terms_text = ?
           WHERE bank = ? AND promo_key = ?""",
        (
            promo.get("title"), promo.get("detail_text"),
            json.dumps(promo.get("terms_pdf_urls", []), ensure_ascii=False),
            promo.get("terms_text"),
            bank, promo_key,
        ),
    )


def find_incomplete(conn, bank):
    """找出详情抓取失败（无正文且无 PDF 列表）的在架活动"""
    rows = conn.execute(
        """SELECT promo_key, category, title, detail_url, banner_img
           FROM promotions
           WHERE bank = ? AND status = 'active'
             AND detail_text IS NULL
             AND (terms_pdf_urls IS NULL OR terms_pdf_urls = '[]')""",
        (bank,),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_promotion(conn, bank, promo_key):
    """已存在活动再次出现：刷新 last_seen_at，恢复 active"""
    conn.execute(
        """UPDATE promotions
           SET last_seen_at = ?, status = 'active', offline_at = NULL
           WHERE bank = ? AND promo_key = ?""",
        (now(), bank, promo_key),
    )


def mark_offline(conn, bank, promo_key):
    conn.execute(
        """UPDATE promotions SET status = 'offline', offline_at = ?
           WHERE bank = ? AND promo_key = ?""",
        (now(), bank, promo_key),
    )


def log_run(conn, bank, total_seen, new_count, offline_count, message=""):
    conn.execute(
        """INSERT INTO run_log (bank, run_at, total_seen, new_count, offline_count, message)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (bank, now(), total_seen, new_count, offline_count, message),
    )


def export_snapshot(conn):
    """导出全部活动到本地 JSON 快照文件，便于人工查看与对比"""
    rows = conn.execute(
        """SELECT bank, promo_key, category, title, detail_url, banner_img,
                  first_seen_at, last_seen_at, status, terms_pdf_urls
           FROM promotions ORDER BY bank, status, category, promo_key"""
    ).fetchall()
    data = []
    for r in rows:
        d = dict(r)
        d["terms_pdf_urls"] = json.loads(d["terms_pdf_urls"] or "[]")
        data.append(d)
    with open(config.SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(data)
