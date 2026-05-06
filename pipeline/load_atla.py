"""ATLA本庁（防衛装備庁本庁）月次/年次Excelの収集・パース・DB投入。

対象FYと取得方法:
  FY2025 (r07): 月次ライブURL（公表され次第・現状ファイルなしも可）
  FY2024 (r06): 月次ライブURL（4種×12ヶ月）
  FY2023 (r05): 月次ライブURL（直接取得→404時のみWARP）
  FY2022 (r04): 単一年次ファイル × 4種、WARP id_経由のみ

URL:
  Live:  https://www.mod.go.jp/atla/souhon/supply/jisseki/rakusatu/kohyo_r{YY}/{YY}_{kind}-{NN}.xlsx
  WARP:  https://warp.ndl.go.jp/{coll}/{ts}id_/https://www.mod.go.jp/atla/souhon/supply/jisseki/rakusatu/xls/04{kind}.xlsx
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from parsers.excel_parser import iter_records, parse_excel_bytes  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "atla"

ATLA_BASE_LIVE = "https://www.mod.go.jp/atla/souhon/supply/jisseki/rakusatu"
ATLA_R04_PATH  = "https://www.mod.go.jp/atla/souhon/supply/jisseki/rakusatu/xls"

# WARP（FY2022 r04 用、複数候補をフォールバックで試す）
# 20230715 スナップは FY2022 1-3月分まで収録（20230301 は4-12月のみ）
WARP_R04_BASES = [
    "https://warp.ndl.go.jp/20230715/20230715000000id_",
    "https://warp.ndl.go.jp/20230301/20230301002334id_",
    "https://warp.ndl.go.jp/20240401/20240401010452id_",
]

# r05/r06 までの命名: 4種（基準以上/未満で分割）
FILE_KINDS_LEGACY: list[tuple[str, str]] = [
    ("kyoso_kijunijo",    "競争（基準以上）"),
    ("kyoso_kijunmiman",  "競争（基準未満）"),
    ("zuikei_kijunijo",   "随意契約（基準以上）"),
    ("zuikei_kijunmiman", "随意契約（基準未満）"),
]

# r07 以降の命名: 基準分割なし、特定契約（防衛生産基盤強化法）追加
FILE_KINDS_NEW: list[tuple[str, str]] = [
    ("kyoso",   "競争"),
    ("zuikei",  "随意契約"),
    ("tokutei", "特定（防衛生産基盤強化法）"),
]


def _file_kinds_for_fy(fy: int) -> list[tuple[str, str]]:
    return FILE_KINDS_NEW if fy >= 2025 else FILE_KINDS_LEGACY


# 日本の会計年度: 4月〜翌3月
FY_MONTHS = list(range(4, 13)) + list(range(1, 4))

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


def _live_url(reiwa: int, kind: str, month: int) -> str:
    rr = f"{reiwa:02d}"
    mm = f"{month:02d}"
    return f"{ATLA_BASE_LIVE}/kohyo_r{rr}/{rr}_{kind}-{mm}.xlsx"


def _warp_r04_urls(filename: str) -> list[str]:
    return [f"{base}/{ATLA_R04_PATH}/{filename}" for base in WARP_R04_BASES]


def _enrich_record(rec: dict, *, kind: str, kind_label: str, source_url: str) -> dict:
    rec.update({
        "agency_id": "atla",
        "agency_name": "防衛装備庁本庁",
        "agency_category": "防衛装備庁",
        "contract_type": kind_label,
        "source_url": source_url,
        "source_type": "excel",
    })
    if not rec.get("bid_method"):
        if kind.startswith("zuikei"):
            rec["bid_method"] = "随意契約"
        elif kind.startswith("kyoso"):
            rec["bid_method"] = "一般競争入札"
        elif kind.startswith("tokutei"):
            # 特定調達契約: 防衛生産基盤強化法による随意契約の一種
            rec["bid_method"] = "随意契約"
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def _parse_one(data: bytes, *, target_fy: int, kind: str, kind_label: str,
               source_url: str) -> list[dict]:
    try:
        df, header_idx, col_map = parse_excel_bytes(data)
    except Exception as e:
        logger.warning(f"Excel解析失敗: {source_url} - {e}")
        return []
    if df.empty or not col_map:
        logger.debug(f"  empty/no-headers: {source_url}")
        return []
    return [
        _enrich_record(rec, kind=kind, kind_label=kind_label, source_url=source_url)
        for rec in iter_records(df, header_idx, col_map, target_fy=target_fy)
    ]


def collect_live_monthly(fiscal_year: int) -> tuple[list[dict], dict]:
    reiwa = fiscal_year - 2018
    save_dir = RAW_DIR / f"r{reiwa:02d}"
    save_dir.mkdir(parents=True, exist_ok=True)

    stats = {"files_tried": 0, "files_ok": 0, "files_404": 0, "rows_parsed": 0}
    records: list[dict] = []

    file_kinds = _file_kinds_for_fy(fiscal_year)
    for kind, kind_label in file_kinds:
        for month in FY_MONTHS:
            url = _live_url(reiwa, kind, month)
            local = save_dir / Path(url).name
            stats["files_tried"] += 1

            data = fetch(url, save_to=local)
            if data is None:
                stats["files_404"] += 1
                continue
            stats["files_ok"] += 1

            recs = _parse_one(data, target_fy=fiscal_year, kind=kind,
                              kind_label=kind_label, source_url=url)
            records.extend(recs)
            stats["rows_parsed"] += len(recs)
            logger.info(f"  {Path(url).name}: {len(recs)}件")

    return records, stats


def collect_warp_r04(fiscal_year: int = 2022) -> tuple[list[dict], dict]:
    """FY2022（r04）はWARP経由で年次単一ファイル × 4種を取得。"""
    save_dir = RAW_DIR / "r04"
    save_dir.mkdir(parents=True, exist_ok=True)

    stats = {"files_tried": 0, "files_ok": 0, "files_404": 0, "rows_parsed": 0}
    records: list[dict] = []

    # FY2022 (r04) は legacy 命名規則のみ
    for kind, kind_label in FILE_KINDS_LEGACY:
        # ファイル名: 04kyoso_kijunijo.xlsx 等
        filename = f"04{kind}.xlsx"
        local = save_dir / filename
        stats["files_tried"] += 1

        data = None
        used_url = ""
        for url in _warp_r04_urls(filename):
            data = fetch(url, save_to=local, is_warp=True)
            if data:
                used_url = url
                break
        if data is None:
            stats["files_404"] += 1
            logger.warning(f"  WARP取得失敗: {filename}")
            continue
        stats["files_ok"] += 1

        recs = _parse_one(data, target_fy=fiscal_year, kind=kind,
                          kind_label=kind_label, source_url=used_url)
        records.extend(recs)
        stats["rows_parsed"] += len(recs)
        logger.info(f"  {filename}: {len(recs)}件")

    return records, stats


def collect_and_load(fiscal_year: int, db_path: Path = DB_PATH, *, dry_run: bool = False) -> dict:
    if fiscal_year == 2022:
        records, stats = collect_warp_r04(fiscal_year)
    else:
        records, stats = collect_live_monthly(fiscal_year)

    logger.info(
        f"FY{fiscal_year} ATLA: tried={stats['files_tried']} ok={stats['files_ok']} "
        f"404={stats['files_404']} parsed={stats['rows_parsed']}"
    )

    if dry_run:
        return {"records": records, **stats}

    inserted = 0
    duplicates = 0
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for rec in records:
            cur.execute(INSERT_SQL, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()
    stats["inserted"] = inserted
    stats["duplicates"] = duplicates
    logger.info(f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件")
    return stats


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--fy", type=int, nargs="+", default=[2024])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    for fy in args.fy:
        collect_and_load(fy, dry_run=args.dry_run)
