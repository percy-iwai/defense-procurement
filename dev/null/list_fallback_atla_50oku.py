"""List fallback_atla contracts >= 50億円 — UTF-8 output."""
import sqlite3, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
con = sqlite3.connect("data/db/procurement.db")
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute(
    """
    SELECT c.id, c.fiscal_year, c.agency_id, c.contract_name, c.vendor_name,
           c.contract_amount, c.bid_method, c.contract_date, c.source_url
    FROM contracts c
    JOIN contract_requesting_org r ON c.id = r.contract_id
    WHERE r.match_source = 'fallback_atla'
      AND c.contract_amount >= 5000000000
    ORDER BY c.contract_amount DESC
    """
)
rows = [dict(r) for r in cur.fetchall()]
out_path = "dev/null/fallback_atla_50oku.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print(f"wrote {out_path}: {len(rows)} rows")
for r in rows:
    print(f"#{r['id']:>6}  FY{r['fiscal_year']}  {r['contract_amount']:>14,}  {r['agency_id']}")
    print(f"   契約名: {r['contract_name']}")
    print(f"   業者:   {r['vendor_name']}")
    print(f"   方式:   {r['bid_method']}  日付: {r['contract_date']}")
    print(f"   URL:    {r['source_url']}")
    print()
