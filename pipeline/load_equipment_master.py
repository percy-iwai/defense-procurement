"""
防衛白書（令和6年版）資料5・6・7 の CSV から equipment_master テーブルを構築する。

- 資料5: 主要な陸上装備 (siryo05.csv)  → 7カテゴリ集計のみ → カテゴリ単位で投入
- 資料6: 主要航空機     (siryo06.csv) → 30機種 → 個別エントリ
- 資料7: 主要艦艇       (siryo07.csv) → 6カテゴリ集計のみ → カテゴリ単位で投入

contract_equipment は別途マッピング作業で使用。ここでは空テーブルを作るのみ。
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
CSV_DIR = PROJECT_ROOT / "data" / "whitepaper"

REF_HAKUSHO_INTRO = "https://www.mod.go.jp/j/press/wp/wp2024/html/nse00200.html"
REF_SHIRYO5 = "https://www.mod.go.jp/j/press/wp/wp2024/html/n4421000.html"
REF_SHIRYO6 = "https://www.mod.go.jp/j/press/wp/wp2024/html/n4421000.html"
REF_SHIRYO7 = "https://www.mod.go.jp/j/press/wp/wp2024/html/n4421000.html"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS equipment_master (
  equipment_id TEXT PRIMARY KEY,
  name_ja TEXT NOT NULL,
  name_en TEXT,
  branch TEXT,
  category TEXT,
  ref_url_hakusho TEXT,
  ref_url_official TEXT,
  ref_url_wikipedia TEXT,
  keywords TEXT
);

CREATE TABLE IF NOT EXISTS contract_equipment (
  contract_id INTEGER,
  equipment_id TEXT,
  confidence REAL,
  FOREIGN KEY (equipment_id) REFERENCES equipment_master(equipment_id)
);

CREATE INDEX IF NOT EXISTS idx_eqmaster_branch  ON equipment_master(branch);
CREATE INDEX IF NOT EXISTS idx_eqmaster_cat     ON equipment_master(category);
CREATE INDEX IF NOT EXISTS idx_ce_contract      ON contract_equipment(contract_id);
CREATE INDEX IF NOT EXISTS idx_ce_equipment     ON contract_equipment(equipment_id);
"""


BRANCH_MAP = {
    "陸上自衛隊": "GSDF",
    "海上自衛隊": "MSDF",
    "航空自衛隊": "ASDF",
}


def _wiki_url(name_ja: str) -> str:
    return "https://ja.wikipedia.org/wiki/" + urllib.parse.quote(name_ja)


def _slugify_aircraft(model: str) -> str:
    """F-15J/DJ → f15j_dj, CH-47J/JA → ch47j_ja"""
    s = model.strip().lower()
    s = s.replace("/", "_")
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return s


def _aircraft_keywords(model: str) -> str:
    """F-35A → 'F-35A,F35A,F-35'  /  CH-47J/JA → 'CH-47J/JA,CH-47J,CH-47JA,CH-47,CH47J,CH47JA,CH47'"""
    parts = set()
    parts.add(model)
    parts.add(model.replace("-", ""))
    if "/" in model:
        a, b = model.split("/", 1)
        parts.add(a)
        parts.add(a.replace("-", ""))
        head = a.rsplit(re.search(r"[A-Za-z]+$", a).group(), 1)[0] if re.search(r"[A-Za-z]+$", a) else a
        parts.add(head + b)
        parts.add((head + b).replace("-", ""))
    base = re.match(r"^([A-Za-z]+-?\d+)", model)
    if base:
        parts.add(base.group(1))
        parts.add(base.group(1).replace("-", ""))
    return ",".join(sorted(p for p in parts if p))


def parse_siryo06(path: Path) -> list[dict]:
    """主要航空機 CSV → 機種別エントリ。"""
    with open(path, encoding="cp932") as fp:
        rows = list(csv.reader(fp))
    out = []
    for row in rows:
        if len(row) < 4:
            continue
        kubun, keishiki, model, purpose = (row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip())
        if kubun not in BRANCH_MAP:
            continue
        if not model:
            continue
        branch = BRANCH_MAP[kubun]
        category = f"{keishiki}({purpose})" if purpose else keishiki
        eq_id = f"{branch.lower()}_{_slugify_aircraft(model)}"
        out.append({
            "equipment_id": eq_id,
            "name_ja": model,
            "name_en": model,
            "branch": branch,
            "category": category,
            "ref_url_hakusho": REF_SHIRYO6,
            "ref_url_official": None,
            "ref_url_wikipedia": _wiki_url(model),
            "keywords": _aircraft_keywords(model),
        })
    return out


# 資料5・7 はカテゴリ集計のみのため、カテゴリ単位エントリを定義。
# keywords はDBの contract_name から拾える代表的な装備品名を列挙（拡張可）。
GROUND_CATEGORIES = [
    {
        "equipment_id": "gsdf_cat_tank",
        "name_ja": "戦車",
        "category": "戦闘車両",
        "keywords": "戦車,10式戦車,90式戦車,74式戦車,16式機動戦闘車",
    },
    {
        "equipment_id": "gsdf_cat_armored",
        "name_ja": "装甲車",
        "category": "戦闘車両",
        "keywords": "装甲車,87式偵察警戒車,89式装甲戦闘車,96式装輪装甲車,共通戦術装輪車,軽装甲機動車",
    },
    {
        "equipment_id": "gsdf_cat_arty",
        "name_ja": "各種火砲",
        "category": "火砲",
        "keywords": "火砲,りゅう弾砲,99式自走155mmりゅう弾砲,FH70,19式装輪自走155mmりゅう弾砲,迫撃砲",
    },
    {
        "equipment_id": "gsdf_cat_heavy_mortar",
        "name_ja": "重迫撃砲",
        "category": "火砲",
        "keywords": "重迫撃砲,120mm迫撃砲",
    },
    {
        "equipment_id": "gsdf_cat_portable_sam",
        "name_ja": "携SAM",
        "category": "誘導弾",
        "keywords": "携SAM,携帯地対空誘導弾,91式携帯地対空誘導弾,93式近距離地対空誘導弾",
    },
    {
        "equipment_id": "gsdf_cat_combat_aircraft",
        "name_ja": "戦闘用航空機",
        "category": "航空機",
        "keywords": "戦闘用航空機",
    },
    {
        "equipment_id": "gsdf_cat_ssm_regiment",
        "name_ja": "地対艦誘導弾連隊",
        "category": "誘導弾",
        "keywords": "地対艦誘導弾,12式地対艦誘導弾,SSM,88式地対艦誘導弾",
    },
]

NAVAL_CATEGORIES = [
    {
        "equipment_id": "msdf_cat_destroyer",
        "name_ja": "護衛艦",
        "category": "艦艇",
        "keywords": "護衛艦,DD,DDG,DDH,FFM,いずも,ひゅうが,まや,あたご,あさひ,あきづき,たかなみ,むらさめ,もがみ",
    },
    {
        "equipment_id": "msdf_cat_submarine",
        "name_ja": "潜水艦",
        "category": "艦艇",
        "keywords": "潜水艦,SS,たいげい,そうりゅう,おやしお",
    },
    {
        "equipment_id": "msdf_cat_mine_warfare",
        "name_ja": "機雷艦艇",
        "category": "艦艇",
        "keywords": "掃海艦,掃海艇,えのしま,ひらしま,あわじ",
    },
    {
        "equipment_id": "msdf_cat_patrol",
        "name_ja": "哨戒艦艇",
        "category": "艦艇",
        "keywords": "哨戒艦,ミサイル艇,はやぶさ",
    },
    {
        "equipment_id": "msdf_cat_transport",
        "name_ja": "輸送艦艇",
        "category": "艦艇",
        "keywords": "輸送艦,おおすみ,LCAC,輸送艇",
    },
    {
        "equipment_id": "msdf_cat_auxiliary",
        "name_ja": "補助艦艇",
        "category": "艦艇",
        "keywords": "補助艦,訓練艦,補給艦,海洋観測艦,音響測定艦,砕氷艦,しらせ",
    },
]


def build_category_rows(items: list[dict], branch: str, ref_url: str) -> list[dict]:
    out = []
    for it in items:
        out.append({
            "equipment_id": it["equipment_id"],
            "name_ja": it["name_ja"],
            "name_en": None,
            "branch": branch,
            "category": it["category"],
            "ref_url_hakusho": ref_url,
            "ref_url_official": None,
            "ref_url_wikipedia": _wiki_url(it["name_ja"]),
            "keywords": it["keywords"],
        })
    return out


def upsert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    cur = conn.cursor()
    sql = """
    INSERT OR REPLACE INTO equipment_master
      (equipment_id, name_ja, name_en, branch, category,
       ref_url_hakusho, ref_url_official, ref_url_wikipedia, keywords)
    VALUES (:equipment_id, :name_ja, :name_en, :branch, :category,
            :ref_url_hakusho, :ref_url_official, :ref_url_wikipedia, :keywords)
    """
    cur.executemany(sql, rows)
    return cur.rowcount


def main() -> int:
    if not DB_PATH.exists():
        print(f"[ERROR] DB not found: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        rows: list[dict] = []
        rows += build_category_rows(GROUND_CATEGORIES, "GSDF", REF_SHIRYO5)

        siryo06 = parse_siryo06(CSV_DIR / "siryo06.csv")
        rows += siryo06

        rows += build_category_rows(NAVAL_CATEGORIES, "MSDF", REF_SHIRYO7)

        upsert(conn, rows)
        conn.commit()

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM equipment_master")
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT branch, COUNT(*) FROM equipment_master GROUP BY branch ORDER BY branch
        """)
        per_branch = cur.fetchall()
        cur.execute("""
            SELECT branch, equipment_id, name_ja, category
            FROM equipment_master ORDER BY branch, equipment_id
        """)
        all_rows = cur.fetchall()

        print(f"[load_equipment_master] total: {total} rows")
        for b, c in per_branch:
            print(f"  {b}: {c}")
        print()
        print("---- Equipment list ----")
        for b, eid, ja, cat in all_rows:
            print(f"  [{b}] {eid:30s}  {ja:25s}  ({cat})")

    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
