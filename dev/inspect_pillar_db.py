"""Inspect defense_pillar.db - P4/P7 remaining records + master table."""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
db = ROOT / "data" / "db" / "defense_pillar.db"
conn = sqlite3.connect(db)

print("=== defense_pillar_master ===")
master = conn.execute("""
    SELECT pillar_id, level, name, parent_id, display_order, notes
    FROM defense_pillar_master ORDER BY display_order
""").fetchall()
for r in master:
    indent = "  " if r[1] == 2 else ""
    print(f"  {indent}[{r[0]:>3}] L{r[1]} {r[2]:40s} parent={r[3]} order={r[4]}")

print("\n=== P4 (pillar_id=4) records with ID ===")
p4 = conn.execute("""
    SELECT id, pillar_id, jigyou_name, fiscal_year, source_file
    FROM defense_pillar_jigyou
    WHERE pillar_id = 4
    ORDER BY fiscal_year, jigyou_name
""").fetchall()
print(f"Total P4: {len(p4)}")
for r in p4:
    print(f"  id={r[0]:>4} FY{r[3]} {r[2]!r}")

print("\n=== P7 (pillar_id=7) records with ID ===")
p7 = conn.execute("""
    SELECT id, pillar_id, jigyou_name, fiscal_year, source_file
    FROM defense_pillar_jigyou
    WHERE pillar_id = 7
    ORDER BY fiscal_year, jigyou_name
""").fetchall()
print(f"Total P7: {len(p7)}")
for r in p7:
    print(f"  id={r[0]:>4} FY{r[3]} {r[2]!r}")

conn.close()
