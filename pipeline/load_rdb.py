"""地方防衛局 (RDB) のExcel/PDF/HTMLデータをcollect→parse→DB投入。

戦略:
- index_urls から拡張子 (.pdf/.xlsx/.xls) のリンクを抽出 → 各ファイルをフェッチ→パース
- 補完用に url_patterns があれば iter で 404 スキップ
- html_table_pages は HTML テーブルを直接スクレイピング（東海支局向け）
- 全ての records は contract_date FY ガード付きで TARGET_FYS 内のものを採用
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from collectors.index_scraper import scrape_file_links, scrape_html_tables  # noqa: E402
from parsers.excel_parser import iter_records as excel_iter_records  # noqa: E402
from parsers.excel_parser import parse_excel_bytes  # noqa: E402
from parsers.pdf_table import fy_from_date, parse_pdf_records  # noqa: E402
from parsers.pdf_table import _normalize_bid as pdf_norm_bid  # noqa: E402
from parsers.pdf_table import _to_amount as pdf_to_amount  # noqa: E402
from parsers.pdf_table import _to_date_str as pdf_to_date  # noqa: E402
from parsers.pdf_table import _to_rate as pdf_to_rate  # noqa: E402
from pipeline.rdb_config import RDB_AGENCIES  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "rdb"

INSERT_SQL = """
INSERT OR IGNORE INTO contracts (
    agency_id, agency_name, agency_category,
    fiscal_year, contract_type,
    contract_name, vendor_name, vendor_address, corporate_number,
    contract_amount, estimated_price, award_rate,
    bid_method, zuii_reason, contract_date, contract_officer,
    quantity, unit_measure,
    source_url, source_type
) VALUES (
    :agency_id, :agency_name, :agency_category,
    :fiscal_year, :contract_type,
    :contract_name, :vendor_name, :vendor_address, :corporate_number,
    :contract_amount, :estimated_price, :award_rate,
    :bid_method, :zuii_reason, :contract_date, :contract_officer,
    :quantity, :unit_measure,
    :source_url, :source_type
)
"""

REQUIRED_KEYS = [
    "contract_name", "vendor_name", "vendor_address", "corporate_number",
    "contract_amount", "estimated_price", "award_rate",
    "bid_method", "zuii_reason", "contract_date", "contract_officer",
    "quantity", "unit_measure",
]

TARGET_FYS = {2022, 2023, 2024, 2025}


def _classify_url(url: str) -> tuple[str, str]:
    """URLから (contract_type, bid_method) のヒントを推定。"""
    u = url.lower()
    if any(t in u for t in ("zuikei", "zui", "z-b", "z-k", "_zuikei", "/4z", "kz", "negotiated")):
        return ("随意契約", "随意契約")
    if any(t in u for t in ("kyousou", "kyoso", "competitive", "n-b", "n-k", "kk")):
        return ("一般競争", "一般競争入札")
    return ("調達適正化", None)


# ※ 方針: fiscal_year は contract_date からのみ算出する（URLパターン推定は不採用）。
#    contract_date が無い行は fiscal_year=None でスキップする。


def _is_xls(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".xls")


def _enrich_record(rec: dict, *, agency: dict, source_url: str,
                   source_type: str, fallback_fy: int | None) -> dict:
    rec.update({
        "agency_id": agency["agency_id"],
        "agency_name": agency["agency_name"],
        "agency_category": "地方防衛局",
        "source_url": source_url,
        "source_type": source_type,
    })
    # fiscal_year: contract_date から算出済みのものを優先、無ければ呼び出し側のヒント（東海HTML用）
    if not rec.get("fiscal_year") and fallback_fy:
        rec["fiscal_year"] = fallback_fy
    # それでも未設定なら None のまま → INSERT時にスキップ
    if "contract_type" not in rec or not rec.get("contract_type"):
        ctype, bid_default = _classify_url(source_url)
        rec["contract_type"] = ctype
        if not rec.get("bid_method") and bid_default:
            rec["bid_method"] = bid_default
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def _process_excel(data: bytes, *, url: str, agency: dict) -> list[dict]:
    """Excel 1ファイルを4つの target_fy 全部でパースし、行ごとに正しい FY に振り分け。"""
    is_xls = _is_xls(url)
    try:
        df, header_idx, col_map = parse_excel_bytes(data, is_xls=is_xls)
    except Exception as e:
        logger.warning(f"Excel解析エラー: {url} - {e}")
        return []
    if df.empty or not col_map:
        return []
    if "contract_amount" not in col_map and "vendor_name" not in col_map:
        return []

    out: list[dict] = []
    # excel_parser.iter_records は target_fy 単位で FY ガードする
    # → 4 FY 分回し、contract_date FY と一致するものだけ採用
    seen_keys = set()
    for fy in TARGET_FYS:
        for rec in excel_iter_records(df, header_idx, col_map, target_fy=fy):
            key = (rec.get("contract_name"), rec.get("vendor_name"), rec.get("contract_amount"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rec = _enrich_record(rec, agency=agency, source_url=url,
                                 source_type="excel", fallback_fy=None)
            out.append(rec)
    return out


def _process_pdf(data: bytes, *, url: str, agency: dict) -> list[dict]:
    out: list[dict] = []
    for rec in parse_pdf_records(data, target_fys=TARGET_FYS):
        rec = _enrich_record(rec, agency=agency, source_url=url,
                             source_type="pdf", fallback_fy=None)
        out.append(rec)
    return out


def _process_html_table_page(html_url: str, agency: dict, fy: int,
                             contract_type: str) -> list[dict]:
    """東海支局向け: HTMLテーブルを直接抽出（一覧テーブル形式）。"""
    tables = scrape_html_tables(html_url)
    if not tables:
        return []

    out: list[dict] = []
    for tbl in tables:
        if len(tbl) < 2:
            continue
        header = tbl[0]
        col_map: dict[str, int] = {}
        for i, h in enumerate(header):
            hh = str(h).replace("\n", "").replace(" ", "")
            if any(k in hh for k in ("工事名", "業務名", "件名", "名称")) and "contract_name" not in col_map:
                col_map["contract_name"] = i
            if "業者" in hh and "vendor_name" not in col_map:
                col_map["vendor_name"] = i
            if "法人番号" in hh and "corporate_number" not in col_map:
                col_map["corporate_number"] = i
            if any(k in hh for k in ("落札金額", "契約金額")) and "contract_amount" not in col_map:
                col_map["contract_amount"] = i
            if "予定価格" in hh and "estimated_price" not in col_map:
                col_map["estimated_price"] = i
            if "落札率" in hh and "award_rate" not in col_map:
                col_map["award_rate"] = i
            if any(k in hh for k in ("入札方式", "入札・指名")) and "bid_method" not in col_map:
                col_map["bid_method"] = i
            if any(k in hh for k in ("締結日", "契約日")) and "contract_date" not in col_map:
                col_map["contract_date"] = i
        if "contract_amount" not in col_map:
            continue

        for row in tbl[1:]:
            amt = pdf_to_amount(row[col_map["contract_amount"]]) if col_map["contract_amount"] < len(row) else None
            if not amt or amt < 1000:
                continue

            rec: dict = {"contract_amount": amt}
            if "contract_name" in col_map and col_map["contract_name"] < len(row):
                rec["contract_name"] = str(row[col_map["contract_name"]])[:500].strip() or None
            if "vendor_name" in col_map and col_map["vendor_name"] < len(row):
                v = str(row[col_map["vendor_name"]]).strip()
                if v:
                    rec["vendor_name"] = v[:300]
            if "corporate_number" in col_map and col_map["corporate_number"] < len(row):
                cn = re.sub(r"\D", "", str(row[col_map["corporate_number"]]))
                if re.match(r"^\d{13}$", cn):
                    rec["corporate_number"] = cn
            if "estimated_price" in col_map and col_map["estimated_price"] < len(row):
                rec["estimated_price"] = pdf_to_amount(row[col_map["estimated_price"]])
            if "award_rate" in col_map and col_map["award_rate"] < len(row):
                rec["award_rate"] = pdf_to_rate(row[col_map["award_rate"]])
            if "bid_method" in col_map and col_map["bid_method"] < len(row):
                rec["bid_method"] = pdf_norm_bid(row[col_map["bid_method"]])
            if "contract_date" in col_map and col_map["contract_date"] < len(row):
                rec["contract_date"] = pdf_to_date(row[col_map["contract_date"]])

            cd_fy = fy_from_date(rec.get("contract_date"))
            if cd_fy is not None and cd_fy not in TARGET_FYS:
                continue
            rec["fiscal_year"] = cd_fy or fy
            rec["contract_type"] = contract_type
            rec = _enrich_record(rec, agency=agency, source_url=html_url,
                                 source_type="html", fallback_fy=fy)
            out.append(rec)
    return out


def collect_agency(agency: dict) -> tuple[list[dict], dict]:
    aid = agency["agency_id"]
    save_dir = RAW_DIR / aid
    save_dir.mkdir(parents=True, exist_ok=True)
    stats = {"sources_tried": 0, "files_found": 0, "files_ok": 0,
             "rows_parsed": 0}
    records: list[dict] = []

    # 1) HTMLテーブル直接（東海支局のみ）
    for entry in agency.get("html_table_pages", []) or []:
        url, fy, ctype = entry
        stats["sources_tried"] += 1
        try:
            recs = _process_html_table_page(url, agency, fy, ctype)
        except Exception as e:
            logger.warning(f"HTMLテーブル解析エラー: {url} - {e}")
            recs = []
        if recs:
            stats["files_ok"] += 1
        records.extend(recs)
        stats["rows_parsed"] += len(recs)
        logger.info(f"  [html] {url}: {len(recs)}件")

    # 2) Index ページからファイルリンク収集
    file_urls: set[str] = set()
    for index_url in agency.get("index_urls", []) or []:
        is_warp = "warp.ndl.go.jp" in index_url
        ext = agency.get("extensions", (".pdf", ".xlsx", ".xls"))
        if not ext:
            continue
        try:
            links = scrape_file_links(index_url, extensions=ext, is_warp=is_warp)
        except Exception as e:
            logger.warning(f"index取得エラー: {index_url} - {e}")
            links = []
        logger.info(f"  index {index_url} → {len(links)} links")
        for u, _ in links:
            file_urls.add(u)

    # 3) URL パターン補完（404は無視）
    for u in agency.get("url_patterns", []) or []:
        file_urls.add(u)

    stats["files_found"] = len(file_urls)

    # 4) 各ファイルをダウンロード→パース
    for url in sorted(file_urls):
        stats["sources_tried"] += 1
        is_warp = "warp.ndl.go.jp" in url or "web.archive.org" in url
        try:
            data = fetch(url, is_warp=is_warp)
        except Exception as e:
            logger.warning(f"fetch失敗: {url} - {e}")
            continue
        if data is None:
            continue
        stats["files_ok"] += 1

        u_lo = url.lower().split("?", 1)[0]
        try:
            if u_lo.endswith((".xlsx", ".xls")):
                recs = _process_excel(data, url=url, agency=agency)
            elif u_lo.endswith(".pdf"):
                recs = _process_pdf(data, url=url, agency=agency)
            else:
                recs = []
        except Exception as e:
            logger.warning(f"処理エラー: {url} - {e}")
            recs = []

        records.extend(recs)
        stats["rows_parsed"] += len(recs)
        if recs:
            logger.info(f"  [{Path(url).name}] {len(recs)}件")

    return records, stats


def collect_and_load(*, db_path: Path = DB_PATH, dry_run: bool = False,
                     filter_agency: list[str] | None = None) -> dict:
    agencies = RDB_AGENCIES
    if filter_agency:
        agencies = [a for a in agencies if a["agency_id"] in filter_agency]

    overall = {"agencies": 0, "files_ok": 0, "rows_parsed": 0,
               "inserted": 0, "duplicates": 0, "per_agency": {}}
    all_records: list[dict] = []

    for agency in agencies:
        logger.info(f"=== {agency['agency_id']} ({agency['agency_name']}) ===")
        records, stats = collect_agency(agency)
        all_records.extend(records)
        overall["per_agency"][agency["agency_id"]] = stats
        overall["files_ok"] += stats["files_ok"]
        overall["rows_parsed"] += stats["rows_parsed"]
        overall["agencies"] += 1

    if dry_run:
        return {"records": all_records, **overall}

    inserted = 0
    duplicates = 0
    skipped_no_fy = 0
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for rec in all_records:
            if not rec.get("fiscal_year"):
                skipped_no_fy += 1
                continue
            cur.execute(INSERT_SQL, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()
    overall["skipped_no_fy"] = skipped_no_fy
    overall["inserted"] = inserted
    overall["duplicates"] = duplicates
    logger.info(f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件 / 機関 {overall['agencies']}")
    return overall


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--agency", nargs="*", help="特定の rdb_id のみ実行")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    result = collect_and_load(dry_run=args.dry_run, filter_agency=args.agency)
    print("\n=== 機関別 ===")
    for aid, s in result["per_agency"].items():
        print(f"  {aid:<18} files_ok={s['files_ok']:>3}/{s['files_found']:<3}  rows={s['rows_parsed']:>5}  tried={s['sources_tried']}")
