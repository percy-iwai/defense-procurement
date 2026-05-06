"""3rd-gen defense_procurement DB の差分を元URLから再収集して 2nd DB に投入。

処理:
1. 3rd-gen DB から (agency_id, agency_name, agency_category, source_url, source_type) を取得
2. 2nd-gen DB の source_url set と比較して差分 URL を抽出
3. 各 URL をダウンロード → source_type に応じてパース
4. 2nd DB に INSERT OR IGNORE (同一スキーマなので agency_id マッピング不要)

注意: 3rd-gen DB はソース発見のみ。データは必ず元 URL から再取得。
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
V3_DB_DEFAULT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_3rd\data\db\procurement.db")

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


def _is_xls(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".xls")


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


def _fetch_and_parse(url: str, source_type: str, aid: str,
                     aname: str, acat: str) -> list[dict]:
    is_warp = "warp.ndl.go.jp" in url or "web.archive.org" in url
    if not is_warp:
        time.sleep(0.8)
    data = fetch(url, is_warp=is_warp, use_cache=True, timeout=30)
    if not data:
        return []

    stype_lo = (source_type or "").lower()
    records: list[dict] = []

    try:
        if "pdf" in stype_lo or url.lower().endswith(".pdf"):
            for rec in parse_pdf_records(data, target_fys=TARGET_FYS):
                cd_fy = fy_from_date(rec.get("contract_date"))
                if cd_fy is None or cd_fy not in TARGET_FYS:
                    continue
                rec["fiscal_year"] = cd_fy
                records.append(_enrich(rec, agency_id=aid, agency_name=aname,
                                       agency_category=acat, source_url=url,
                                       source_type="pdf"))

        elif "excel" in stype_lo or url.lower().endswith((".xlsx", ".xls")):
            df, header_idx, col_map = parse_excel_bytes(data, is_xls=_is_xls(url))
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
                    for fld, key in [("contract_name", "contract_name"),
                                      ("vendor_name", "vendor_name"),
                                      ("contract_date", "contract_date")]:
                        if key in col_map_h and col_map_h[key] < len(row):
                            v = str(row[col_map_h[key]]).strip()
                            rec[fld] = _to_date_str(v) if fld == "contract_date" else (v[:500] or None)
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


def migrate(v3_db: Path = V3_DB_DEFAULT, *,
            filter_agency: list[str] | None = None,
            dry_run: bool = False) -> dict:
    if not v3_db.exists():
        logger.error(f"3rd-gen DB が見つかりません: {v3_db}")
        return {}

    # 1. 3rd-gen DB から対象レコード収集
    with sqlite3.connect(v3_db) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT agency_id, agency_name, agency_category, source_url, source_type "
            "FROM contracts WHERE source_url IS NOT NULL AND source_url != ''"
        )
        v3_rows = cur.fetchall()

    # 2. 2nd-gen DB の既存 source_url を取得
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT source_url FROM contracts "
                    "WHERE source_url IS NOT NULL AND source_url != ''")
        existing_urls: set[str] = {r[0] for r in cur.fetchall()}

    # 3. 差分フィルタ
    diff_rows = [
        (aid, aname, acat, url, stype)
        for aid, aname, acat, url, stype in v3_rows
        if url not in existing_urls
        and (filter_agency is None or aid in filter_agency)
    ]

    logger.info(f"3rd-gen 差分 URL: {len(diff_rows)} (既存 {len(existing_urls)} URL を除外)")

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
        for aid, aname, acat, url, stype in diff_rows:
            recs = _fetch_and_parse(url, stype, aid, aname, acat)
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
                logger.info(f"  [{aid}] {url.rsplit('/', 1)[-1][:40]}: {len(recs)}件")
        conn.commit()

    logger.info(f"migrate_from_v3: 新規 {inserted} / 重複 {duplicates} / FYなし {skipped} / 取得失敗 {errors}")
    return {"inserted": inserted, "duplicates": duplicates, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--v3-db", default=str(V3_DB_DEFAULT))
    p.add_argument("--agency", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    result = migrate(Path(args.v3_db), filter_agency=args.agency, dry_run=args.dry_run)
    print(result)
