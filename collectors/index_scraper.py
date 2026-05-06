"""HTML インデックスページからファイルリンク（PDF/Excel）を抽出。"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from collectors.http_client import fetch


def _decode_html(data: bytes) -> str:
    """文字エンコーディングを自動判別してデコード。"""
    # meta charset 検査
    head = data[:2048].decode("ascii", errors="ignore").lower()
    m = re.search(r'charset=["\']?([\w\-]+)', head)
    enc = m.group(1) if m else None
    candidates = []
    if enc:
        candidates.append(enc.replace("shift_jis", "cp932"))
    candidates.extend(["utf-8", "cp932", "shift_jis", "euc-jp"])
    for c in candidates:
        try:
            return data.decode(c, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def fetch_html(url: str, *, is_warp: bool = False) -> str | None:
    data = fetch(url, is_warp=is_warp)
    if data is None:
        return None
    return _decode_html(data)


def _collect_links_from_html(
    html: str,
    base_url: str,
    extensions: tuple[str, ...],
    include_pattern: re.Pattern | None,
    seen: set[str],
) -> list[tuple[str, str]]:
    """html 文字列から拡張子一致リンクを収集し (absurl, text) リストで返す。"""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        href_lo = href.lower().split("?", 1)[0]
        if not any(href_lo.endswith(ext) for ext in extensions):
            continue
        if include_pattern and not include_pattern.search(href):
            continue
        absurl = urljoin(base_url, href)
        # urljoin collapses https:// → https:/ in WARP embedded URLs; restore it
        absurl = re.sub(r"/https:/([^/])", r"/https://\1", absurl)
        if absurl in seen:
            continue
        seen.add(absurl)
        text = a.get_text(strip=True)[:120]
        out.append((absurl, text))
    return out


def scrape_file_links(
    index_url: str,
    *,
    extensions: tuple[str, ...] = (".pdf", ".xlsx", ".xls"),
    include_pattern: str | None = None,
    is_warp: bool = False,
) -> list[tuple[str, str]]:
    """index_url から該当拡張子のリンクを (絶対URL, リンクテキスト) で返す。

    include_pattern: 指定すると href がこの正規表現にマッチするもののみ採用。
    Excel Workbook Frameset ページは *.files/sheet001.html をフォローして PDF リンクを収集
    （base URL はシートページ自身を使うことで相対パスを正しく解決）。
    """
    html = fetch_html(index_url, is_warp=is_warp)
    if html is None:
        logger.warning(f"index取得失敗: {index_url}")
        return []

    pat = re.compile(include_pattern) if include_pattern else None
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    # メインページのリンクを収集（base = index_url）
    out.extend(_collect_links_from_html(html, index_url, extensions, pat, seen))

    # Excel Workbook Frameset → sheet001.html を base を変えてフォロー
    if "Excel Workbook Frameset" in html or "Excel.Sheet" in html:
        m = re.search(r'href=["\']([^"\']*sheet001\.html)["\']', html, re.I)
        if m:
            sheet_url = urljoin(index_url, m.group(1))
            sheet_html = fetch_html(sheet_url)
            if sheet_html:
                # base は sheet_url なので相対パスが正しく解決される
                out.extend(_collect_links_from_html(sheet_html, sheet_url, extensions, pat, seen))

    return out


def scrape_html_tables(index_url: str, *, is_warp: bool = False) -> list[list[list[str]]]:
    """index_url のHTMLから全 <table> をリストとして返す。各table = list[row]、各row = list[str]。

    通常: table → tr → td の階層でセル抽出。
    フォールバック: Excel Web Archive (sheet*.htm) などで per-table アプローチが有効な
    ヘッダー行を返さない場合、soup.find_all("tr") を全体スキャンして1テーブルとして扱う。
    """
    html = fetch_html(index_url, is_warp=is_warp)
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")

    def _cell_text(td) -> str:
        text = td.get_text(separator=" ", strip=True)
        return re.sub(r"\(PDF[:：][^)]*\)", "", text).strip()

    tables: list[list[list[str]]] = []
    for tbl in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in tbl.find_all("tr"):
            cells = [_cell_text(td) for td in tr.find_all(["td", "th"])]
            if any(c for c in cells):  # 空セルのみの行はスキップ
                rows.append(cells)
        if rows:
            tables.append(rows)

    # フォールバック: Excel Web Archive など nested table 構造で per-table アプローチが
    # 有効なヘッダー行（契約金額/落札金額）を見つけられない場合、全 <tr> をフラット収集
    _AMOUNT_KEYS = ("契約金額", "落札金額")
    has_valid = any(
        any(any(k in " ".join(row) for k in _AMOUNT_KEYS) for row in tbl)
        for tbl in tables
    )
    if not has_valid:
        seen_rows: set[tuple[str, ...]] = set()
        flat_rows: list[list[str]] = []
        for tr in soup.find_all("tr"):
            cells = [_cell_text(td) for td in tr.find_all(["td", "th"])]
            if not any(c for c in cells):
                continue
            key = tuple(cells)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            flat_rows.append(cells)
        if flat_rows:
            tables = [flat_rows]

    return tables
