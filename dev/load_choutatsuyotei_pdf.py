"""調達予定品目表 PDF（R02〜R06）のパース → choutatsuyotei テーブル投入。

入力: data/choutatsuyotei/r02/, r03/, r04/, r05/, r06/ の各13〜14本
出力: procurement.db の choutatsuyotei テーブル（FY2020〜2024）

使い方:
  python dev/load_choutatsuyotei_pdf.py --fy 2020 2021 2022 2023 2024
  python dev/load_choutatsuyotei_pdf.py --fy 2022 2023 2024 --dry-run

カラム構造はPDFの年度ごとに動的検出:
  1. ページ上の「要求元」ヘッダーワードを検索 (y上限200pt)
  2. 「件数/件」「納」「区」を検索して右側列境界を決定
  3. 左ゾーン (x < reqorg_x-5) の先頭数字ワードを担当官室コード、
     残りを品名として取り出す
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

FY_DIR = {
    2015: "h27",
    2016: "h28",
    2017: "h29",
    2018: "h30",
    2019: "r01",
    2020: "r02",
    2021: "r03",
    2022: "r04",
    2023: "r05",
    2024: "r06",
}

# 要求元（PDF生値）→ 正規化キー
REQ_ORG_NORMALIZE: dict[str, str] = {
    "陸自": "GSDF",
    "海自": "MSDF",
    "空自": "ASDF",
    "医大": "NDMC",
    "防医大": "NDMC",
    "防大": "NDA",
    "装備庁": "ATLA",
    "統幕": "JS",
    "情本": "DIH",
    "内局": "NAIKYOKU",
    "監本": "KANSATSU",
    "防研": "NIDS",
    "防衛局": "RDB",
    "北方局": "RDB",
    "東北局": "RDB",
    "東方局": "RDB",
    "近中局": "RDB",
    "中四局": "RDB",
    "九防局": "RDB",
    "沖縄局": "RDB",
}

# ヘッダー行を探すy上限
HEADER_SEARCH_Y_MAX = 200.0
# 担当官室コード（left col）として扱う最大x（これを超えたら品名扱い）
TANTOU_CODE_MAX_X = 130.0
# 列境界の左オフセット（ヘッダーx座標からデータ左端までのバッファ）
COL_OFFSET = 8.0

# 品名正規化用
_PUNCT_RE = re.compile(r"[\s　，、,．。・／/＿_\-－‐ー（）()「」『』【】［］\[\]]+")


def normalize_item_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = _PUNCT_RE.sub("", s)
    return s.strip().lower()


def _parse_contract_month(date_str: str | None) -> int | None:
    """
    各年度のフォーマットに対応:
      R6.2   → 2    (R05/R06)
      2022/6/1 → 6  (R04)
      2021年6月 → 6  (R02/R03)
    """
    if not date_str:
        return None
    s = date_str.strip()
    m = re.match(r"R\d+\.(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.match(r"\d{4}/(\d{1,2})/", s)
    if m:
        return int(m.group(1))
    m = re.match(r"\d{4}年(\d{1,2})月", s)
    if m:
        return int(m.group(1))
    return None


def _find_keyword_x(words: list, keywords: list[str], header_y: float,
                    delta_y: float = 25.0, min_x: float = 0.0) -> float | None:
    """ヘッダー行付近 (header_y ± delta_y) かつ min_x より右にある
    keywords のいずれかを含む最初のワードの x0 を返す。"""
    for w in sorted(words, key=lambda w: w["x0"]):
        if abs(w["top"] - header_y) <= delta_y and w["x0"] >= min_x:
            for kw in keywords:
                if kw in w["text"]:
                    return w["x0"]
    return None


def _build_col_config(words: list, fallback: dict | None = None) -> dict | None:
    """
    ページの words から列境界辞書を構築して返す。
    「要求元」ヘッダーワードを動的に検出し、右側列を
    「件数/件」「納」「区」ヘッダーで特定する。
    ヘッダーが見つからない場合は fallback を返す。
    """
    # 「要求元」ヘッダーを探す（y上限 HEADER_SEARCH_Y_MAX）
    reqorg_word = None
    for w in words:
        if "要求元" in w["text"] and w["top"] < HEADER_SEARCH_Y_MAX:
            if reqorg_word is None or w["top"] < reqorg_word["top"]:
                reqorg_word = w
    if reqorg_word is None:
        return fallback

    header_y = reqorg_word["top"]
    reqorg_x = reqorg_word["x0"]

    # 右側列ヘッダーを検出（reqorg_x より右）
    qty_x_raw = _find_keyword_x(
        words, ["件数", "件"], header_y, delta_y=25.0, min_x=reqorg_x + 15
    ) or (reqorg_x + 40)

    noki_x_raw = _find_keyword_x(
        words, ["納期", "納"], header_y, delta_y=25.0, min_x=reqorg_x + 40
    ) or (qty_x_raw + 35)

    bunrui_x_raw = _find_keyword_x(
        words, ["区分", "区"], header_y, delta_y=25.0, min_x=noki_x_raw + 10
    ) or (noki_x_raw + 35)

    # データ行開始y（ヘッダー行より25pt以降）
    data_start_y = header_y + 25.0

    return {
        "data_start_y": data_start_y,
        "reqorg_x":   reqorg_x,
        "qty_x":      qty_x_raw,
        "noki_x":     noki_x_raw,
        "bunrui_x":   bunrui_x_raw,
    }


def _extract_rows_from_page(page, col_config: dict | None = None) -> tuple[list[dict], dict | None]:
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    if not words:
        return [], col_config

    col_config = _build_col_config(words, fallback=col_config)
    if col_config is None:
        return [], col_config

    data_start_y = col_config["data_start_y"]
    reqorg_x     = col_config["reqorg_x"]
    qty_x        = col_config["qty_x"]
    noki_x       = col_config["noki_x"]
    bunrui_x     = col_config["bunrui_x"]

    # 列境界（左オフセットを適用）
    b_reqorg  = reqorg_x  - COL_OFFSET / 2
    b_qty     = qty_x     - COL_OFFSET
    b_noki    = noki_x    - COL_OFFSET
    b_bunrui  = bunrui_x  - COL_OFFSET

    def col_text(wlist, xmin: float, xmax: float) -> str:
        return " ".join(w["text"] for w in wlist if xmin <= w["x0"] < xmax).strip()

    # y 座標でグルーピング
    rows_by_y: dict[int, list] = defaultdict(list)
    for w in words:
        if w["top"] >= data_start_y:
            rows_by_y[round(w["top"])].append(w)

    result = []
    for y_key in sorted(rows_by_y):
        wlist = sorted(rows_by_y[y_key], key=lambda w: w["x0"])

        # 左ゾーン (tantou + item)
        left_words = [w for w in wlist if w["x0"] < b_reqorg]
        # 先頭の「小さな数字ワード (x ≤ TANTOU_CODE_MAX_X)」を担当官室コードとして取り出す
        item_start_idx = 0
        for i, w in enumerate(left_words):
            if (w["text"].isdigit()
                    and len(w["text"]) <= 2
                    and w["x0"] <= TANTOU_CODE_MAX_X):
                item_start_idx = i + 1
            else:
                break
        tantou = " ".join(w["text"] for w in left_words[:item_start_idx])
        item   = " ".join(w["text"] for w in left_words[item_start_idx:])

        reqorg = col_text(wlist, b_reqorg, b_qty)
        qty_s  = col_text(wlist, b_qty,    b_noki)
        cmonth = col_text(wlist, b_noki,   b_bunrui)
        bunrui = col_text(wlist, b_bunrui, 999)

        if not reqorg:
            continue

        try:
            qty_val = int(qty_s) if qty_s and qty_s.isdigit() else None
        except (ValueError, TypeError):
            qty_val = None

        result.append({
            "tantou_code":         tantou,
            "item_name":           item,
            "req_org_raw":         reqorg,
            "qty":                 qty_val,
            "contract_month_str":  cmonth,
            "bunrui":              bunrui,
        })

    return result, col_config


def parse_pdf(pdf_path: Path, fiscal_year: int) -> list[dict]:
    records: list[dict] = []
    row_idx = 0
    tantou_office = pdf_path.stem

    col_config: dict | None = None
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            rows, col_config = _extract_rows_from_page(page, col_config)
            for row in rows:
                row_idx += 1
                raw = row["req_org_raw"]
                # 複数ワードが混入した場合は最初の1語のみを使う
                raw_key = raw.split()[0] if raw else ""
                org = REQ_ORG_NORMALIZE.get(raw_key)
                if org is None:
                    logger.debug(
                        f"{pdf_path.name} page={page_num} row={row_idx}: "
                        f"未知の要求元 {raw!r} → スキップ"
                    )
                    continue

                cm = _parse_contract_month(row["contract_month_str"])
                contract_month_fy = cm if cm is not None and cm >= 4 else (
                    cm + 12 if cm is not None else None
                )

                records.append({
                    "fiscal_year":         fiscal_year,
                    "source_file":         pdf_path.name,
                    "source_row":          row_idx,
                    "requesting_org_raw":  raw_key,
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
        f"(rows scanned: {row_idx})"
    )
    return records


def load_into_db(records: list[dict], db_path: Path,
                 reload: bool = False) -> dict:
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
    inserted = skipped = deleted = 0
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        if reload and records:
            fy = records[0]["fiscal_year"]
            cur.execute("DELETE FROM choutatsuyotei WHERE fiscal_year = ?", (fy,))
            deleted = cur.rowcount
            logger.info(f"[reload] FY{fy}: {deleted} 行削除")
        for rec in records:
            cur.execute(insert_sql, rec)
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
        con.commit()
    return {"deleted": deleted, "inserted": inserted, "skipped": skipped, "total": len(records)}


def run_fy(fiscal_year: int, db_path: Path = DB_PATH,
           dry_run: bool = False, reload: bool = False) -> dict:
    fy_key = FY_DIR.get(fiscal_year)
    if fy_key is None:
        return {"error": f"未対応のFY: {fiscal_year}"}

    fy_dir = PDF_BASE / fy_key
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

    logger.info(f"[FY{fiscal_year}] {len(pdf_files)} PDFs, {len(all_records)} records total")

    if dry_run:
        from collections import Counter
        dist = Counter(r["requesting_org"] for r in all_records)
        item_empty = sum(1 for r in all_records if not r["item_name"])
        return {
            "fiscal_year":    fiscal_year,
            "pdf_count":      len(pdf_files),
            "total_records":  len(all_records),
            "item_empty_pct": f"{100*item_empty/len(all_records):.0f}%" if all_records else "N/A",
            "req_org_dist":   dict(dist.most_common()),
        }

    stats = load_into_db(all_records, db_path, reload=reload)
    stats["fiscal_year"] = fiscal_year
    stats["pdf_count"] = len(pdf_files)
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fy", nargs="+", type=int,
        default=[2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
        choices=[2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
        help="処理する会計年度 (default: 2015〜2024)",
    )
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--reload", action="store_true",
        help="既存FYを一旦DELETE → 再INSERT（item_name修正・再収集用）",
    )
    args = p.parse_args()

    db_path = Path(args.db)

    for fy in sorted(set(args.fy)):
        logger.info(f"=== FY{fy} 処理開始 ===")
        stats = run_fy(fy, db_path, dry_run=args.dry_run, reload=args.reload)
        print(f"\n[FY{fy}] results:")
        for k, v in stats.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for kk, vv in v.items():
                    print(f"    {kk:<14} {vv}")
            else:
                print(f"  {k:<32} {v}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
