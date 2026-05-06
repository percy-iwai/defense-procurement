"""防衛省内局・情報本部・統合幕僚監部・防衛医科大学校・防衛研究所・防衛大学校の収集・DB投入。

機関:
  naikyoku_kaikei: 大臣官房会計課   — Excel月次 (buppin/kouji × k/z)
  dih:             情報本部         — PDF月次 R{ry}.{mm}-{kind}.pdf
  js:              統合幕僚監部     — PDF月次 {kind}{YYMM}.pdf
  ndmc:            防衛医科大学校   — PDF (ndmc.ac.jp インデックス)
  nids:            防衛研究所       — PDF月次 {k|z}{YYYYMM}.pdf (nids.mod.go.jp)
  nda:             防衛大学校       — PDF (bidding_result/ インデックス)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from collectors.index_scraper import scrape_file_links  # noqa: E402
from parsers.excel_parser import fy_from_date, iter_records, parse_excel_bytes  # noqa: E402
from parsers.pdf_table import parse_pdf_records  # noqa: E402
from pipeline.load_gsdf import INSERT_SQL, REQUIRED_KEYS, TARGET_FYS  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

# 既知バグ対策: naikyoku_kaikeiに単価×数量パースエラーで約19兆円になる件がある
MAX_AMOUNT = 1_000_000_000_000  # 1兆円超はNULL化


def _enrich(rec: dict, **meta) -> dict:
    rec.update(meta)
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    if rec.get("contract_amount") and rec["contract_amount"] > MAX_AMOUNT:
        rec["contract_amount"] = None
    return rec


# ── naikyoku_kaikei ──────────────────────────────────────────────────────────
_NAIKYOKU_BASE = "https://www.mod.go.jp/j/budget/chotatsu/naikyoku/keiyaku"
_NAIKYOKU_KINDS = {
    "buppin_k": ("物品役務", "一般競争入札"),
    "buppin_z": ("物品役務", "随意契約"),
    "kouji_k":  ("工事",    "一般競争入札"),
    "kouji_z":  ("工事",    "随意契約"),
}


def _naikyoku_url_list() -> list[tuple[str, int, str, str]]:
    """(url, fy, contract_type, bid_method) のリスト。"""
    out = []
    for fy in sorted(TARGET_FYS):
        for mm in list(range(4, 13)) + list(range(1, 4)):
            for kind, (ctype, bid) in _NAIKYOKU_KINDS.items():
                url = f"{_NAIKYOKU_BASE}/fy{fy}/{mm:02d}/{mm:02d}_{kind}.xlsx"
                out.append((url, fy, ctype, bid))
    return out


def collect_naikyoku() -> tuple[list[dict], dict]:
    stats = {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
    records: list[dict] = []
    for url, fy, ctype, bid in _naikyoku_url_list():
        stats["files_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            df, header_idx, col_map = parse_excel_bytes(data)
        except Exception as e:
            logger.warning(f"Excel解析失敗: {url} - {e}")
            continue
        if df.empty or not col_map:
            continue
        cnt = 0
        for rec in iter_records(df, header_idx, col_map, target_fy=fy):
            # ダミー行スキップ（契約金額NULLかつ件名/業者が「0」のプレースホルダー）
            if rec.get("contract_name") == "0一式" and str(rec.get("vendor_name", "")).strip() in ("", "0"):
                continue
            # 工事系2行構造の continuation row スキップ（工期/住所が誤マップされた行）
            # contract_date もNULL のため、本来のレコードではない
            if not rec.get("contract_date") and not rec.get("contract_amount"):
                continue
            rec = _enrich(
                rec,
                agency_id="naikyoku_kaikei",
                agency_name="大臣官房会計課",
                agency_category="防衛省内局",
                fiscal_year=fy,
                contract_type=rec.get("contract_type") or ctype,
                bid_method=rec.get("bid_method") or bid,
                source_url=url,
                source_type="excel",
            )
            records.append(rec)
            cnt += 1
        if cnt:
            logger.info(f"  {Path(url).name}: {cnt}件")
        stats["rows_parsed"] += cnt
    return records, stats


# ── dih ──────────────────────────────────────────────────────────────────────
_DIH_BASE = "https://www.mod.go.jp/dih"
# WARP スナップショット (2025-01-05): R5(FY2023)全月・R6(FY2024)ほぼ全月 確認済み
_DIH_WARP_SNAP = "https://warp.ndl.go.jp/20250105/20250105000000id_"
# 調達情報は supply/ 配下の年度別ページ: public-r{ry}.html にPDFリンクあり
# R{ry}.{mm}-{kyousou|zuikei}.pdf 命名規則
_DIH_SUPPLY_PAGES = [
    f"{_DIH_BASE}/supply/public-r{ry}.html" for ry in range(4, 9)
] + [
    # NDL WARP 2025-08-02 スナップ (FY2024 完了版: R7.3まで含む可能性)
    "https://warp.ndl.go.jp/20250802/20250802124433id_/https://www.mod.go.jp/dih/supply/public-r6.html",
]
# Wayback / NDL WARP スナップショット: R7.1-3 (FY2024完了月)
# R7.1-2: Wayback 2025-04-21に確認
# R7.3: NDL WARP 2025-08-09 スナップ (coll=20250809, ts=20250802034432)
_DIH_WAYBACK_URLS = [
    "https://web.archive.org/web/20250421161149id_/https://www.mod.go.jp/dih/R7.1-kyousou.pdf",
    "https://web.archive.org/web/20250421125242id_/https://www.mod.go.jp/dih/R7.1-zuikei.pdf",
    "https://web.archive.org/web/20250421133926id_/https://www.mod.go.jp/dih/R7.2-kyousou.pdf",
    "https://web.archive.org/web/20250421165435id_/https://www.mod.go.jp/dih/R7.2-zuikei.pdf",
    # R7.3 (2025年3月 = FY2024末): NDL WARP
    "https://warp.ndl.go.jp/20250809/20250802034432id_/https://www.mod.go.jp/dih/R7.3-kyousou.pdf",
    "https://warp.ndl.go.jp/20250809/20250802034432id_/https://www.mod.go.jp/dih/R7.3-zuikei.pdf",
]


def _dih_pdf_urls() -> set[str]:
    """supply/public-r{ry}.html からPDFリンクを収集 + URLパターンで補完。"""
    found: set[str] = set()
    for page_url in _DIH_SUPPLY_PAGES:
        links = scrape_file_links(page_url, extensions=(".pdf",))
        for url, _ in links:
            found.add(url)

    # R5(FY2023)・R6(FY2024) → WARP スナップ経由（live URL は 404）
    for ry in range(5, 7):
        for mm in range(1, 13):
            for kind in ("zuikei", "kyousou"):
                found.add(f"{_DIH_WARP_SNAP}/{_DIH_BASE}/R{ry}.{mm}-{kind}.pdf")

    # 直接アクセス可能な年度（R4=FY2022 は 404 だが試行、R7/R8 は有効）
    for ry in (4, 7, 8):
        for mm in range(1, 13):
            for kind in ("zuikei", "kyousou"):
                found.add(f"{_DIH_BASE}/R{ry}.{mm}-{kind}.pdf")

    # R7.1-2 (FY2024完了月): Wayback Machine スナップ（live削除済み、R7.3は未アーカイブ）
    found.update(_DIH_WAYBACK_URLS)
    return found


def collect_dih() -> tuple[list[dict], dict]:
    stats = {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
    records: list[dict] = []
    for url in sorted(_dih_pdf_urls()):
        stats["files_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            recs_raw = list(parse_pdf_records(data, target_fys=TARGET_FYS))
        except Exception as e:
            logger.warning(f"PDF解析エラー: {url} - {e}")
            continue
        for rec in recs_raw:
            # manifest注記: contract_nameは500→2000文字に拡張
            if rec.get("contract_name"):
                rec["contract_name"] = str(rec["contract_name"])[:2000]
            rec = _enrich(
                rec,
                agency_id="dih",
                agency_name="情報本部",
                agency_category="情報本部",
                source_url=url,
                source_type="pdf",
            )
            records.append(rec)
        if recs_raw:
            logger.info(f"  {Path(url).name}: {len(recs_raw)}件")
        stats["rows_parsed"] += len(recs_raw)
    return records, stats


# ── js ────────────────────────────────────────────────────────────────────────
_JS_CONTRACT_BASE = "https://www.mod.go.jp/js/pdf/supply/contract"


def _js_url_list() -> list[tuple[str, int]]:
    """(url, fy) のリスト。{kind}{YYMM}.pdf 命名規則 (YYMM = calendar year下2桁 + month)。"""
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for fy in sorted(TARGET_FYS):
        for mm in list(range(4, 13)) + list(range(1, 4)):
            cy = fy if mm >= 4 else fy + 1
            yymm = f"{cy % 100:02d}{mm:02d}"
            for kind in ("zui", "kyo", "kyoso", "rakusatu"):
                url = f"{_JS_CONTRACT_BASE}/{kind}{yymm}.pdf"
                if url not in seen:
                    seen.add(url)
                    out.append((url, fy))
    return out


def collect_js() -> tuple[list[dict], dict]:
    stats = {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
    records: list[dict] = []
    found_urls: set[str] = set()

    # インデックスページからPDFリンクを収集
    for index_url in ["https://www.mod.go.jp/js/", f"{_JS_CONTRACT_BASE}/"]:
        try:
            links = scrape_file_links(
                index_url, extensions=(".pdf",),
                include_pattern=r"supply/contract",
            )
        except Exception as e:
            logger.warning(f"JS index取得エラー: {index_url} - {e}")
            links = []
        for url, _ in links:
            if url in found_urls:
                continue
            found_urls.add(url)
            stats["files_tried"] += 1
            data = fetch(url)
            if data is None:
                continue
            stats["files_ok"] += 1
            try:
                recs_raw = list(parse_pdf_records(data, target_fys=TARGET_FYS))
            except Exception as e:
                logger.warning(f"JS PDF解析エラー: {url} - {e}")
                continue
            for rec in recs_raw:
                records.append(_enrich(
                    rec,
                    agency_id="js",
                    agency_name="統合幕僚監部",
                    agency_category="統合幕僚監部",
                    source_url=url,
                    source_type="pdf",
                ))
            if recs_raw:
                logger.info(f"  [{Path(url).name}] {len(recs_raw)}件")
            stats["rows_parsed"] += len(recs_raw)

    # URLパターンでの補完（インデックスで見つからなかった分）
    for url, fy in _js_url_list():
        if url in found_urls:
            continue
        found_urls.add(url)
        stats["files_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            recs_raw = list(parse_pdf_records(data, target_fys={fy}))
        except Exception as e:
            logger.warning(f"JS PDF解析エラー: {url} - {e}")
            continue
        for rec in recs_raw:
            records.append(_enrich(
                rec,
                agency_id="js",
                agency_name="統合幕僚監部",
                agency_category="統合幕僚監部",
                source_url=url,
                source_type="pdf",
            ))
        if recs_raw:
            logger.info(f"  [{Path(url).name}] {len(recs_raw)}件")
        stats["rows_parsed"] += len(recs_raw)

    return records, stats


# ── ndmc ──────────────────────────────────────────────────────────────────────
# URLパターン: /wp-content/uploads/{YYYY}/{MM:02d}/koukyou{RY:02d}{MM:02d}-{3|4}.pdf
# 3=競争, 4=随意 (manifest注記: koukyou{RYYMM}-{3,4}.pdf)
_NDMC_BASE = "https://www.ndmc.ac.jp/wp-content/uploads"


def _ndmc_url_list() -> list[str]:
    out = []
    for fy in sorted(TARGET_FYS):
        ry = fy - 2018
        for mm in list(range(4, 13)) + list(range(1, 4)):
            cy = fy if mm >= 4 else fy + 1
            for kind in (3, 4):  # 3=競争, 4=随意
                url = f"{_NDMC_BASE}/{cy}/{mm:02d}/koukyou{ry:02d}{mm:02d}-{kind}.pdf"
                out.append(url)
    return out


def collect_ndmc() -> tuple[list[dict], dict]:
    stats = {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
    records: list[dict] = []

    file_urls: set[str] = set(_ndmc_url_list())

    for url in sorted(file_urls):
        stats["files_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            recs_raw = list(parse_pdf_records(data, target_fys=TARGET_FYS))
        except Exception as e:
            logger.warning(f"NDMC PDF解析エラー: {url} - {e}")
            continue
        for rec in recs_raw:
            records.append(_enrich(
                rec,
                agency_id="ndmc",
                agency_name="防衛医科大学校",
                agency_category="防衛医科大学校",
                source_url=url,
                source_type="pdf",
            ))
        if recs_raw:
            logger.info(f"  [{Path(url).name}] {len(recs_raw)}件")
        stats["rows_parsed"] += len(recs_raw)

    return records, stats


# ── nids ──────────────────────────────────────────────────────────────────────
# URL: https://www.nids.mod.go.jp/procurement/keiyaku/pdf/{k|z}{YYYYMM}.pdf
# インデックス: https://www.nids.mod.go.jp/procurement/ にFY2022〜現在のリンク掲載
_NIDS_INDEX = "https://www.nids.mod.go.jp/procurement/"


def _nids_url_list() -> list[str]:
    """FY2022-2025 の全月分 URL パターン補完。"""
    base = "https://www.nids.mod.go.jp/procurement/keiyaku/pdf"
    out = []
    for fy in sorted(TARGET_FYS):
        for mm in list(range(4, 13)) + list(range(1, 4)):
            cy = fy if mm >= 4 else fy + 1
            yyyymm = f"{cy}{mm:02d}"
            for kind in ("k", "z"):
                out.append(f"{base}/{kind}{yyyymm}.pdf")
    return out


def collect_nids() -> tuple[list[dict], dict]:
    stats = {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
    records: list[dict] = []

    file_urls: set[str] = set()
    # インデックスページからリンク収集（より正確）
    links = scrape_file_links(_NIDS_INDEX, extensions=(".pdf",))
    for url, _ in links:
        if "keiyaku/pdf/" in url:
            file_urls.add(url)
    # パターン補完
    for url in _nids_url_list():
        file_urls.add(url)

    for url in sorted(file_urls):
        stats["files_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            recs_raw = list(parse_pdf_records(data, target_fys=TARGET_FYS))
        except Exception as e:
            logger.warning(f"NIDS PDF解析エラー: {url} - {e}")
            continue
        for rec in recs_raw:
            records.append(_enrich(
                rec,
                agency_id="nids",
                agency_name="防衛研究所",
                agency_category="防衛研究所",
                source_url=url,
                source_type="pdf",
            ))
        if recs_raw:
            logger.info(f"  [{Path(url).name}] {len(recs_raw)}件")
        stats["rows_parsed"] += len(recs_raw)
    return records, stats


# ── nda ───────────────────────────────────────────────────────────────────────
# インデックス: https://www.mod.go.jp/nda/procurement/bidding_result/
# 標準形式: /files/kouji/kouzi_nyuusatsu_kekkaR{RY}{NN}.pdf
_NDA_INDEX = "https://www.mod.go.jp/nda/procurement/bidding_result/"


def collect_nda() -> tuple[list[dict], dict]:
    stats = {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
    records: list[dict] = []

    links = scrape_file_links(_NDA_INDEX, extensions=(".pdf",))
    for url, _ in links:
        stats["files_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            recs_raw = list(parse_pdf_records(data, target_fys=TARGET_FYS))
        except Exception as e:
            logger.warning(f"NDA PDF解析エラー: {url} - {e}")
            continue
        for rec in recs_raw:
            records.append(_enrich(
                rec,
                agency_id="nda",
                agency_name="防衛大学校",
                agency_category="防衛大学校",
                source_url=url,
                source_type="pdf",
            ))
        if recs_raw:
            logger.info(f"  [{Path(url).name}] {len(recs_raw)}件")
        stats["rows_parsed"] += len(recs_raw)
    return records, stats


# ── エントリポイント ───────────────────────────────────────────────────────────
MISC_COLLECTORS = {
    "naikyoku_kaikei": collect_naikyoku,
    "dih":             collect_dih,
    "js":              collect_js,
    "ndmc":            collect_ndmc,
    "nids":            collect_nids,
    "nda":             collect_nda,
}

MISC_NAMES = {
    "naikyoku_kaikei": "大臣官房会計課",
    "dih":             "情報本部",
    "js":              "統合幕僚監部",
    "ndmc":            "防衛医科大学校",
    "nids":            "防衛研究所",
    "nda":             "防衛大学校",
}


def collect_and_load(*, db_path: Path = DB_PATH, dry_run: bool = False,
                     filter_agency: list[str] | None = None) -> dict:
    targets = list(MISC_COLLECTORS.keys())
    if filter_agency:
        targets = [a for a in targets if a in filter_agency]

    overall = {"agencies": 0, "files_ok": 0, "rows_parsed": 0,
               "inserted": 0, "duplicates": 0, "skipped_no_fy": 0,
               "per_agency": {}}
    all_records: list[dict] = []

    for aid in targets:
        logger.info(f"=== {aid} ({MISC_NAMES[aid]}) ===")
        try:
            records, stats = MISC_COLLECTORS[aid]()
        except Exception as e:
            logger.error(f"{aid} 収集失敗: {e}")
            records, stats = [], {"files_ok": 0, "files_tried": 0, "rows_parsed": 0}
        all_records.extend(records)
        overall["per_agency"][aid] = stats
        overall["files_ok"] += stats["files_ok"]
        overall["rows_parsed"] += stats["rows_parsed"]
        overall["agencies"] += 1

    if dry_run:
        return {"records": all_records, **overall}

    inserted = duplicates = skipped = 0
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for rec in all_records:
            if not rec.get("fiscal_year"):
                skipped += 1
                continue
            cur.execute(INSERT_SQL, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()
    overall["inserted"] = inserted
    overall["duplicates"] = duplicates
    overall["skipped_no_fy"] = skipped
    logger.info(f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件 / スキップ {skipped}件")
    return overall


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--agency", nargs="*",
                   help=f"対象機関: {', '.join(MISC_COLLECTORS.keys())}")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    result = collect_and_load(dry_run=args.dry_run, filter_agency=args.agency)
    print("\n=== 機関別 ===")
    for aid, s in result["per_agency"].items():
        print(f"  {aid:<22} files_ok={s['files_ok']:>4}  rows={s['rows_parsed']:>5}")
