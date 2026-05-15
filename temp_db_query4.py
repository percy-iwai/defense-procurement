import sqlite3

db_path = "data/db/procurement.db"
conn = sqlite3.connect(db_path)
conn.text_factory = str  # Ensure proper text handling
cursor = conn.cursor()

print("=" * 80)
print("ATLA CONTRACTS - AMOUNT STATISTICS BY AGENCY_ID")
print("=" * 80)

agencies_to_check = ['atla', 'atla_kanbo', 'atla_riku', 'atla_koukuu']

for agency_id in agencies_to_check:
    cursor.execute(f"""
    SELECT 
        COUNT(*) as cnt,
        COUNT(CASE WHEN contract_amount > 0 THEN 1 END) as cnt_nonzero,
        AVG(contract_amount) as avg_amt,
        MIN(contract_amount) as min_amt,
        MAX(contract_amount) as max_amt
    FROM contracts
    WHERE agency_id = ?
    """, (agency_id,))
    
    cnt, cnt_nonzero, avg_amt, min_amt, max_amt = cursor.fetchone()
    print(f"\n{agency_id}:")
    print(f"  Total records: {cnt}")
    print(f"  Non-zero amounts: {cnt_nonzero}")
    if avg_amt:
        print(f"  Avg amount: {avg_amt:,.0f}")
    print(f"  Min: {min_amt:,}" if min_amt else "  Min: None")
    print(f"  Max: {max_amt:,}" if max_amt else "  Max: None")

print("\n" + "=" * 80)
print("ALL CONTRACTS TABLE COLUMNS")
print("=" * 80)
cursor.execute("PRAGMA table_info(contracts)")
for cid, name, type_, notnull, default_val, pk in cursor.fetchall():
    print(f"  {name}: {type_}")

conn.close()
