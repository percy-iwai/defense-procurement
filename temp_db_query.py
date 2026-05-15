import sqlite3
import sys

db_path = "data/db/procurement.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get schema
print("=" * 80)
print("DATABASE SCHEMA")
print("=" * 80)
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
for (table_name,) in tables:
    print(f"\n--- TABLE: {table_name} ---")
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()
    for col in columns:
        cid, name, type_, notnull, default_val, pk = col
        pk_str = " PRIMARY KEY" if pk else ""
        notnull_str = " NOT NULL" if notnull else ""
        print(f"  {name}: {type_}{pk_str}{notnull_str}")

conn.close()
