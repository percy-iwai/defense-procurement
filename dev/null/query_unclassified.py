import sqlite3
conn = sqlite3.connect(r'C:\Users\Percy Iwai\Documents\defense_procurement_2nd\data\db\procurement.db')
cur = conn.cursor()
cur.execute('''
SELECT c.id, c.contract_name, c.agency_name, c.estimated_price/1e8 as oku
FROM contracts c
WHERE c.fiscal_year=2023
  AND c.id NOT IN (SELECT contract_id FROM contract_pillar WHERE fiscal_year=2023)
  AND c.estimated_price IS NOT NULL
ORDER BY c.estimated_price DESC
LIMIT 15
''')
rows = cur.fetchall()
for i, r in enumerate(rows, 1):
    print(f"{i:2}. id={r[0]}  {r[3]:.1f}億円  [{r[2]}]  {r[1]}")
conn.close()
