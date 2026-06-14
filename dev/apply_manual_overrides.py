"""
A-2a: fallback_50oku_apply 12件を contract_requesting_org に再適用
kit/exports/manual_overrides_natural.json の fallback_50oku_apply セクションを読み込み、
自然キー（agency_id, fiscal_year, contract_name, vendor_name, contract_amount）で
contracts と突合し、contract_requesting_org に INSERT OR REPLACE する。
"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db" / "procurement.db"
OVERRIDES_JSON = Path(__file__).parent.parent / "kit" / "exports" / "manual_overrides_natural.json"


def run() -> None:
    data = json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))
    entries = data.get("fallback_50oku_apply", [])
    print(f"fallback_50oku_apply エントリ数: {len(entries)}件")

    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    applied = 0
    not_found = 0

    for e in entries:
        agency_id = e["agency_id"]
        fiscal_year = e["fiscal_year"]
        contract_name = e["contract_name"]
        vendor_name = e["vendor_name"]
        contract_amount = e["contract_amount"]
        requesting_org = e["requesting_org"]
        match_source = e["match_source"]
        confidence = e["confidence"]

        # 自然キーで contract_id を取得
        cur.execute("""
            SELECT id FROM contracts
            WHERE agency_id = ?
              AND fiscal_year = ?
              AND contract_name = ?
              AND vendor_name = ?
              AND contract_amount = ?
            LIMIT 1
        """, (agency_id, fiscal_year, contract_name, vendor_name, contract_amount))
        row = cur.fetchone()
        if row is None:
            print(f"  [NOT FOUND] FY{fiscal_year} {contract_name[:40]} / {vendor_name[:20]}")
            not_found += 1
            continue

        contract_id = row[0]
        cur.execute("""
            INSERT OR REPLACE INTO contract_requesting_org
              (contract_id, requesting_org, match_source, confidence)
            VALUES (?, ?, ?, ?)
        """, (contract_id, requesting_org, match_source, confidence))
        applied += 1
        print(f"  [OK] #{contract_id} FY{fiscal_year} → {requesting_org} ({match_source})")

    conn.commit()
    conn.close()
    print(f"\n適用: {applied}件 / 未発見: {not_found}件")


if __name__ == "__main__":
    run()
