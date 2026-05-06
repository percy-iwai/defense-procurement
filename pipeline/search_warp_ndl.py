"""NDL WARP でスナップショット URL を探索し url_matrix に登録する。

WARP HEAD プローブ方式:
  https://warp.ndl.go.jp/{YYYYMMDD}/{YYYYMMDD}000000id_/{site_url}
  → 200 or 302 なら有効スナップとして確定

実行:
    python -m pipeline.search_warp_ndl --dry-run
    python -m pipeline.search_warp_ndl
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

TARGETS = [
    ("2025_07", "20250715"),
    ("2024_07", "20240715"),
    ("2023_07", "20230715"),
]

WARP_TIMEOUT = 5
MAX_WORKERS = 10

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; defense-procurement-research/1.0)"
})


def probe_warp(site_url: str, date_str: str) -> str | None:
    """WARP HEAD リクエストで指定日付のスナップショットを確認する。"""
    warp_url = f"https://warp.ndl.go.jp/{date_str}/{date_str}000000id_/{site_url}"
    try:
        r = SESSION.head(warp_url, timeout=WARP_TIMEOUT, allow_redirects=True)
        if r.status_code in (200, 302, 301):
            # display URL（id_ なし）を返す
            return f"https://warp.ndl.go.jp/{date_str}/{date_str}000000/{site_url}"
        return None
    except Exception:
        return None


def probe_one(agency_id: str, site_url: str, label: str, date_str: str) -> tuple[str, str, str | None]:
    """1リクエスト分: (agency_id, label, snap_url or None) を返す。"""
    snap = probe_warp(site_url, date_str)
    return (agency_id, label, snap)


def run(dry_run: bool = False) -> None:
    if not URL_DB.exists():
        logger.error(f"url_matrix.db が見つかりません: {URL_DB}")
        return

    with sqlite3.connect(URL_DB) as conn:
        rows = conn.execute(
            "SELECT agency_id, site_url FROM url_matrix "
            "WHERE site_url IS NOT NULL AND site_url != '' "
            "GROUP BY agency_id"
        ).fetchall()

    logger.info(f"対象機関数: {len(rows)}")
    total_req = len(rows) * len(TARGETS)
    logger.info(f"総リクエスト数: {total_req} (workers={MAX_WORKERS})")

    # (agency_id, label, snap_url) の全結果を収集
    results: dict[str, dict[str, str | None]] = {r[0]: {} for r in rows}

    tasks = [
        (agency_id, site_url, label, date_str)
        for agency_id, site_url in rows
        for label, date_str in TARGETS
    ]

    completed = 0
    hits = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(probe_one, agency_id, site_url, label, date_str): (agency_id, label)
            for agency_id, site_url, label, date_str in tasks
        }
        for future in as_completed(futures):
            agency_id, label, snap = future.result()
            results[agency_id][label] = snap
            completed += 1
            if snap:
                hits += 1
                logger.info(f"  HIT {agency_id} {label}: {snap}")
            if completed % 50 == 0 or completed == total_req:
                elapsed = time.time() - start
                logger.info(f"進捗: {completed}/{total_req} ({hits}ヒット) {elapsed:.0f}s")

    elapsed = time.time() - start
    logger.info(f"探索完了: {elapsed:.1f}s")

    # 期間別集計
    for label, _ in TARGETS:
        n = sum(1 for v in results.values() if v.get(label))
        logger.info(f"集計 {label}: {n}/{len(rows)} 件")

    if dry_run:
        logger.info("[dry-run] DB 書き込みをスキップ")
        return

    with sqlite3.connect(URL_DB) as conn:
        updated = 0
        for agency_id, snaps in results.items():
            sets, vals = [], []
            for label, val in snaps.items():
                if val is not None:
                    sets.append(f"site_url_{label} = ?")
                    vals.append(val)
            if sets:
                vals.append(agency_id)
                conn.execute(
                    f"UPDATE url_matrix SET {', '.join(sets)} WHERE agency_id = ?",
                    vals,
                )
                updated += 1
        conn.commit()
    logger.info(f"DB 更新: {updated} 機関")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
