"""Apply matched ref_url_official values to procurement.db."""
import sys, io, json, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open("temp/mod_equipment/_matches.json", "r", encoding="utf-8") as f:
    matches = json.load(f)

DB = "C:/Users/Percy Iwai/Documents/defense_procurement_2nd/data/db/procurement.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

updated = 0
for m in matches:
    if not m["ref_url_official"]:
        continue
    cur.execute(
        "UPDATE equipment_master SET ref_url_official = ? WHERE equipment_id = ?",
        (m["ref_url_official"], m["equipment_id"]),
    )
    updated += cur.rowcount

conn.commit()

# Verify
n_total = cur.execute("SELECT COUNT(*) FROM equipment_master").fetchone()[0]
n_official = cur.execute("SELECT COUNT(*) FROM equipment_master WHERE ref_url_official IS NOT NULL").fetchone()[0]
print(f"Updated: {updated} rows")
print(f"Total: {n_total}, with ref_url_official: {n_official}")

# Per-branch breakdown
for row in cur.execute("""
    SELECT branch,
           COUNT(*) AS n,
           SUM(CASE WHEN ref_url_official IS NOT NULL THEN 1 ELSE 0 END) AS n_official,
           SUM(CASE WHEN ref_url_wikipedia IS NOT NULL THEN 1 ELSE 0 END) AS n_wiki,
           SUM(CASE WHEN ref_url_hakusho IS NOT NULL THEN 1 ELSE 0 END) AS n_hakusho
    FROM equipment_master GROUP BY branch ORDER BY branch
""").fetchall():
    print(row)

conn.close()
