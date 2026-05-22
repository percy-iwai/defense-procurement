"""陸上自衛隊 (GSDF) 25機関のPDF/HTMLデータをcollect→parse→DB投入。

戦略:
- index_urls から拡張子 .pdf のリンクを抽出
- url_patterns があれば iter で 404 スキップ
- scrape_html_tables=True の機関は HTML テーブル直接抽出（gsdf_eafin）
- contract_date FY ガード付き
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from collectors.index_scraper import scrape_file_links, scrape_html_tables  # noqa: E402
from parsers.pdf_table import (  # noqa: E402
    _normalize_bid as pdf_norm_bid,
    _to_amount as pdf_to_amount,
    _to_date_str as pdf_to_date,
    _to_rate as pdf_to_rate,
    fy_from_date,
    parse_pdf_records,
)
from pipeline.gsdf_config import GSDF_AGENCIES  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

INSERT_SQL = """
INSERT OR IGNORE INTO contracts (
    agency_id, agency_name, agency_category,
    fiscal_year, contract_type,
    contract_name, vendor_name, vendor_address, corporate_number,
    contract_amount, estimated_price, award_rate,
    bid_method, zuii_reason, contract_date, contract_officer,
    quantity, unit_measure,
    source_url, source_type
) VALUES (
    :agency_id, :agency_name, :agency_category,
    :fiscal_year, :contract_type,
    :contract_name, :vendor_name, :vendor_address, :corporate_number,
    :contract_amount, :estimated_price, :award_rate,
    :bid_method, :zuii_reason, :contract_date, :contract_officer,
    :quantity, :unit_measure,
    :source_url, :source_type
)
"""

REQUIRED_KEYS = [
    "contract_name", "vendor_name", "vendor_address", "corporate_number",
    "contract_amount", "estimated_price", "award_rate",
    "bid_method", "zuii_reason", "contract_date", "contract_officer",
    "quantity", "unit_measure", "contract_type",
]

TARGET_FYS = {2022, 2023, 2024, 2025}


def _fy_from_pdf_url(url: str) -> int | None:
    """URLから令和年度→FYを推定。
    koukyou7.4.pdf → R7年4月 → FY2025 (月>=4なのでそのまま 2018+7=2025)
    koukyou7.1.pdf → R7年1月 → FY2024 (月<4なので 2018+7-1=2024)
    hzyo071201.pdf → R7年12月 → FY2025
    汎用: [rR]0?(\\d{1,2})[\\.\\-_]?(\\d{1,2}) 形式"""
    # hzyo{RR}{MM}{NN}.pdf pattern (gsdf_gmcc 補給統制本部)
    m = re.search(r"hzyo(\d{2})(\d{2})\d{2}\.pdf", url.lower())
    if m:
        ry, mm = int(m.group(1)), int(m.group(2))
        if 1 <= ry <= 20 and 1 <= mm <= 12:
            base = 2018 + ry
            return base if mm >= 4 else base - 1
    # 汎用パターン
    m = re.search(r"[rR]0?(\d{1,2})[\.\-_](\d{1,2})", url)
    if m:
        ry, mm = int(m.group(1)), int(m.group(2))
        if 1 <= ry <= 20 and 1 <= mm <= 12:
            base = 2018 + ry
            return base if mm >= 4 else base - 1
    return None


def _classify_url(url: str) -> tuple[str | None, str | None]:
    u = url.lower()
    if any(t in u for t in ("zuikei", "zui", "_z.", "z_", "z6", "z7", "随意")):
        return ("随意契約", "随意契約")
    if any(t in u for t in ("kyousou", "kyoso", "kyo_", "_k.")):
        return ("一般競争", "一般競争入札")
    return (None, None)


def _enrich_record(rec: dict, *, agency: dict, source_url: str,
                   source_type: str) -> dict:
    rec.update({
        "agency_id": agency["agency_id"],
        "agency_name": agency["agency_name"],
        "agency_category": "陸上自衛隊",
        "source_url": source_url,
        "source_type": source_type,
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


def _process_pdf(data: bytes, *, url: str, agency: dict) -> list[dict]:
    out: list[dict] = []
    url_fy_fallback = agency.get("url_fy_fallback", False)
    url_fy = _fy_from_pdf_url(url) if url_fy_fallback else None
    for rec in parse_pdf_records(data, target_fys=TARGET_FYS):
        # contract_date なし & url_fy_fallback 有効 → URLのFYで補完
        if not rec.get("fiscal_year") and url_fy and url_fy in TARGET_FYS:
            rec["fiscal_year"] = url_fy
        rec = _enrich_record(rec, agency=agency, source_url=url, source_type="pdf")
        out.append(rec)
    return out


def _process_html_tables(html_url: str, agency: dict) -> list[dict]:
    """gsdf_eafin 向け: HTMLテーブル → records。"""
    tables = scrape_html_tables(html_url)
    if not tables:
        return []

    out: list[dict] = []
    for tbl in tables:
        if len(tbl) < 2:
            continue
        # find header row by scanning first 5 rows
        h_idx = -1
        for i, r in enumerate(tbl[:5]):
            text = " ".join(str(c) for c in r if c)
            if any(t in text for t in ("契約金額", "落札金額")) and any(k in text for k in ("名称", "件名", "業務", "工事", "品名")):
                h_idx = i
                break
        if h_idx < 0:
            continue
        header = tbl[h_idx]
        col_map: dict[str, int] = {}
        for i, h in enumerate(header):
            hh = str(h).replace("\n", "").replace(" ", "")
            for kw, fld in [
                ("件名", "contract_name"), ("名称", "contract_name"),
                ("品名", "contract_name"),
                ("業者", "vendor_name"), ("相手方", "vendor_name"),
                ("法人番号", "corporate_number"),
                ("契約金額", "contract_amount"), ("落札金額", "contract_amount"),
                ("予定価格", "estimated_price"), ("落札率", "award_rate"),
                ("入札方式", "bid_method"), ("入札・指名", "bid_method"),
                ("締結日", "contract_date"), ("契約日", "contract_date"),
                ("締結年月日", "contract_date"), ("締結した日", "contract_date"),
            ]:
                if kw in hh and fld not in col_map:
                    col_map[fld] = i
                    break
        if "contract_amount" not in col_map:
            continue

        for row in tbl[h_idx + 1:]:
            if col_map["contract_amount"] >= len(row):
                continue
            amt = pdf_to_amount(row[col_map["contract_amount"]])
            if not amt or amt < 1000:
                continue

            rec: dict = {"contract_amount": amt}
            for fld in ("contract_name", "vendor_name", "corporate_number",
                        "estimated_price", "award_rate", "bid_method",
                        "contract_date"):
                if fld in col_map and col_map[fld] < len(row):
                    val = row[col_map[fld]]
                    if not val:
                        continue
                    if fld == "estimated_price":
                        rec[fld] = pdf_to_amount(val)
                    elif fld == "award_rate":
                        rec[fld] = pdf_to_rate(val)
                    elif fld == "bid_method":
                        rec[fld] = pdf_norm_bid(val)
                    elif fld == "contract_date":
                        rec[fld] = pdf_to_date(val)
                    elif fld == "corporate_number":
                        cn = re.sub(r"\D", "", str(val))
                        if re.match(r"^\d{13}$", cn):
                            rec[fld] = cn
                    elif fld == "vendor_name":
                        # "会社名\n住所" 形式の分離
                        lines = [l.strip() for l in str(val).split("\n") if l.strip()]
                        if lines:
                            rec["vendor_name"] = lines[0][:300]
                            if len(lines) > 1:
                                rec["vendor_address"] = " / ".join(lines[1:])[:500]
                    else:
                        rec[fld] = str(val).strip()[:500]

            cd_fy = fy_from_date(rec.get("contract_date"))
            if cd_fy is None or cd_fy not in TARGET_FYS:
                continue
            rec["fiscal_year"] = cd_fy
            rec = _enrich_record(rec, agency=agency, source_url=html_url, source_type="html")
            out.append(rec)
    return out


def collect_agency(agency: dict) -> tuple[list[dict], dict]:
    aid = agency["agency_id"]
    stats = {"sources_tried": 0, "files_found": 0, "files_ok": 0, "rows_parsed": 0}
    records: list[dict] = []

    # HTMLテーブル直接（gsdf_eafin）
    if agency.get("scrape_html_tables"):
        for url in agency.get("index_urls", []):
            stats["sources_tried"] += 1
            try:
                recs = _process_html_tables(url, agency)
            except Exception as e:
                logger.warning(f"HTML解析エラー: {url} - {e}")
                recs = []
            if recs:
                stats["files_ok"] += 1
            records.extend(recs)
            stats["rows_parsed"] += len(recs)
            if recs:
                logger.info(f"  [html] {url}: {len(recs)}件")
        return records, stats

    # 通常: index → PDF リンク収集
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

    # url_patterns 補完（404はスキップ）
    for u in agency.get("url_patterns", []) or []:
        file_urls.add(u)

    stats["files_found"] = len(file_urls)

    for url in sorted(file_urls):
        stats["sources_tried"] += 1
        try:
            data = fetch(url)
        except Exception as e:
            logger.warning(f"fetch失敗: {url} - {e}")
            continue
        if data is None:
            continue
        stats["files_ok"] += 1

        try:
            recs = _process_pdf(data, url=url, agency=agency)
        except Exception as e:
            logger.warning(f"PDF処理エラー: {url} - {e}")
            recs = []
        records.extend(recs)
        stats["rows_parsed"] += len(recs)
        if recs:
            logger.info(f"  [{Path(url).name}] {len(recs)}件")

    return records, stats


def collect_and_load(*, db_path: Path = DB_PATH, dry_run: bool = False,
                     filter_agency: list[str] | None = None) -> dict:
    agencies = GSDF_AGENCIES
    if filter_agency:
        agencies = [a for a in agencies if a["agency_id"] in filter_agency]

    overall = {"agencies": 0, "files_ok": 0, "rows_parsed": 0,
               "inserted": 0, "duplicates": 0, "skipped_no_fy": 0,
               "per_agency": {}}
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

    inserted = 0
    duplicates = 0
    skipped = 0
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
    logger.info(f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件 / スキップ {skipped}件 / 機関 {overall['agencies']}")
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
        print(f"  {aid:<22} files_ok={s['files_ok']:>4}/{s['files_found']:<4}  rows={s['rows_parsed']:>5}")
