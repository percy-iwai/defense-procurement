"""防衛監察本部（igo）の調達データ収集スクリプト。

Sources:
  - Aggregated annual files: R4_k_buppinekimu.pdf, R5_k_buppin_ekimu.pdf, etc.
  - Individual kekka files: koukoku_*_kekka.pdf, open_*_kekka.pdf, opencounter_*_kekka.pdf
"""
from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import pdfplumber
import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROC_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; defense-procurement-research/1.0)"})
TIMEOUT = 20

BASE_URL = "https://www.mod.go.jp/igo/procurement/index.html"
PDF_BASE = "https://www.mod.go.jp/igo/procurement/pdf/"

AGENCY_ID = "igo"
AGENCY_NAME = "防衛監察本部"


def _fy_from_date(yyyymmdd: str) -> Optional[int]:
    if not yyyymmdd or len(yyyymmdd) < 6:
        return None
    y, m = int(yyyymmdd[:4]), int(yyyymmdd[4:6])
    return y if m >= 4 else y - 1


def _to_amount(text) -> Optional[int]:
    if text is None:
        return None
    s = str(text).replace(",", "").replace("，", "").replace("円", "").replace("¥", "").strip()
    s = re.sub(r"[^\d\.\-]", "", s)
    if not s:
        return None
    try:
        return int(round(float(s)))
    except (ValueError, OverflowError):
        return None


def fetch_pdf_links() -> list[tuple[str, str]]:
    """Returns list of (filename, url) for all PDFs on the IGO procurement page."""
    r = SESSION.get(BASE_URL, timeout=TIMEOUT)
    content = r.content
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            html = content.decode(enc)
            break
        except Exception:
            pass
    else:
        html = content.decode("utf-8", errors="replace")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" not in href.lower():
            continue
        full_url = urljoin(BASE_URL, href)
        fname = full_url.split("/")[-1]
        results.append((fname, full_url))
    return results


def _parse_kekka_pdf(content: bytes, filename: str, url: str) -> list[dict]:
    """Parse individual kekka PDFs (both koukoku and open-counter results).

    These PDFs use custom font encoding so Japanese text is garbled,
    but numeric amounts can be extracted from the table.
    """
    # Extract date from filename (YYYYMMDD pattern, must have valid month 01-12)
    # Also handle typos like "202600202" → "20260202"
    filename_date = None
    all_nums = re.findall(r"\d+", filename)
    for chunk in all_nums:
        # Try 8-digit match first
        for start in range(len(chunk) - 7):
            candidate = chunk[start:start + 8]
            mo = int(candidate[4:6])
            dd = int(candidate[6:8])
            yr = int(candidate[:4])
            if 2020 <= yr <= 2030 and 1 <= mo <= 12 and 1 <= dd <= 31:
                filename_date = candidate
                break
        if filename_date:
            break
    # Fallback: fix 9-digit date typos like "202600202" → try "20260202"
    if not filename_date:
        for chunk in all_nums:
            if len(chunk) == 9 and chunk.startswith("2026"):
                fixed = chunk[:4] + chunk[5:]  # remove extra zero
                mo = int(fixed[4:6])
                dd = int(fixed[6:8])
                if 1 <= mo <= 12 and 1 <= dd <= 31:
                    filename_date = fixed
                    break

    # Determine bid_method from filename prefix
    fname_lower = filename.lower()
    if fname_lower.startswith("koukoku_"):
        bid_method = "一般競争入札"
    elif fname_lower.startswith("open_") or fname_lower.startswith("opencounter_"):
        bid_method = "一般競争入札"  # open counter is competitive
    else:
        bid_method = None

    records = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if len(table) < 2:
                        continue
                    for row in table[1:]:  # skip header row
                        if not row:
                            continue
                        # Find amount: look for cell with numeric amount > 10,000
                        amount = None
                        amount_col = -1
                        for ci, cell in enumerate(row):
                            if not cell:
                                continue
                            cell_clean = str(cell).replace(" ", "").replace("\n", "")
                            amt = _to_amount(cell_clean)
                            if amt and amt >= 10000:
                                amount = amt
                                amount_col = ci
                                break

                        if not amount:
                            continue

                        # Extract contract name (usually column 2)
                        contract_name = None
                        if len(row) > 2 and row[2]:
                            contract_name = str(row[2]).strip().replace("\n", " ")[:500]

                        # Vendor name (usually last non-empty column)
                        vendor_name = None
                        for cell in reversed(row):
                            if cell and str(cell).strip() and _to_amount(str(cell).replace(" ", "")) is None:
                                vendor_name = str(cell).strip().replace("\n", " ")[:200]
                                break

                        if not filename_date:
                            continue

                        fiscal_year = _fy_from_date(filename_date)
                        if fiscal_year not in {2022, 2023, 2024, 2025}:
                            continue

                        rec = {
                            "agency_id": AGENCY_ID,
                            "agency_name": AGENCY_NAME,
                            "agency_category": "防衛監察",
                            "fiscal_year": fiscal_year,
                            "contract_date": filename_date,
                            "contract_name": contract_name,
                            "vendor_name": vendor_name,
                            "contract_amount": amount,
                            "bid_method": bid_method,
                            "source_url": url,
                        }
                        records.append(rec)
    except Exception as e:
        logger.warning(f"  kekka parse error {filename}: {e}")

    return records


def _parse_aggregated_pdf(content: bytes, url: str) -> list[dict]:
    """Parse aggregated R4-R7 annual summary PDFs using the standard parser."""
    from parsers.pdf_table import parse_pdf_records
    results = []
    try:
        for rec in parse_pdf_records(content, target_fys={2022, 2023, 2024, 2025}):
            rec["agency_id"] = AGENCY_ID
            rec["agency_name"] = AGENCY_NAME
            rec["agency_category"] = "防衛監察"
            rec["source_url"] = url
            results.append(rec)
    except Exception as e:
        logger.warning(f"  aggregated parse error: {e}")
    return results


def _insert_records(records: list[dict]) -> tuple[int, int]:
    """Insert records into procurement.db. Returns (inserted, skipped)."""
    if not records:
        return 0, 0

    inserted = skipped = 0
    with sqlite3.connect(PROC_DB) as conn:
        for rec in records:
            fiscal_year = rec.get("fiscal_year")
            contract_date = rec.get("contract_date")
            contract_name = rec.get("contract_name") or ""
            contract_amount = rec.get("contract_amount")

            if not fiscal_year or not contract_date or not contract_amount:
                skipped += 1
                continue

            cur = conn.execute(
                """INSERT OR IGNORE INTO contracts
                   (agency_id, agency_name, agency_category, fiscal_year, contract_date, contract_name,
                    vendor_name, vendor_address, contract_amount, estimated_price, award_rate,
                    bid_method, corporate_number, source_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rec.get("agency_id"), rec.get("agency_name"), rec.get("agency_category"),
                    fiscal_year, contract_date, contract_name,
                    rec.get("vendor_name"), rec.get("vendor_address"),
                    contract_amount, rec.get("estimated_price"), rec.get("award_rate"),
                    rec.get("bid_method"), rec.get("corporate_number"),
                    rec.get("source_url"),
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    return inserted, skipped


def _update_url_matrix_cell(
    agency_id: str, category: str, bid_method: str, month: int,
    url: str, filename: str, status: str = "filled_new",
) -> bool:
    """Update a url_matrix cell. Returns True if updated."""
    with sqlite3.connect(URL_DB) as conn:
        row = conn.execute(
            "SELECT id, status FROM url_matrix WHERE agency_id=? AND category=? "
            "AND bid_method=? AND month=?",
            (agency_id, category, bid_method, month),
        ).fetchone()
        if not row:
            logger.warning(f"  No url_matrix row for {agency_id}/{category}/{bid_method}/m{month}")
            return False
        row_id, cur_status = row
        if cur_status == "dash":
            # Only update dash → filled_new
            conn.execute(
                "UPDATE url_matrix SET url=?, filename=?, status=?, flag_collected=1 WHERE id=?",
                (url, filename, status, row_id),
            )
            conn.commit()
            logger.info(f"  Updated url_matrix: {category}/{bid_method}/m{month} → {filename}")
            return True
        else:
            logger.debug(f"  Skip (already {cur_status}): {category}/{bid_method}/m{month}")
            return False


def run() -> None:
    logger.info("=== IGO収集開始 ===")

    # Get all PDF links
    all_links = fetch_pdf_links()
    logger.info(f"PDFリンク数: {len(all_links)}")

    # Separate aggregated files from individual kekka files
    AGGREGATED_PREFIXES = ("R4_", "R5_", "R6_", "R7_", "R8_")
    KEKKA_SUFFIXES = ("_kekka.pdf", ".kekka.pdf", "_kekka.pdf", "kekkapdf.pdf")
    SKIP_PREFIXES = ("ouinn", "mitumo", "kokoroe", "kokuzi")

    aggregated_files = [(f, u) for f, u in all_links
                        if any(f.startswith(p) for p in AGGREGATED_PREFIXES)]
    kekka_files = [(f, u) for f, u in all_links
                   if any(f.lower().endswith(s) for s in KEKKA_SUFFIXES)
                   and not any(f.startswith(p) for p in SKIP_PREFIXES)]

    logger.info(f"集約ファイル: {len(aggregated_files)}, kekkaファイル: {len(kekka_files)}")

    total_inserted = 0
    total_skipped = 0

    # Process aggregated files
    logger.info("--- 集約ファイル処理 ---")
    for fname, url in aggregated_files:
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"  HTTP {r.status_code}: {fname}")
                continue
            records = _parse_aggregated_pdf(r.content, url)
            ins, skp = _insert_records(records)
            total_inserted += ins
            total_skipped += skp
            logger.info(f"  {fname}: {len(records)}件パース, {ins}件挿入, {skp}件スキップ")
        except Exception as e:
            logger.error(f"  ERROR {fname}: {e}")

    # Process individual kekka files
    logger.info("--- kekkaファイル処理 ---")
    for fname, url in kekka_files:
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"  HTTP {r.status_code}: {fname}")
                continue
            records = _parse_kekka_pdf(r.content, fname, url)
            ins, skp = _insert_records(records)
            total_inserted += ins
            total_skipped += skp
            if records:
                logger.info(f"  {fname}: {len(records)}件パース, {ins}件挿入, {skp}件スキップ")
        except Exception as e:
            logger.error(f"  ERROR {fname}: {e}")

    logger.info(f"=== 挿入完了: {total_inserted}件新規, {total_skipped}件スキップ ===")

    # Update url_matrix cells based on what's now in procurement.db
    _update_url_matrix_from_db()


def _update_url_matrix_from_db() -> None:
    """Update url_matrix cells based on source_urls of records in procurement.db."""
    logger.info("--- url_matrix更新 ---")

    # Get all distinct (source_url, fiscal_year, month) combinations for igo
    with sqlite3.connect(PROC_DB) as conn:
        rows = conn.execute(
            "SELECT source_url, fiscal_year, contract_date FROM contracts "
            "WHERE agency_id=? AND source_url IS NOT NULL",
            (AGENCY_ID,),
        ).fetchall()

    # Group: source_url → set of (fiscal_year, month)
    from collections import defaultdict
    url_to_months: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for source_url, fy, cdate in rows:
        if cdate and len(cdate) >= 6:
            month = int(cdate[4:6])
            url_to_months[source_url].add((fy, month))

    categories = ["物品役務"]

    updated_total = 0
    for source_url, fy_months in url_to_months.items():
        fname = source_url.split("/")[-1]
        # IGO contracts are competitive; update 競争 cell only
        bid_methods = ["競争"]
        for fy, month in fy_months:
            for cat in categories:
                for bid in bid_methods:
                    if _update_url_matrix_cell(AGENCY_ID, cat, bid, month, source_url, fname):
                        updated_total += 1

    logger.info(f"url_matrix更新: {updated_total}セル")


if __name__ == "__main__":
    run()
