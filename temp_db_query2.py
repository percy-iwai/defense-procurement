import sqlite3

db_path = "data/db/procurement.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 80)
print("QUERY 1: Top 30 agency_id values by contract count")
print("=" * 80)
cursor.execute("SELECT DISTINCT agency_id, COUNT(*) as cnt FROM contracts GROUP BY agency_id ORDER BY cnt DESC LIMIT 30;")
for agency_id, cnt in cursor.fetchall():
    print(f"{agency_id}: {cnt}")

print("\n" + "=" * 80)
print("QUERY 2: All agency_id values containing 'atla'")
print("=" * 80)
cursor.execute("SELECT DISTINCT agency_id FROM contracts WHERE agency_id LIKE '%atla%' ORDER BY agency_id;")
atla_ids = cursor.fetchall()
for (agency_id,) in atla_ids:
    print(f"  {agency_id}")

if not atla_ids:
    print("  (none found)")

print("\n" + "=" * 80)
print("QUERY 3: Contract count distribution for ATLA agencies")
print("=" * 80)
cursor.execute("SELECT DISTINCT agency_id, COUNT(*) as cnt FROM contracts WHERE agency_id LIKE '%atla%' GROUP BY agency_id ORDER BY cnt DESC;")
for agency_id, cnt in cursor.fetchall():
    print(f"{agency_id}: {cnt}")

print("\n" + "=" * 80)
print("QUERY 4: Contract amount distribution for ATLA under 100M yen")
print("=" * 80)
cursor.execute("SELECT COUNT(*), MIN(contract_amount), MAX(contract_amount) FROM contracts WHERE agency_id LIKE '%atla%' AND contract_amount > 0 AND contract_amount <= 100000000;")
for count, min_amt, max_amt in cursor.fetchall():
    print(f"Count: {count}, Min: {min_amt}, Max: {max_amt}")

conn.close()
