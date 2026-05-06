"""防衛装備庁傘下機関（長官官房会計官・DISTI等）のPDF収集・DB投入。

P3パターン: pdf_ichiran/r{YY}/ インデックスページからPDFリンクを抽出し pdfplumber で解析。
URL生成: インデックス取得 + 命名規則が明確な機関は url_patterns で補完（404はスキップ）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from collectors.index_scraper import scrape_file_links  # noqa: E402
from parsers.pdf_table import parse_pdf_records  # noqa: E402
from pipeline.load_gsdf import INSERT_SQL, REQUIRED_KEYS, TARGET_FYS, _classify_url  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

_ATLA_INFO_BASE = "https://www.mod.go.jp/atla/data/info"


def _pdf_patterns(subpath: str, suffix: str, ry_range: range = range(4, 8),
                  nn_max: int = 20) -> list[str]:
    """研究所・試験場共通URLパターン生成。"""
    out = []
    for ry in ry_range:
        base = f"{_ATLA_INFO_BASE}/{subpath}/pdf_ichiran/r{ry:02d}"
        for ek in ("ekimu", "kouji"):
            for kd in ("kyousou", "zuikei"):
                for nn in range(1, nn_max + 1):
                    out.append(f"{base}/{ry:02d}-{ek}-{kd}-{suffix}-{nn:02d}.pdf")
    return out


def _index_urls(subpath: str, ry_range: range = range(4, 8)) -> list[str]:
    return [f"{_ATLA_INFO_BASE}/{subpath}/pdf_ichiran/r{ry:02d}/" for ry in ry_range]


ATLA_SUB_AGENCIES: list[dict] = [
    {
        "agency_id": "atla_kanbo",
        "agency_name": "防衛装備庁長官官房会計官",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_honbu"),
        "url_patterns": _pdf_patterns("ny_honbu", "h", nn_max=24),
    },
    {
        "agency_id": "atla_koukuu",
        "agency_name": "航空装備研究所",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_kenkyu_koukuu"),
        "url_patterns": _pdf_patterns("ny_kenkyu_koukuu", "ko"),
    },
    {
        "agency_id": "atla_riku",
        "agency_name": "陸上装備研究所",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_kenkyu_riku"),
        "url_patterns": _pdf_patterns("ny_kenkyu_riku", "r"),
    },
    {
        "agency_id": "atla_kantei",
        "agency_name": "艦艇装備研究所",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_kenkyu_kantei"),
        "url_patterns": _pdf_patterns("ny_kenkyu_kantei", "ka"),
    },
    {
        "agency_id": "atla_shinsedai",
        "agency_name": "新世代装備研究所",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_kenkyu_shinsedai", range(6, 8)),
        "url_patterns": _pdf_patterns("ny_kenkyu_shinsedai", "shi", range(6, 8)),
    },
    {
        "agency_id": "atla_chitose",
        "agency_name": "千歳試験場",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_chitose"),
        "url_patterns": _pdf_patterns("ny_chitose", "sa"),
    },
    {
        "agency_id": "atla_shimokita",
        "agency_name": "下北試験場",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_shimokita"),
        "url_patterns": _pdf_patterns("ny_shimokita", "sh"),
    },
    {
        "agency_id": "atla_gifu",
        "agency_name": "岐阜試験場",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_gifu"),
        "url_patterns": _pdf_patterns("ny_gifu", "g"),
    },
    {
        "agency_id": "atla_disti",
        "agency_name": "防衛イノベーション科学技術研究所",
        "agency_category": "防衛装備庁",
        "index_urls": _index_urls("ny_disti", range(6, 8)),
        "url_patterns": _pdf_patterns("ny_disti", "disti", range(6, 8)),
    },
]


def _enrich_record(rec: dict, *, agency: dict, source_url: str) -> dict:
    rec.update({
        "agency_id": agency["agency_id"],
        "agency_name": agency["agency_name"],
        "agency_category": agency.get("agency_category", "防衛装備庁"),
        "source_url": source_url,
        "source_type": "pdf",
    })
    if not rec.get("contract_type") or not rec.get("bid_method"):
        ctype, bid_default = _classify_url(source_url)
        if not rec.get("contract_type"):
            rec["contract_type"] = ctype or "調達適正化"
        if not rec.get("bid_method") and bid_default:
            rec["bid_method"] = bid_default
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def collect_agency(agency: dict) -> tuple[list[dict], dict]:
    stats = {"sources_tried": 0, "files_found": 0, "files_ok": 0, "rows_parsed": 0}
    records: list[dict] = []

    file_urls: set[str] = set()
    for index_url in agency.get("index_urls", []):
        try:
            links = scrape_file_links(index_url, extensions=(".pdf",))
        except Exception as e:
            logger.warning(f"index取得エラー: {index_url} - {e}")
            links = []
        if links:
            logger.info(f"  index {index_url} → {len(links)} links")
        for u, _ in links:
            file_urls.add(u)

    for u in agency.get("url_patterns", []) or []:
        file_urls.add(u)

    stats["files_found"] = len(file_urls)

    for url in sorted(file_urls):
        stats["sources_tried"] += 1
        data = fetch(url)
        if data is None:
            continue
        stats["files_ok"] += 1
        try:
            recs_raw = list(parse_pdf_records(data, target_fys=TARGET_FYS))
        except Exception as e:
            logger.warning(f"PDF解析エラー: {url} - {e}")
            continue
        for rec in recs_raw:
            records.append(_enrich_record(rec, agency=agency, source_url=url))
        if recs_raw:
            logger.info(f"  [{Path(url).name}] {len(recs_raw)}件")
        stats["rows_parsed"] += len(recs_raw)

    return records, stats


def collect_and_load(*, db_path: Path = DB_PATH, dry_run: bool = False,
                     filter_agency: list[str] | None = None) -> dict:
    agencies = ATLA_SUB_AGENCIES
    if filter_agency:
        agencies = [a for a in agencies if a["agency_id"] in filter_agency]

    overall = {"agencies": 0, "files_ok": 0, "rows_parsed": 0,
               "inserted": 0, "duplicates": 0, "per_agency": {}}
    all_records: list[dict] = []

    for agency in agencies:
        logger.info(f"=== {agency['agency_id']} ({agency['agency_name']}) ===")
        records, stats = collect_agency(agency)
        all_records.extend(records)
        overall["per_agency"][agency["agency_id"]] = stats
        overall["files_ok"] += stats["files_ok"]
        overall["rows_parsed"] += stats["rows_parsed"]
        overall["agencies"] += 1

    if dry_run:
        return {"records": all_records, **overall}

    inserted = duplicates = skipped = 0
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for rec in all_records:
            if not rec.get("fiscal_year"):
                skipped += 1
                continue
            cur.execute(INSERT_SQL, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()
    overall["inserted"] = inserted
    overall["duplicates"] = duplicates
    overall["skipped_no_fy"] = skipped
    logger.info(f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件 / スキップ {skipped}件")
    return overall


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--agency", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    result = collect_and_load(dry_run=args.dry_run, filter_agency=args.agency)
    print("\n=== 機関別 ===")
    for aid, s in result["per_agency"].items():
        print(f"  {aid:<25} files_ok={s['files_ok']:>4}/{s['files_found']:<4}  rows={s['rows_parsed']:>5}")
