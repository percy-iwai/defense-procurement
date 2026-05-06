"""海上自衛隊 (MSDF) 各機関のExcel/XLSデータをcollect→parse→DB投入。

特徴:
- 1つの累積ExcelからFY混在を contract_date で振り分け（FY汚染ガード）
- 同一レコードはUNIQUE制約 (agency_id, fy, name, vendor, amount) で重複除去
- ライブ + WARP + Wayback を順次試行、取得できたものを全部パース
- .xlsx (openpyxl) と .xls (xlrd) を自動判別
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
from parsers.excel_parser import iter_records, parse_excel_bytes, fy_from_date  # noqa: E402
from parsers.pdf_table import parse_pdf_records  # noqa: E402
from pipeline.msdf_config import all_agencies, all_sources  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "msdf"

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

# 対象FY（contract_date から算出した fiscal_year がここに含まれるレコードのみ採用）
TARGET_FYS = {2022, 2023, 2024, 2025}


def _classify_kind(filename: str) -> tuple[str, str]:
    """ファイル名から契約種別と入札方式デフォルトを判定。"""
    name = filename.upper()
    is_zuikei = "ZUIKEI" in name
    is_kouji = name.endswith("_K.XLSX") or name.endswith("_K.XLS")
    if is_zuikei and is_kouji:
        return "随意契約（工事）", "随意契約"
    if is_zuikei:
        return "随意契約（物品）", "随意契約"
    if is_kouji:
        return "一般競争（工事）", "一般競争入札"
    return "一般競争（物品）", "一般競争入札"


def _enrich_record(rec: dict, *, agency: dict, kind_label: str,
                   bid_default: str, source_url: str, source_type: str) -> dict:
    rec.update({
        "agency_id": agency["agency_id"],
        "agency_name": agency["agency_name"],
        "agency_category": "海上自衛隊",
        "contract_type": kind_label,
        "source_url": source_url,
        "source_type": source_type,  # 'excel' / 'excel_warp' / 'excel_wayback'
    })
    if not rec.get("bid_method"):
        rec["bid_method"] = bid_default
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def _parse_for_all_fys(data: bytes, *, is_xls: bool, agency: dict,
                       source_url: str, source_type: str) -> list[dict]:
    """1つのExcelをパースし、contract_date FY が TARGET_FYS のものを全部返す。

    1つのファイルが複数FYのデータを含む（ローリングウィンドウ）場合がある。
    """
    try:
        df, header_idx, col_map = parse_excel_bytes(data, is_xls=is_xls)
    except Exception as e:
        logger.warning(f"Excel解析失敗: {source_url} - {e}")
        return []
    if df.empty or not col_map:
        logger.debug(f"  empty/no-headers: {source_url}")
        return []
    if "contract_amount" not in col_map and "vendor_name" not in col_map:
        logger.debug(f"  insufficient columns: {source_url}")
        return []

    # ファイル名から種別判定
    fname = source_url.rsplit("/", 1)[-1].split("?")[0]
    kind_label, bid_default = _classify_kind(fname)

    out: list[dict] = []
    # iter_records は target_fy 単位なので、ここでは target_fy=None 相当の処理を自前で行う
    # → 各行を一旦 fy_guard なしで取り出し、contract_date から fy を算出
    data_start = header_idx + 1
    if data_start < len(df):
        first_text = " ".join(str(v) for v in df.iloc[data_start] if str(v) != "nan")
        if any(k in first_text for k in ("応札者", "備考", "者数")) and "件名" not in first_text:
            data_start += 1

    import pandas as pd
    import re as _re
    from parsers.excel_parser import (
        normalize_bid_method, to_date_str
    )

    for i in range(data_start, len(df)):
        row = df.iloc[i]
        if all(pd.isna(v) or str(v).strip() in ("", "nan") for v in row):
            continue

        rec: dict = {}

        if "vendor_name" in col_map:
            v = row.iloc[col_map["vendor_name"]]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                lines = [l.strip() for l in str(v).split("\n") if l.strip()]
                if lines:
                    rec["vendor_name"] = lines[0][:300]
                    if len(lines) > 1:
                        rec["vendor_address"] = " / ".join(lines[1:])[:500]

        if "contract_name" in col_map:
            v = row.iloc[col_map["contract_name"]]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                s = str(v).split("\n")[0].strip()
                if s and s != "nan":
                    rec["contract_name"] = s[:500]

        # 金額
        from parsers.excel_parser import _to_int_amount  # type: ignore
        if "contract_amount" in col_map:
            rec["contract_amount"] = _to_int_amount(row.iloc[col_map["contract_amount"]])
        if "estimated_price" in col_map:
            rec["estimated_price"] = _to_int_amount(row.iloc[col_map["estimated_price"]])

        if not rec.get("contract_amount"):
            for v in row:
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                m = _re.search(r"予定調達総額[^\d]*([\d,]+)\s*円", str(v))
                if m:
                    try:
                        rec["contract_amount"] = int(m.group(1).replace(",", ""))
                    except ValueError:
                        pass
                    break

        if "award_rate" in col_map:
            v = row.iloc[col_map["award_rate"]]
            try:
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    r = float(str(v).replace("%", "").strip())
                    rec["award_rate"] = round(r * 100, 2) if r <= 1.0 else round(r, 2)
            except (ValueError, TypeError):
                pass

        if "bid_method" in col_map:
            v = row.iloc[col_map["bid_method"]]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                rec["bid_method"] = normalize_bid_method(str(v))

        if "contract_date" in col_map:
            rec["contract_date"] = to_date_str(row.iloc[col_map["contract_date"]])

        for f in ("corporate_number", "quantity", "unit_measure",
                  "zuii_reason", "contract_officer"):
            if f in col_map:
                v = row.iloc[col_map[f]]
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    s = str(v).strip()
                    if s and s != "nan":
                        rec[f] = s[:500]

        # スキップ判定
        if not rec.get("vendor_name") and not rec.get("contract_amount"):
            continue
        if not rec.get("contract_name") and not rec.get("contract_amount"):
            continue

        # FY算出（contract_date 必須・なければスキップ）
        cd_fy = fy_from_date(rec.get("contract_date"))
        if cd_fy is None or cd_fy not in TARGET_FYS:
            continue
        rec["fiscal_year"] = cd_fy

        rec = _enrich_record(rec, agency=agency, kind_label=kind_label,
                             bid_default=bid_default, source_url=source_url,
                             source_type=source_type)
        out.append(rec)

    return out


def _process_pdf_msdf(data: bytes, *, url: str, agency: dict,
                      source_type: str) -> list[dict]:
    """MSDF向けPDF処理: parse_pdf_records → contract_date FYで TARGET_FYS フィルタ。"""
    fname = url.rsplit("/", 1)[-1].split("?")[0]
    kind_label, bid_default = _classify_kind(fname)
    out: list[dict] = []
    try:
        recs = list(parse_pdf_records(data, target_fys=TARGET_FYS))
    except Exception as e:
        logger.warning(f"PDF解析失敗: {url} - {e}")
        return []
    for rec in recs:
        cd_fy = fy_from_date(rec.get("contract_date"))
        if cd_fy is None or cd_fy not in TARGET_FYS:
            continue
        rec["fiscal_year"] = cd_fy
        rec = _enrich_record(rec, agency=agency, kind_label=kind_label,
                             bid_default=bid_default, source_url=url,
                             source_type=source_type)
        out.append(rec)
    return out


def collect_agency(agency: dict) -> tuple[list[dict], dict]:
    save_dir = RAW_DIR / agency["agency_id"]
    save_dir.mkdir(parents=True, exist_ok=True)

    stats = {"sources_tried": 0, "sources_ok": 0, "rows_parsed": 0}
    records: list[dict] = []

    for url, kind in all_sources(agency):
        stats["sources_tried"] += 1
        is_warp_or_wb = kind in ("warp", "wayback")
        # ローカルファイル名（重複防止）
        # WARP/Wayback URLは長いのでhash化はhttp_clientの_cacheに任せ、save_toは指定しない
        local = save_dir / Path(url.split("?", 1)[0]).name if kind == "live" else None

        data = fetch(url, save_to=local, is_warp=is_warp_or_wb)
        if data is None:
            logger.debug(f"  miss [{kind}] {url}")
            continue
        stats["sources_ok"] += 1

        is_xls = url.lower().split("?")[0].endswith(".xls")
        source_type = "excel" if kind == "live" else f"excel_{kind}"
        recs = _parse_for_all_fys(
            data, is_xls=is_xls, agency=agency,
            source_url=url, source_type=source_type,
        )
        records.extend(recs)
        stats["rows_parsed"] += len(recs)
        logger.info(f"  [{kind}] {Path(url).name}: {len(recs)}件 ({agency['agency_id']})")

    # 新規: index_urls 経由でHTMLからPDF/Excelリンクを辿る
    seen_urls: set[str] = {u for u, _ in all_sources(agency)}
    for index_url in agency.get("index_urls", []) or []:
        try:
            file_links = scrape_file_links(index_url, extensions=(".pdf", ".xlsx", ".xls"))
        except Exception as e:
            logger.warning(f"  index scrape error: {index_url} - {e}")
            continue
        if not file_links:
            continue
        logger.info(f"  index {index_url}: {len(file_links)} links")
        for item in file_links:
            url = item[0] if isinstance(item, tuple) else item
            if url in seen_urls:
                continue
            seen_urls.add(url)
            stats["sources_tried"] += 1
            data = fetch(url)
            if data is None:
                continue
            stats["sources_ok"] += 1
            url_lower = url.lower().split("?", 1)[0]
            if url_lower.endswith(".pdf"):
                recs = _process_pdf_msdf(data, url=url, agency=agency, source_type="pdf_index")
            else:
                is_xls = url_lower.endswith(".xls")
                recs = _parse_for_all_fys(
                    data, is_xls=is_xls, agency=agency,
                    source_url=url, source_type="excel_index",
                )
            records.extend(recs)
            stats["rows_parsed"] += len(recs)
            if recs:
                logger.info(f"  [index] {Path(url).name}: {len(recs)}件 ({agency['agency_id']})")

    return records, stats


def collect_and_load(*, db_path: Path = DB_PATH, dry_run: bool = False,
                     filter_agency: list[str] | None = None) -> dict:
    overall = {"agencies": 0, "sources_ok": 0, "rows_parsed": 0,
               "inserted": 0, "duplicates": 0, "per_agency": {}}

    agencies = all_agencies()
    if filter_agency:
        agencies = [a for a in agencies if a["agency_id"] in filter_agency]

    all_records: list[dict] = []
    for agency in agencies:
        logger.info(f"=== {agency['agency_id']} ({agency['agency_name']}) ===")
        records, stats = collect_agency(agency)
        all_records.extend(records)
        overall["per_agency"][agency["agency_id"]] = stats
        overall["sources_ok"] += stats["sources_ok"]
        overall["rows_parsed"] += stats["rows_parsed"]
        overall["agencies"] += 1

    if dry_run:
        return {"records": all_records, **overall}

    inserted = 0
    duplicates = 0
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for rec in all_records:
            cur.execute(INSERT_SQL, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()
    overall["inserted"] = inserted
    overall["duplicates"] = duplicates
    logger.info(f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件 / 機関数 {overall['agencies']}")
    return overall


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--agency", nargs="*", help="特定の agency_id のみ実行")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    result = collect_and_load(dry_run=args.dry_run, filter_agency=args.agency)
    print("\n=== 機関別 ===")
    for aid, s in result["per_agency"].items():
        print(f"  {aid:<12} sources_ok={s['sources_ok']:>2}/{s['sources_tried']:<2}  rows={s['rows_parsed']}")
