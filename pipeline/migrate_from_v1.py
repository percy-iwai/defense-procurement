"""初代 defense_procurement DB の差分を元URLから再収集して 2nd DB に投入。

処理:
1. 1st-gen DB から (agency_id, agency_name, agency_category, source_url, source_type) を取得
2. 2nd-gen DB の source_url set と比較して差分 URL を抽出
3. 各 URL をダウンロード → source_type に応じてパース
4. agency_id マッピングを適用して 2nd DB に INSERT OR IGNORE

注意: 初代 DB はソース発見のみ。データは必ず元 URL から再取得。
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from collectors.index_scraper import scrape_html_tables  # noqa: E402
from parsers.excel_parser import iter_records as excel_iter  # noqa: E402
from parsers.excel_parser import parse_excel_bytes  # noqa: E402
from parsers.pdf_table import fy_from_date, parse_pdf_records  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

# 初代 DB のデフォルトパス（コマンドライン引数で上書き可能）
V1_DB_DEFAULT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement\data\db\procurement.db")

TARGET_FYS = {2022, 2023, 2024, 2025}

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
    "quantity", "unit_measure", "contract_type",
]

# 初代 → 2nd の agency_id マッピング
# 独自機関はそのまま保持（2nd DB に存在しないため新規作成）
AGENCY_REMAP: dict[str, tuple[str, str, str]] = {
    "msdf_yokosuka": ("msdf_yokosuka", "横須賀地方総監部",   "海上自衛隊"),
    "msdf_kure":     ("msdf_kure",     "呉地方総監部",       "海上自衛隊"),
    "msdf_sasebo":   ("msdf_sasebo",   "佐世保地方総監部",   "海上自衛隊"),
    "msdf_ominato":  ("msdf_ominato",  "大湊地方総監部",     "海上自衛隊"),
    "msdf_maizuru":  ("msdf_maizuru",  "舞鶴地方総監部",     "海上自衛隊"),
    "gsdf_hokubu":   ("gsdf_hokubu",   "北部方面総監部",     "陸上自衛隊"),
    "gsdf_jujyo":    ("gsdf_jujyo",    "陸上自衛隊（什器）", "陸上自衛隊"),
    "asdf_ashiya":   ("asdf_ashiya",   "芦屋基地",           "航空自衛隊"),
    "igo":           ("igo",           "防衛装備庁（旧）",   "防衛装備庁"),
    "nda":           ("nda",           "防衛大学校",         "防衛大学校"),
}


def _enrich(rec: dict, *, agency_id: str, agency_name: str, agency_category: str,
            source_url: str, source_type: str) -> dict:
    rec.update({
        "agency_id": agency_id,
        "agency_name": agency_name,
        "agency_category": agency_category,
        "source_url": source_url,
        "source_type": source_type,
    })
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def _is_xls(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".xls")


def _fetch_and_parse(url: str, source_type: str, aid: str,
                     aname: str, acat: str) -> list[dict]:
    """URL をフェッチしてパース。source_type で分岐。"""
    is_warp = "warp.ndl.go.jp" in url or "web.archive.org" in url
    if not is_warp:
        time.sleep(0.8)  # mod.go.jp レート制限
    data = fetch(url, is_warp=is_warp, use_cache=True, timeout=30)
    if not data:
        return []

    stype_lo = (source_type or "").lower()
    records: list[dict] = []

    try:
        if "pdf" in stype_lo:
            for rec in parse_pdf_records(data, target_fys=TARGET_FYS):
                cd_fy = fy_from_date(rec.get("contract_date"))
                if cd_fy is None or cd_fy not in TARGET_FYS:
                    continue
                rec["fiscal_year"] = cd_fy
                records.append(_enrich(rec, agency_id=aid, agency_name=aname,
                                       agency_category=acat, source_url=url,
                                       source_type="pdf"))

        elif "excel" in stype_lo or url.lower().endswith((".xlsx", ".xls")):
            is_xls = _is_xls(url)
            df, header_idx, col_map = parse_excel_bytes(data, is_xls=is_xls)
            if df.empty or not col_map:
                return []
            seen: set = set()
            for fy in TARGET_FYS:
                for rec in excel_iter(df, header_idx, col_map, target_fy=fy):
                    key = (rec.get("contract_name"), rec.get("vendor_name"),
                           rec.get("contract_amount"))
                    if key in seen:
                        continue
                    seen.add(key)
                    records.append(_enrich(rec, agency_id=aid, agency_name=aname,
                                           agency_category=acat, source_url=url,
                                           source_type="excel"))

        elif "html" in stype_lo:
            tables = scrape_html_tables(url)
            for tbl in tables:
                if len(tbl) < 2:
                    continue
                hdr = tbl[0]
                col_map_h: dict[str, int] = {}
                for i, h in enumerate(hdr):
                    hh = str(h).replace(" ", "")
                    if any(k in hh for k in ("件名", "業務名", "工事名", "品名")):
                        col_map_h.setdefault("contract_name", i)
                    if "業者" in hh or "相手方" in hh:
                        col_map_h.setdefault("vendor_name", i)
                    if any(k in hh for k in ("契約金額", "落札金額")):
                        col_map_h.setdefault("contract_amount", i)
                    if any(k in hh for k in ("締結日", "契約日")):
                        col_map_h.setdefault("contract_date", i)
                if "contract_amount" not in col_map_h:
                    continue
                from parsers.pdf_table import _to_amount, _to_date_str
                for row in tbl[1:]:
                    n = col_map_h["contract_amount"]
                    if n >= len(row):
                        continue
                    amt = _to_amount(row[n])
                    if not amt or amt < 1000:
                        continue
                    rec: dict = {"contract_amount": amt}
                    for fld, idx_key in [("contract_name", "contract_name"),
                                          ("vendor_name", "vendor_name"),
                                          ("contract_date", "contract_date")]:
                        if idx_key in col_map_h and col_map_h[idx_key] < len(row):
                            v = str(row[col_map_h[idx_key]]).strip()
                            if fld == "contract_date":
                                rec[fld] = _to_date_str(v)
                            else:
                                rec[fld] = v[:500] or None
                    cd_fy = fy_from_date(rec.get("contract_date"))
                    if cd_fy is None or cd_fy not in TARGET_FYS:
                        continue
                    rec["fiscal_year"] = cd_fy
                    records.append(_enrich(rec, agency_id=aid, agency_name=aname,
                                           agency_category=acat, source_url=url,
                                           source_type="html"))
    except Exception as e:
        logger.warning(f"  parse error: {url} ({stype_lo}) - {e}")

    return records


def migrate(v1_db: Path = V1_DB_DEFAULT, *,
            filter_agency: list[str] | None = None,
            dry_run: bool = False) -> dict:
    if not v1_db.exists():
        logger.error(f"1st-gen DB が見つかりません: {v1_db}")
        return {}

    # 1. 1st-gen DB から対象レコード収集
    with sqlite3.connect(v1_db) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT agency_id, agency_name, agency_category, source_url, source_type "
            "FROM contracts WHERE source_url IS NOT NULL AND source_url != ''"
        )
        v1_rows = cur.fetchall()

    # 2. 2nd-gen DB の既存 source_url を取得
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT source_url FROM contracts "
                    "WHERE source_url IS NOT NULL AND source_url != ''")
        existing_urls: set[str] = {r[0] for r in cur.fetchall()}

    # 3. 差分フィルタ
    diff_rows = [
        (aid, aname, acat, url, stype)
        for aid, aname, acat, url, stype in v1_rows
        if url not in existing_urls
        and (filter_agency is None or aid in filter_agency)
        and aid in AGENCY_REMAP  # マッピング定義済み機関のみ
    ]

    logger.info(f"1st-gen 差分 URL: {len(diff_rows)} (既存 {len(existing_urls)} URL を除外)")

    # 機関別サマリー
    from collections import Counter
    by_agency: Counter = Counter(r[0] for r in diff_rows)
    for aid, cnt in by_agency.most_common():
        logger.info(f"  {aid}: {cnt} URLs")

    if dry_run:
        return {"diff_urls": len(diff_rows), "by_agency": dict(by_agency)}

    # 4. 各 URL を fetch → parse → insert
    inserted = duplicates = skipped = errors = 0
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for orig_aid, _, _, url, stype in diff_rows:
            new_aid, aname, acat = AGENCY_REMAP[orig_aid]
            recs = _fetch_and_parse(url, stype, new_aid, aname, acat)
            if not recs:
                errors += 1
                continue
            for rec in recs:
                if not rec.get("fiscal_year"):
                    skipped += 1
                    continue
                cur.execute(INSERT_SQL, rec)
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1
            if recs:
                logger.info(f"  [{orig_aid}] {url.rsplit('/', 1)[-1][:40]}: {len(recs)}件")
        conn.commit()

    logger.info(f"migrate_from_v1: 新規 {inserted} / 重複 {duplicates} / FYなし {skipped} / 取得失敗 {errors}")
    return {"inserted": inserted, "duplicates": duplicates, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--v1-db", default=str(V1_DB_DEFAULT))
    p.add_argument("--agency", nargs="*", help=f"対象機関: {list(AGENCY_REMAP.keys())}")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    result = migrate(Path(args.v1_db), filter_agency=args.agency, dry_run=args.dry_run)
    print(result)
