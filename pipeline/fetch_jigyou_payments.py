"""FY2022/2023の行政事業レビュー contractor-payments を API から取得して DB に投入する。

使用方法:
    python -m pipeline.fetch_jigyou_payments --fy 2023
    python -m pipeline.fetch_jigyou_payments --fy 2022 2023
    python -m pipeline.fetch_jigyou_payments --fy 2023 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from loguru import logger

from collectors.http_client import fetch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "jigyou_review.db"

RATE_LIMIT_SEC = 0.5  # rssystem は静的API、0.5秒で十分


def _fetch_contractor_payments(project_id: str) -> list[dict]:
    """1事業の contractor-payments を取得。失敗時は空リスト。"""
    url = f"https://rssystem.go.jp/api/projects/{project_id}/contractor-payments/"
    data = fetch(url, is_warp=False)
    if not data:
        return []
    try:
        result = json.loads(data)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


def _payments_to_rows(project_id: str, fiscal_year: int, items: list[dict]) -> list[tuple]:
    """API レスポンスを payments テーブルの行タプルに変換。"""
    rows = []
    for rank, item in enumerate(items, start=1):
        payee_name = item.get("name")
        corporate_number = item.get("corporate_number")
        amount = item.get("total_contract_amount")
        cost_type = item.get("type")
        contracts = item.get("contracts", [])
        note = f"contracts={len(contracts)}, is_others={item.get('is_others', False)}"
        rows.append((project_id, fiscal_year, rank, payee_name, corporate_number, amount, cost_type, note))
    return rows


def run(target_fys: list[int], dry_run: bool = False) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        for fy in target_fys:
            project_ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM projects WHERE fiscal_year=?", (fy,)
                ).fetchall()
            ]
            logger.info(f"FY{fy}: {len(project_ids)}事業のpayments取得開始")

            inserted = 0
            skipped = 0
            empty = 0

            for i, pid in enumerate(project_ids):
                # 既存チェック
                existing = conn.execute(
                    "SELECT COUNT(*) FROM payments WHERE project_id=? AND fiscal_year=?",
                    (pid, fy)
                ).fetchone()[0]
                if existing > 0:
                    skipped += 1
                    continue

                items = _fetch_contractor_payments(pid)
                time.sleep(RATE_LIMIT_SEC)

                if not items:
                    empty += 1
                    if (i + 1) % 50 == 0:
                        logger.debug(f"  FY{fy}: {i+1}/{len(project_ids)} 処理中 (空={empty})")
                    continue

                rows = _payments_to_rows(pid, fy, items)
                if not dry_run:
                    conn.executemany(
                        """INSERT OR IGNORE INTO payments
                           (project_id, fiscal_year, rank, payee_name, corporate_number, amount, cost_type, note)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        rows,
                    )
                    conn.commit()
                inserted += len(rows)

                if (i + 1) % 20 == 0:
                    logger.info(f"  FY{fy}: {i+1}/{len(project_ids)} 処理中 — 挿入:{inserted}行, 空:{empty}")

            logger.info(f"FY{fy} 完了 — 挿入:{inserted}行, スキップ:{skipped}件, 空:{empty}件")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fy", nargs="+", type=int, default=[2023], help="対象年度")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run(args.fy, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
