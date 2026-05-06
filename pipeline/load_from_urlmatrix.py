"""url_matrix.db から未収録URLを読み取り、形式別に既存パーサーで収集してDB投入。

優先順位: filled_new → filled
形式: Excel / PDF / HTML (通常) + WARP/Wayback (is_warp=True、自動レート制限2.5秒)
ThreadPoolExecutor(4) で非WARPを並行処理、WARPは順次処理。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch                    # noqa: E402
from collectors.index_scraper import scrape_html_tables    # noqa: E402
from parsers.excel_parser import iter_records, parse_excel_bytes  # noqa: E402
from parsers.pdf_table import (                            # noqa: E402
    _normalize_bid as pdf_norm_bid,
    _to_amount as pdf_to_amount,
    _to_date_str as pdf_to_date,
    _to_rate as pdf_to_rate,
    fy_from_date,
    parse_pdf_records,
)
from pipeline.load_gsdf import INSERT_SQL, REQUIRED_KEYS, TARGET_FYS  # noqa: E402

DB_PATH      = PROJECT_ROOT / "data" / "db" / "procurement.db"
MATRIX_PATH  = PROJECT_ROOT / "data" / "db" / "url_matrix.db"
MAX_WORKERS  = 4
MAX_AMOUNT   = 1_000_000_000_000  # 1兆円超はNULLに

# ── Agency category マッピング ────────────────────────────────────────────────

_DIRECT_CAT: dict[str, str] = {
    "naikyoku_kaikei":  "防衛省内局",
    "dih":              "情報本部",
    "js":               "統合幕僚監部",
    "ndmc":             "防衛医科大学校",
    "nids":             "防衛研究所",
    "nda":              "防衛大学校",
    "tohoku_kaikei":    "陸上自衛隊",
    "hokubu_kaikei":    "陸上自衛隊",
    "gsdf_eafin":       "陸上自衛隊",
    "gsdf_seibu":       "陸上自衛隊",
}

_PREFIX_CAT: list[tuple[str, str]] = [
    ("atla",  "防衛装備庁"),
    ("asdf",  "航空自衛隊"),
    ("msdf",  "海上自衛隊"),
    ("gsdf",  "陸上自衛隊"),
    ("rdb",   "地方防衛局"),
]


def _get_category(agency_id: str) -> str:
    if agency_id in _DIRECT_CAT:
        return _DIRECT_CAT[agency_id]
    for prefix, cat in _PREFIX_CAT:
        if agency_id.startswith(prefix):
            return cat
    return "その他"


# ── URL ユーティリティ ─────────────────────────────────────────────────────────

def _unwrap_url(url: str) -> str:
    """WARP/Wayback ラッパーから元URLを取り出す。"""
    m = re.search(r"warp\.ndl\.go\.jp/\d+/\d+/(https?://)", url)
    if m:
        return url[url.index(m.group(1)):]
    m = re.search(r"web\.archive\.org/web/\d+/(https?://)", url)
    if m:
        return url[url.index(m.group(1)):]
    return url


def _detect_type(url: str) -> str:
    """URLから拡張子でファイルタイプを判定。"""
    actual = _unwrap_url(url).lower().split("?")[0]
    fn = actual.rsplit("/", 1)[-1]
    if fn.endswith((".xlsx", ".xls")):
        return "excel"
    if fn.endswith(".pdf"):
        return "pdf"
    if fn.endswith((".html", ".htm")):
        return "html"
    return "unknown"


def _is_warp(url: str) -> bool:
    return "warp.ndl.go.jp" in url or "web.archive.org" in url


def _fy_from_url(url: str) -> Optional[int]:
    """URLから年度を推定（失敗時は None）。"""
    actual = _unwrap_url(url)

    # fy2024 / fy2023 形式
    m = re.search(r"fy(202[2-9])", actual, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # /r06/ や r0604 / R6.4 / 令和6 形式（月付き）
    m = re.search(r"[rR]0?(\d{1,2})[\.\-_/](\d{1,2})", actual)
    if m:
        ry, mm = int(m.group(1)), int(m.group(2))
        if 1 <= ry <= 20 and 1 <= mm <= 12:
            base = 2018 + ry
            return base if mm >= 4 else base - 1

    # /r06/ ← 月なし（4月起算でFY = 2018+ry）
    m = re.search(r"[/\-_]r0?(\d{1,2})[/\-_]", actual, re.IGNORECASE)
    if m:
        ry = int(m.group(1))
        if 1 <= ry <= 20:
            return 2018 + ry

    # /2024/ など
    m = re.search(r"[/\-_](202[2-9])[/\-_]", actual)
    if m:
        return int(m.group(1))

    return None


# ── 入札方式・種別推定 ─────────────────────────────────────────────────────────

def _classify_url_bid(url: str) -> tuple[Optional[str], Optional[str]]:
    """(contract_type, bid_method) を URLパターンから推定。"""
    u = _unwrap_url(url).lower()
    fn = u.rsplit("/", 1)[-1]

    # 入札方式
    if any(k in u for k in ("zuikei", "zuii", "_z.", "_z_", "buppin_z", "kouji_z")):
        bid = "随意契約"
        ctype = "随意契約"
    elif any(k in u for k in ("kyousou", "kyoso", "ippan", "rakusatsu", "nyuusatu",
                               "buppin_k", "kouji_k")):
        bid = "一般競争入札"
        ctype = "一般競争入札"
    else:
        bid = None
        ctype = None

    # 物件カテゴリ
    if any(k in u for k in ("kouji", "kouzi", "kensetsu", "kenchiku")):
        ctype = "公共工事"

    return ctype, bid


# ── パーサー ──────────────────────────────────────────────────────────────────

def _build_agency_meta(agency_id: str, agency_name: str) -> dict:
    return {
        "agency_id":       agency_id,
        "agency_name":     agency_name,
        "agency_category": _get_category(agency_id),
    }


def _enrich(rec: dict, agency_meta: dict, source_url: str, source_type: str,
            url_ctype: Optional[str], url_bid: Optional[str]) -> dict:
    rec.update(agency_meta)
    rec["source_url"]  = source_url
    rec["source_type"] = source_type
    if not rec.get("contract_type") and url_ctype:
        rec["contract_type"] = url_ctype
    if not rec.get("bid_method") and url_bid:
        rec["bid_method"] = url_bid
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    if rec.get("contract_amount") and rec["contract_amount"] > MAX_AMOUNT:
        rec["contract_amount"] = None
    return rec


def _parse_excel_url(data: bytes, url: str, agency_meta: dict) -> list[dict]:
    actual = _unwrap_url(url)
    is_xls = actual.lower().endswith(".xls")
    url_ctype, url_bid = _classify_url_bid(url)

    try:
        df, h, col_map = parse_excel_bytes(data, is_xls=is_xls)
    except Exception as exc:
        logger.warning(f"Excel parse error {url}: {exc}")
        return []

    if df.empty or not col_map:
        return []

    # FY推定 → できれば1回、無理なら全TARGET_FYSを試す（fy_guard=True で汚染防止）
    url_fy = _fy_from_url(url)
    fys_to_try = [url_fy] if url_fy in TARGET_FYS else list(sorted(TARGET_FYS))

    records: list[dict] = []
    seen: set[tuple] = set()
    for fy in fys_to_try:
        for rec in iter_records(df, h, col_map, target_fy=fy, fy_guard=True):
            key = (rec.get("contract_name"), rec.get("vendor_name"),
                   rec.get("contract_amount"), rec.get("fiscal_year"))
            if key in seen:
                continue
            seen.add(key)
            records.append(_enrich(rec, agency_meta, url, "excel", url_ctype, url_bid))

    return records


def _parse_pdf_url(data: bytes, url: str, agency_meta: dict) -> list[dict]:
    url_ctype, url_bid = _classify_url_bid(url)
    try:
        raw_recs = parse_pdf_records(data, target_fys=TARGET_FYS)
    except Exception as exc:
        logger.warning(f"PDF parse error {url}: {exc}")
        return []

    records: list[dict] = []
    for rec in raw_recs:
        records.append(_enrich(rec, agency_meta, url, "pdf", url_ctype, url_bid))
    return records


def _parse_html_url(url: str, agency_meta: dict) -> list[dict]:
    """HTMLテーブルを汎用パース（load_gsdf._process_html_tables の汎用版）。"""
    url_ctype, url_bid = _classify_url_bid(url)
    try:
        tables = scrape_html_tables(url)
    except Exception as exc:
        logger.warning(f"HTML scrape error {url}: {exc}")
        return []
    if not tables:
        return []

    records: list[dict] = []
    for tbl in tables:
        if len(tbl) < 2:
            continue
        h_idx = -1
        for i, row in enumerate(tbl[:5]):
            text = " ".join(str(c) for c in row if c)
            if any(k in text for k in ("契約金額", "落札金額")) and \
               any(k in text for k in ("名称", "件名", "業務", "工事", "品名")):
                h_idx = i
                break
        if h_idx < 0:
            continue

        header = tbl[h_idx]
        col_map: dict[str, int] = {}
        for ci, h in enumerate(header):
            hh = str(h).replace("\n", "").replace(" ", "")
            for kw, fld in [
                ("件名",     "contract_name"),
                ("名称",     "contract_name"),
                ("品名",     "contract_name"),
                ("業者",     "vendor_name"),
                ("相手方",   "vendor_name"),
                ("法人番号", "corporate_number"),
                ("契約金額", "contract_amount"),
                ("落札金額", "contract_amount"),
                ("予定価格", "estimated_price"),
                ("落札率",   "award_rate"),
                ("入札方式", "bid_method"),
                ("入札・指名", "bid_method"),
                ("締結日",   "contract_date"),
                ("契約日",   "contract_date"),
                ("締結年月日", "contract_date"),
                ("締結した日", "contract_date"),
            ]:
                if kw in hh and fld not in col_map:
                    col_map[fld] = ci
                    break
        if "contract_amount" not in col_map:
            continue

        for row in tbl[h_idx + 1:]:
            if col_map["contract_amount"] >= len(row):
                continue
            amt = pdf_to_amount(row[col_map["contract_amount"]])
            if not amt or amt < 1000:
                continue
            rec: dict = {"contract_amount": amt}
            for fld, ci in col_map.items():
                if fld == "contract_amount" or ci >= len(row):
                    continue
                val = row[ci]
                if not val:
                    continue
                if fld == "estimated_price":
                    rec[fld] = pdf_to_amount(val)
                elif fld == "award_rate":
                    rec[fld] = pdf_to_rate(val)
                elif fld == "bid_method":
                    rec[fld] = pdf_norm_bid(val)
                elif fld == "contract_date":
                    rec[fld] = pdf_to_date(val)
                elif fld == "corporate_number":
                    cn = re.sub(r"\D", "", str(val))
                    if re.match(r"^\d{13}$", cn):
                        rec[fld] = cn
                elif fld == "vendor_name":
                    lines = [ln.strip() for ln in str(val).split("\n") if ln.strip()]
                    if lines:
                        rec["vendor_name"] = lines[0][:300]
                        if len(lines) > 1:
                            rec["vendor_address"] = " / ".join(lines[1:])[:500]
                else:
                    rec[fld] = str(val).strip()[:500]

            cd_fy = fy_from_date(rec.get("contract_date"))
            if cd_fy is None or cd_fy not in TARGET_FYS:
                continue
            records.append(_enrich(rec, agency_meta, url, "html", url_ctype, url_bid))

    return records


# ── メインコレクター ──────────────────────────────────────────────────────────

def _process_row(row: dict) -> tuple[str, list[dict]]:
    """単一URLを処理してレコードリストを返す（スレッドセーフ）。"""
    url = row["url"]
    is_warp = bool(row.get("flag_warp")) or _is_warp(url)
    url_type = _detect_type(url)
    agency_meta = _build_agency_meta(row["agency_id"], row["agency_name"])

    if url_type == "html":
        # HTMLはfetch不要（scrape_html_tablesが内部でfetchする）
        records = _parse_html_url(url, agency_meta)
        if records:
            logger.info(f"  HTML: {len(records)}件 <- {url[:80]}")
        return url, records

    data = fetch(url, is_warp=is_warp)
    if data is None:
        logger.warning(f"  SKIP(404/error): {url[:80]}")
        return url, []

    if url_type == "excel":
        records = _parse_excel_url(data, url, agency_meta)
    elif url_type == "pdf":
        records = _parse_pdf_url(data, url, agency_meta)
    else:
        logger.warning(f"  SKIP(unknown type): {url[:80]}")
        return url, []

    if records:
        logger.info(f"  {url_type.upper()}: {len(records)}件 <- {url[:80]}")
    return url, records


def _insert_records(records: list[dict], conn: sqlite3.Connection) -> int:
    """レコードをDBに挿入し、実際にINSERTされた件数を返す。"""
    inserted = 0
    for rec in records:
        try:
            conn.execute(INSERT_SQL, rec)
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception as exc:
            logger.debug(f"  INSERT skip: {exc} | {str(rec.get('contract_name') or '')[:40]}")
    conn.commit()
    return inserted


def _load_uncollected(limit: Optional[int] = None) -> list[dict]:
    """url_matrix.db から未収録URLを取得（filled_new優先）。"""
    if not MATRIX_PATH.exists():
        logger.error(f"url_matrix.db が見つかりません: {MATRIX_PATH}")
        return []

    with sqlite3.connect(MATRIX_PATH) as mconn:
        mconn.row_factory = sqlite3.Row
        rows = mconn.execute(
            """
            SELECT agency_id, agency_name, url, status, flag_warp, flag_rolling, month
            FROM url_matrix
            WHERE status IN ('filled', 'filled_new')
              AND url IS NOT NULL
              AND url != ''
            ORDER BY
              CASE status WHEN 'filled_new' THEN 0 ELSE 1 END,
              agency_id,
              month
            """
        ).fetchall()

    # 既収録URLを取得
    with sqlite3.connect(DB_PATH) as dconn:
        existing = {r[0] for r in dconn.execute(
            "SELECT DISTINCT source_url FROM contracts WHERE source_url IS NOT NULL"
        ).fetchall()}

    # 未収録フィルタ
    uncollected = [dict(r) for r in rows if r["url"] not in existing]
    logger.info(f"url_matrix: filled/filled_new合計{len(rows)}件 → 未収録{len(uncollected)}件")

    if limit:
        uncollected = uncollected[:limit]

    return uncollected


def run(
    *,
    limit: Optional[int] = None,
    warp_only: bool = False,
    non_warp_only: bool = False,
    dry_run: bool = False,
) -> None:
    rows = _load_uncollected(limit=limit)
    if not rows:
        logger.info("未収録URLなし。終了。")
        return

    # 分類
    warp_rows     = [r for r in rows if _is_warp(r["url"]) or r.get("flag_warp")]
    non_warp_rows = [r for r in rows if not (_is_warp(r["url"]) or r.get("flag_warp"))]
    logger.info(f"非WARP: {len(non_warp_rows)}件  WARP: {len(warp_rows)}件")

    if warp_only:
        non_warp_rows = []
    if non_warp_only:
        warp_rows = []

    if dry_run:
        logger.info("[DRY-RUN] 実際には書き込みません。")
        for r in (non_warp_rows + warp_rows)[:20]:
            logger.info(f"  [{r['status']}] {_detect_type(r['url']):<7} {r['agency_id']:<25} {r['url'][:70]}")
        return

    total_inserted = 0
    total_processed = 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        db_lock = threading.Lock()

        # ── 非WARP: ThreadPoolExecutor(4) ────────────────────────────────────
        if non_warp_rows:
            logger.info(f"=== 非WARP {len(non_warp_rows)}件 処理開始 (workers={MAX_WORKERS}) ===")
            futures = {}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                for row in non_warp_rows:
                    futures[ex.submit(_process_row, row)] = row["url"]

                for fut in as_completed(futures):
                    url = futures[fut]
                    try:
                        _, records = fut.result()
                    except Exception as exc:
                        logger.error(f"  ERROR {url[:60]}: {exc}")
                        continue
                    total_processed += 1
                    if records:
                        with db_lock:
                            n = _insert_records(records, conn)
                        total_inserted += n

            logger.info(f"非WARP完了: {total_processed}件処理 / {total_inserted}件投入")

        # ── WARP: 順次処理 ────────────────────────────────────────────────────
        if warp_rows:
            logger.info(f"=== WARP {len(warp_rows)}件 順次処理開始 ===")
            warp_inserted = 0
            for i, row in enumerate(warp_rows, 1):
                try:
                    _, records = _process_row(row)
                except Exception as exc:
                    logger.error(f"  ERROR {row['url'][:60]}: {exc}")
                    continue
                total_processed += 1
                if records:
                    n = _insert_records(records, conn)
                    warp_inserted += n
                    total_inserted += n
                if i % 10 == 0:
                    logger.info(f"  WARP進捗: {i}/{len(warp_rows)} ({warp_inserted}件投入済み)")
            logger.info(f"WARP完了: {warp_inserted}件投入")

    # ── 結果サマリー ──────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"処理済URL: {total_processed}件  新規投入: {total_inserted}件")

    with sqlite3.connect(DB_PATH) as conn:
        total, total_oku = conn.execute(
            "SELECT COUNT(*), ROUND(SUM(contract_amount)/1e8, 0) FROM contracts"
        ).fetchone()
        logger.info(f"DB合計: {total:,}件 / {total_oku:,.0f}億円")
        rows_by_cat = conn.execute(
            """
            SELECT agency_category, COUNT(*) AS cnt,
                   ROUND(SUM(contract_amount)/1e8, 0) AS oku
            FROM contracts
            GROUP BY agency_category
            ORDER BY oku DESC
            """
        ).fetchall()
        logger.info("カテゴリ別:")
        for cat, cnt, oku in rows_by_cat:
            logger.info(f"  {cat:<20} {cnt:>8,}件  {oku:>10,.0f}億円")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="url_matrix.db から未収録データを収集してDB投入")
    parser.add_argument("--limit",       type=int, default=None, help="処理URL数の上限（デバッグ用）")
    parser.add_argument("--warp-only",   action="store_true",    help="WARP URLのみ処理")
    parser.add_argument("--non-warp-only", action="store_true",  help="非WARP URLのみ処理")
    parser.add_argument("--dry-run",     action="store_true",    help="DB書き込みなし（確認用）")
    args = parser.parse_args()

    run(
        limit=args.limit,
        warp_only=args.warp_only,
        non_warp_only=args.non_warp_only,
        dry_run=args.dry_run,
    )
