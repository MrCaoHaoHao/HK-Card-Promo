# -*- coding: utf-8 -*-
"""工银亚洲（ICBC Asia）信用卡活动适配器

页面特性（已实地侦查验证）：
- 列表页为纯静态 HTML：section.col-link-list 内 a.col-link-list__link，
  每条仅标题文字+详情链接，无图片、无分类、无分页。
- 详情页 /hk/{lang}/promotion/{slug}.html：
  * 标题：h2.inner-main-sl__title
  * 达标要求/奖励内容：div.container.rte 正文纯文本（推广期也写在正文里）
  * 条款：两种形态——① section.remark-txt 内的独立 PDF 链接；
    ② 无 PDF 时直接以编号正文写在 rte 内（"條款及細則：1 …"），随正文一并入库
  * 参与条件备注：section.remark-txt 注脚
- 无反爬、无登录墙，可直接 requests 抓取。
"""
import os
import re
import time
from urllib.parse import urljoin, urlparse, urldefrag

from bs4 import BeautifulSoup

import config
import utils

BANK = "icbcasia"
LIST_URL = ("https://www.icbcasia.com/hk/sc/personal/credit-cards/"
            "latest-promotions/default.html")
CATEGORY = "最新优惠"

_session = None


def _sess():
    global _session
    if _session is None:
        _session = utils.build_session()
    return _session


def _normalize_path(url):
    """归一化 URL：去 fragment，统一 tc/sc/en 语言路径，用于唯一键"""
    url, _ = urldefrag(url)
    path = urlparse(url).path
    for lang in ("/hk/tc/", "/hk/sc/", "/hk/en/"):
        path = path.replace(lang, "/hk/")
    return path


# ---------------------------------------------------------------- 列表抓取

def fetch_promotions():
    """抓取列表页全部活动。该列表无 Banner 图，promo_key 即归一化路径。"""
    soup = BeautifulSoup(utils.get(_sess(), LIST_URL).content, "lxml")

    promos, seen = [], set()
    for a in soup.select("section.col-link-list a.col-link-list__link"):
        href = a.get("href", "").strip()
        if not href:
            continue
        detail_url = urldefrag(urljoin(LIST_URL, href))[0]
        key = _normalize_path(detail_url)
        if key in seen:
            continue
        seen.add(key)
        item = a.select_one("p.col-link-list__item")
        title = item.get_text(strip=True) if item else ""
        promos.append({
            "promo_key": key,
            "category": CATEGORY,
            "title": title or utils.slug_of(detail_url),
            "detail_url": detail_url,
            "banner_img": "",
        })
    return promos


# ---------------------------------------------------------------- 详情抓取

# 推广期行：冒号后必须紧跟日期数字，避免误匹配"于推广期内..."这类句子
_PERIOD_RE = re.compile(r"推广期[：:︰]\s*(\d[^\n]{0,59})")


def fetch_detail(promo):
    """抓取详情页：标题、正文（含达标要求/奖励内容/内联条款）、推广期、
    条款 PDF 链接及文本。原地更新传入的 promo dict，失败仅告警不中断。
    """
    url = promo["detail_url"]
    try:
        resp = utils.get(_sess(), url)
    except Exception as e:
        print(f"    [警告] 详情页请求失败 {url}: {e}")
        return
    soup = BeautifulSoup(resp.content, "lxml")

    # 标题：优先详情页主标题，其次保留列表页标题
    h2 = soup.select_one("h2.inner-main-sl__title")
    if h2 and h2.get_text(strip=True):
        promo["title"] = h2.get_text(strip=True)

    # 正文：达标要求、奖励内容（以及部分活动的内联条款）
    parts = []
    for block in soup.select("div.container.rte"):
        txt = block.get_text("\n", strip=True)
        if txt:
            parts.append(txt)
    # 备注/参与条件注脚
    for block in soup.select("section.remark-txt"):
        txt = block.get_text("\n", strip=True)
        if txt:
            parts.append(txt)
    body = "\n\n".join(parts)[:30000]
    promo["detail_text"] = body or None

    # 推广期：从正文提取，拼进标题便于快速辨识
    m = _PERIOD_RE.search(body)
    if m:
        period = m.group(1).strip()[:60]
        if period and period not in promo["title"]:
            promo["title"] = f"{promo['title']}（{period}）"

    # 条款 PDF：remark-txt 区优先，其次全页
    pdf_urls, seen = [], set()
    scope = soup.select("section.remark-txt a[href$='.pdf']") or \
        soup.select("a[href$='.pdf'], a[href$='.PDF']")
    for a in scope:
        href = urljoin(url, a.get("href", ""))
        if href not in seen:
            seen.add(href)
            pdf_urls.append(href)
    promo["terms_pdf_urls"] = pdf_urls

    # 条款文本：优先文件名含 tnc 的 PDF；无 PDF 的活动条款已内联在正文中
    tnc = [u for u in pdf_urls if re.search(r"tnc|terms", u, re.I)] or pdf_urls
    text_parts = []
    for pdf_url in tnc[:2]:  # 最多解析 2 份，控制耗时
        txt = utils.extract_pdf_text(_sess(), pdf_url)
        if txt:
            text_parts.append(
                f"===== 条款文件: {os.path.basename(urlparse(pdf_url).path)} =====\n{txt}"
            )
        time.sleep(config.POLITE_DELAY)
    promo["terms_text"] = "\n\n".join(text_parts)[:60000] or None

    _save_detail_file(promo)


def _save_detail_file(promo):
    path = os.path.join(config.DETAIL_DIR, f"{BANK}_{utils.slug_of(promo['detail_url'])}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"活动标题: {promo.get('title')}\n")
        f.write(f"分类: {promo.get('category')}\n")
        f.write(f"详情页: {promo.get('detail_url')}\n")
        f.write("\n----- 详情页正文（达标要求/奖励内容） -----\n")
        f.write(promo.get("detail_text") or "（无文本内容）")
        f.write("\n\n----- 条款 PDF 链接 -----\n")
        for u in promo.get("terms_pdf_urls", []):
            f.write(u + "\n")
        f.write("\n----- 条款文本 -----\n")
        f.write(promo.get("terms_text") or "（无独立条款 PDF，条款已内联在上方正文中）")
