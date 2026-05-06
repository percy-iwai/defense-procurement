"""航空自衛隊（ASDF）29機関のPDF/Excel/HTMLデータを収集→parse→DB投入。

戦略:
- source_format == "excel" → parsers.excel_parser で解析（asdf_2dep, asdf_3dep）
- scrape_html_tables == True → collectors.index_scraper.scrape_html_tables で解析
- それ以外（デフォルト）→ PDF: parsers.pdf_table.parse_pdf_records で解析
- skip == True → 画像PDFのためスキップ
- is_warp == True → index_urls の取得に WARP Cookie を使用（url_patterns はそのままWARPドメイン）
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
from parsers.excel_parser import (  # noqa: E402
    fy_from_date,
    iter_records,
    parse_excel_bytes,
)
from parsers.pdf_table import (  # noqa: E402
    _normalize_bid as pdf_norm_bid,
    _to_amount as pdf_to_amount,
    _to_date_str as pdf_to_date,
    _to_rate as pdf_to_rate,
    parse_pdf_records,
)
from pipeline.asdf_config import ASDF_AGENCIES  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

TARGET_FYS = {2022, 2023, 2024, 2025}

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


def _classify_url(url: str) -> tuple[str | None, str | None]:
    u = url.lower()
    if any(t in u for t in ("zui", "zuikei", "随意")):
        return ("随意契約", "随意契約")
    if any(t in u for t in ("kyousou", "nyu", "kyo", "一般", "競争", "kouhyou")):
        return ("一般競争", "一般競争入札")
    return (None, None)


def _fy_from_excel_url(url: str) -> int | None:
    """asdf_2dep: kou_{nyu|zui}_{RR}{MM}.xlsx → FY推定。
    RR=04→2022/2023, 05→2023/2024, 06→2024/2025, 07→2025/2026
    MM>=4 → FY = 2018+RR, MM<4 → FY = 2018+RR-1
    """
    m = re.search(r"kou_(?:nyu|zui)_(\d{2})(\d{2})\.xlsx", url)
    if m:
        rr, mm = int(m.group(1)), int(m.group(2))
        y = 2018 + rr
        return y if mm >= 4 else y - 1
    # asdf_3dep WARP: kyousou{RR}{MM}.xlsx / zuikei{RR}{MM}.xlsx
    m2 = re.search(r"(?:kyousou|zuikei)(\d{2})(\d{2})\.xlsx", url)
    if m2:
        rr, mm = int(m2.group(1)), int(m2.group(2))
        y = 2018 + rr
        return y if mm >= 4 else y - 1
    return None


def _enrich_record(rec: dict, *, agency: dict, source_url: str,
                   source_type: str) -> dict:
    rec.update({
        "agency_id": agency["agency_id"],
        "agency_name": agency["agency_name"],
        "agency_category": "航空自衛隊",
        "source_url": source_url,
        "source_type": source_type,
    })
    if not rec.get("contract_type") or not rec.get("bid_method"):
        ctype, bid_default = _classify_url(source_url)
        if not rec.get("contract_type"):
            rec["contract_type"] = ctype or "物品役務"
        if not rec.get("bid_method") and bid_default:
            rec["bid_method"] = bid_default
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def _process_excel(data: bytes, *, url: str, agency: dict) -> list[dict]:
    """Excel bytes → レコードリスト。"""
    is_xls = url.lower().endswith(".xls")
    try:
        df, header_idx, col_map = parse_excel_bytes(data, is_xls=is_xls)
    except Exception as e:
        logger.warning(f"Excel解析エラー: {url} - {e}")
        return []

    if df.empty or not col_map:
        return []

    # FY候補: URLから推定（asdf_2dep/3dep は URL から確定、その他は契約日から動的判定）
    url_fy = _fy_from_excel_url(url)

    out: list[dict] = []
    for rec in iter_records(df, header_idx, col_map,
                            target_fy=url_fy or 2024,
                            fy_guard=(url_fy is not None)):
        # url_fy が不明な場合、契約日から実際のFYを上書き（iter_records が target_fy を代入するため）
        if url_fy is None and rec.get("contract_date"):
            actual_fy = fy_from_date(rec.get("contract_date"))
            if actual_fy:
                rec["fiscal_year"] = actual_fy
        if rec.get("fiscal_year") not in TARGET_FYS:
            continue
        rec = _enrich_record(rec, agency=agency, source_url=url, source_type="excel")
        out.append(rec)
    return out


def _process_pdf(data: bytes, *, url: str, agency: dict) -> list[dict]:
    """PDF bytes → レコードリスト。"""
    out: list[dict] = []
    try:
        for rec in parse_pdf_records(data, target_fys=TARGET_FYS):
            rec = _enrich_record(rec, agency=agency, source_url=url, source_type="pdf")
            out.append(rec)
    except Exception as e:
        logger.warning(f"PDF処理エラー: {url} - {e}")
    return out


def _fy_from_html_url(url: str) -> int | None:
    """URLのReiwa年からFYを推定。kekka_06.html → FY2024, kekka_07.html → FY2025 など。
    パターン: kekka_{RY}[_.]... / r{RY}/ / R{RY} / _{RY}_
    """
    import re as _re
    # kekka_06.html, kekka_07.html 形式
    m = _re.search(r"kekka[_\-]0?(\d{1,2})", url)
    if m:
        ry = int(m.group(1))
        if 1 <= ry <= 20:
            return 2018 + ry  # 令和RY年度 = FY(2018+RY)
    # r6/ または R6 形式（年度）
    m = _re.search(r"[rR]0?(\d{1,2})[/\-_]", url)
    if m:
        ry = int(m.group(1))
        if 1 <= ry <= 20:
            return 2018 + ry
    return None


def _process_html_tables(html_url: str, agency: dict) -> list[dict]:
    """HTMLテーブル → レコードリスト（scrape_html_tables機関用）。

    contract_dateが取れない場合はURLのReiwa年からFYを推定する（工事系HTML機関対応）。
    """
    is_warp = agency.get("is_warp", False)
    tables = scrape_html_tables(html_url, is_warp=is_warp)
    if not tables:
        return []

    # URLからFY推定（date無し機関のフォールバック）
    url_fy = _fy_from_html_url(html_url)

    out: list[dict] = []
    for tbl in tables:
        if len(tbl) < 2:
            continue
        # ヘッダー行検索（最初の5行）
        h_idx = -1
        for i, r in enumerate(tbl[:5]):
            # セル内のスペース・改行を除去してから結合（Excel Web Archive は空白区切りで
            # 「落札 金額」になるため、スペース除去しないと "落札金額" にマッチしない）
            text = " ".join(str(c).replace("\n", "").replace(" ", "") for c in r if c)
            if any(t in text for t in ("契約金額", "落札金額")) and any(
                k in text for k in ("名称", "件名", "業務", "工事", "品名")
            ):
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
                ("品名", "contract_name"), ("工事名", "contract_name"),
                ("業者", "vendor_name"), ("相手方", "vendor_name"),
                ("法人番号", "corporate_number"),
                ("契約金額", "contract_amount"), ("落札金額", "contract_amount"),
                ("予定価格", "estimated_price"), ("落札率", "award_rate"),
                ("入札方式", "bid_method"), ("入札・指名", "bid_method"),
                ("締結日", "contract_date"), ("契約日", "contract_date"),
                ("締結年月日", "contract_date"), ("締結した日", "contract_date"),
                # 工事系HTMLで使われる日付代替列
                ("工期始", "contract_date"), ("着手日", "contract_date"),
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
                    else:
                        rec[fld] = str(val).strip()[:500]

            # FY決定: contract_dateから算出、なければURLから推定
            cd_fy = fy_from_date(rec.get("contract_date"))
            if cd_fy is None:
                cd_fy = url_fy  # フォールバック: kekka_06.html → FY2024
            if cd_fy is None or cd_fy not in TARGET_FYS:
                continue
            rec["fiscal_year"] = cd_fy
            rec = _enrich_record(rec, agency=agency,
                                 source_url=html_url, source_type="html")
            out.append(rec)
    return out


def collect_agency(agency: dict) -> tuple[list[dict], dict]:
    aid = agency["agency_id"]
    stats = {"sources_tried": 0, "files_found": 0, "files_ok": 0, "rows_parsed": 0}
    records: list[dict] = []
    is_warp = agency.get("is_warp", False)

    # スキップ機関
    if agency.get("skip"):
        logger.info(f"  スキップ: {agency.get('skip_reason', '')}")
        return records, stats

    # HTML テーブル直接抽出機関
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
                logger.info(f"  [html] {url}: {len(recs)}件")
            records.extend(recs)
            stats["rows_parsed"] += len(recs)
        return records, stats

    # インデックスからファイルリンク収集
    file_urls: set[str] = set()
    fmt = agency.get("source_format", "pdf")
    extensions = (".xlsx", ".xls") if fmt == "excel" else (".pdf", ".xlsx", ".xls")

    for index_url in agency.get("index_urls", []):
        try:
            links = scrape_file_links(
                index_url, extensions=extensions, is_warp=is_warp
            )
        except Exception as e:
            logger.warning(f"index取得エラー: {index_url} - {e}")
            links = []
        if links:
            logger.info(f"  index {index_url} → {len(links)} links")
        for u, _ in links:
            file_urls.add(u)

    # url_patterns 補完
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

        # 拡張子で処理分岐
        url_lo = url.lower()
        if url_lo.endswith((".xlsx", ".xls")) or fmt == "excel":
            recs = _process_excel(data, url=url, agency=agency)
        else:
            recs = _process_pdf(data, url=url, agency=agency)

        records.extend(recs)
        stats["rows_parsed"] += len(recs)
        if recs:
            logger.info(f"  [{Path(url).name}] {len(recs)}件")

    return records, stats


def collect_and_load(*, db_path: Path = DB_PATH, dry_run: bool = False,
                     filter_agency: list[str] | None = None) -> dict:
    agencies = ASDF_AGENCIES
    if filter_agency:
        agencies = [a for a in agencies if a["agency_id"] in filter_agency]

    overall = {
        "agencies": 0, "files_ok": 0, "rows_parsed": 0,
        "inserted": 0, "duplicates": 0, "skipped_no_fy": 0,
        "per_agency": {},
    }
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
    logger.info(
        f"DB投入: 新規 {inserted}件 / 重複 {duplicates}件 / スキップ {skipped}件 / "
        f"機関 {overall['agencies']}"
    )
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
        print(
            f"  {aid:<22} files_ok={s['files_ok']:>4}/{s['files_found']:<4}"
            f"  rows={s['rows_parsed']:>5}"
        )
