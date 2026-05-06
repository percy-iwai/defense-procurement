"""WARP/ライブサイト 自動クローラー — FY横断データ収集。

FY別クロール起点:
  FY2025/2024 → site_url (ライブサイト)
  FY2023      → site_url_2024_07 (WARP 2024-07スナップ)
  FY2022      → site_url_2023_07 (WARP 2023-07スナップ)

使い方:
  python -m pipeline.crawl_warp_fy --fy 2025 --all
  python -m pipeline.crawl_warp_fy --fy 2023 --agency rdb_hokkaido rdb_tohoku
  python -m pipeline.crawl_warp_fy --fy 2022 2023 --all --workers 2
  python -m pipeline.crawl_warp_fy --fy 2025 --agency rdb_hokkaido --dry-run
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from loguru import logger

from collectors.http_client import fetch
from collectors.index_scraper import _decode_html, scrape_file_links
from parsers.excel_parser import iter_records, parse_excel_bytes
from parsers.pdf_table import fy_from_date, parse_pdf_records

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROC_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

TARGET_FYS = {2022, 2023, 2024, 2025}

# FY → (url_matrix カラム名, is_warp)
FY_URL_MAP: dict[int, tuple[str, bool]] = {
    2025: ("site_url", False),
    2024: ("site_url", False),
    2023: ("site_url_2024_07", True),
    2022: ("site_url_2023_07", True),
}

# 調達関連URLパターン（HTML subpage フォロー用）
_PROC_PAT = re.compile(
    r"(調達|契約|入札|落札|適正化|nyusatu|nyusatsu|keiyaku|kouhyou|kekka|"
    r"chotatsu|rakusatu|jouhou|document|disclosure|procurement|"
    r"tekiseika|kouhyou|pdf|buppin|yakumu|kohyo)",
    re.IGNORECASE,
)

# 随意契約判定キーワード
_ZUII_KEYWORDS = ("随意", "随契", "見積合わせ", "随")
# 競争契約判定キーワード
_KYOUSOU_KEYWORDS = ("競争", "指名", "総合評価", "プロポーザル", "一般", "open")

# 公共工事判定キーワード（contract_name に含まれるもの）
_KOUJI_KEYWORDS = ("工事", "整備工事", "補修工事", "施設工事", "建設工事", "改修工事")


# ===== ユーティリティ =====

def _bid_to_matrix(bid_method: Optional[str]) -> Optional[str]:
    """入札方法を url_matrix の bid_method 値（競争/随契）に変換。"""
    if not bid_method:
        return None
    b = str(bid_method).lower()
    for k in _ZUII_KEYWORDS:
        if k.lower() in b:
            return "随契"
    for k in _KYOUSOU_KEYWORDS:
        if k.lower() in b:
            return "競争"
    return None


def _infer_category(contract_name: Optional[str]) -> str:
    """契約件名から url_matrix の category（公共工事/物品役務）を推定。"""
    if contract_name:
        for k in _KOUJI_KEYWORDS:
            if k in contract_name:
                return "公共工事"
    return "物品役務"


def _get_agency_meta(agency_id: str, conn_um) -> tuple[str, str]:
    """url_matrix から (agency_name, agency_category) を取得。"""
    row = conn_um.execute(
        "SELECT agency_name FROM url_matrix WHERE agency_id=? LIMIT 1",
        (agency_id,),
    ).fetchone()
    agency_name = row[0] if row else agency_id

    # agency_category は procurement.db から既存レコードを参照
    try:
        with sqlite3.connect(PROC_DB) as pc:
            r = pc.execute(
                "SELECT agency_category FROM contracts WHERE agency_id=? "
                "AND agency_category IS NOT NULL LIMIT 1",
                (agency_id,),
            ).fetchone()
            agency_cat = r[0] if r else ""
    except Exception:
        agency_cat = ""
    return agency_name, agency_cat


def _get_entry_url(agency_id: str, fiscal_year: int, conn_um) -> tuple[Optional[str], bool]:
    """FY別の起点URL と is_warp フラグを返す。"""
    col, is_warp = FY_URL_MAP.get(fiscal_year, ("site_url", False))
    row = conn_um.execute(
        f"SELECT {col} FROM url_matrix WHERE agency_id=? AND fiscal_year=2024 LIMIT 1",
        (agency_id,),
    ).fetchone()
    if not row or not row[0]:
        # site_url_2023_07 が NULL の場合は site_url にフォールバック
        if col != "site_url":
            row2 = conn_um.execute(
                "SELECT site_url FROM url_matrix WHERE agency_id=? AND fiscal_year=2024 LIMIT 1",
                (agency_id,),
            ).fetchone()
            if row2 and row2[0]:
                logger.debug(f"  {agency_id}: {col} がNULL → site_url にフォールバック")
                return row2[0], False
        return None, False
    return row[0], is_warp


# ===== HTML 深度クロール =====

def _deep_scrape_files(
    url: str,
    *,
    is_warp: bool,
    depth: int,
    visited: set[str],
) -> list[tuple[str, str]]:
    """url から PDF/Excel リンクを再帰的に収集。(file_url, link_text) リストを返す。"""
    if depth <= 0 or url in visited:
        return []
    visited.add(url)

    # まず直接のファイルリンクを収集
    files = scrape_file_links(url, is_warp=is_warp)

    if depth > 1:
        # HTML サブページもフォロー
        content = fetch(url, is_warp=is_warp)
        if content:
            try:
                html = _decode_html(content)
                # 調達関連の HTML リンクを抽出
                for m in re.finditer(r'href=["\']([^"\'#][^"\']*)["\']', html, re.IGNORECASE):
                    href = m.group(1).strip()
                    href_lo = href.lower().split("?", 1)[0]
                    # PDF/Excel は scrape_file_links で処理済み
                    if any(href_lo.endswith(ext) for ext in (".pdf", ".xlsx", ".xls")):
                        continue
                    # HTML リンクのみフォロー
                    if not any(href_lo.endswith(ext) for ext in (".html", ".htm", "/")):
                        if "." in href_lo.rsplit("/", 1)[-1]:
                            continue
                    if not _PROC_PAT.search(href):
                        continue
                    abs_url = re.sub(r"/https:/([^/])", r"/https://\1", urljoin(url, href))
                    if "mod.go.jp" not in abs_url and "ndl.go.jp" not in abs_url:
                        continue
                    if abs_url in visited:
                        continue
                    sub_files = _deep_scrape_files(
                        abs_url, is_warp=is_warp, depth=depth - 1, visited=visited
                    )
                    files.extend(sub_files)
            except Exception as e:
                logger.debug(f"  HTML subpage parse error {url}: {e}")

    return files


# ===== レコード挿入 =====

def _insert_records(records: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """procurement.db にレコード挿入。(inserted, skipped) を返す。"""
    if not records:
        return 0, 0
    if dry_run:
        return len(records), 0

    inserted = skipped = 0
    with sqlite3.connect(PROC_DB) as conn:
        for rec in records:
            fy = rec.get("fiscal_year")
            cdate = rec.get("contract_date")
            amount = rec.get("contract_amount")
            if not fy or not amount:
                skipped += 1
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO contracts
                   (agency_id, agency_name, agency_category, fiscal_year,
                    contract_name, vendor_name, vendor_address, corporate_number,
                    contract_amount, estimated_price, award_rate,
                    bid_method, contract_date, source_url, source_type)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.get("agency_id"), rec.get("agency_name"), rec.get("agency_category"),
                    fy,
                    rec.get("contract_name", ""), rec.get("vendor_name"),
                    rec.get("vendor_address"), rec.get("corporate_number"),
                    amount, rec.get("estimated_price"), rec.get("award_rate"),
                    rec.get("bid_method"), cdate,
                    rec.get("source_url"), "warp_crawler",
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    return inserted, skipped


# ===== url_matrix 更新 =====

def _update_matrix_cells(
    agency_id: str,
    fiscal_year: int,
    file_url: str,
    months: set[int],
    bid_methods: set[str],      # "競争", "随契"
    categories: set[str],       # "公共工事", "物品役務"
    dry_run: bool = False,
) -> int:
    """url_matrix のセルを更新。更新セル数を返す。"""
    if dry_run or not months:
        return 0

    filename = file_url.split("/")[-1].split("?")[0]
    updated = 0
    with sqlite3.connect(URL_DB) as conn:
        for month in months:
            for bm in bid_methods:
                for cat in categories:
                    cur = conn.execute(
                        """UPDATE url_matrix
                           SET url=?, filename=?, status='filled_new', flag_collected=1
                           WHERE agency_id=? AND fiscal_year=? AND category=?
                             AND bid_method=? AND month=? AND status='dash'""",
                        (file_url, filename, agency_id, fiscal_year, cat, bm, month),
                    )
                    updated += cur.rowcount
        conn.commit()
    return updated


# ===== ファイルのパース =====

def _parse_file(
    content: bytes,
    file_url: str,
    target_fy: int,
    agency_id: str,
    agency_name: str,
    agency_category: str,
) -> list[dict]:
    """PDF/Excel コンテンツをパースしてレコードリストを返す。"""
    url_lo = file_url.lower().split("?")[0]
    records: list[dict] = []

    is_xls = url_lo.endswith(".xls")
    is_xlsx = url_lo.endswith(".xlsx")
    is_pdf = url_lo.endswith(".pdf")

    if is_pdf:
        try:
            for rec in parse_pdf_records(content, target_fys={target_fy}):
                rec.setdefault("agency_id", agency_id)
                rec.setdefault("agency_name", agency_name)
                rec.setdefault("agency_category", agency_category)
                rec.setdefault("source_url", file_url)
                records.append(rec)
        except Exception as e:
            logger.debug(f"  PDF parse error {file_url}: {e}")

    elif is_xlsx or is_xls:
        try:
            df, header_idx, col_map = parse_excel_bytes(content, is_xls=is_xls)
            if col_map:
                for rec in iter_records(df, header_idx, col_map, target_fy=target_fy):
                    rec.setdefault("agency_id", agency_id)
                    rec.setdefault("agency_name", agency_name)
                    rec.setdefault("agency_category", agency_category)
                    rec.setdefault("source_url", file_url)
                    records.append(rec)
        except Exception as e:
            logger.debug(f"  Excel parse error {file_url}: {e}")

    return records


# ===== 機関単位クロール =====

def crawl_agency(
    agency_id: str,
    target_fy: int,
    *,
    dry_run: bool = False,
    depth: int = 2,
) -> dict:
    """1機関・1FY のクロール。統計 dict を返す。"""
    stats = {
        "agency_id": agency_id,
        "fiscal_year": target_fy,
        "files_found": 0,
        "files_parsed": 0,
        "records_parsed": 0,
        "inserted": 0,
        "skipped": 0,
        "matrix_updated": 0,
        "errors": [],
    }

    with sqlite3.connect(URL_DB) as conn_um:
        entry_url, is_warp = _get_entry_url(agency_id, target_fy, conn_um)
        if not entry_url:
            logger.debug(f"  {agency_id} FY{target_fy}: 起点URL なし → スキップ")
            return stats

        agency_name, agency_category = _get_agency_meta(agency_id, conn_um)

    logger.info(f"  {agency_id} FY{target_fy}: {entry_url} (warp={is_warp})")

    # ファイルリンク収集
    visited: set[str] = set()
    try:
        file_links = _deep_scrape_files(
            entry_url, is_warp=is_warp, depth=depth, visited=visited
        )
    except Exception as e:
        stats["errors"].append(f"scrape error: {e}")
        logger.warning(f"  {agency_id} FY{target_fy}: scrape error: {e}")
        return stats

    stats["files_found"] = len(file_links)
    if not file_links:
        logger.debug(f"  {agency_id} FY{target_fy}: ファイルリンク0件")
        return stats

    # 各ファイルをダウンロード→パース→挿入
    # file_url → records のマッピング（url_matrix 更新用）
    file_records: dict[str, list[dict]] = {}

    for file_url, link_text in file_links:
        try:
            content = fetch(file_url, is_warp=is_warp)
            if content is None:
                continue
            recs = _parse_file(
                content, file_url, target_fy,
                agency_id, agency_name, agency_category,
            )
            if recs:
                file_records[file_url] = recs
                stats["files_parsed"] += 1
                stats["records_parsed"] += len(recs)
        except Exception as e:
            stats["errors"].append(f"{file_url}: {e}")
            logger.debug(f"  file error {file_url}: {e}")

    # DB挿入
    all_records = [r for recs in file_records.values() for r in recs]
    ins, skp = _insert_records(all_records, dry_run=dry_run)
    stats["inserted"] = ins
    stats["skipped"] = skp

    # url_matrix 更新（ファイルごとに月・入札方法・カテゴリを集約）
    for file_url, recs in file_records.items():
        months: set[int] = set()
        bid_methods_matrix: set[str] = set()
        categories_matrix: set[str] = set()

        for rec in recs:
            cdate = rec.get("contract_date")
            if cdate and len(cdate) >= 6:
                try:
                    months.add(int(cdate[4:6]))
                except ValueError:
                    pass

            bm_matrix = _bid_to_matrix(rec.get("bid_method"))
            if bm_matrix:
                bid_methods_matrix.add(bm_matrix)

            cat_matrix = _infer_category(rec.get("contract_name"))
            categories_matrix.add(cat_matrix)

        if not bid_methods_matrix:
            bid_methods_matrix = {"競争", "随契"}  # 不明な場合は両方試す

        updated = _update_matrix_cells(
            agency_id, target_fy, file_url,
            months, bid_methods_matrix, categories_matrix,
            dry_run=dry_run,
        )
        stats["matrix_updated"] += updated

    return stats


# ===== メイン =====

def run(
    fys: list[int],
    agency_ids: list[str],
    *,
    workers: int = 4,
    dry_run: bool = False,
    depth: int = 2,
) -> None:
    total_inserted = 0
    total_matrix = 0
    total_errors = 0

    for fy in fys:
        logger.info(f"=== FY{fy} クロール開始 ({len(agency_ids)}機関, workers={workers}) ===")

        _, is_warp_fy = FY_URL_MAP.get(fy, ("site_url", False))
        # WARP は1ワーカーに制限（レート制限対応）
        effective_workers = 1 if is_warp_fy else workers

        def _task(aid: str) -> dict:
            return crawl_agency(aid, fy, dry_run=dry_run, depth=depth)

        results: list[dict] = []
        if effective_workers <= 1:
            for aid in agency_ids:
                results.append(_task(aid))
        else:
            with ThreadPoolExecutor(max_workers=effective_workers) as pool:
                futures = {pool.submit(_task, aid): aid for aid in agency_ids}
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        logger.error(f"  thread error {futures[fut]}: {e}")
                        total_errors += 1

        fy_inserted = sum(r["inserted"] for r in results)
        fy_matrix = sum(r["matrix_updated"] for r in results)
        fy_files = sum(r["files_found"] for r in results)
        fy_parsed = sum(r["records_parsed"] for r in results)
        fy_errors = sum(len(r["errors"]) for r in results)

        total_inserted += fy_inserted
        total_matrix += fy_matrix
        total_errors += fy_errors

        logger.info(
            f"FY{fy} 完了: ファイル{fy_files}件発見, レコード{fy_parsed}件パース, "
            f"{fy_inserted}件新規挿入, matrix{fy_matrix}セル更新, エラー{fy_errors}件"
        )
        if dry_run:
            logger.info(f"  [DRY RUN] 実際の書き込みは行われていません")

    logger.info(
        f"=== 全体完了: {total_inserted}件新規挿入, matrix{total_matrix}セル更新, "
        f"エラー{total_errors}件 ==="
    )


def _all_agency_ids() -> list[str]:
    with sqlite3.connect(URL_DB) as conn:
        rows = conn.execute(
            "SELECT DISTINCT agency_id FROM url_matrix WHERE fiscal_year=2024 "
            "ORDER BY agency_id"
        ).fetchall()
    return [r[0] for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="WARP/ライブサイト FY横断クローラー")
    parser.add_argument("--fy", type=int, nargs="+", default=[2025],
                        choices=[2022, 2023, 2024, 2025],
                        help="収集対象FY（複数指定可）")
    parser.add_argument("--all", action="store_true", help="全機関を対象にする")
    parser.add_argument("--agency", nargs="+", metavar="AGENCY_ID",
                        help="対象機関IDを指定（例: rdb_hokkaido rdb_tohoku）")
    parser.add_argument("--branch", nargs="+", metavar="BRANCH",
                        help="機関ブランチプレフィックスで絞り込み（例: rdb gsdf msdf）")
    parser.add_argument("--workers", type=int, default=4,
                        help="並行ワーカー数（WARP FYは自動的に1に制限）")
    parser.add_argument("--depth", type=int, default=2,
                        help="クロール深度（デフォルト: 2）")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB書き込みなし（解析のみ）")
    args = parser.parse_args()

    if args.all:
        agency_ids = _all_agency_ids()
    elif args.agency:
        agency_ids = args.agency
    elif args.branch:
        all_ids = _all_agency_ids()
        agency_ids = [
            aid for aid in all_ids
            if any(aid.startswith(br + "_") or aid == br for br in args.branch)
        ]
    else:
        parser.error("--all, --agency, または --branch のいずれかを指定してください")
        return

    if not agency_ids:
        logger.error("対象機関が見つかりません")
        return

    logger.info(f"対象機関: {len(agency_ids)}件, FY: {args.fy}, workers: {args.workers}")
    run(
        fys=args.fy,
        agency_ids=agency_ids,
        workers=args.workers,
        dry_run=args.dry_run,
        depth=args.depth,
    )


if __name__ == "__main__":
    main()
