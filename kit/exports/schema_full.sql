-- procurement.db full DDL (exported by kit/export_kit_data.py)

CREATE TABLE "choutatsuyotei" (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_year         INTEGER NOT NULL,
    source_file         TEXT    NOT NULL,
    source_row          INTEGER NOT NULL,
    requesting_org_raw  TEXT    NOT NULL,
    requesting_org      TEXT    NOT NULL,
    item_name           TEXT    NOT NULL,
    item_name_norm      TEXT    NOT NULL,
    spec_class          TEXT,
    qty                 INTEGER,
    request_month       INTEGER,
    contract_month      INTEGER,
    delivery_date       TEXT,
    tantou_office       TEXT,
    UNIQUE(fiscal_year, source_file, source_row)
);

CREATE TABLE contract_equipment (
  contract_id INTEGER,
  equipment_id TEXT,
  confidence REAL,
  FOREIGN KEY (equipment_id) REFERENCES equipment_master(equipment_id)
);

CREATE TABLE "contract_pillar" (
            contract_id INTEGER PRIMARY KEY,
            pillar_l1_code INTEGER,
            pillar_l2_code INTEGER,
            confidence REAL,
            match_method TEXT,
            match_source TEXT,
            fiscal_year INTEGER,
            updated_at TEXT
        );

CREATE TABLE contract_requesting_org (
    contract_id         INTEGER NOT NULL,
    requesting_org      TEXT    NOT NULL,
    match_source        TEXT    NOT NULL,
    choutatsuyotei_id   INTEGER,
    confidence          REAL,
    PRIMARY KEY (contract_id, match_source)
);

CREATE TABLE contracts (
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
    source_type TEXT, category_large TEXT, category_mid TEXT, category_small TEXT,
    UNIQUE(agency_id, fiscal_year, contract_name, vendor_name, contract_amount)
);

CREATE TABLE equipment_master (
  equipment_id TEXT PRIMARY KEY,
  name_ja TEXT NOT NULL,
  name_en TEXT,
  branch TEXT,
  category TEXT,
  ref_url_hakusho TEXT,
  ref_url_official TEXT,
  ref_url_wikipedia TEXT,
  keywords TEXT
, jigyou_review_id TEXT);

CREATE TABLE fy_budget (
    fiscal_year INTEGER PRIMARY KEY,
    budget_oku_yen INTEGER,                    -- 物件費（契約ベース）億円
    db_target_oku_yen INTEGER,                 -- DB対象予算（基地対策経費除く）
    source_pdf_url TEXT,
    note TEXT
);

CREATE TABLE kenkyuu_hyouka (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fiscal_year INTEGER NOT NULL,
        hyouka_kubun TEXT NOT NULL,
        jigyou_name TEXT NOT NULL,
        jigyou_name_norm TEXT NOT NULL,
        tantou_bukyoku TEXT,
        tantou_org TEXT,
        pdf_url TEXT NOT NULL,
        page_anchor INTEGER,
        UNIQUE(fiscal_year, hyouka_kubun, jigyou_name)
    );

CREATE INDEX idx_ce_contract      ON contract_equipment(contract_id);

CREATE INDEX idx_ce_equipment     ON contract_equipment(equipment_id);

CREATE INDEX idx_contracts_agency    ON contracts(agency_id);

CREATE INDEX idx_contracts_bid       ON contracts(bid_method);

CREATE INDEX idx_contracts_cat_large ON contracts(category_large);

CREATE INDEX idx_contracts_category  ON contracts(agency_category);

CREATE INDEX idx_contracts_date      ON contracts(contract_date);

CREATE INDEX idx_contracts_fy        ON contracts(fiscal_year);

CREATE INDEX idx_contracts_vendor    ON contracts(vendor_name);

CREATE INDEX idx_cro_contract ON contract_requesting_org(contract_id);

CREATE INDEX idx_cro_org      ON contract_requesting_org(requesting_org);

CREATE INDEX idx_eqmaster_branch  ON equipment_master(branch);

CREATE INDEX idx_eqmaster_cat     ON equipment_master(category);
