"""調達予定品目表 xlsx（r07/r08）のパース → choutatsuyotei テーブル投入。

使い方:
  python dev/load_choutatsuyotei_xlsx.py --fy 2025 2026
  python dev/load_choutatsuyotei_xlsx.py --fy 2026 --dry-run
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
PDF_BASE = PROJECT_ROOT / "data" / "choutatsuyotei"

FY_TO_FILE = {
    2025: PDF_BASE / "r07_choutatsuyotei.xlsx",
    2026: PDF_BASE / "r08_choutatsuyotei.xlsx",
}

REQ_ORG_NORMALIZE: dict[str, str] = {
    "陸自": "GSDF",
    "海自": "MSDF",
    "空自": "ASDF",
    "医大": "NDMC",
    "防医大": "NDMC",
    "防大": "NDA",
    "装備庁": "ATLA",
    "統幕": "JS",
    "情本": "DIH",
    "内局": "NAIKYOKU",
    "監本": "KANSATSU",
    "防研": "NIDS",
    "防衛局": "RDB",
}

_PUNCT_RE = re.compile(r"[\s　，、,．。・／/＿_\-－‐ー（）()「」『』【】［］\[\]]+")


def normalize_item_name(s) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = _PUNCT_RE.sub("", s)
    return s.strip().lower()


def parse_xlsx(path: Path, fiscal_year: int) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    records = []
    source_row = 0

    for row in ws.iter_rows(values_only=True):
        # ヘッダー行・タイトル行スキップ（col0が要求元コードでなければスキップ）
        req_raw = str(row[0]).strip() if row[0] is not None else ""
        if req_raw not in REQ_ORG_NORMALIZE:
            continue

        item_name = str(row[1]).strip() if row[1] is not None else ""
        spec_class = str(row[2]).strip() if row[2] is not None else None
        qty_val = int(row[3]) if row[3] is not None and str(row[3]).isdigit() else None
        req_month = int(row[4]) if row[4] is not None else None
        contract_month_raw = int(row[5]) if row[5] is not None else None
        tantou = str(row[7]).strip() if len(row) > 7 and row[7] is not None else None

        # 契約月を会計年度月に変換（4-12=そのまま、1-3=+12）
        if contract_month_raw is not None:
            contract_month = contract_month_raw if contract_month_raw >= 4 else contract_month_raw + 12
        else:
            contract_month = None

        source_row += 1
        records.append({
            "fiscal_year": fiscal_year,
            "source_file": path.name,
            "source_row": source_row,
            "requesting_org_raw": req_raw,
            "requesting_org": REQ_ORG_NORMALIZE[req_raw],
            "item_name": item_name,
            "item_name_norm": normalize_item_name(item_name),
            "spec_class": spec_class,
            "qty": qty_val,
            "request_month": req_month,
            "contract_month": contract_month,
            "delivery_date": None,
            "tantou_office": tantou,
        })

    wb.close()
    return records


def load_into_db(records: list[dict], db_path: Path) -> dict:
    sql = """
    INSERT OR IGNORE INTO choutatsuyotei
      (fiscal_year, source_file, source_row, requesting_org_raw, requesting_org,
       item_name, item_name_norm, spec_class, qty,
       request_month, contract_month, delivery_date, tantou_office)
    VALUES
      (:fiscal_year, :source_file, :source_row, :requesting_org_raw, :requesting_org,
       :item_name, :item_name_norm, :spec_class, :qty,
       :request_month, :contract_month, :delivery_date, :tantou_office)
    """
    inserted = duplicates = 0
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        for rec in records:
            cur.execute(sql, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        con.commit()
    return {"inserted": inserted, "duplicates": duplicates}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fy", nargs="+", type=int, default=[2026], choices=[2025, 2026])
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    db_path = Path(args.db)
    for fy in sorted(set(args.fy)):
        xlsx_path = FY_TO_FILE[fy]
        if not xlsx_path.exists():
            print(f"[FY{fy}] ファイルが見つからない: {xlsx_path}")
            continue

        records = parse_xlsx(xlsx_path, fy)
        from collections import Counter
        dist = Counter(r["requesting_org"] for r in records)
        print(f"[FY{fy}] {len(records)}件  {dict(dist.most_common())}")

        if args.dry_run:
            print("  [dry-run] DB書き込みスキップ")
            for r in records[:3]:
                print(f"  sample: [{r['requesting_org']}] {r['item_name'][:50]}")
        else:
            stats = load_into_db(records, db_path)
            print(f"  inserted={stats['inserted']} duplicates={stats['duplicates']}")


if __name__ == "__main__":
    main()
