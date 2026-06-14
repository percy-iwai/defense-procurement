"""ギャップフィル: 期待値に満たない source_url を直接リプレイして投入する。

rebuild_all.py の既存ローダー群はインデックスページ経由でURLを発見するため、
ライブページからリンクが消えたファイルを取りこぼすことがある。
本スクリプトは expected_state.json の URL×agency 別期待行数と再構築DBを突合し、
不足している source_url を data/raw/_cache/（downloader.py が温めた）から
直接パースして INSERT OR IGNORE で投入する。

パーサーは pipeline/load_from_urlmatrix.py の汎用パース部をそのまま流用する。

実行:
  python kit/replay_load.py             # 不足URLを全て処理
  python kit/replay_load.py --dry-run   # 不足URL一覧の表示のみ
  python kit/replay_load.py --limit 50  # 上限つき

出力:
  kit/exports/replay_gaps_report.json   # 処理結果と残ギャップ
  kit/exports/missing_urls.txt          # なお埋まらないURL（downloader --urls 用）
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from pipeline.load_from_urlmatrix import (  # noqa: E402
    _build_agency_meta,
    _detect_type,
    _insert_records,
    _is_warp,
    _parse_excel_url,
    _parse_html_url,
    _parse_pdf_url,
)

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
EXPORTS = PROJECT_ROOT / "kit" / "exports"
EXPECTED = EXPORTS / "expected_state.json"
REPORT = EXPORTS / "replay_gaps_report.json"
MISSING_TXT = EXPORTS / "missing_urls.txt"


def find_gaps(con: sqlite3.Connection, expected: dict) -> list[dict]:
    """期待値に満たない (url, agency_id, expected, actual) を返す。"""
    actual: dict[tuple[str, str], int] = {}
    for url, aid, n in con.execute(
            "SELECT source_url, agency_id, COUNT(*) FROM contracts "
            "GROUP BY source_url, agency_id"):
        actual[(url, aid)] = n

    gaps = []
    for rec in expected["url_agency_rows"]:
        url, aid, exp = rec["source_url"], rec["agency_id"], rec["rows"]
        act = actual.get((url, aid), 0)
        if act < exp:
            gaps.append({"url": url, "agency_id": aid,
                         "expected": exp, "actual": act})
    return gaps


def replay_one(con: sqlite3.Connection, url: str, agency_id: str,
               agency_name: str) -> int:
    """1 URL × 1 agency をパースして投入。投入行数を返す。"""
    meta = _build_agency_meta(agency_id, agency_name)
    url_type = _detect_type(url)

    if url_type == "html":
        records = _parse_html_url(url, meta)
    else:
        data = fetch(url, is_warp=_is_warp(url))
        if data is None:
            return -1  # 取得不能
        if url_type == "excel":
            records = _parse_excel_url(data, url, meta)
        elif url_type == "pdf":
            records = _parse_pdf_url(data, url, meta)
        else:
            return -2  # 未知タイプ
    if not records:
        return 0
    return _insert_records(records, con)


def main() -> None:
    parser = argparse.ArgumentParser(description="不足URLの直接リプレイ投入")
    parser.add_argument("--dry-run", action="store_true", help="一覧表示のみ")
    parser.add_argument("--limit", type=int, help="処理URL数上限")
    args = parser.parse_args()

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    agencies = expected.get("agencies", {})

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")

    gaps = find_gaps(con, expected)
    # URL単位でまとめる（同一URL複数agencyあり）
    by_url: dict[str, list[dict]] = defaultdict(list)
    for g in gaps:
        by_url[g["url"]].append(g)

    missing_rows = sum(g["expected"] - g["actual"] for g in gaps)
    print(f"不足: {len(gaps)} (url×agency) / {len(by_url)} URL / {missing_rows:,}行")

    if args.dry_run:
        for url, gs in list(by_url.items())[:30]:
            tot = sum(g["expected"] - g["actual"] for g in gs)
            print(f"  -{tot:>5,}行 {url[:100]}")
        if len(by_url) > 30:
            print(f"  ... 他{len(by_url) - 30} URL")
        return

    urls = list(by_url.items())
    if args.limit:
        urls = urls[: args.limit]

    results = []
    inserted_total = 0
    unfetchable: list[str] = []
    for i, (url, gs) in enumerate(urls, 1):
        for g in gs:
            aid = g["agency_id"]
            aname = agencies.get(aid, {}).get("agency_name") or aid
            n = replay_one(con, url, aid, aname)
            if n == -1:
                unfetchable.append(url)
            results.append({**g, "inserted": max(n, 0)})
            if n > 0:
                inserted_total += n
        if i % 50 == 0:
            print(f"進捗 {i}/{len(urls)} URL  投入 {inserted_total:,}行")

    # 残ギャップ再計算
    remaining = find_gaps(con, expected)
    con.close()

    REPORT.write_text(json.dumps(
        {"ts": datetime.now().isoformat(),
         "processed_urls": len(urls), "inserted_rows": inserted_total,
         "remaining_gaps": len(remaining),
         "remaining_rows": sum(g["expected"] - g["actual"] for g in remaining),
         "unfetchable_urls": sorted(set(unfetchable)),
         "details": remaining},
        ensure_ascii=False, indent=1), encoding="utf-8")

    rem_urls = sorted({g["url"] for g in remaining})
    MISSING_TXT.write_text("\n".join(rem_urls), encoding="utf-8")

    print(f"SUMMARY inserted={inserted_total:,} remaining_gap_rows="
          f"{sum(g['expected'] - g['actual'] for g in remaining):,} "
          f"remaining_urls={len(rem_urls)}")
    print(f"レポート: {REPORT}")
    if rem_urls:
        print(f"未解決URL一覧: {MISSING_TXT}（downloader.py --urls に渡して再取得可）")


if __name__ == "__main__":
    main()
