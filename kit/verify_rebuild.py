"""再構築DBを expected_state.json と突合して再現度レポートを出す。

判定基準:
  PASS  contracts 行数差 <1% かつ 金額合計差 <0.5% かつ enrichment 充足 >98%
  WARN  上記は満たすが、URL単位の欠損や source_type 分布差がある
  FAIL  基準未達（欠損URLリストを kit/exports/verify_missing_urls.txt に出力）

実行:
  python kit/verify_rebuild.py
  python kit/verify_rebuild.py --db path/to/other.db

出力:
  kit/exports/verify_report.json        全比較結果
  kit/exports/verify_missing_urls.txt   欠損URL（downloader.py --urls に渡せる）
終了コード: 0=PASS/WARN, 1=FAIL
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
EXPORTS = PROJECT_ROOT / "kit" / "exports"
EXPECTED = EXPORTS / "expected_state.json"
REPORT = EXPORTS / "verify_report.json"
MISSING_TXT = EXPORTS / "verify_missing_urls.txt"

TOL_CONTRACTS_ROWS = 0.01   # 1%
TOL_AMOUNT = 0.005          # 0.5%
TOL_ENRICHMENT = 0.02       # 2%


def main() -> None:
    parser = argparse.ArgumentParser(description="再構築DBの期待値突合")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)

    report: dict = {"ts": datetime.now().isoformat(), "db": args.db,
                    "checks": [], "result": None}
    fails: list[str] = []
    warns: list[str] = []

    def check(name: str, expected, actual, ok: bool, level: str = "fail",
              detail=None) -> None:
        report["checks"].append({"name": name, "expected": expected,
                                 "actual": actual, "ok": ok, "detail": detail})
        mark = "OK  " if ok else ("WARN" if level == "warn" else "FAIL")
        print(f"[{mark}] {name}: expected={expected} actual={actual}")
        if not ok:
            (warns if level == "warn" else fails).append(name)

    # 1. contracts 行数・金額
    exp_rows = exp["totals"]["contracts_rows"]
    act_rows = con.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    check("contracts行数", exp_rows, act_rows,
          abs(act_rows - exp_rows) <= exp_rows * TOL_CONTRACTS_ROWS)

    exp_amt = exp["totals"]["contracts_amount_sum"] or 0
    act_amt = con.execute(
        "SELECT SUM(contract_amount) FROM contracts").fetchone()[0] or 0
    check("contracts金額合計(億円)", round(exp_amt / 1e8), round(act_amt / 1e8),
          abs(act_amt - exp_amt) <= exp_amt * TOL_AMOUNT)

    # 2. enrichment テーブル（孤児除外後の期待値と比較）
    for table, exp_n in exp.get("enrichment_joined_counts", {}).items():
        act_n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        check(f"{table}行数", exp_n, act_n,
              act_n >= exp_n * (1 - TOL_ENRICHMENT))

    # 3. その他テーブル
    for table in ("choutatsuyotei", "kenkyuu_hyouka", "fy_budget",
                  "equipment_master"):
        exp_n = exp["table_counts"].get(table)
        if exp_n is None:
            continue
        try:
            act_n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.DatabaseError:
            act_n = -1
        check(f"{table}行数", exp_n, act_n, act_n >= exp_n * 0.99)

    # 4. agency×FY 差分（上位20の乖離を表示、informational）
    act_af = {(r[0], r[1]): (r[2], r[3] or 0) for r in con.execute(
        """SELECT agency_id, fiscal_year, COUNT(*), SUM(contract_amount)
           FROM contracts GROUP BY agency_id, fiscal_year""")}
    diffs = []
    for rec in exp["agency_fy"]:
        key = (rec["agency_id"], rec["fiscal_year"])
        act_n, _act_a = act_af.get(key, (0, 0))
        d = rec["rows"] - act_n
        if d != 0:
            diffs.append({"agency_id": rec["agency_id"],
                          "fiscal_year": rec["fiscal_year"],
                          "expected": rec["rows"], "actual": act_n, "diff": d})
    diffs.sort(key=lambda x: -abs(x["diff"]))
    check("agency×FY 完全一致セル",
          len(exp["agency_fy"]), len(exp["agency_fy"]) - len(diffs),
          len(diffs) == 0, level="warn", detail=diffs[:20])
    if diffs:
        print("  乖離上位:")
        for d in diffs[:10]:
            print(f"    {d['agency_id']:<22} FY{d['fiscal_year']} "
                  f"expected={d['expected']:>6,} actual={d['actual']:>6,}")

    # 5. pillar match_method / requesting_org match_source（informational）
    for name, table, col, exp_key in [
            ("pillar match_method", "contract_pillar", "match_method",
             "pillar_match_method"),
            ("requesting_org match_source", "contract_requesting_org",
             "match_source", "requesting_org_match_source")]:
        act = {r[0]: r[1] for r in con.execute(
            f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col}")}
        exp_d = exp.get(exp_key, {})
        mism = {k: {"expected": v, "actual": act.get(k, 0)}
                for k, v in exp_d.items() if act.get(k, 0) < v * 0.98}
        check(name, len(exp_d), len(exp_d) - len(mism), not mism,
              level="warn", detail=mism)

    # 6. URL単位欠損
    act_urls = {r[0]: r[1] for r in con.execute(
        "SELECT source_url, COUNT(*) FROM contracts GROUP BY source_url")}
    missing = {u: {"expected": n, "actual": act_urls.get(u, 0)}
               for u, n in exp["url_rows"].items() if act_urls.get(u, 0) < n}
    missing_rows = sum(v["expected"] - v["actual"] for v in missing.values())
    check("URL欠損（informational）", 0, len(missing),
          len(missing) == 0, level="warn",
          detail={"missing_urls": len(missing), "missing_rows": missing_rows})
    MISSING_TXT.write_text("\n".join(sorted(missing)), encoding="utf-8")

    # 結果
    result = "FAIL" if fails else ("WARN" if warns else "PASS")
    report["result"] = result
    report["fails"] = fails
    report["warns"] = warns
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    print(f"\nSUMMARY result={result} fails={len(fails)} warns={len(warns)} "
          f"missing_urls={len(missing)} missing_rows={missing_rows:,}")
    print(f"レポート: {REPORT}")
    if missing:
        print(f"欠損URL: {MISSING_TXT}（downloader.py --urls で再取得→"
              f"replay_load.py 再実行）")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
