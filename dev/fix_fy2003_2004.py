"""
FY2003 (H15) / FY2004 (H16) の中央調達実績を正しい値で上書き。

ソース:
  H15: https://web.archive.org/web/20041024045044/http://www.cco.jda.go.jp/supply/jisseki/jisseki_mikomi.html
  H16: https://web.archive.org/web/20060420062419/http://www.cco.jda.go.jp/supply/jisseki/jisseki_mikomi.html

問題:
  スクリプトが H15 ページの「H16 見込」総額を H15 実績として誤取込み（13,304 億円 → 正: 12,731.63 億円）
  H16 も類似の誤取込みにより修正対象。
"""

import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "chuou_chotatsu.db"

# ─── 修正データ（百万円 → 億円に変換済み = /100）────────────────────────────

FY2003_SUMMARY = {
    "fiscal_year": 2003,
    "total_100m": 12731.63,
    "army_100m":  3644.64,
    "navy_100m":  4126.08,
    "airforce_100m": 3308.88,
    "other_100m": 1652.02,   # 技本+内局等+防大+防医大
    "data_type": "jisseki",
    "source_file": "wayback_h15_jisseki_mikomi.html",
}

FY2003_COMPANIES = [
    (1,  "三菱重工業(株)",              213,  2816.97, 22.1),
    (2,  "川崎重工業(株)",               97,  1588.09, 12.5),
    (3,  "三菱電機(株)",                170,   948.78,  7.5),
    (4,  "日本電気(株)",                306,   562.84,  4.4),
    (5,  "(株)東芝",                    107,   388.81,  3.1),
    (6,  "(株)小松製作所",               56,   375.52,  2.9),
    (7,  "石川島播磨重工業(株)",          39,   361.70,  2.8),
    (8,  "富士重工業(株)",               35,   287.88,  2.3),
    (9,  "(株)川崎造船",                  4,   257.22,  2.0),
    (10, "伊藤忠商事(株)",                3,   219.38,  1.7),
    (11, "富士通(株)",                  164,   209.86,  1.6),
    (12, "(株)日立製作所",               78,   209.67,  1.6),
    (13, "(株)アイ・エイチ・アイ・エアロスペース", 38, 168.98, 1.3),
    (14, "(株)日本製綱所",               22,   151.09,  1.2),
    (15, "ダイキン工業(株)",             60,   142.49,  1.1),
    (16, "日本電子計算機(株)",           131,   129.54,  1.0),
    (17, "三菱商事(株)",                 16,    88.15,  0.7),
    (18, "いすゞ自動車(株)",             58,    86.48,  0.7),
    (19, "沖電気工業(株)",               43,    83.85,  0.7),
    (20, "住友商事(株)",                 42,    77.23,  0.6),
]

FY2004_SUMMARY = {
    "fiscal_year": 2004,
    "total_100m": 13061.70,
    "army_100m":  3468.26,
    "navy_100m":  4377.99,
    "airforce_100m": 3615.60,
    "other_100m": 1599.86,   # 技本+内局等+防大+防医大
    "data_type": "jisseki",
    "source_file": "wayback_h16_jisseki_mikomi.html",
}

FY2004_COMPANIES = [
    (1,  "三菱重工業(株)",              164,  2706.05, 20.7),
    (2,  "川崎重工業(株)",               97,  1428.57, 10.9),
    (3,  "三菱電機(株)",                169,  1032.04,  7.9),
    (4,  "日本電気(株)",                270,   905.64,  6.9),
    (5,  "石川島播磨重工業(株)",          40,   492.82,  3.8),
    (6,  "(株)アイ・エイチ・アイマリンユナイテッド", 5, 480.20, 3.7),
    (7,  "(株)東芝",                     74,   415.42,  3.2),
    (8,  "(株)小松製作所",               50,   347.06,  2.7),
    (9,  "富士重工業(株)",               36,   240.33,  1.8),
    (10, "伊藤忠商事(株)",                2,   227.72,  1.7),
    (11, "富士通(株)",                  161,   218.05,  1.7),
    (12, "(株)アイ・エイチ・アイ・エアロスペース", 35, 157.28, 1.2),
    (13, "(株)日立製作所",               76,   144.68,  1.1),
    (14, "中川物産(株)",                135,   142.43,  1.1),
    (15, "ダイキン工業(株)",             53,   135.64,  1.0),
    (16, "ユニバーサル造船(株)",          25,   111.26,  0.9),
    (17, "新日本石油(株)",               94,   107.02,  0.8),
    (18, "(株)日本製鋼所",               18,   103.96,  0.8),
    (19, "日本電子計算機(株)",            84,   100.63,  0.8),
    (20, "コスモ石油(株)",              118,    93.58,  0.7),
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

    # FY2003 (H15)
    upsert_summary(cur, FY2003_SUMMARY)
    replace_companies(cur, 2003, FY2003_COMPANIES, "wayback_h15_jisseki_mikomi.html")
    print(f"[OK] FY2003 summary updated: total={FY2003_SUMMARY['total_100m']}億")
    print(f"[OK] FY2003 companies inserted: {len(FY2003_COMPANIES)}社")

    # FY2004 (H16)
    upsert_summary(cur, FY2004_SUMMARY)
    replace_companies(cur, 2004, FY2004_COMPANIES, "wayback_h16_jisseki_mikomi.html")
    print(f"[OK] FY2004 summary updated: total={FY2004_SUMMARY['total_100m']}億")
    print(f"[OK] FY2004 companies inserted: {len(FY2004_COMPANIES)}社")

    con.commit()
    con.close()

    # 検証
    con2 = sqlite3.connect(DB)
    rows = con2.execute(
        "SELECT fiscal_year, total_100m, army_100m, navy_100m, airforce_100m, other_100m "
        "FROM chuou_chotatsu_summary WHERE fiscal_year IN (2003, 2004) ORDER BY fiscal_year"
    ).fetchall()
    print("\n--- summary 確認 ---")
    for r in rows:
        total = r[1]; comps = r[2:]
        comp_sum = sum(c for c in comps if c is not None)
        print(f"  FY{r[0]}: total={total:.2f}億, 機関別合計={comp_sum:.2f}億, 差={total-comp_sum:.2f}億")

    counts = con2.execute(
        "SELECT fiscal_year, COUNT(*) FROM chuou_chotatsu_companies "
        "WHERE fiscal_year IN (2003, 2004) GROUP BY fiscal_year ORDER BY fiscal_year"
    ).fetchall()
    print("--- companies 確認 ---")
    for fy, cnt in counts:
        print(f"  FY{fy}: {cnt}社")

    # WARN チェック: top20比率が総額の30%以上ならWARN
    print("\n--- WARN チェック ---")
    for fy in (2003, 2004):
        total = con2.execute(
            "SELECT total_100m FROM chuou_chotatsu_summary WHERE fiscal_year=?", (fy,)
        ).fetchone()[0]
        top20 = con2.execute(
            "SELECT COALESCE(SUM(amount_100m),0) FROM chuou_chotatsu_companies "
            "WHERE fiscal_year=?", (fy,)
        ).fetchone()[0]
        ratio = top20 / total if total else 0
        status = "WARN" if ratio > 1.5 else "OK"
        print(f"  FY{fy}: top20={top20:.2f}億 / total={total:.2f}億 = {ratio:.2f} [{status}]")

    con2.close()
    print("\n完了。")


if __name__ == "__main__":
    main()
