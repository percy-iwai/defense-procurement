"""画像スキャン PDF OCR 収集スクリプト（春日・芦屋・浜松 等）。

画像スキャン PDF を easyocr で解析し contracts テーブルに INSERT OR IGNORE する。
- CCITTFaxDecode (1bpc landscape): tekiseika_parser 経由（is_landscape_scan() が True の場合）
- DCTDecode (JPEG 等): 汎用 parse_ocr_records 経由

実行:
    python -m pipeline.load_asdf_ocr                          # 全機関
    python -m pipeline.load_asdf_ocr --agency asdf_kasuga     # 春日のみ
    python -m pipeline.load_asdf_ocr --agency asdf_ashiya     # 芦屋のみ
    python -m pipeline.load_asdf_ocr --agency asdf_hamamatsu  # 浜松のみ（FY2024 7・8月分）
    python -m pipeline.load_asdf_ocr --dry-run
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
from collectors.index_scraper import scrape_file_links  # noqa: E402
from parsers.ocr_parser import parse_ocr_records  # noqa: E402
from parsers.tekiseika_parser import is_landscape_scan, parse_tekiseika_pdf  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

TARGET_FYS = {2024, 2025}

# ---------------------------------------------------------------------------
# 機関設定
# ---------------------------------------------------------------------------

# 春日基地: WARP 20250510/20250509054434 でのみ FY2024 アクセス可
KASUGA_WARP_INDEX = (
    "https://warp.ndl.go.jp/20250510/20250509054434/"
    "https://www.mod.go.jp/asdf/kasuga/second/kaikei/koujijouhou6nendo.htm"
)

# 各機関の画像PDF URL → デフォルトFY マッピング
# OCR で contract_date からFYが取れない場合のフォールバック

# 芦屋基地: 4月分は画像PDF（CCITTFaxDecode）、FY2024 3月・FY2025 4月も追加
ASHIYA_IMAGE_URLS: dict[str, int] = {
    "https://www.mod.go.jp/asdf/ashiya/choutatsu/kaikei/rakusatu/6/zyouhoukoukai/zyouhoukoukai6-4.pdf": 2024,
    "https://www.mod.go.jp/asdf/ashiya/choutatsu/kaikei/rakusatu/6/zyouhoukoukai/zyouhoukoukai7-3.pdf": 2024,  # FY2024 3月: フォントエンコード問題→OCR
    "https://www.mod.go.jp/asdf/ashiya/choutatsu/kaikei/rakusatu/7/zyouhoukoukai/zyouhoukoukai7-4.pdf": 2025,  # FY2025 4月: 画像PDF
}

# 浜松基地: FY2024 7月・8月分のみ画像PDF（DCTDecode/JPEG）
# 他月（6月・7月・10月・12月・1月・2月）は通常テキストPDFで load_asdf.py 経由収集済み
HAMAMATSU_IMAGE_URLS: dict[str, int] = {
    "https://www.mod.go.jp/asdf/hamamatsu/choutatsu/koukoku/r6kokyo20240801.pdf": 2024,
    "https://www.mod.go.jp/asdf/hamamatsu/choutatsu/koukoku/r6kokyo20240905.pdf": 2024,
}

AGENCIES: dict[str, dict] = {
    "asdf_kasuga": {
        "agency_name": "春日基地",
        "agency_category": "航空自衛隊",
        "default_fy": 2024,
        # warp_index キーがある機関はインデックスページを動的にスクレイプする
        "warp_index": KASUGA_WARP_INDEX,
    },
    "asdf_ashiya": {
        "agency_name": "芦屋基地",
        "agency_category": "航空自衛隊",
        "default_fy": 2024,
        "image_pdf_urls": ASHIYA_IMAGE_URLS,
    },
    "asdf_hamamatsu": {
        "agency_name": "浜松基地",
        "agency_category": "航空自衛隊",
        "default_fy": 2024,
        "image_pdf_urls": HAMAMATSU_IMAGE_URLS,
    },
}

# ---------------------------------------------------------------------------
# DB 定数（load_misawa_ocr.py と同じスキーマ）
# ---------------------------------------------------------------------------
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


def _enrich(rec: dict, *, agency_id: str, source_url: str) -> dict:
    """agency 情報・source情報を付与し、必須キーを None で埋める。"""
    cfg = AGENCIES[agency_id]
    rec.update({
        "agency_id": agency_id,
        "agency_name": cfg["agency_name"],
        "agency_category": cfg["agency_category"],
        "source_url": source_url,
        "source_type": "ocr_pdf",
    })
    if not rec.get("contract_type"):
        rec["contract_type"] = "物品役務"
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def _pdf_urls_for_warp_index(warp_index_url: str) -> list[str]:
    """WARP インデックスページから PDF URL リストを収集する。"""
    links = scrape_file_links(
        warp_index_url,
        extensions=(".pdf",),
        is_warp=True,
    )
    urls = [url for url, _ in links]
    if not urls:
        logger.warning(f"WARP インデックス {warp_index_url} から PDF リンクが見つかりませんでした")
    else:
        logger.info(f"{len(urls)}件の PDF リンクを発見")
        for url in urls:
            logger.debug(f"  {url.split('/')[-1]}")
    return urls


def collect(agency_id: str, *, dry_run: bool = False) -> dict:
    """指定機関の OCR 収集を実行する。"""
    stats = {
        "agency_id": agency_id,
        "files_tried": 0,
        "files_ok": 0,
        "rows_parsed": 0,
        "inserted": 0,
        "duplicates": 0,
        "skipped_no_fy": 0,
    }

    cfg = AGENCIES[agency_id]
    if "warp_index" in cfg:
        # WARP インデックスページを動的スクレイプ（春日基地等）
        urls = _pdf_urls_for_warp_index(cfg["warp_index"])
        pdf_url_map: dict[str, int] = {u: cfg["default_fy"] for u in urls}
    else:
        # 固定 URL リスト（芦屋・浜松等）
        pdf_url_map = dict(cfg.get("image_pdf_urls", {}))

    if not pdf_url_map:
        logger.warning(f"{agency_id}: 対象 PDF が見つかりませんでした")
        return stats

    all_records: list[dict] = []

    for url, url_default_fy in pdf_url_map.items():
        fname = url.split("/")[-1]
        stats["files_tried"] += 1
        logger.info(f"[{fname}] 取得中...")

        is_warp = "warp.ndl.go.jp" in url
        data = fetch(url, timeout=60, use_cache=True, is_warp=is_warp)
        if data is None:
            logger.warning(f"  [{fname}] 404 / 取得失敗 → スキップ")
            continue

        logger.info(f"  [{fname}] {len(data) // 1024}KB → OCR開始")
        try:
            if is_landscape_scan(data):
                logger.info(f"  [{fname}] landscape scan 検出 → tekiseika parser 使用")
                recs = parse_tekiseika_pdf(data, target_fys=TARGET_FYS)
            else:
                recs = parse_ocr_records(data, target_fys=TARGET_FYS)
        except Exception as e:
            logger.warning(f"  [{fname}] OCR失敗: {e}")
            recs = []

        if not recs:
            logger.info(f"  [{fname}] 0件（OCR結果なし）")
            stats["files_ok"] += 1
            continue

        stats["files_ok"] += 1
        for rec in recs:
            if not rec.get("fiscal_year"):
                rec["fiscal_year"] = url_default_fy
            _enrich(rec, agency_id=agency_id, source_url=url)
        all_records.extend(recs)
        stats["rows_parsed"] += len(recs)
        logger.info(f"  [{fname}] {len(recs)}件取得")

    logger.info(
        f"\n{agency_id} 収集完了: {stats['files_ok']}/{stats['files_tried']}ファイル成功 / "
        f"合計 {stats['rows_parsed']}件"
    )

    if dry_run:
        logger.info("--dry-run: DB書き込みをスキップ")
        _print_fy_summary(all_records, agency_id)
        stats["records"] = all_records
        return stats

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

    _print_db_counts(agency_id)
    return stats


def _print_fy_summary(records: list[dict], agency_id: str) -> None:
    from collections import Counter
    fy_counts: Counter = Counter()
    for rec in records:
        fy_counts[rec.get("fiscal_year")] += 1
    print(f"\n=== {agency_id} FY別件数（ドライラン）===")
    for fy in sorted(fy_counts):
        print(f"  FY{fy}: {fy_counts[fy]}件")
    print(f"  合計: {sum(fy_counts.values())}件")


def _print_db_counts(agency_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT fiscal_year, COUNT(*) FROM contracts "
            "WHERE agency_id = ? GROUP BY fiscal_year ORDER BY fiscal_year",
            (agency_id,),
        )
        rows = cur.fetchall()
    print(f"\n=== DB: {agency_id} FY別件数 ===")
    total = 0
    for fy, cnt in rows:
        print(f"  FY{fy}: {cnt}件")
        total += cnt
    print(f"  合計: {total}件")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="画像スキャン PDF OCR 収集（春日・芦屋・浜松等）")
    p.add_argument(
        "--agency",
        choices=list(AGENCIES.keys()),
        help="対象機関（省略時は全機関）",
    )
    p.add_argument("--dry-run", action="store_true", help="DB書き込みを行わない")
    args = p.parse_args()

    targets = [args.agency] if args.agency else list(AGENCIES.keys())

    total_inserted = 0
    for aid in targets:
        result = collect(aid, dry_run=args.dry_run)
        total_inserted += result.get("inserted", 0)
        print(
            f"\n{aid}: files_ok={result['files_ok']}/{result['files_tried']} "
            f"rows={result['rows_parsed']} "
            f"inserted={result.get('inserted', 'N/A')} "
            f"dup={result.get('duplicates', 'N/A')}"
        )

    if not args.dry_run and len(targets) > 1:
        print(f"\n合計新規投入: {total_inserted}件")
