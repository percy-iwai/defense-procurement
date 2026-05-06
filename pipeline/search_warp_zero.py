"""ゼロヒット33機関に対する多アプローチWARP再探索。

アプローチ:
  1. URL階層を上に辿る（最大4レベル）
  2. index.html 付きを試す
  3. 末尾スラッシュ有無両方試す
  4. MSDF bukei 共通ページを試す
  5. 試行日付を増やす（1, 10, 15, 20, 28日）

実行:
    python -m pipeline.search_warp_zero --dry-run
    python -m pipeline.search_warp_zero
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

ZERO_HIT_AGENCIES = [
    "asdf_shizuhama",
    "atla", "atla_chitose", "atla_disti", "atla_gifu",
    "atla_kantei", "atla_koukuu", "atla_riku", "atla_shimokita", "atla_shinsedai",
    "gsdf_buki", "gsdf_cfin", "gsdf_ctrans", "gsdf_eisei", "gsdf_gmcc",
    "msdf_asd", "msdf_d0", "msdf_d1", "msdf_dw", "msdf_dy",
    "msdf_k0", "msdf_k1", "msdf_k2", "msdf_k7", "msdf_s0",
    "msdf_sa", "msdf_sn", "msdf_y0", "msdf_y2", "msdf_yd",
    "rdb_kinchu", "rdb_n_kanto", "rdb_s_kanto",
]

# (label, [dates to try in priority order])
PERIODS = [
    ("2025_07", ["20250715", "20250701", "20250710", "20250720", "20250728"]),
    ("2024_07", ["20240715", "20240701", "20240710", "20240720", "20240728"]),
    ("2023_07", ["20230715", "20230701", "20230710", "20230720", "20230728"]),
]

WARP_TIMEOUT = 5
MAX_WORKERS = 20

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; defense-procurement-research/1.0)"
})


def get_url_variants(url: str, agency_id: str) -> list[tuple[str, int]]:
    """URL変種リストを (url, priority) で返す。priority 小さいほど優先。"""
    parsed = urlparse(url)
    path = parsed.path
    variants: list[tuple[str, int]] = []

    # Priority 0: 元URL
    variants.append((url, 0))

    # Priority 1: 末尾スラッシュ反転
    if path.endswith('/'):
        toggled = path.rstrip('/')
    else:
        toggled = path + '/'
    variants.append((urlunparse(parsed._replace(path=toggled)), 1))

    # Priority 2: index.html 付加
    base = path if path.endswith('/') else path + '/'
    variants.append((urlunparse(parsed._replace(path=base + 'index.html')), 2))

    # Priority 3〜6: 親ディレクトリ（最大4レベル上）
    parts = [p for p in path.split('/') if p]
    for level, i in enumerate(range(len(parts) - 1, max(len(parts) - 5, 0), -1)):
        parent_path = '/' + '/'.join(parts[:i]) + '/'
        variants.append((urlunparse(parsed._replace(path=parent_path)), 3 + level))

    # Special: MSDF bukei 共通ページ
    if agency_id.startswith('msdf_'):
        variants.append(('https://www.mod.go.jp/msdf/bukei/', 8))
        variants.append(('https://www.mod.go.jp/msdf/bukei/keiyakukeka_menu.html', 9))
        variants.append(('https://www.mod.go.jp/msdf/', 10))

    # Special: ATLA → atla/
    if agency_id.startswith('atla'):
        variants.append(('https://www.mod.go.jp/atla/', 10))

    # Special: GSDF
    if agency_id.startswith('gsdf_'):
        variants.append(('https://www.mod.go.jp/gsdf/', 10))

    # 重複除去（順序維持）
    seen: set[str] = set()
    result: list[tuple[str, int]] = []
    for v, p in variants:
        if v not in seen:
            seen.add(v)
            result.append((v, p))
    return result


def probe_warp(url: str, date_str: str) -> str | None:
    """WARP HEAD プローブ。ヒットすれば表示用 URL を返す。"""
    warp_url = f"https://warp.ndl.go.jp/{date_str}/{date_str}000000id_/{url}"
    try:
        r = SESSION.head(warp_url, timeout=WARP_TIMEOUT, allow_redirects=True)
        if r.status_code in (200, 301, 302):
            return f"https://warp.ndl.go.jp/{date_str}/{date_str}000000/{url}"
        return None
    except Exception:
        return None


def run(dry_run: bool = False) -> None:
    with sqlite3.connect(URL_DB) as conn:
        placeholders = ','.join('?' * len(ZERO_HIT_AGENCIES))
        rows = conn.execute(
            f"SELECT agency_id, site_url FROM url_matrix "
            f"WHERE agency_id IN ({placeholders}) "
            f"AND site_url IS NOT NULL AND site_url != '' "
            f"GROUP BY agency_id",
            ZERO_HIT_AGENCIES,
        ).fetchall()

    agency_urls = {r[0]: r[1] for r in rows}
    logger.info(f"対象機関: {len(agency_urls)}")

    # 全タスク生成: (agency_id, label, url_var, date_str, composite_priority)
    # composite_priority = url_priority * 100 + date_index（小さいほど優先）
    tasks: list[tuple[str, str, str, str, int]] = []
    for agency_id, site_url in agency_urls.items():
        url_variants = get_url_variants(site_url, agency_id)
        for label, dates in PERIODS:
            for date_idx, date_str in enumerate(dates):
                for url_var, url_prio in url_variants:
                    prio = url_prio * 100 + date_idx
                    tasks.append((agency_id, label, url_var, date_str, prio))

    logger.info(f"総リクエスト数: {len(tasks)} (workers={MAX_WORKERS})")

    # (agency_id, label) → (best_priority, snap_url)
    best: dict[tuple[str, str], tuple[int, str]] = {}
    completed = 0
    hits = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {
            pool.submit(probe_warp, url_var, date_str): (agency_id, label, url_var, prio)
            for agency_id, label, url_var, date_str, prio in tasks
        }
        for future in as_completed(future_map):
            agency_id, label, url_var, prio = future_map[future]
            snap = future.result()
            completed += 1
            if snap:
                key = (agency_id, label)
                if key not in best or prio < best[key][0]:
                    best[key] = (prio, snap)
                    hits += 1
                    logger.info(f"  HIT {agency_id} {label} prio={prio}: {snap}")
            if completed % 300 == 0 or completed == len(tasks):
                logger.info(
                    f"進捗: {completed}/{len(tasks)} ({hits}ヒット) {time.time()-start:.0f}s"
                )

    elapsed = time.time() - start
    logger.info(f"探索完了: {elapsed:.1f}s")

    # 期間別集計
    hit_agencies: set[str] = set()
    for label, _ in PERIODS:
        n = sum(1 for (aid, lbl) in best if lbl == label)
        logger.info(f"集計 {label}: {n}/{len(agency_urls)} 件ヒット")
        for (aid, lbl) in best:
            if lbl == label:
                hit_agencies.add(aid)

    still_zero = [a for a in ZERO_HIT_AGENCIES if a not in hit_agencies]
    logger.info(f"解消: {len(hit_agencies)}/{len(agency_urls)} 機関")
    if still_zero:
        logger.info(f"残存ゼロヒット: {still_zero}")

    if dry_run:
        logger.info("[dry-run] DB 書き込みをスキップ")
        return

    # DB書き込み: label単位で最良スナップを更新
    grouped: dict[str, dict[str, str]] = {}
    for (agency_id, label), (_, snap) in best.items():
        grouped.setdefault(agency_id, {})[label] = snap

    with sqlite3.connect(URL_DB) as conn:
        updated = 0
        for agency_id, snaps in grouped.items():
            sets = [f"site_url_{label} = ?" for label in snaps]
            vals = list(snaps.values()) + [agency_id]
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
