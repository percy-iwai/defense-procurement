"""Phase 1: ATLA本庁 FY2024 を end-to-end で実行する。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.init_db import init_db  # noqa: E402
from pipeline.load_atla import DB_PATH, collect_and_load  # noqa: E402


def main(years: list[int] | None = None) -> None:
    init_db()
    years = years or [2024]
    for fy in years:
        print(f"\n--- FY{fy} 収集中 ---")
        stats = collect_and_load(fy)
        print(f"FY{fy} stats: {stats}")

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        print("\n=== DB集計 ===")
        for fy in (2022, 2023, 2024, 2025):
            row = cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(contract_amount), 0) "
                "FROM contracts WHERE fiscal_year=?",
                (fy,),
            ).fetchone()
            print(f"FY{fy}: 件数={row[0]:,}  総額={row[1]/1e8:,.1f}億円")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--fy", type=int, nargs="+", default=[2024])
    args = p.parse_args()
    main(args.fy)
