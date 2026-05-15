import sqlite3

db_path = "data/db/procurement.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 80)
print("SAMPLE ATLA CONTRACTS (first 3 from agency_id='atla')")
print("=" * 80)
cursor.execute("""
SELECT 
    id, fiscal_year, contract_name, vendor_name, contract_amount, 
    bid_method, contract_date, contract_type
FROM contracts
WHERE agency_id = 'atla'
LIMIT 3;
""")
for row in cursor.fetchall():
    contract_id, fy, name, vendor, amt, bid, date, ctype = row
    print(f"\nID: {contract_id}")
    print(f"  FY: {fy}")
    print(f"  Name: {name}")
    print(f"  Vendor: {vendor}")
    print(f"  Amount: {amt:,}" if amt else "  Amount: None")
    print(f"  Bid Method: {bid}")
    print(f"  Date: {date}")
    print(f"  Type: {ctype}")

print("\n" + "=" * 80)
print("SAMPLE ATLA_KANBO CONTRACTS (first 2 from agency_id='atla_kanbo')")
print("=" * 80)
cursor.execute("""
SELECT 
    id, fiscal_year, contract_name, vendor_name, contract_amount, 
    bid_method, contract_date, contract_type
FROM contracts
WHERE agency_id = 'atla_kanbo'
LIMIT 2;
""")
for row in cursor.fetchall():
    contract_id, fy, name, vendor, amt, bid, date, ctype = row
    print(f"\nID: {contract_id}")
    print(f"  FY: {fy}")
    print(f"  Name: {name}")
    print(f"  Vendor: {vendor}")
    print(f"  Amount: {amt:,}" if amt else "  Amount: None")
    print(f"  Bid Method: {bid}")
    print(f"  Date: {date}")
    print(f"  Type: {ctype}")

conn.close()
