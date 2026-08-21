# -*- coding: utf-8 -*-
"""通用工具：带重试的 HTTP 会话、PDF 文本提取（供各银行适配器复用）"""
import io
import os
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


def build_session():
    """带自动重试的会话（4 次指数退避），应对偶发断连/限流"""
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


def get(session, url, tries=3, **kwargs):
    """GET 请求，urllib3 重试之上再包一层手动重试兜底"""
    last_err = None
    for attempt in range(tries):
        try:
            resp = session.get(url, timeout=config.REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            time.sleep(2 + 2 * attempt)
    raise last_err


def extract_pdf_text(session, pdf_url):
    """下载 PDF 并用 pdfplumber 提取文本，最多 MAX_PDF_PAGES 页"""
    try:
        import pdfplumber
        data = get(session, pdf_url).content
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages[: config.MAX_PDF_PAGES]
            text = "\n".join((p.extract_text() or "") for p in pages)
        return text.strip() or None
    except Exception as e:
        print(f"    [警告] PDF 解析失败 {pdf_url}: {e}")
        return None


def slug_of(url):
    """URL 末段去扩展名，用作兜底标题/文件名"""
    return os.path.splitext(os.path.basename(urlparse(url).path))[0]
