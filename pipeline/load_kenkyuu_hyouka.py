"""総務省「政策評価ポータル」掲載の防衛省 政策評価書（研究開発系・H27以降）を
収集して `kenkyuu_hyouka` テーブルに投入する。

各エントリのPDFから「担当部局（等名）」を抽出し、org_key へマップする。
このテーブルは `dev/match_kenkyuu_hyouka_fallback.py` で fallback_atla
契約への要求元割当に使用される。

ポータル: https://www.soumu.go.jp/main_sosiki/hyouka/seisaku_n/portal/index/kenkyu/mod.html

使い方:
    python -m pipeline.load_kenkyuu_hyouka --dry-run
    python -m pipeline.load_kenkyuu_hyouka --limit 10
    python -m pipeline.load_kenkyuu_hyouka
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup
from loguru import logger

from collectors.http_client import fetch as http_fetch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
LOG_DIR = PROJECT_ROOT / "logs"

PORTAL_URL = "https://www.soumu.go.jp/main_sosiki/hyouka/seisaku_n/portal/index/kenkyu/mod.html"

TARGET_FY_MIN = 2015  # H27 = FY2015
PAGE_WINDOW = 6       # 評価書 PDF の #page=N から N+PAGE_WINDOW まで担当部局を探索

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
WARP_RATE_LIMIT_SEC = 2.5

# ─── 担当部局 → org_key マッピング ─────────────────────────────────────────

BUREAU_TO_ORG: list[tuple[str, str]] = [
    # 各幕僚監部（自衛隊系）— 幕僚監部名義のエントリはほぼ存在しないが念のため
    ("陸上幕僚監部",          "GSDF"),
    ("海上幕僚監部",          "MSDF"),
    ("航空幕僚監部",          "ASDF"),
    ("統合幕僚監部",          "JS"),
    ("情報本部",              "DIH"),
    ("防衛医科大学校",        "NDMC"),
    ("防衛大学校",            "NDA"),
    ("防衛研究所",            "NIDS"),

    # ── 事業監理官サブユニット（担当分野から要求元を特定） ────────────────────
    # 「艦船担当」: 潜水艦・魚雷・UUV・機雷 → 全件 MSDF
    ("艦船担当",              "MSDF"),
    # 「航空機担当」: 次期戦闘機・スタンド・オフ電子戦機 → 全件 ASDF
    ("航空機担当",            "ASDF"),
    # 「情報・武器・車両担当」/ 半角濁点バリアント: 92式信管・NBC偵察車・水陸両用→ GSDF
    # ※ map_bureau_to_org 内でスペース・記号除去して照合するため表記揺れは吸収
    ("情報・武器・車両担当",  "GSDF"),
    ("情報武器車両担当",      "GSDF"),

    # ── ATLA内部部局・研究所（R&D主担当） ───────────────────────────────────
    ("艦艇装備研究所",        "ATLA"),
    ("航空装備研究所",        "ATLA"),
    ("陸上装備研究所",        "ATLA"),
    ("電子装備研究所",        "ATLA"),
    ("先進技術推進センター",  "ATLA"),
    ("次世代装備研究所",      "ATLA"),
    ("プロジェクト管理部",    "ATLA"),
    ("装備政策部",            "ATLA"),
    ("技術戦略部",            "ATLA"),
    ("研究開発官",            "ATLA"),

    # ── ATLA前身組織（H27以前） ──────────────────────────────────────────────
    ("経理装備局",            "ATLA"),
    ("装備庁",                "ATLA"),
    # 旧防衛庁 管理局（H15以前の装備開発計画部門）
    ("管理局",                "ATLA"),

    # ── 内局 ────────────────────────────────────────────────────────────────
    ("防衛局",                "NAIKYOKU"),
    ("防衛政策局",            "NAIKYOKU"),
    ("整備計画局",            "NAIKYOKU"),
    ("人事教育局",            "NAIKYOKU"),
    ("地方協力局",            "NAIKYOKU"),
    ("大臣官房",              "NAIKYOKU"),
]

# 担当部局抽出パターン（「担当部局等名：xxx」 / 「担当部局：xxx」 等）
_TANTOU_PAT = re.compile(r"担当部局(?:等名)?\s*[:：]\s*([^\n\r]+)")

# 区切り文字 (一つ目の値だけ取りたい)
_BUREAU_SPLIT = re.compile(r"[、,／/]")

_PUNCT_RE = re.compile(r"[\s\-－―ー~〜・,，、.。:：;；'\"\(\)\[\]【】「」『』]")


# ─── ヘルパー ───────────────────────────────────────────────────────────────

def nfkc(s: Optional[str]) -> str:
    return unicodedata.normalize("NFKC", str(s or ""))


def normalize_jigyou_name(s: Optional[str]) -> str:
    s = nfkc(s)
    s = _PUNCT_RE.sub("", s)
    return s.lower().strip()


def wareki_to_seireki(text: str) -> Optional[int]:
    """「平成27年度」「令和3年度」「令和元年度」などを西暦FYに変換。"""
    text = nfkc(text)
    m = re.search(r"平成\s*(\d{1,2})\s*年度", text)
    if m:
        return 1988 + int(m.group(1))
    m = re.search(r"令和\s*(\d{1,2})\s*年度", text)
    if m:
        return 2018 + int(m.group(1))
    if "令和元年度" in text:
        return 2019
    return None


def map_bureau_to_org(bureau_text: Optional[str]) -> Optional[str]:
    """担当部局テキストを org_key（GSDF/MSDF/ASDF/JS/DIH/ATLA等）に変換する。

    複数部局（「、」「/」「,」で連結）の場合は最初の部局を採用。
    括弧内サブユニット（例:「装備政策部（艦船担当）」の「艦船担当」）は
    本文より優先的に照合して要求元を特定する。
    辞書登録なしの場合は None。
    """
    if not bureau_text:
        return None
    text = nfkc(bureau_text)

    # 優先パス: 括弧内サブユニット（「艦船担当」「航空機担当」等）を先に確認
    # 「装備政策部（艦船担当）」→ 括弧内「艦船担当」→ MSDF
    paren_m = re.search(r"[（(]([^）)]+)[）)]", text)
    if paren_m:
        paren = paren_m.group(1).strip()
        paren_nospace = re.sub(r"\s+", "", paren)
        for keyword, org in sorted(BUREAU_TO_ORG, key=lambda x: -len(x[0])):
            kw = nfkc(keyword)
            if kw in paren or kw in paren_nospace:
                return org

    # 通常パス: 区切りでsplitし最初の部局
    first = _BUREAU_SPLIT.split(text, maxsplit=1)[0].strip()
    if not first:
        first = text
    # 文字間スペース除去（OCR由来の「経 理 装 備 局」→「経理装備局」）
    first_nospace = re.sub(r"\s+", "", first)
    # longest match first
    for keyword, org in sorted(BUREAU_TO_ORG, key=lambda x: -len(x[0])):
        kw = nfkc(keyword)
        if kw in first or kw in first_nospace:
            return org
    return None


# ─── ポータルHTML取得・パース ────────────────────────────────────────────────

@dataclass
class PortalEntry:
    fiscal_year: int
    hyouka_kubun: str       # '事前' or '事後'
    jigyou_name: str
    pdf_url: str            # 評価書（本文）のURL（要旨ではなく）
    page_anchor: Optional[int]


def fetch_portal_html() -> str:
    data = http_fetch(PORTAL_URL, use_cache=True)
    if data is None:
        raise RuntimeError(f"ポータルHTML取得失敗: {PORTAL_URL}")
    # ポータルはShift_JIS
    return data.decode("shift_jis", errors="replace")


def parse_index_rows(html: str, base_url: str = PORTAL_URL) -> list[PortalEntry]:
    """ポータルHTMLから評価書エントリを抽出する。

    構造: 各 <h3> "令和7年度（事前評価）" のあと <table> が続く。
    各<tr>には [区分] [事業名] [評価書等(要旨/評価書/参考)] のセル。
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[PortalEntry] = []

    h3_pattern = re.compile(r"(平成\d+年度|令和\d+年度|令和元年度).*?[(（](事前|事後)評価")

    for h3 in soup.find_all("h3"):
        title = h3.get_text(strip=True)
        m = h3_pattern.search(nfkc(title))
        if not m:
            continue
        fy = wareki_to_seireki(m.group(1))
        if fy is None or fy < TARGET_FY_MIN:
            continue
        kubun = m.group(2)  # '事前' or '事後'

        # 直後の<table>を取得
        tbl = h3.find_next("table")
        if tbl is None:
            continue

        for tr in tbl.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            cell_texts = [c.get_text(strip=True) for c in cells]
            # ヘッダー行スキップ
            if any(k in t for t in cell_texts for k in ["区分", "評価対象政策", "評価書等"]):
                # ただし最初の事前評価列がheaderしか含まないこともあるので、
                # PDFリンクが含まれる行は data 行とみなす
                if not any(a.get("href", "").lower().endswith(".pdf") or ".pdf#" in a.get("href", "")
                           for a in tr.find_all("a")):
                    continue

            # 事業名候補（PDFリンクを含まないセルかつ十分長い）
            jigyou_name: Optional[str] = None
            for c in cells:
                t = c.get_text(strip=True)
                if not t:
                    continue
                if t in ("事前評価", "事後評価", "区分", "評価対象政策", "評価書等"):
                    continue
                # PDFリンクラベル
                if t in ("要旨", "評価書", "参考", "要旨評価書", "要旨評価書参考"):
                    continue
                # cell内に<a>のテキストだけ含むケース（"要旨評価書"のような）
                a_texts = "".join(a.get_text(strip=True) for a in c.find_all("a"))
                if a_texts and a_texts == t:
                    continue
                if len(t) >= 4:
                    jigyou_name = t
                    break

            if not jigyou_name:
                continue

            # 評価書（本文）リンクを取得：複数の<a>から「評価書」「本文」のものを優先
            hyoukasho_url: Optional[str] = None
            youshi_url: Optional[str] = None
            for a in tr.find_all("a"):
                href = a.get("href", "")
                if not href or ".pdf" not in href.lower():
                    continue
                label = a.get_text(strip=True)
                full = urljoin(base_url, href)
                if "評価書" in label or "本文" in label:
                    hyoukasho_url = full
                elif "要旨" in label or "概要" in label:
                    youshi_url = full

            # 評価書を優先、なければ要旨を使う
            chosen = hyoukasho_url or youshi_url
            if not chosen:
                continue

            # #page=N アンカー抽出
            page_anchor: Optional[int] = None
            am = re.search(r"#page=(\d+)", chosen)
            if am:
                page_anchor = int(am.group(1))
                chosen = chosen.split("#", 1)[0]

            entries.append(PortalEntry(
                fiscal_year=fy,
                hyouka_kubun=kubun,
                jigyou_name=jigyou_name,
                pdf_url=chosen,
                page_anchor=page_anchor,
            ))

    return entries


# ─── PDF取得・担当部局抽出 ──────────────────────────────────────────────────

def _resolve_warp_url(url: str) -> str:
    """`warp.da.ndl.go.jp/info:ndljp/...` 形式のラッパーURLを直接URLに解決する。

    新形式 `/{coll}/{ts}/{origUrl}` を返す。失敗時は元URL。
    """
    if "warp.da.ndl.go.jp" not in url and "warp.ndl.go.jp/info:" not in url:
        return url
    # 既に新形式（`/web/...` や `/20190813/...`）なら何もしない
    if re.search(r"warp\.ndl\.go\.jp/(?:web/)?\d{8}", url):
        return url
    try:
        time.sleep(WARP_RATE_LIMIT_SEC)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
        if r.status_code != 200:
            return url
        body = r.content.decode("utf-8", errors="replace")
        # iframe src または input[name=waybackUrl] から実URL抽出
        m = re.search(r'name=["\']waybackUrl["\'] value=["\']([^"\']+)["\']', body)
        if m:
            wayback_path = m.group(1)
            return urljoin("https://warp.ndl.go.jp", wayback_path)
        m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', body)
        if m:
            iframe_src = m.group(1)
            return urljoin("https://warp.ndl.go.jp", iframe_src)
    except requests.RequestException as e:
        logger.warning(f"WARP URL解決失敗: {url} ({e})")
    return url


def download_pdf(url: str) -> Optional[bytes]:
    """PDFを取得する。WARP/info:形式の場合は直接URLに解決してから取得。"""
    resolved = _resolve_warp_url(url)
    is_warp = "warp.ndl.go.jp" in resolved or "web.archive.org" in resolved
    data = http_fetch(resolved, use_cache=True, is_warp=is_warp)
    if data is None:
        return None
    # 取得物がPDFか確認
    if data[:4] != b"%PDF":
        logger.warning(f"非PDFを取得: {url} → {resolved} (size={len(data)})")
        return None
    return data


def extract_tantou_bukyoku(
    pdf_data: bytes,
    page_anchor: Optional[int],
    *,
    window: int = PAGE_WINDOW,
) -> Optional[str]:
    """評価書PDFから「担当部局（等名）」を抽出する。

    page_anchor が指定されていれば該当ページから window ページ範囲を走査。
    なければ先頭から最大 window ページを走査。
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
            n_pages = len(pdf.pages)
            if page_anchor is not None and 1 <= page_anchor <= n_pages:
                start = page_anchor - 1
            else:
                start = 0
            end = min(start + window, n_pages)
            for pn in range(start, end):
                text = pdf.pages[pn].extract_text() or ""
                m = _TANTOU_PAT.search(text)
                if m:
                    return m.group(1).strip()
    except Exception as e:
        logger.warning(f"PDF読み込みエラー: {e}")
        return None
    return None


# ─── DB操作 ─────────────────────────────────────────────────────────────────

def upsert_entry(
    con: sqlite3.Connection,
    entry: PortalEntry,
    bureau: Optional[str],
    org: Optional[str],
) -> bool:
    """1件UPSERTし、新規挿入なら True を返す。"""
    norm = normalize_jigyou_name(entry.jigyou_name)
    cur = con.execute(
        """
        INSERT OR IGNORE INTO kenkyuu_hyouka
            (fiscal_year, hyouka_kubun, jigyou_name, jigyou_name_norm,
             tantou_bukyoku, tantou_org, pdf_url, page_anchor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.fiscal_year, entry.hyouka_kubun, entry.jigyou_name, norm,
            bureau, org, entry.pdf_url, entry.page_anchor,
        ),
    )
    return cur.rowcount > 0


# ─── メイン処理 ─────────────────────────────────────────────────────────────

def run(dry_run: bool, limit: Optional[int]) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    logger.info(f"ポータル取得: {PORTAL_URL}")
    html = fetch_portal_html()
    entries = parse_index_rows(html)
    logger.info(f"パースしたエントリ数: {len(entries)}")

    if limit:
        entries = entries[:limit]
        logger.info(f"--limit {limit} を適用 → {len(entries)}件")

    fy_breakdown: dict[int, int] = {}
    for e in entries:
        fy_breakdown[e.fiscal_year] = fy_breakdown.get(e.fiscal_year, 0) + 1
    logger.info(f"FY別: {sorted(fy_breakdown.items())}")

    if dry_run:
        con = None
    else:
        con = sqlite3.connect(DB_PATH)

    inserted = 0
    skipped_existing = 0
    pdf_failures = 0
    bureau_failures = 0
    org_failures = 0
    org_breakdown: dict[str, int] = {}
    unmapped_bureaus: list[str] = []

    for i, entry in enumerate(entries, 1):
        logger.info(f"[{i}/{len(entries)}] FY{entry.fiscal_year} {entry.hyouka_kubun}: "
                    f"{entry.jigyou_name[:50]} (page={entry.page_anchor})")

        pdf_data = download_pdf(entry.pdf_url)
        if pdf_data is None:
            pdf_failures += 1
            logger.warning(f"  PDF取得失敗: {entry.pdf_url}")
            bureau = None
            org = None
        else:
            bureau = extract_tantou_bukyoku(pdf_data, entry.page_anchor)
            if not bureau:
                bureau_failures += 1
                logger.warning("  担当部局抽出失敗")
                org = None
            else:
                logger.info(f"  担当部局: {bureau}")
                org = map_bureau_to_org(bureau)
                if org is None:
                    org_failures += 1
                    if bureau not in unmapped_bureaus:
                        unmapped_bureaus.append(bureau)
                else:
                    org_breakdown[org] = org_breakdown.get(org, 0) + 1

        if dry_run:
            continue

        if upsert_entry(con, entry, bureau, org):
            inserted += 1
        else:
            skipped_existing += 1

    if con is not None:
        con.commit()
        con.close()

    result = {
        "dry_run": dry_run,
        "portal_url": PORTAL_URL,
        "entries_total": len(entries),
        "fy_breakdown": dict(sorted(fy_breakdown.items())),
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "pdf_failures": pdf_failures,
        "bureau_extraction_failures": bureau_failures,
        "org_mapping_failures": org_failures,
        "org_breakdown": dict(sorted(org_breakdown.items())),
        "unmapped_bureaus": unmapped_bureaus,
    }

    if not dry_run:
        log_path = LOG_DIR / f"load_kenkyuu_hyouka_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"ログ: {log_path}")

    print()
    print(f"{'[DRY-RUN] ' if dry_run else ''}kenkyuu_hyouka 収集結果")
    print(f"  エントリ総数         : {len(entries)}")
    print(f"  挿入                 : {inserted}")
    print(f"  既存スキップ         : {skipped_existing}")
    print(f"  PDF取得失敗          : {pdf_failures}")
    print(f"  担当部局抽出失敗     : {bureau_failures}")
    print(f"  org_keyマッピング失敗: {org_failures}")
    print(f"  org内訳              : {dict(sorted(org_breakdown.items()))}")
    if unmapped_bureaus:
        print("  未マップ部局一覧:")
        for b in unmapped_bureaus:
            print(f"    - {b}")

    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="DB書き込みなし")
    ap.add_argument("--limit", type=int, help="最初のN件のみ処理（デバッグ用）")
    args = ap.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
