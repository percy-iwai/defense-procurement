#!/usr/bin/env python3
"""FY1999/2000/2002/2003/2004 上位企業データを正確な値で修正する。

出典:
- FY1999/2000: Wayback Machine HTML kakuteichi pages
- FY2002: Wayback Machine 14jisseki15mikomi.htm TABLE 8/9
- FY2003/2004: Wayback Machine jisseki_mikomi.html TABLE 9
"""
from __future__ import annotations
import shutil, sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "chuou_chotatsu.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"

# ── 確定データ ────────────────────────────────────────────────────────────

# FY1999: rank=10 が欠けている (旧スクリプトが三菱重工業の重複を削除したが、
#         正しい rank=10 の会社（日本電子計算機）を挿入しなかった)
# 出典: https://web.archive.org/web/20010411184238/http://www.jda-cco.go.jp/kakuteichi-11nendo-3.htm
FY1999_MISSING = {
    "rank": 10,
    "company_name": "日本電子計算機(株)",
    "contracts_cnt": 233,
    "amount_100m": 255.25,
    "share_pct": 2.0,
    "source_file": "html_wayback_1999",
}

# FY2000: rank=11 が欠けている
# 出典: https://web.archive.org/web/20020206195044/http://www.jda-cco.go.jp/12_kakuteichi/3_12_joi_20sha.htm
FY2000_MISSING = {
    "rank": 11,
    "company_name": "(株)アイ・エイチ・アイ・エアロスペース",
    "contracts_cnt": 46,
    "amount_100m": 260.93,
    "share_pct": 2.1,
    "source_file": "html_wayback_2000",
}

# FY2002: 正しい上位20社データ
# 出典: https://web.archive.org/web/20031002005953/http://www.jda-cco.go.jp/14jisseki15mikomi/14jisseki15mikomi.htm TABLE 8/9
FY2002_COMPANIES = [
    {"rank":  1, "company_name": "三菱重工業(株)",              "contracts_cnt": 205, "amount_100m": 3481.08, "share_pct": 27.2},
    {"rank":  2, "company_name": "川崎重工業(株)",              "contracts_cnt": 102, "amount_100m": 1102.09, "share_pct":  8.6},
    {"rank":  3, "company_name": "三菱電機(株)",                "contracts_cnt": 178, "amount_100m":  734.59, "share_pct":  5.7},
    {"rank":  4, "company_name": "石川島播磨重工業(株)",        "contracts_cnt":  48, "amount_100m":  526.94, "share_pct":  4.1},
    {"rank":  5, "company_name": "(株)東芝",                    "contracts_cnt": 123, "amount_100m":  497.86, "share_pct":  3.9},
    {"rank":  6, "company_name": "日本電気(株)",                "contracts_cnt": 312, "amount_100m":  484.82, "share_pct":  3.8},
    {"rank":  7, "company_name": "(株)小松製作所",              "contracts_cnt":  43, "amount_100m":  357.42, "share_pct":  2.8},
    {"rank":  8, "company_name": "伊藤忠商事(株)",              "contracts_cnt":   5, "amount_100m":  232.16, "share_pct":  1.8},
    {"rank":  9, "company_name": "新明和工業(株)",              "contracts_cnt":  13, "amount_100m":  229.30, "share_pct":  1.8},
    {"rank": 10, "company_name": "富士通(株)",                  "contracts_cnt": 166, "amount_100m":  222.95, "share_pct":  1.7},
    {"rank": 11, "company_name": "富士重工業(株)",              "contracts_cnt":  38, "amount_100m":  216.09, "share_pct":  1.7},
    {"rank": 12, "company_name": "日本電子計算機(株)",          "contracts_cnt": 164, "amount_100m":  186.77, "share_pct":  1.5},
    {"rank": 13, "company_name": "ダイキン工業(株)",            "contracts_cnt":  57, "amount_100m":  179.23, "share_pct":  1.4},
    {"rank": 14, "company_name": "(株)アイ・エイチ・アイ・エアロスペース", "contracts_cnt": 42, "amount_100m": 159.34, "share_pct": 1.2},
    {"rank": 15, "company_name": "(株)日本製鋼所",              "contracts_cnt":  22, "amount_100m":  142.61, "share_pct":  1.1},
    {"rank": 16, "company_name": "(株)日立製作所",              "contracts_cnt":  69, "amount_100m":  142.11, "share_pct":  1.1},
    {"rank": 17, "company_name": "三菱商事(株)",                "contracts_cnt":  17, "amount_100m":  108.74, "share_pct":  0.8},
    {"rank": 18, "company_name": "いすゞ自動車(株)",            "contracts_cnt":  61, "amount_100m":   94.09, "share_pct":  0.7},
    {"rank": 19, "company_name": "ユニバーサル造船(株)",        "contracts_cnt":  26, "amount_100m":   82.10, "share_pct":  0.6},
    {"rank": 20, "company_name": "伊藤忠アビエーション(株)",    "contracts_cnt":  33, "amount_100m":   80.58, "share_pct":  0.6},
]
for r in FY2002_COMPANIES:
    r["source_file"] = "html_wayback_2002"

# FY2003: TABLE 9 より（jisseki_mikomi.html snapshot 2004-08-04）
FY2003_COMPANIES = [
    {"rank":  1, "company_name": "三菱重工業(株)",              "contracts_cnt": 213, "amount_100m": 2816.97, "share_pct": 22.1},
    {"rank":  2, "company_name": "川崎重工業(株)",              "contracts_cnt":  97, "amount_100m": 1588.09, "share_pct": 12.5},
    {"rank":  3, "company_name": "三菱電機(株)",                "contracts_cnt": 170, "amount_100m":  948.78, "share_pct":  7.5},
    {"rank":  4, "company_name": "日本電気(株)",                "contracts_cnt": 306, "amount_100m":  562.84, "share_pct":  4.4},
    {"rank":  5, "company_name": "(株)東芝",                    "contracts_cnt": 107, "amount_100m":  388.81, "share_pct":  3.1},
    {"rank":  6, "company_name": "(株)小松製作所",              "contracts_cnt":  56, "amount_100m":  375.52, "share_pct":  2.9},
    {"rank":  7, "company_name": "石川島播磨重工業(株)",        "contracts_cnt":  39, "amount_100m":  361.70, "share_pct":  2.8},
    {"rank":  8, "company_name": "富士重工業(株)",              "contracts_cnt":  35, "amount_100m":  287.88, "share_pct":  2.3},
    {"rank":  9, "company_name": "(株)川崎造船",                "contracts_cnt":   4, "amount_100m":  257.22, "share_pct":  2.0},
    {"rank": 10, "company_name": "伊藤忠商事(株)",              "contracts_cnt":   3, "amount_100m":  219.38, "share_pct":  1.7},
    {"rank": 11, "company_name": "富士通(株)",                  "contracts_cnt": 164, "amount_100m":  209.86, "share_pct":  1.6},
    {"rank": 12, "company_name": "(株)日立製作所",              "contracts_cnt":  78, "amount_100m":  209.67, "share_pct":  1.6},
    {"rank": 13, "company_name": "(株)アイ・エイチ・アイ・エアロスペース", "contracts_cnt": 38, "amount_100m": 168.98, "share_pct": 1.3},
    {"rank": 14, "company_name": "(株)日本製鋼所",              "contracts_cnt":  22, "amount_100m":  151.09, "share_pct":  1.2},
    {"rank": 15, "company_name": "ダイキン工業(株)",            "contracts_cnt":  60, "amount_100m":  142.49, "share_pct":  1.1},
    {"rank": 16, "company_name": "日本電子計算機(株)",          "contracts_cnt": 131, "amount_100m":  129.54, "share_pct":  1.0},
    {"rank": 17, "company_name": "三菱商事(株)",                "contracts_cnt":  16, "amount_100m":   88.15, "share_pct":  0.7},
    {"rank": 18, "company_name": "いすゞ自動車(株)",            "contracts_cnt":  58, "amount_100m":   86.48, "share_pct":  0.7},
    {"rank": 19, "company_name": "沖電気工業(株)",              "contracts_cnt":  43, "amount_100m":   83.85, "share_pct":  0.7},
    {"rank": 20, "company_name": "住友商事(株)",                "contracts_cnt":  42, "amount_100m":   77.23, "share_pct":  0.6},
]
for r in FY2003_COMPANIES:
    r["source_file"] = "html_wayback_2003"

# FY2004: TABLE 9 より（jisseki_mikomi.html snapshot 2006-04-20）
FY2004_COMPANIES = [
    {"rank":  1, "company_name": "三菱重工業(株)",              "contracts_cnt": 164, "amount_100m": 2706.05, "share_pct": 20.7},
    {"rank":  2, "company_name": "川崎重工業(株)",              "contracts_cnt":  97, "amount_100m": 1428.57, "share_pct": 10.9},
    {"rank":  3, "company_name": "三菱電機(株)",                "contracts_cnt": 169, "amount_100m": 1032.04, "share_pct":  7.9},
    {"rank":  4, "company_name": "日本電気(株)",                "contracts_cnt": 270, "amount_100m":  905.64, "share_pct":  6.9},
    {"rank":  5, "company_name": "石川島播磨重工業(株)",        "contracts_cnt":  40, "amount_100m":  492.82, "share_pct":  3.8},
    {"rank":  6, "company_name": "(株)アイ・エイチ・アイマリンユナイテッド", "contracts_cnt": 5, "amount_100m": 480.20, "share_pct": 3.7},
    {"rank":  7, "company_name": "(株)東芝",                    "contracts_cnt":  74, "amount_100m":  415.42, "share_pct":  3.2},
    {"rank":  8, "company_name": "(株)小松製作所",              "contracts_cnt":  50, "amount_100m":  347.06, "share_pct":  2.7},
    {"rank":  9, "company_name": "富士重工業(株)",              "contracts_cnt":  36, "amount_100m":  240.33, "share_pct":  1.8},
    {"rank": 10, "company_name": "伊藤忠商事(株)",              "contracts_cnt":   2, "amount_100m":  227.72, "share_pct":  1.7},
    {"rank": 11, "company_name": "富士通(株)",                  "contracts_cnt": 161, "amount_100m":  218.05, "share_pct":  1.7},
    {"rank": 12, "company_name": "(株)アイ・エイチ・アイ・エアロスペース", "contracts_cnt": 35, "amount_100m": 157.28, "share_pct": 1.2},
    {"rank": 13, "company_name": "(株)日立製作所",              "contracts_cnt":  76, "amount_100m":  144.68, "share_pct":  1.1},
    {"rank": 14, "company_name": "中川物産(株)",                "contracts_cnt": 135, "amount_100m":  142.43, "share_pct":  1.1},
    {"rank": 15, "company_name": "ダイキン工業(株)",            "contracts_cnt":  53, "amount_100m":  135.64, "share_pct":  1.0},
    {"rank": 16, "company_name": "ユニバーサル造船(株)",        "contracts_cnt":  25, "amount_100m":  111.26, "share_pct":  0.9},
    {"rank": 17, "company_name": "新日本石油(株)",              "contracts_cnt":  94, "amount_100m":  107.02, "share_pct":  0.8},
    {"rank": 18, "company_name": "(株)日本製鋼所",              "contracts_cnt":  18, "amount_100m":  103.96, "share_pct":  0.8},
    {"rank": 19, "company_name": "日本電子計算機(株)",          "contracts_cnt":  84, "amount_100m":  100.63, "share_pct":  0.8},
    {"rank": 20, "company_name": "コスモ石油(株)",              "contracts_cnt": 118, "amount_100m":   93.58, "share_pct":  0.7},
]
for r in FY2004_COMPANIES:
    r["source_file"] = "html_wayback_2004"


def main():
    # バックアップ
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"chuou_chotatsu_pre_earlyfy_fix_{ts}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backup: {backup_path}")

    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()

    # ── FY1999: rank 10-19 → 11-20（逆順で競合なし）、rank=10 を挿入 ─
    print("\n--- FY1999 ---")
    for old_rank in range(19, 9, -1):  # 19→18→...→10 の逆順
        cur.execute("UPDATE chuou_chotatsu_companies SET rank=? WHERE fiscal_year=1999 AND rank=?",
                    (old_rank + 1, old_rank))
    m = FY1999_MISSING
    cur.execute("""
        INSERT INTO chuou_chotatsu_companies
        (fiscal_year, rank, company_name, contracts_cnt, amount_100m, share_pct, source_file)
        VALUES (1999, ?, ?, ?, ?, ?, ?)
    """, (m["rank"], m["company_name"], m["contracts_cnt"], m["amount_100m"],
          m["share_pct"], m["source_file"]))
    rows = cur.execute("SELECT rank FROM chuou_chotatsu_companies WHERE fiscal_year=1999 ORDER BY rank").fetchall()
    print(f"  FY1999 after fix: {len(rows)} rows, ranks: {[r[0] for r in rows]}")

    # ── FY2000: rank 11-19 → 12-20（逆順で競合なし）、rank=11 を挿入 ─
    print("\n--- FY2000 ---")
    for old_rank in range(19, 10, -1):  # 19→18→...→11 の逆順
        cur.execute("UPDATE chuou_chotatsu_companies SET rank=? WHERE fiscal_year=2000 AND rank=?",
                    (old_rank + 1, old_rank))
    m = FY2000_MISSING
    cur.execute("""
        INSERT INTO chuou_chotatsu_companies
        (fiscal_year, rank, company_name, contracts_cnt, amount_100m, share_pct, source_file)
        VALUES (2000, ?, ?, ?, ?, ?, ?)
    """, (m["rank"], m["company_name"], m["contracts_cnt"], m["amount_100m"],
          m["share_pct"], m["source_file"]))
    rows = cur.execute("SELECT rank FROM chuou_chotatsu_companies WHERE fiscal_year=2000 ORDER BY rank").fetchall()
    print(f"  FY2000 after fix: {len(rows)} rows, ranks: {[r[0] for r in rows]}")

    # ── FY2002/2003/2004: 全削除 → 正確な20社を挿入 ─────────────────
    for fy, companies in [(2002, FY2002_COMPANIES), (2003, FY2003_COMPANIES), (2004, FY2004_COMPANIES)]:
        print(f"\n--- FY{fy} ---")
        cur.execute("DELETE FROM chuou_chotatsu_companies WHERE fiscal_year=?", (fy,))
        print(f"  Deleted all existing entries")
        for c in companies:
            cur.execute("""
                INSERT INTO chuou_chotatsu_companies
                (fiscal_year, rank, company_name, contracts_cnt, amount_100m, share_pct, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (fy, c["rank"], c["company_name"], c["contracts_cnt"],
                  c["amount_100m"], c["share_pct"], c["source_file"]))
        print(f"  Inserted {len(companies)} companies")

    con.commit()
    con.close()

    # ── 確認 ─────────────────────────────────────────────────────────
    con = sqlite3.connect(str(DB_PATH))
    for fy in [1999, 2000, 2002, 2003, 2004]:
        rows = con.execute(
            "SELECT rank, amount_100m, company_name FROM chuou_chotatsu_companies WHERE fiscal_year=? ORDER BY rank",
            (fy,)
        ).fetchall()
        print(f"\n=== FY{fy} ({len(rows)} rows) ===")
        for r in rows:
            print(f"  rank={r[0]:2d}  amt={r[1]}  {r[2]}")
    con.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
