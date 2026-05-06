-- 防衛省調達データベース スキーマ (Phase 1)
-- UNIQUE 制約により同一機関・年度・契約名・業者・金額の重複投入を防止

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agency_id TEXT NOT NULL,
    agency_name TEXT,
    agency_category TEXT,
    fiscal_year INTEGER NOT NULL,
    contract_type TEXT,
    contract_name TEXT,
    vendor_name TEXT,
    vendor_address TEXT,
    corporate_number TEXT,
    contract_amount INTEGER,
    estimated_price INTEGER,
    award_rate REAL,
    bid_method TEXT,
    zuii_reason TEXT,
    contract_date TEXT,
    contract_officer TEXT,
    quantity TEXT,
    unit_measure TEXT,
    source_url TEXT,
    source_type TEXT,
    UNIQUE(agency_id, fiscal_year, contract_name, vendor_name, contract_amount)
);

CREATE INDEX IF NOT EXISTS idx_contracts_fy        ON contracts(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_contracts_agency    ON contracts(agency_id);
CREATE INDEX IF NOT EXISTS idx_contracts_category  ON contracts(agency_category);
CREATE INDEX IF NOT EXISTS idx_contracts_vendor    ON contracts(vendor_name);
CREATE INDEX IF NOT EXISTS idx_contracts_bid       ON contracts(bid_method);
CREATE INDEX IF NOT EXISTS idx_contracts_date      ON contracts(contract_date);

-- 年度別予算（PDF出典: yosan_gaiyo/）
CREATE TABLE IF NOT EXISTS fy_budget (
    fiscal_year INTEGER PRIMARY KEY,
    budget_oku_yen INTEGER,                    -- 物件費（契約ベース）億円
    db_target_oku_yen INTEGER,                 -- DB対象予算（基地対策経費除く）
    source_pdf_url TEXT,
    note TEXT
);

INSERT OR REPLACE INTO fy_budget VALUES
    (2022, 34980, 34980, 'https://www.mod.go.jp/j/budget/yosan_gaiyo/2022/yosan_20220324.pdf', NULL),
    (2023, 95277, 95277, 'https://www.mod.go.jp/j/budget/yosan_gaiyo/2023/yosan_20230328.pdf', NULL),
    (2024, 93625, 88517, 'https://www.mod.go.jp/j/budget/yosan_gaiyo/2024/yosan_20240328.pdf',
     '基地対策経費5,108億円はDB対象外'),
    (2025, NULL,  NULL,  'https://www.mod.go.jp/j/budget/yosan_gaiyo/fy2025/yosan_20250402.pdf',
     'PDFから抽出予定'),
    (2026, NULL,  NULL,  'https://www.mod.go.jp/j/budget/yosan_gaiyo/fy2026/yosan_20251226.pdf',
     'PDFから抽出予定');
