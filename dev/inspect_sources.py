"""Inspect existing pillar_mapping_sources entries."""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
db = ROOT / "data" / "db" / "defense_pillar.db"
conn = sqlite3.connect(db)

for stype in ("bukai", "hakusho"):
    print(f"\n=== {stype} sample (first 10) ===")
    rows = conn.execute("""
        SELECT id, source_type, fiscal_year, pillar_id, pillar_name, jigyou_name, source_url, source_file
        FROM pillar_mapping_sources WHERE source_type=? LIMIT 10
    """, (stype,)).fetchall()
    for r in rows:
        print(f"  id={r[0]} FY={r[2]} P{r[3]} {r[4][:20]:20s} | {r[5]!r}")
        print(f"       url={r[6]}")
        print(f"       file={r[7]}")

    count = conn.execute("SELECT COUNT(*) FROM pillar_mapping_sources WHERE source_type=?", (stype,)).fetchone()[0]
    print(f"  Total: {count}")

    fy_dist = conn.execute("""
        SELECT fiscal_year, COUNT(*) FROM pillar_mapping_sources
        WHERE source_type=? GROUP BY fiscal_year ORDER BY fiscal_year
    """, (stype,)).fetchall()
    print(f"  FY dist: {fy_dist}")

conn.close()
