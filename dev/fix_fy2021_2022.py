"""
FY2021 (R03) / FY2022 (R04) の上位20社 + 機関別内訳をDBに投入。

ソース:
  FY2021: r03_jisseki_r04_mikomi.pdf (p.2 機関別, p.3 上位20社)
  FY2022: r04_jisseki_r05_mikomi.pdf (p.2 機関別, p.3 上位20社)

単位: 億円 (PDFに「単位：億円」と明記されているため /100 変換不要)
"""

import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "chuou_chotatsu.db"

# ─── FY2021 (令和3年度) ──────────────────────────────────────────────────────

FY2021_SUMMARY = {
    "fiscal_year": 2021,
    "total_100m": 18031.0,
    "army_100m":  3115.0,   # 陸幕
    "navy_100m":  6330.0,   # 海幕
    "airforce_100m": 6207.0, # 空幕
    "other_100m": 2379.0,   # 装備庁1580 + 防大8 + 防医大8 + 内局等782 = 2378 (+1 rounding)
    "data_type": "jisseki",
    "source_file": "r03_jisseki_r04_mikomi.pdf",
}

FY2021_COMPANIES = [
    (1,  "三菱重工業株式会社",                          157, 4591.0, 25.5),
    (2,  "川崎重工業株式会社",                           99, 2071.0, 11.5),
    (3,  "三菱電機株式会社",                             93,  966.0,  5.4),
    (4,  "日本電気株式会社",                            166,  900.0,  5.0),
    (5,  "富士通株式会社",                              141,  757.0,  4.2),
    (6,  "東芝インフラシステムズ株式会社",               62,  664.0,  3.7),
    (7,  "株式会社ＩＨＩ",                              34,  575.0,  3.2),
    (8,  "株式会社ＳＵＢＡＲＵ",                        13,  417.0,  2.3),
    (9,  "株式会社日立製作所",                           66,  342.0,  1.9),
    (10, "沖電気工業株式会社",                           54,  277.0,  1.5),
    (11, "株式会社小松製作所",                           16,  183.0,  1.0),
    (12, "ダイキン工業株式会社",                         46,  181.0,  1.0),
    (13, "エアバス・ヘリコプターズ・ジャパン株式会社",    3,  175.0,  1.0),
    (14, "国立研究開発法人宇宙航空研究開発機構",          3,  174.0,  1.0),
    (15, "ＥＮＥＯＳ株式会社",                         106,  141.0,  0.8),
    (16, "株式会社日本製鋼所",                           20,  138.0,  0.8),
    (17, "中川物産株式会社",                            136,  133.0,  0.7),
    (18, "株式会社ジーエス・ユアサテクノロジー",          12,  130.0,  0.7),
    (19, "出光興産株式会社",                            103,  110.0,  0.6),
    (20, "新明和工業株式会社",                            7,  107.0,  0.6),
]

# ─── FY2022 (令和4年度) ──────────────────────────────────────────────────────

FY2022_SUMMARY = {
    "fiscal_year": 2022,
    "total_100m": 17217.0,   # PDF注に明記（個別合計17,208は端数丸め）
    "army_100m":  3035.0,   # 陸幕
    "navy_100m":  5528.0,   # 海幕
    "airforce_100m": 5556.0, # 空幕
    "other_100m": 3089.0,   # 装備庁2326 + 防大8 + 防医大22 + 内局等733 = 3089
    "data_type": "jisseki",
    "source_file": "r04_jisseki_r05_mikomi.pdf",
}

FY2022_COMPANIES = [
    (1,  "三菱重工業株式会社",                  121, 3652.0, 21.2),
    (2,  "川崎重工業株式会社",                  104, 1692.0,  9.8),
    (3,  "日本電気株式会社",                    185,  944.0,  5.5),
    (4,  "三菱電機株式会社",                     84,  752.0,  4.4),
    (5,  "富士通株式会社",                      103,  652.0,  3.8),
    (6,  "東芝インフラシステムズ株式会社",        48,  363.0,  2.1),
    (7,  "株式会社ＩＨＩ",                      19,  291.0,  1.7),
    (8,  "株式会社小松製作所",                   24,  274.0,  1.6),
    (9,  "株式会社日本製鋼所",                   14,  254.0,  1.5),
    (10, "藤倉航装株式会社",                     45,  249.0,  1.4),
    (11, "沖電気工業株式会社",                   44,  224.0,  1.3),
    (12, "株式会社日立製作所",                   69,  218.0,  1.3),
    (13, "出光興産株式会社",                     79,  185.0,  1.1),
    (14, "中川物産株式会社",                    119,  168.0,  1.0),
    (15, "ダイキン工業株式会社",                 39,  163.0,  0.9),
    (16, "日本飛行機株式会社",                    9,  137.0,  0.8),
    (17, "株式会社ジーエス・ユアサテクノロジー",   7,  131.0,  0.8),
    (18, "日本無線株式会社",                     27,  124.0,  0.7),
    (19, "ジャパンマリンユナイテッド株式会社",     2,  119.0,  0.7),
    (20, "株式会社日立国際電気",                 43,  119.0,  0.7),
]

# ─── DB 更新 ──────────────────────────────────────────────────────────────────

def upsert_summary(cur, s):
    cur.execute("""
        INSERT OR REPLACE INTO chuou_chotatsu_summary
          (fiscal_year, total_100m, army_100m, navy_100m, airforce_100m,
           other_100m, data_type, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        s["fiscal_year"], s["total_100m"],
        s["army_100m"], s["navy_100m"], s["airforce_100m"], s["other_100m"],
        s["data_type"], s["source_file"],
    ))


def replace_companies(cur, fiscal_year, companies, source_file):
    cur.execute("DELETE FROM chuou_chotatsu_companies WHERE fiscal_year = ?", (fiscal_year,))
    for rank, name, cnt, amt, share in companies:
        cur.execute("""
            INSERT INTO chuou_chotatsu_companies
              (fiscal_year, rank, company_name, contracts_cnt, amount_100m, share_pct, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (fiscal_year, rank, name, cnt, amt, share, source_file))


def main():
    print(f"DB: {DB}")
    con = sqlite3.connect(DB)
    cur = con.cursor()

    upsert_summary(cur, FY2021_SUMMARY)
    replace_companies(cur, 2021, FY2021_COMPANIES, "r03_jisseki_r04_mikomi.pdf")
    print(f"[OK] FY2021 summary updated: total={FY2021_SUMMARY['total_100m']}億")
    print(f"[OK] FY2021 companies inserted: {len(FY2021_COMPANIES)}社")

    upsert_summary(cur, FY2022_SUMMARY)
    replace_companies(cur, 2022, FY2022_COMPANIES, "r04_jisseki_r05_mikomi.pdf")
    print(f"[OK] FY2022 summary updated: total={FY2022_SUMMARY['total_100m']}億")
    print(f"[OK] FY2022 companies inserted: {len(FY2022_COMPANIES)}社")

    con.commit()
    con.close()

    # 検証
    con2 = sqlite3.connect(DB)
    print("\n--- 検証 ---")
    for fy in (2021, 2022):
        row = con2.execute(
            "SELECT total_100m, COUNT(c.id), COALESCE(SUM(c.amount_100m),0) "
            "FROM chuou_chotatsu_summary s "
            "LEFT JOIN chuou_chotatsu_companies c ON s.fiscal_year=c.fiscal_year "
            "WHERE s.fiscal_year=? GROUP BY s.fiscal_year", (fy,)
        ).fetchone()
        if row:
            total, cnt, top20 = row
            ratio = top20 / total if total else 0
            print(f"  FY{fy}: total={total:.0f}億, companies={cnt}社, top20/total={ratio:.2f}")
    con2.close()
    print("\n完了。")


if __name__ == "__main__":
    main()
