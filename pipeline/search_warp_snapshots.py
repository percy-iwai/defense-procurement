"""Wayback Machine CDX API でスナップショット URL を探索し url_matrix に登録する。

NDL WARP はタイムスタンプを事前に知る方法がないため Wayback Machine を使用する。
mod.go.jp は archive.org にも収録されており十分な代替となる。

実行:
    python -m pipeline.search_warp_snapshots --dry-run   # 確認のみ
    python -m pipeline.search_warp_snapshots             # DB 書き込み
    python -m pipeline.search_warp_snapshots --limit 10  # 最大10機関
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

TARGETS = [
    ("2025_07", 2025, 7),
    ("2024_07", 2024, 7),
    ("2023_07", 2023, 7),
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; defense-procurement-research/1.0)"
})
CDX_TIMEOUT = 20


def probe_wayback(url: str, year: int, month: int) -> str | None:
    """Wayback CDX API で当該年月の最初の 200 スナップショットを返す。"""
    from_ts = f"{year}{month:02d}01000000"
    to_ts   = f"{year}{month:02d}31235959"
    cdx = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={quote(url, safe='')}"
        f"&output=json&from={from_ts}&to={to_ts}"
        "&limit=1&fl=timestamp"
        "&filter=statuscode:200&matchType=prefix&collapse=urlkey"
    )
    try:
        r = SESSION.get(cdx, timeout=CDX_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        if len(data) < 2:
            return None
        ts = data[1][0]
        return f"https://web.archive.org/web/{ts}/{url}"
    except Exception:
        return None


def run(dry_run: bool = False, limit: int | None = None) -> None:
    if not URL_DB.exists():
        logger.error(f"url_matrix.db が見つかりません: {URL_DB}")
        return

    with sqlite3.connect(URL_DB) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(url_matrix)")}
        for label, _, _ in TARGETS:
            if f"site_url_{label}" not in cols:
                logger.warning(f"カラム site_url_{label} がありません。setup_categories.py を先に実行してください。")
                return

        rows = conn.execute(
            "SELECT agency_id, site_url FROM url_matrix "
            "WHERE site_url IS NOT NULL AND site_url != ''"
        ).fetchall()

    seen: dict[str, str] = {}
    for agency_id, site_url in rows:
        if agency_id not in seen:
            seen[agency_id] = site_url

    targets = list(seen.items())
    if limit:
        targets = targets[:limit]

    logger.info(f"対象機関数: {len(targets)}")

    results: dict[str, dict[str, str | None]] = {}
    for i, (agency_id, site_url) in enumerate(targets, 1):
        logger.info(f"[{i}/{len(targets)}] {agency_id}")
        results[agency_id] = {}
        any_found = False
        for label, year, month in TARGETS:
            snap = probe_wayback(site_url, year, month)
            results[agency_id][label] = snap
            if snap:
                any_found = True
                logger.info(f"  {label}: ✓ {snap}")
            else:
                logger.debug(f"  {label}: ✗")
        if not any_found:
            logger.info(f"  → 全期間ヒットなし")
        if i < len(targets):
            time.sleep(0.5)

    for label, _, _ in TARGETS:
        found = sum(1 for v in results.values() if v.get(label))
        logger.info(f"集計 {label}: {found}/{len(targets)} 件")

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
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
