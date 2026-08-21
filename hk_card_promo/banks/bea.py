# -*- coding: utf-8 -*-
"""东亚银行（BEA）信用卡活动适配器

页面特性（已实地侦查验证）：
- 列表页为纯静态 HTML，无数据接口；7 个分类的全部活动卡片预先写在
  隐藏容器 div.update-discover-offer-list-source[data-tag] 中，
  下拉控件只是前端 JS 把对应 data-tag 容器的卡片搬运到可见区。
- 卡片标题文字烧录在 Banner 图片里，DOM 中为空，
  标题需从详情页 h1.page-title 提取，缺失时用 URL slug 兜底。
- 条款细则为独立 PDF（/pdf/...tnc...pdf），挂在详情页链接上。
"""
import io
import os
import re
import time
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

BANK = "bea"
LIST_URL = "https://www.hkbea.com/html/sc/bea-credit-card-hot-promotions.html"
SITE_ORIGIN = "https://www.hkbea.com"

# 详情页通用标题（无活动辨识度），不作为活动标题
GENERIC_TITLES = {"信用卡", "火热优惠", "东亚银行", ""}
# 站点全局装饰图片路径特征（菜单/社交图标等），其 alt 不可作为标题
CHROME_IMG_MARKS = ("/images-solar/", "/images/common/", "logo", "icon", "banner_bg")

_session = None


def _build_session():
    """带自动重试的会话：站点有 Incapsula WAF，偶发 SSL EOF / 连接重置"""
    s = requests.Session()
    retry = Retry(
        total=4, connect=4, read=4, status=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.headers.update(config.HEADERS)
    return s


def _get(url, **kwargs):
    """GET 请求，urllib3 重试之上再包一层手动重试兜底"""
    global _session
    if _session is None:
        _session = _build_session()
    last_err = None
    for attempt in range(3):
        try:
            resp = _session.get(url, timeout=config.REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            time.sleep(2 + 2 * attempt)
    raise last_err


def _normalize_path(url):
    """归一化 URL：去掉 fragment，统一 tc/sc 语言路径，用于唯一键"""
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path.replace("/html/tc/", "/html/sc/")
    return path


def _title_from_slug(url):
    """从 URL slug 生成兜底标题，如 bea-credit-card-dining-offer-yro"""
    name = os.path.splitext(os.path.basename(urlparse(url).path))[0]
    return name


# ---------------------------------------------------------------- 列表抓取

def fetch_promotions():
    """抓取列表页，返回全部活动（含所有分类）。

    返回 list[dict]: {promo_key, category, title, detail_url, banner_img}
    """
    html = _get(LIST_URL).content
    soup = BeautifulSoup(html, "lxml")  # 按字节解析，lxml 自动识别 UTF-8

    promos, seen_keys = [], set()
    # 移动版隐藏源容器即全量数据；桌面版 swiper-source 内容重复，跳过
    containers = soup.select("div.update-discover-offer-list-source[data-tag]")
    for cont in containers:
        category = cont.get("data-tag", "").strip()
        for card in cont.select("div.image-title-card"):
            a = card.select_one("a[href]")
            img = card.select_one("img")
            if not a:
                continue
            detail_url = urljoin(LIST_URL, a.get("href", ""))
            banner = urljoin(LIST_URL, img.get("src", "")) if img else ""
            promo_key = _normalize_path(detail_url) + "|" + os.path.basename(urlparse(banner).path)
            if promo_key in seen_keys:
                continue
            seen_keys.add(promo_key)
            promos.append({
                "promo_key": promo_key,
                "category": category,
                "title": _title_from_slug(detail_url),  # 兜底标题，详情抓取时刷新
                "detail_url": urldefrag(detail_url)[0],
                "banner_img": banner,
            })
    return promos


# ---------------------------------------------------------------- 详情抓取

def fetch_detail(promo):
    """抓取活动详情页：标题、正文文本、条款 PDF 链接及 PDF 文本。

    直接原地更新传入的 promo dict。失败时仅打印警告，不中断整体流程。
    """
    url = promo["detail_url"]
    try:
        resp = _get(url)
    except Exception as e:
        print(f"    [警告] 详情页请求失败 {url}: {e}")
        return
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.content, "lxml")  # 按字节解析，避免编码误判

    # 标题：h1.page-title 为通用的"信用卡"，无辨识度；
    # 优先取 <title> / section-subtitle h2 中有信息量的文本，否则用 slug 兜底
    promo["title"] = _pick_title(soup, promo.get("category", ""), url)

    # 正文：freeContent 组件内的可见文本（注意：主体内容多为图片，文本有限）
    texts = []
    for block in soup.select('div[data-component-type="freeContent"]'):
        txt = block.get_text("\n", strip=True)
        if txt:
            texts.append(txt)
    promo["detail_text"] = "\n\n".join(texts)[:20000] or None

    # 条款 PDF：页面上全部 .pdf 链接（去重、保序）
    pdf_urls, seen = [], set()
    for a in soup.select('a[href$=".pdf"], a[href$=".PDF"]'):
        href = urljoin(url, a.get("href", ""))
        if href not in seen:
            seen.add(href)
            pdf_urls.append(href)
    promo["terms_pdf_urls"] = pdf_urls

    # 提取条款文本：优先解析文件名含 tnc/条款 的 PDF，其次全部
    tnc_pdfs = [u for u in pdf_urls if re.search(r"tnc|terms|条款", u, re.I)]
    target = (tnc_pdfs or pdf_urls)[:2]  # 最多解析 2 份，控制耗时
    parts = []
    for pdf_url in target:
        txt = _extract_pdf_text(pdf_url)
        if txt:
            parts.append(f"===== 条款文件: {os.path.basename(urlparse(pdf_url).path)} =====\n{txt}")
        time.sleep(config.POLITE_DELAY)
    promo["terms_text"] = "\n\n".join(parts)[:60000] or None

    # 详情文本落盘，方便人工查看
    _save_detail_file(promo)


def _pick_title(soup, category, url):
    """选择有辨识度的活动标题：
    <title>、正文区图片 alt、详情页首图文件名依次尝试；
    跳过分类同名文案与全局导航/页脚图片的 alt，全部无效时用 slug 兜底。
    """
    candidates = []
    if soup.title:
        candidates.append(soup.title.get_text(strip=True))
    # 仅主内容区内、非全局装饰图的长 alt（活动主视觉 Banner）
    scope = soup.select_one("main") or soup
    for img in scope.select("img"):
        src = (img.get("src") or "")
        alt = (img.get("alt") or "").strip()
        if len(alt) >= 6 and not any(m in src.lower() for m in CHROME_IMG_MARKS):
            candidates.append(alt)
    # 活动主视觉文件名（如 BEA_YRO_Dining_2026_...）去掉尺寸后缀也较有辨识度
    for img in scope.select("img"):
        src = img.get("src") or ""
        base = os.path.splitext(os.path.basename(src))[0]
        if base and "/images/" in src and not re.search(r"350x234|banner", base, re.I):
            candidates.append(re.sub(r"_+", " ", base))
            break
    for c in candidates:
        if c and c not in GENERIC_TITLES and c != category:
            return c
    return _title_from_slug(url)


def _extract_pdf_text(pdf_url):
    """下载 PDF 并用 pdfplumber 提取文本，最多 MAX_PDF_PAGES 页"""
    try:
        import pdfplumber
        data = _get(pdf_url).content
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages[: config.MAX_PDF_PAGES]
            text = "\n".join((p.extract_text() or "") for p in pages)
        if text.strip():
            return text.strip()
        # 纯扫描/图片型 PDF 时回退用 PyMuPDF 再试一次
        try:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            text = "\n".join(p.get_text() for p in doc[: config.MAX_PDF_PAGES])
            return text.strip() or None
        except Exception:
            return None
    except Exception as e:
        print(f"    [警告] PDF 解析失败 {pdf_url}: {e}")
        return None


def _save_detail_file(promo):
    slug = _title_from_slug(promo["detail_url"])
    path = os.path.join(config.DETAIL_DIR, f"{BANK}_{slug}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"活动标题: {promo.get('title')}\n")
        f.write(f"分类: {promo.get('category')}\n")
        f.write(f"详情页: {promo.get('detail_url')}\n")
        f.write(f"Banner: {promo.get('banner_img')}\n")
        f.write("\n----- 详情页正文 -----\n")
        f.write(promo.get("detail_text") or "（无文本内容，主体为图片）")
        f.write("\n\n----- 条款 PDF 链接 -----\n")
        for u in promo.get("terms_pdf_urls", []):
            f.write(u + "\n")
        f.write("\n----- 条款文本 -----\n")
        f.write(promo.get("terms_text") or "（未提取到条款文本）")
