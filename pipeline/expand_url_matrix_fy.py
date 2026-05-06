"""url_matrix.db に fiscal_year カラムを追加し、FY2022/2023/2025 の行を複製する。

実行後: 4,608行(FY2024のみ) → 18,432行(FY2022/2023/2024/2025)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"


def run() -> None:
    with sqlite3.connect(URL_DB) as conn:
        # --- 1-A: fiscal_year カラム追加（既存行は DEFAULT 2024）---
        cols = {r[1] for r in conn.execute("PRAGMA table_info(url_matrix)")}
        if "fiscal_year" not in cols:
            conn.execute("ALTER TABLE url_matrix ADD COLUMN fiscal_year INTEGER DEFAULT 2024")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_um_fy ON url_matrix(fiscal_year, agency_id)"
            )
            conn.commit()
            logger.info("fiscal_year カラム追加完了（既存行 = 2024）")
        else:
            logger.info("fiscal_year カラムは既存")

        existing_fys = {r[0] for r in conn.execute(
            "SELECT DISTINCT fiscal_year FROM url_matrix"
        ).fetchall()}
        logger.info(f"既存FY: {sorted(existing_fys)}")

        base_count = conn.execute(
            "SELECT COUNT(*) FROM url_matrix WHERE fiscal_year = 2024"
        ).fetchone()[0]
        logger.info(f"FY2024行数: {base_count}")

        # --- 1-B: FY2022/2023/2025 行を生成 ---
        for new_fy in [2022, 2023, 2025]:
            if new_fy in existing_fys:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM url_matrix WHERE fiscal_year=?", (new_fy,)
                ).fetchone()[0]
                logger.info(f"FY{new_fy} 既存: {cnt}行 → スキップ")
                continue

            conn.execute("""
                INSERT INTO url_matrix
                  (excel_row, agency_name, agency_id, category, bid_method, month,
                   status, flag_rolling, flag_warp, flag_mixed_cat, flag_mixed_month,
                   flag_collected, flag_404, site_url,
                   site_url_2025_07, site_url_2024_07, site_url_2023_07, sort_order,
                   fiscal_year)
                SELECT
                  excel_row, agency_name, agency_id, category, bid_method, month,
                  'dash', 0, 0, 0, 0, 0, 0,
                  site_url, site_url_2025_07, site_url_2024_07, site_url_2023_07,
                  sort_order, ?
                FROM url_matrix WHERE fiscal_year = 2024
            """, (new_fy,))
            inserted = conn.execute(
                "SELECT COUNT(*) FROM url_matrix WHERE fiscal_year=?", (new_fy,)
            ).fetchone()[0]
            logger.info(f"FY{new_fy} 挿入: {inserted}行")

        conn.commit()

        # --- 確認 ---
        totals = conn.execute(
            "SELECT fiscal_year, COUNT(*) FROM url_matrix GROUP BY fiscal_year ORDER BY fiscal_year"
        ).fetchall()
        logger.info("FY別行数:")
        for fy, cnt in totals:
            logger.info(f"  FY{fy}: {cnt}行")
        total = sum(c for _, c in totals)
        logger.info(f"合計: {total}行")


if __name__ == "__main__":
    run()
