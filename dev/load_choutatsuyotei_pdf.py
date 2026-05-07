"""調達予定品目表 PDF（R04/R05/R06）のパース → choutatsuyotei テーブル投入。

入力: data/choutatsuyotei/r04/, r05/, r06/ の各13本
出力: procurement.db の choutatsuyotei テーブル（FY2022/2023/2024）

使い方:
  python dev/load_choutatsuyotei_pdf.py --fy 2022 2023 2024
  python dev/load_choutatsuyotei_pdf.py --fy 2022 2023 2024 --dry-run

カラム構造（pdfplumber extract_words の x 座標ベース）:
  担当官室コード : x = 60-88
  品名           : x = 88-378
  要求元         : x = 378-418
  予定件数       : x = 418-458
  契約予定月     : x = 458-493  (例: R6.2 → 月=2)
  区分           : x >= 493     (新/継/改)
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

import pdfplumber
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
PDF_BASE = PROJECT_ROOT / "data" / "choutatsuyotei"

# FY番号 → 和暦対応
FY_TO_REIWA = {2022: 4, 2023: 5, 2024: 6}
REIWA_TO_FY = {v: k for k, v in FY_TO_REIWA.items()}
FY_DIR = {2022: "r04", 2023: "r05", 2024: "r06"}

# 要求元（PDF生値）→ 正規化キー（FY2025 xlsx + PDF固有略称を追加）
REQ_ORG_NORMALIZE: dict[str, str] = {
    "陸自": "GSDF",
    "海自": "MSDF",
    "空自": "ASDF",
    "医大": "NDMC",
    "防医大": "NDMC",   # PDF固有略称
    "防大": "NDA",
    "装備庁": "ATLA",
    "統幕": "JS",
    "情本": "DIH",
    "内局": "NAIKYOKU",
    "監本": "KANSATSU",
    "防研": "NIDS",
    "防衛局": "RDB",
    # 地方防衛局の略称（PDF固有）
    "北方局": "RDB",
    "東北局": "RDB",
    "東方局": "RDB",
    "近中局": "RDB",
    "中四局": "RDB",
    "九防局": "RDB",
    "沖縄局": "RDB",
}

# デフォルト PDF x 座標によるカラム境界（ページ毎に動的調整される）
_DEFAULT_REQORG_X = 381.0   # '要求元' ヘッダーが見つからない場合のフォールバック

# ヘッダー行のy閾値（この値以下の行はヘッダー/タイトル → スキップ）
HEADER_Y_MAX = 82.0

# 品名正規化用 punctuation パターン（FY2025と同じ）
_PUNCT_RE = re.compile(r"[\s　，、,．。・／/＿_\-－‐ー（）()「」『』【】［］\[\]]+")


def normalize_item_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = _PUNCT_RE.sub("", s)
    return s.strip().lower()


def _parse_contract_month(date_str: str | None) -> int | None:
    """'R6.2' → 2、'R5.10' → 10 のように暦月を返す。"""
    if not date_str:
        return None
    m = re.match(r"R\d+\.(\d{1,2})", date_str.strip())
    if m:
        return int(m.group(1))
    return None


def _detect_header_x(words: list, text: str, default: float) -> float:
    """ヘッダー行から指定テキストを含む word の x0 を返す。"""
    for w in words:
        if w["top"] < HEADER_Y_MAX and text in w["text"]:
            return w["x0"]
    return default


def _build_col_config(words: list, fallback: dict | None = None) -> dict | None:
    """
    words からカラム境界辞書を構築して返す。
    ヘッダー行が存在しない場合は fallback を返す（None なら None）。
    """
    # 要求元ヘッダーが存在するかチェック
    has_header = any(
        w["top"] < HEADER_Y_MAX and "要求元" in w["text"] for w in words
    )
    if not has_header:
        return fallback

    reqorg_x  = _detect_header_x(words, "要求元",  _DEFAULT_REQORG_X)
    qty_x     = _detect_header_x(words, "予定件数", reqorg_x + 45)
    cmonth_x  = _detect_header_x(words, "納期",    qty_x + 40)
    bunrui_x  = _detect_header_x(words, "区分",    cmonth_x + 35)

    return {
        "col_tantou": (reqorg_x - 330, reqorg_x - 270),
        "col_item":   (reqorg_x - 270, reqorg_x - 12),
        "col_reqorg": (reqorg_x - 12,  qty_x - 5),
        "col_qty":    (qty_x - 5,      cmonth_x - 5),
        "col_cmonth": (cmonth_x - 5,   bunrui_x - 3),
        "col_bunrui": (bunrui_x - 3,   999),
    }


def _extract_rows_from_page(page, col_config: dict | None = None) -> tuple[list[dict], dict | None]:
    """
    1ページ分の words を解析して (行リスト, col_config) を返す。
    col_config はこのページで検出または引き継いだカラム境界辞書。
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    if not words:
        return [], col_config

    # このページのヘッダーからカラム境界を更新（なければ引き継ぎ）
    col_config = _build_col_config(words, fallback=col_config)
    if col_config is None:
        # デフォルト値で構築
        reqorg_x = _DEFAULT_REQORG_X
        qty_x    = reqorg_x + 45
        cmonth_x = qty_x + 40
        bunrui_x = cmonth_x + 35
        col_config = {
            "col_tantou": (reqorg_x - 330, reqorg_x - 270),
            "col_item":   (reqorg_x - 270, reqorg_x - 12),
            "col_reqorg": (reqorg_x - 12,  qty_x - 5),
            "col_qty":    (qty_x - 5,      cmonth_x - 5),
            "col_cmonth": (cmonth_x - 5,   bunrui_x - 3),
            "col_bunrui": (bunrui_x - 3,   999),
        }

    col_tantou = col_config["col_tantou"]
    col_item   = col_config["col_item"]
    col_reqorg = col_config["col_reqorg"]
    col_qty    = col_config["col_qty"]
    col_cmonth = col_config["col_cmonth"]
    col_bunrui = col_config["col_bunrui"]

    # y 座標でグルーピング（同じ行なら y 差 ≤3 とみなす）
    rows_by_y: dict[int, list] = defaultdict(list)
    for w in words:
        y_key = round(w["top"])
        rows_by_y[y_key].append(w)

    result = []
    for y_key in sorted(rows_by_y):
        if y_key < HEADER_Y_MAX:
            continue  # ヘッダー行スキップ

        wlist = sorted(rows_by_y[y_key], key=lambda w: w["x0"])

        def col_text(xmin: float, xmax: float) -> str:
            parts = [w["text"] for w in wlist if xmin <= w["x0"] < xmax]
            return " ".join(parts).strip()

        tantou = col_text(*col_tantou)
        item   = col_text(*col_item)
        reqorg = col_text(*col_reqorg)
        qty_s  = col_text(*col_qty)
        cmonth = col_text(*col_cmonth)
        bunrui = col_text(*col_bunrui)

        # 品名と要求元のどちらかがないとデータ行でない
        if not item and not reqorg:
            continue
        # 要求元が空の行（品名の続き行 = 長い品名が2行に折り返した場合）はスキップ
        if not reqorg:
            continue

        try:
            qty_val = int(qty_s) if qty_s and qty_s.isdigit() else None
        except (ValueError, TypeError):
            qty_val = None

        result.append({
            "tantou_code": tantou,
            "item_name":   item,
            "req_org_raw": reqorg,
            "qty":         qty_val,
            "contract_month_str": cmonth,
            "bunrui":      bunrui,
        })

    return result, col_config


def parse_pdf(pdf_path: Path, fiscal_year: int) -> list[dict]:
    """PDF 1本 → DB 投入用 dict のリスト。"""
    records: list[dict] = []
    row_idx = 0

    with pdfplumber.open(pdf_path) as pdf:
        # ページ1の先頭からタイトル行（担当官室名）を取得
        tantou_office = pdf_path.stem  # fallback: ファイル名 stem

        col_config: dict | None = None  # PDF内で共有するカラム境界
        for page_num, page in enumerate(pdf.pages, start=1):
            rows, col_config = _extract_rows_from_page(page, col_config)
            for row in rows:
                row_idx += 1
                raw = row["req_org_raw"]
                org = REQ_ORG_NORMALIZE.get(raw)
                if org is None:
                    logger.warning(
                        f"{pdf_path.name} page={page_num} row={row_idx}: "
                        f"未知の要求元 {raw!r} - スキップ"
                    )
                    continue

                cm = _parse_contract_month(row["contract_month_str"])
                # 暦月 → 会計年度月（4=4月, ..., 12=12月, 13=1月, 14=2月, 15=3月）
                contract_month_fy = cm if cm is not None and cm >= 4 else (
                    cm + 12 if cm is not None else None
                )

                records.append({
                    "fiscal_year":         fiscal_year,
                    "source_file":         pdf_path.name,
                    "source_row":          row_idx,
                    "requesting_org_raw":  raw,
                    "requesting_org":      org,
                    "item_name":           row["item_name"],
                    "item_name_norm":      normalize_item_name(row["item_name"]),
                    "spec_class":          None,
                    "qty":                 row["qty"],
                    "request_month":       None,
                    "contract_month":      contract_month_fy,
                    "delivery_date":       None,
                    "tantou_office":       tantou_office,
                })

    logger.info(
        f"[parse] {pdf_path.name}: {len(records)} records "
        f"(total rows scanned: {row_idx})"
    )
    return records


def load_into_db(records: list[dict], db_path: Path = DB_PATH) -> dict:
    insert_sql = """
    INSERT OR IGNORE INTO choutatsuyotei
      (fiscal_year, source_file, source_row, requesting_org_raw, requesting_org,
       item_name, item_name_norm, spec_class, qty,
       request_month, contract_month, delivery_date, tantou_office)
    VALUES
      (:fiscal_year, :source_file, :source_row, :requesting_org_raw, :requesting_org,
       :item_name, :item_name_norm, :spec_class, :qty,
       :request_month, :contract_month, :delivery_date, :tantou_office)
    """
    inserted = duplicates = 0
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        for rec in records:
            cur.execute(insert_sql, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        con.commit()
    return {"inserted": inserted, "duplicates": duplicates, "total": len(records)}


def run_fy(fiscal_year: int, db_path: Path = DB_PATH, dry_run: bool = False) -> dict:
    fy_dir = PDF_BASE / FY_DIR[fiscal_year]
    if not fy_dir.exists():
        logger.error(f"ディレクトリが存在しない: {fy_dir}")
        return {"error": str(fy_dir)}

    pdf_files = sorted(fy_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"PDFが見つからない: {fy_dir}")
        return {"pdf_count": 0}

    all_records: list[dict] = []
    for pdf_path in pdf_files:
        recs = parse_pdf(pdf_path, fiscal_year)
        all_records.extend(recs)

    logger.info(
        f"[FY{fiscal_year}] {len(pdf_files)} PDFs, {len(all_records)} records total"
    )

    if dry_run:
        logger.info("[dry-run] DB書き込みスキップ")
        # req_org 分布を出力
        from collections import Counter
        dist = Counter(r["requesting_org"] for r in all_records)
        return {
            "fiscal_year": fiscal_year,
            "pdf_count": len(pdf_files),
            "total_records": len(all_records),
            "req_org_dist": dict(dist.most_common()),
        }

    stats = load_into_db(all_records, db_path)
    stats["fiscal_year"] = fiscal_year
    stats["pdf_count"] = len(pdf_files)
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fy", nargs="+", type=int, default=[2022, 2023, 2024],
        choices=[2022, 2023, 2024],
        help="処理する会計年度 (default: 2022 2023 2024)",
    )
    p.add_argument("--db", default=str(DB_PATH), help="DB パス")
    p.add_argument("--dry-run", action="store_true", help="DB書き込みなしで解析のみ")
    args = p.parse_args()

    db_path = Path(args.db)

    for fy in sorted(set(args.fy)):
        logger.info(f"=== FY{fy} 処理開始 ===")
        stats = run_fy(fy, db_path, dry_run=args.dry_run)
        print(f"\n[FY{fy}] results:")
        for k, v in stats.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for kk, vv in v.items():
                    print(f"    {kk:<12} {vv}")
            else:
                print(f"  {k:<30} {v}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
