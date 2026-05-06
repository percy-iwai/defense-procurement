"""url_matrix.db を procurement.db の source_url と照合して状態を更新。

処理:
1. procurement.db の DISTINCT source_url を取得
2. url_matrix.db の各レコードと URL 完全一致 / ファイル名一致で照合
3. status を更新:
   - filled: 一致あり（既収集確認）
   - filled_new: 一致あり、かつ新規追加分
   - dash: URLなし、もしくは未収集（既存値維持）
4. 404 URL を fetch で確認、見つからなければ flag を立てる
5. ローリングPDF（複数月を1ファイルにまとめた公表PDF）を検出して各月セルに展開
6. 充填率レポート出力
"""
from __future__ import annotations

import io
import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROC_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

# HTML index page パターン（これらは実体URLでなく収集元ページ）
_INDEX_BASENAMES = {
    "sheet001.htm", "sheet002.htm", "sheet003.htm", "sheet004.htm",
    "index.html", "index.htm", "kohyo.html", "kohyo.htm",
}

# procurement.db ↔ url_matrix.db の agency_id 表記揺れ吸収
AGENCY_ALIAS_PROC_TO_MATRIX: dict[str, str] = {
    "gsdf_eadep_yooga": "gsdf_eadep_yoga",  # 用賀支処（procurement: yooga, url_matrix: yoga）
}

# ローリングPDFのファイル名パターン（既知の命名規則）
ROLLING_FILENAME_RE = re.compile(
    r"(?:R\d{1,2}(?:ippan|zuikei|zuii|kyousou)\d{6,}|"
    r"\d{2}kouhyo[-_]ippan\d*|\d{2}kouhyo[-_]zuii\d*|"
    r"koukyoutyoutatu\d+|youahiki\d+)\.pdf$",
    re.IGNORECASE,
)
ROLLING_SPAN_DAYS = 60

# PDFヘッダ判定キャッシュ: source_url → (category, bid_method) | None
_HEADER_CACHE: dict[str, "tuple[str, str] | None"] = {}


def _strip_warp(url: str) -> str:
    """WARP/Wayback プレフィックスを除去して元 URL を返す。"""
    m = re.match(r"https?://warp\.ndl\.go\.jp/\d+/\d+(?:id_)?/?(https?://.*)", url)
    if m:
        return m.group(1).rstrip("/")
    m = re.match(r"https?://web\.archive\.org/web/\d+(?:id_)?/?(https?://.*)", url)
    if m:
        return m.group(1).rstrip("/")
    return url.rstrip("/")


def _classify_from_pdf_header(source_url: str) -> "tuple[str, str] | None":
    """PDF を取得して 1 ページ目の最初の数行から (category, bid_method) を判定。

    判定キーワード:
      bid_method: '競争入札' → '競争' / '随意契約' → '随契'
      category:   '物品役務' or '物品・役務' → '物品役務' / '公共工事' → '公共工事'

    取得失敗・分類不能の場合は None を返す。結果はキャッシュ。
    """
    if source_url in _HEADER_CACHE:
        return _HEADER_CACHE[source_url]

    try:
        from collectors.http_client import fetch as http_fetch
    except Exception as e:
        logger.warning(f"http_client 読み込み失敗: {e}")
        _HEADER_CACHE[source_url] = None
        return None

    data = http_fetch(source_url, use_cache=True, timeout=30)
    if not data:
        logger.warning(f"PDF取得失敗: {source_url}")
        _HEADER_CACHE[source_url] = None
        return None

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                _HEADER_CACHE[source_url] = None
                return None
            text = pdf.pages[0].extract_text() or ""
    except Exception as e:
        logger.warning(f"PDFパース失敗 {source_url}: {e}")
        _HEADER_CACHE[source_url] = None
        return None

    # 先頭10行を文書種別判定用に確保（4-5行目に "随意契約による" がある PDF があるため）
    head = "\n".join(text.split("\n")[:10])

    # bid_method 判定（優先度順）
    # 1) 「随意契約に係る情報の公表」or 「随意契約による」or 「付紙様式第４」 → 随契
    # 2) 「競争入札に係る情報の公表」 → 競争
    # 3) 単独の "競争入札" 出現は法令引用の可能性があるためフォールバック
    bm: str | None = None
    if (
        "随意契約に係る情報の公表" in head
        or "随意契約による" in head
        or "付紙様式第４" in head
        or "付紙様式第4" in head
    ):
        bm = "随契"
    elif "競争入札に係る情報の公表" in head:
        bm = "競争"
    elif "随意契約" in head and "競争入札" not in head:
        bm = "随契"
    elif "競争入札" in head:
        bm = "競争"

    if bm is None:
        logger.warning(f"PDF冒頭から bid_method 判定不能: {source_url} | head={head[:120]!r}")
        _HEADER_CACHE[source_url] = None
        return None

    # category 判定（物品・役務 / 物品役務 を優先、次に 公共工事）
    if "物品役務" in head or "物品・役務" in head:
        cat = "物品役務"
    elif "公共工事" in head:
        cat = "公共工事"
    else:
        logger.warning(f"PDF冒頭から category 判定不能: {source_url} | head={head[:120]!r}")
        _HEADER_CACHE[source_url] = None
        return None

    result = (cat, bm)
    _HEADER_CACHE[source_url] = result
    return result


def _parse_rolling_digits(digits: str) -> list[int]:
    """'456789101112123' → [4,5,6,7,8,9,10,11,12,1,2,3]

    貪欲左→右パース。現在桁が '1' で次桁が '0/1/2' でかつ
    その2桁解釈(10/11/12)が既出でない場合のみ2桁消費、それ以外は1桁。
    重複や1-12範囲外が出たらパース失敗とみなし空リストを返す。

    例: '456789101112123' → 4,5,6,7,8,9,10,11,12 まで消費後、残り '123'
        次は '1' 次桁 '2'。'12' は既に消費済みなので 1桁モードで '1' を取る。
        以降 '2','3' で → [4,5,6,7,8,9,10,11,12,1,2,3]
    """
    months: list[int] = []
    seen: set[int] = set()
    i = 0
    n = len(digits)
    while i < n:
        m: int
        if digits[i] == "1" and i + 1 < n and digits[i + 1] in "012":
            two = int(digits[i:i + 2])
            if two not in seen:
                m = two
                i += 2
            else:
                m = 1
                i += 1
        else:
            m = int(digits[i])
            i += 1
        if m < 1 or m > 12 or m in seen:
            return []
        months.append(m)
        seen.add(m)
    return months


def _fy_months_from_dates(min_date: str, max_date: str, fy: int) -> list[int]:
    """contract_date YYYYMMDD 文字列から、FY 年度内の月リストを返す。

    FY=2024 なら 2024-04 ~ 2025-03 の範囲、月は会計年度順 [4..12,1..3]。
    """
    def _parse(s: str) -> "date | None":
        s = (s or "").strip()
        if len(s) != 8 or not s.isdigit():
            return None
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None

    d_min = _parse(min_date)
    d_max = _parse(max_date)
    if not d_min or not d_max:
        return []

    fy_start = date(fy, 4, 1)
    fy_end = date(fy + 1, 3, 31)
    d_min = max(d_min, fy_start)
    d_max = min(d_max, fy_end)
    if d_min > d_max:
        return []

    fy_order = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    months_in_range: set[int] = set()
    cur = d_min.replace(day=1)
    while cur <= d_max:
        months_in_range.add(cur.month)
        # advance to first day of next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return [m for m in fy_order if m in months_in_range]


def _extract_digits_after_marker(filename: str) -> str:
    """ファイル名から月数字部分を抽出（regex によるトークン位置）。

    例: 'R06ippan456789101112123.pdf' → '456789101112123'
        '06kouhyo-ippan.pdf' → ''
        'koukyoutyoutatu1919.pdf' → '1919'
        'youahiki3.pdf' → '3'
    """
    name = filename.lower()
    if name.endswith(".pdf"):
        name = name[:-4]
    # 末尾の連続数字
    m = re.search(r"(\d+)$", name)
    return m.group(1) if m else ""


def expand_rolling_pdfs(*, dry_run: bool = False) -> dict:
    """ローリングPDFを検出して url_matrix の dash セルを埋める。

    1. procurement.db を (agency_id, fiscal_year, source_url) で集計
    2. span >= 60日 OR ファイル名がローリングパターン → 候補
    3. ファイル名末尾の数字列が 12ヶ月分にパース可能 → 全12ヶ月、それ以外 → 日付範囲の月
    4. PDF冒頭文言から (category, bid_method) を判定
    5. AGENCY_ALIAS_PROC_TO_MATRIX で agency_id 変換
    6. status='dash' のセルのみ UPDATE（既存マッチを壊さない）

    戻り値: 統計 dict
    """
    if not URL_DB.exists():
        logger.error(f"{URL_DB} が存在しません")
        return {}

    # 集計
    with sqlite3.connect(PROC_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT agency_id, fiscal_year, source_url,
                   MIN(contract_date), MAX(contract_date), COUNT(*)
            FROM contracts
            WHERE source_url IS NOT NULL AND source_url != ''
              AND fiscal_year IS NOT NULL
              AND contract_date IS NOT NULL AND contract_date != ''
            GROUP BY agency_id, fiscal_year, source_url
            """
        )
        groups = cur.fetchall()

    candidates: list[dict] = []
    for agency_id, fy, source_url, dmin, dmax, n in groups:
        try:
            fy_int = int(fy)
        except (TypeError, ValueError):
            continue
        basename = os.path.basename(urlparse(source_url.split("?", 1)[0]).path)
        # 本タスクはローリング "PDF" スコープ。Excel等は対象外
        if not basename.lower().endswith(".pdf"):
            continue
        is_rolling_filename = bool(ROLLING_FILENAME_RE.search(basename))
        # span 計算
        try:
            d1 = date(int(dmin[:4]), int(dmin[4:6]), int(dmin[6:8]))
            d2 = date(int(dmax[:4]), int(dmax[4:6]), int(dmax[6:8]))
            span_days = (d2 - d1).days
        except Exception:
            span_days = 0
        if not is_rolling_filename and span_days < ROLLING_SPAN_DAYS:
            continue
        candidates.append({
            "agency_id": agency_id,
            "fy": fy_int,
            "source_url": source_url,
            "basename": basename,
            "dmin": dmin,
            "dmax": dmax,
            "n": n,
            "is_rolling_filename": is_rolling_filename,
            "span_days": span_days,
        })

    logger.info(f"ローリング候補グループ: {len(candidates)} 件")

    stats = {
        "candidates": len(candidates),
        "classified_ok": 0,
        "header_failed": 0,
        "updated_cells": 0,
        "skipped_no_match": 0,
        "details": [],
    }

    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()

        for c in candidates:
            # category/bid_method 判定（PDF冒頭文言）
            cls = _classify_from_pdf_header(c["source_url"])
            if cls is None:
                stats["header_failed"] += 1
                continue
            stats["classified_ok"] += 1
            category, bid_method = cls

            # 月リスト決定
            digits = _extract_digits_after_marker(c["basename"])
            months: list[int] = []
            if c["is_rolling_filename"] and digits:
                parsed = _parse_rolling_digits(digits)
                # 12ヶ月かつ4..12,1..3を全カバーしている場合のみ採用
                if len(parsed) == 12 and set(parsed) == set(range(1, 13)):
                    months = parsed
            if not months:
                months = _fy_months_from_dates(c["dmin"], c["dmax"], c["fy"])

            if not months:
                logger.warning(
                    f"月リスト決定不能: {c['agency_id']} fy={c['fy']} {c['basename']}"
                )
                continue

            matrix_agency = AGENCY_ALIAS_PROC_TO_MATRIX.get(c["agency_id"], c["agency_id"])

            # 各月セルに UPDATE
            cell_updates = 0
            for m in months:
                # 対象セル取得（status='dash' のみ）
                cur.execute(
                    """
                    SELECT id FROM url_matrix
                    WHERE agency_id=? AND fiscal_year=? AND month=?
                      AND category=? AND bid_method=? AND status='dash'
                    """,
                    (matrix_agency, c["fy"], m, category, bid_method),
                )
                target = cur.fetchone()
                if not target:
                    continue
                row_id = target[0]
                if not dry_run:
                    cur.execute(
                        """
                        UPDATE url_matrix
                           SET url=?, filename=?, status='filled_new',
                               flag_collected=1, flag_rolling=1
                         WHERE id=?
                        """,
                        (c["source_url"], c["basename"], row_id),
                    )
                cell_updates += 1

            if cell_updates == 0:
                stats["skipped_no_match"] += 1
            else:
                stats["updated_cells"] += cell_updates
                stats["details"].append({
                    "agency": matrix_agency,
                    "fy": c["fy"],
                    "category": category,
                    "bid_method": bid_method,
                    "months": months,
                    "filename": c["basename"],
                    "cells": cell_updates,
                })

        if not dry_run:
            conn.commit()

    logger.info(
        f"ローリング展開: 候補 {stats['candidates']}, 分類成功 {stats['classified_ok']}, "
        f"分類失敗 {stats['header_failed']}, 更新セル {stats['updated_cells']}, "
        f"対応セルなし {stats['skipped_no_match']} (dry_run={dry_run})"
    )
    return stats


def audit_headers() -> list[dict]:
    """既存 filled セルについて、URL 先 PDF の冒頭文言から推定される
    (category, bid_method) と url_matrix の登録値が食い違うものを列挙。

    UPDATE は行わず、リストを返すのみ。"""
    if not URL_DB.exists():
        logger.error(f"{URL_DB} が存在しません")
        return []
    mismatches: list[dict] = []
    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, agency_id, fiscal_year, month, category, bid_method, url, filename
            FROM url_matrix
            WHERE url IS NOT NULL AND url != ''
              AND status IN ('filled', 'filled_new')
            """
        )
        rows = cur.fetchall()

    pdf_rows = [r for r in rows if (r[7] or r[6]).lower().endswith(".pdf")]
    logger.info(f"PDF 既存filled対象: {len(pdf_rows)} 件 / 全filled {len(rows)} 件")

    for row_id, agency_id, fy, month, cat, bm, url, fn in pdf_rows:
        cls = _classify_from_pdf_header(url)
        if cls is None:
            continue
        h_cat, h_bm = cls
        if (cat, bm) != (h_cat, h_bm):
            mismatches.append({
                "id": row_id,
                "agency_id": agency_id,
                "fy": fy,
                "month": month,
                "matrix": (cat, bm),
                "header": (h_cat, h_bm),
                "url": url,
            })
    logger.info(f"category/bid_method 不一致: {len(mismatches)} 件")
    return mismatches


def reconcile() -> dict:
    # 1. 全 source_url 取得（procurement.db）
    with sqlite3.connect(PROC_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT source_url FROM contracts "
            "WHERE source_url IS NOT NULL AND source_url != ''"
        )
        proc_urls: set[str] = {row[0] for row in cur.fetchall()}

    # 完全一致用・ファイル名一致用・WARP正規化一致用のインデックスを構築
    proc_urls_normalized: set[str] = set()
    proc_filenames: dict[str, set[str]] = {}
    for u in proc_urls:
        # WARP正規化 URL インデックス
        norm = _strip_warp(u)
        proc_urls_normalized.add(norm)
        try:
            base = os.path.basename(urlparse(norm.split("?", 1)[0]).path)
        except Exception:
            base = ""
        if base:
            proc_filenames.setdefault(base.lower(), set()).add(norm)

    # agency_id → 収集済みフラグ（HTML index URL向け）
    with sqlite3.connect(PROC_DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT agency_id FROM contracts")
        proc_agencies: set[str] = {r[0] for r in cur.fetchall()}

    logger.info(f"procurement.db 内 distinct source_url 数: {len(proc_urls):,}")

    # 2. url_matrix.db 照合
    if not URL_DB.exists():
        logger.error(f"{URL_DB} が存在しません")
        return {}

    # url_matrix.db に flag_collected カラムを増設（既存なら無視）
    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(url_matrix)")
        cols = {row[1] for row in cur.fetchall()}
        if "flag_collected" not in cols:
            cur.execute("ALTER TABLE url_matrix ADD COLUMN flag_collected INTEGER DEFAULT 0")
            logger.info("flag_collected カラム追加")
        if "flag_404" not in cols:
            cur.execute("ALTER TABLE url_matrix ADD COLUMN flag_404 INTEGER DEFAULT 0")
            logger.info("flag_404 カラム追加")
        conn.commit()

    # 3. 照合 + フラグ更新
    matched_exact = 0
    matched_filename = 0
    not_matched_with_url = 0
    no_url = 0
    new_filled = 0  # status が dash → filled に遷移する数

    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, url, status, agency_id FROM url_matrix"
        )
        rows = cur.fetchall()

        updates: list[tuple[int, int, str | None]] = []  # (id, flag_collected, new_status)

        for row_id, url, status, agency_id in rows:
            if not url or not url.strip():
                no_url += 1
                continue

            url_clean = url.strip()
            url_norm = _strip_warp(url_clean)
            collected_flag = 0
            new_status = None
            match_type = None

            # ① 完全一致（元URL）
            if url_clean in proc_urls:
                collected_flag = 1
                match_type = "exact"
                matched_exact += 1
            # ② 完全一致（WARP正規化後）
            elif url_norm in proc_urls or url_norm in proc_urls_normalized:
                collected_flag = 1
                match_type = "exact_norm"
                matched_exact += 1
            else:
                # ③ ファイル名末尾一致
                fname = os.path.basename(urlparse(url_norm.split("?", 1)[0]).path).lower()
                if fname and fname in proc_filenames:
                    collected_flag = 1
                    match_type = "filename"
                    matched_filename += 1
                # ④ HTML index URL + agency 収集済み（例: sheet001.htm, index.html）
                elif fname in _INDEX_BASENAMES and agency_id and agency_id in proc_agencies:
                    collected_flag = 1
                    match_type = "agency_index"
                    matched_filename += 1
                else:
                    not_matched_with_url += 1

            if collected_flag:
                if status == "dash":
                    new_status = "filled_new"
                    new_filled += 1
                updates.append((row_id, collected_flag, new_status))
            elif new_status is not None:
                updates.append((row_id, 0, new_status))

        # 一括更新
        for row_id, flag, new_status in updates:
            if new_status:
                cur.execute(
                    "UPDATE url_matrix SET flag_collected = ?, status = ? WHERE id = ?",
                    (flag, new_status, row_id),
                )
            else:
                cur.execute(
                    "UPDATE url_matrix SET flag_collected = ? WHERE id = ?",
                    (flag, row_id),
                )
        conn.commit()

    logger.info(
        f"照合結果: 完全一致 {matched_exact}, ファイル名一致 {matched_filename}, "
        f"未一致(URLあり) {not_matched_with_url}, URLなし {no_url}"
    )
    logger.info(f"status 'dash' → 'filled_new' 遷移: {new_filled}件")

    # 4. status 分布レポート
    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM url_matrix GROUP BY status ORDER BY 2 DESC")
        dist = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) FROM url_matrix WHERE flag_collected = 1"
        )
        collected_n = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM url_matrix WHERE url IS NOT NULL AND url != ''"
        )
        with_url = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM url_matrix")
        total = cur.fetchone()[0]

    print("\n=== url_matrix.db 充填状況 ===")
    print(f"総レコード数:          {total:,}")
    print(f"URL設定済:             {with_url:,} ({with_url/total*100:.1f}%)")
    print(f"既収集確認 (flag=1):   {collected_n:,} ({collected_n/total*100:.1f}%)")
    print(f"\n=== status 分布 ===")
    for status, n in dist:
        print(f"  {status:>15}: {n:6,}")

    return {
        "total": total,
        "with_url": with_url,
        "collected": collected_n,
        "matched_exact": matched_exact,
        "matched_filename": matched_filename,
        "new_filled": new_filled,
        "status_dist": dict(dist),
    }


def check_404_urls(*, limit: int = 100, dry_run: bool = True) -> int:
    """flag_collected=0 で URL がある行を fetch で確認、404 を flag_404 にマーク。

    軽量化のため limit 制限付き（HEAD リクエスト推奨だが requests.head は 4xx の挙動が不安定）。
    """
    from collectors.http_client import fetch as http_fetch

    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, url FROM url_matrix "
            "WHERE flag_collected = 0 "
            "  AND (flag_404 IS NULL OR flag_404 = 0) "
            "  AND url IS NOT NULL AND url != '' "
            "ORDER BY id LIMIT ?",
            (limit,),
        )
        targets = cur.fetchall()

    logger.info(f"404 確認対象: {len(targets)}件")
    flagged = 0
    for row_id, url in targets:
        d = http_fetch(url, use_cache=True, timeout=15)
        if d is None:
            flagged += 1
            if not dry_run:
                with sqlite3.connect(URL_DB) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE url_matrix SET flag_404 = 1 WHERE id = ?",
                        (row_id,),
                    )
                    conn.commit()
    logger.info(f"404 flagged: {flagged}/{len(targets)}件 (dry_run={dry_run})")
    return flagged


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--check-404", action="store_true",
                   help="未収集URLを fetch で確認し404をflag付け")
    p.add_argument("--check-404-limit", type=int, default=200)
    p.add_argument("--dry-run", action="store_true",
                   help="DB書き込みしない（reconcile/rolling/404 全てに適用）")
    p.add_argument("--no-rolling", action="store_true",
                   help="ローリングPDF展開を無効化")
    p.add_argument("--rolling-only", action="store_true",
                   help="既存reconcileを飛ばしてローリングPDF展開のみ実行")
    p.add_argument("--audit-headers", action="store_true",
                   help="既存filledセルとPDF冒頭文言の不整合を監査")
    args = p.parse_args()

    if not args.rolling_only:
        reconcile()

    if not args.no_rolling:
        expand_rolling_pdfs(dry_run=args.dry_run)

    if args.audit_headers:
        miss = audit_headers()
        print("\n=== category/bid_method 不一致 ===")
        for m in miss:
            print(
                f"  id={m['id']} {m['agency_id']} FY{m['fy']} M{m['month']}: "
                f"matrix={m['matrix']} vs header={m['header']} | {m['url']}"
            )
        print(f"  計 {len(miss)} 件")

    if args.check_404:
        flagged = check_404_urls(limit=args.check_404_limit, dry_run=args.dry_run)
        print(f"\n404 flagged: {flagged}件")
