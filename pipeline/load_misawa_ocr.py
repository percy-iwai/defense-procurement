"""三沢基地 FY2024 OCR 収集スクリプト。

FY2024 の画像スキャン PDF（R604〜R703、全12ファイル）を easyocr で解析し、
contracts テーブルに INSERT する。

実行:
    python -m pipeline.load_misawa_ocr
    python -m pipeline.load_misawa_ocr --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from parsers.ocr_parser import parse_ocr_records  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

TARGET_FYS = {2024}

AGENCY_ID = "asdf_misawa"
AGENCY_NAME = "三沢基地"
AGENCY_CATEGORY = "航空自衛隊"

BASE_URL = "https://www.mod.go.jp/asdf/misawa/offer/public_offering/kouhyou/"

# FY2024: 令和6年4月〜令和7年3月 = R604〜R612, R701〜R703
FY2024_URLS: list[str] = (
    [f"{BASE_URL}R6{mm:02d}.pdf" for mm in range(4, 13)]   # R604〜R612
    + [f"{BASE_URL}R70{mm}.pdf" for mm in range(1, 4)]      # R701〜R703
)


def _fy_from_url(url: str) -> int | None:
    """URL のファイル名 R{RY}{MM}.pdf から FY を推定する。
    R604 → RY=6, MM=4 → FY2024
    R701 → RY=7, MM=1 → FY2024
    """
    import re as _re
    m = _re.search(r"R(\d)(\d{2})\.pdf", url, _re.IGNORECASE)
    if m:
        ry, mm = int(m.group(1)), int(m.group(2))
        y = 2018 + ry
        return y if mm >= 4 else y - 1
    return None


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


def _enrich(rec: dict, *, source_url: str) -> dict:
    """agency 情報・source情報を付与し、必須キーを None で埋める。"""
    rec.update({
        "agency_id": AGENCY_ID,
        "agency_name": AGENCY_NAME,
        "agency_category": AGENCY_CATEGORY,
        "source_url": source_url,
        "source_type": "ocr_pdf",
    })
    # contract_type: URL に kouhyou → 競争入札扱い（物品・役務）
    if not rec.get("contract_type"):
        rec["contract_type"] = "物品役務"
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def collect(*, dry_run: bool = False) -> dict:
    """FY2024 の全 PDF を収集・解析して DB に投入する。

    Returns
    -------
    dict: 統計情報
    """
    stats = {
        "files_tried": 0,
        "files_ok": 0,
        "rows_parsed": 0,
        "inserted": 0,
        "duplicates": 0,
        "skipped_no_fy": 0,
    }

    all_records: list[dict] = []

    for url in FY2024_URLS:
        fname = Path(url).name
        stats["files_tried"] += 1
        logger.info(f"[{fname}] 取得中...")

        data = fetch(url, timeout=60, use_cache=True)
        if data is None:
            logger.warning(f"  [{fname}] 404 / 取得失敗 → スキップ")
            continue

        logger.info(f"  [{fname}] {len(data) // 1024}KB → OCR開始")
        try:
            recs = parse_ocr_records(data, target_fys=TARGET_FYS)
        except Exception as e:
            logger.warning(f"  [{fname}] OCR失敗: {e}")
            recs = []

        if not recs:
            logger.info(f"  [{fname}] 0件")
            continue

        stats["files_ok"] += 1
        url_fy = _fy_from_url(url)
        for rec in recs:
            # contract_date から FY が取れていない場合は URL ベースで補完
            if not rec.get("fiscal_year") and url_fy is not None:
                rec["fiscal_year"] = url_fy
            _enrich(rec, source_url=url)
        all_records.extend(recs)
        stats["rows_parsed"] += len(recs)
        logger.info(f"  [{fname}] {len(recs)}件取得")

    logger.info(
        f"\n収集完了: {stats['files_ok']}/{stats['files_tried']}ファイル成功 / "
        f"合計 {stats['rows_parsed']}件"
    )

    if dry_run:
        logger.info("--dry-run: DB書き込みをスキップ")
        # ドライラン時は件数サマリのみ表示
        _print_fy_summary(all_records)
        stats["records"] = all_records
        return stats

    # DB 投入
    inserted = 0
    duplicates = 0
    skipped = 0

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for rec in all_records:
            if not rec.get("fiscal_year"):
                skipped += 1
                continue
            try:
                cur.execute(INSERT_SQL, rec)
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.commit()

    stats["inserted"] = inserted
    stats["duplicates"] = duplicates
    stats["skipped_no_fy"] = skipped

    logger.info(
        f"DB投入完了: 新規 {inserted}件 / 重複 {duplicates}件 / "
        f"FY不明スキップ {skipped}件"
    )

    # FY 別件数レポート
    _print_fy_from_db()

    return stats


def _print_fy_summary(records: list[dict]) -> None:
    """レコードリストの FY 別件数を表示（ドライラン用）。"""
    from collections import Counter
    fy_counts: Counter = Counter()
    for rec in records:
        fy = rec.get("fiscal_year")
        fy_counts[fy] += 1
    print("\n=== FY別件数（ドライラン）===")
    for fy in sorted(fy_counts):
        print(f"  FY{fy}: {fy_counts[fy]}件")
    print(f"  合計: {sum(fy_counts.values())}件")


def _print_fy_from_db() -> None:
    """DB から asdf_misawa の FY 別件数を表示。"""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT fiscal_year, COUNT(*) FROM contracts "
            "WHERE agency_id = ? GROUP BY fiscal_year ORDER BY fiscal_year",
            (AGENCY_ID,),
        )
        rows = cur.fetchall()

    print(f"\n=== DB: {AGENCY_ID} FY別件数 ===")
    total = 0
    for fy, cnt in rows:
        print(f"  FY{fy}: {cnt}件")
        total += cnt
    print(f"  合計: {total}件")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="三沢基地 FY2024 OCR 収集")
    p.add_argument("--dry-run", action="store_true", help="DB書き込みを行わない")
    args = p.parse_args()

    result = collect(dry_run=args.dry_run)

    print(
        f"\n完了: files_ok={result['files_ok']}/{result['files_tried']} "
        f"rows={result['rows_parsed']} "
        f"inserted={result.get('inserted', 'N/A')} "
        f"dup={result.get('duplicates', 'N/A')}"
    )
