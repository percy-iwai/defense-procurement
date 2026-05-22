"""財計第2017号準拠 縦A4表形式（tekiseika）スキャン PDF パーサー。

春日基地・芦屋基地等の各月分PDFは 1bpc スキャン画像を landscape 向きで埋め込み、
PDF の rotation=270 で縦表示している。fitz でレンダリングすると回転処理が入り
easyocr が機能しないため、raw 画像を直接 OCR する。

列構成（raw 画像 3512x2480 基準、x 座標）:
  0     - 449  : 物品役務等の名称（件名）
  449   - 735  : 契約担当官等の氏名・所在地
  735   - 1020 : 契約を締結した日
  1020  - 1370 : 相手方の商号・名称・住所
  1370  - 1590 : 法人番号
  1590  - 1900 : 入札方式（一般競争/指名競争）
  1900  - 2155 : 予定価格
  2155  - 2400 : 契約金額
  2400  - 2690 : 落札率
  2690+ -      : 備考（公益法人情報含む）

使用例:
    from parsers.tekiseika_parser import parse_tekiseika_pdf
    records = parse_tekiseika_pdf(pdf_bytes, target_fys={2024})
"""
from __future__ import annotations

import io
import re
from typing import Optional

from loguru import logger

from parsers.ocr_parser import _get_reader, _to_amount, _to_date_str, fy_from_date

# ---------------------------------------------------------------------------
# 列境界（raw landscape 画像 3512px 幅基準、比率で持つ）
# ---------------------------------------------------------------------------

_REF_WIDTH = 3512.0

_COL_BOUNDS: list[tuple[float, str]] = [
    (449  / _REF_WIDTH, "contract_name"),
    (735  / _REF_WIDTH, "officer"),
    (1020 / _REF_WIDTH, "contract_date"),
    (1370 / _REF_WIDTH, "vendor"),
    (1590 / _REF_WIDTH, "corporate_number"),
    (1900 / _REF_WIDTH, "bid_method"),
    (2155 / _REF_WIDTH, "estimated_price"),
    (2400 / _REF_WIDTH, "contract_amount"),
    (2690 / _REF_WIDTH, "award_rate"),
    (1.0,               "notes"),
]

# ヘッダー行の終端（raw 高さ 2480 基準、比率）
_HEADER_END_RATIO = 480 / 2480.0
# フッター注釈の開始（raw 高さ 2480 基準、比率）= ページ下部 ~10%
_FOOTER_START_RATIO = 2250 / 2480.0
# Y バンドのデフォルト最大幅（midpoint 計算のフォールバック用）
_Y_BAND_MAX_RATIO = 160 / 2480.0

# 金額パターン
_AMT_PAT = re.compile(r"\b(\d{1,3}(?:[,，]\d{3})+)\b")
# 法人番号（13 桁）
_CORP_PAT = re.compile(r"\b(\d{13})\b")
# 日付（和暦 or 西暦）
_DATE_PAT = re.compile(
    r"(?:令和|[Rr])\s*\d{1,2}\s*[./年]\s*\d{1,2}\s*[./月]\s*\d{1,2}"
    r"|"
    r"\d{4}[/\-年]\d{1,2}[/\-月]\d{1,2}"
)
# 住所目印
_ADDR_PAT = re.compile(r"(?:都|道|府|県|市|区|町|村)")
# 会社名目印
_COMPANY_PAT = re.compile(r"(?:株式会社|有限会社|合同会社|一般社団|一般財団|公益財団|合資会社|企業組合|協同組合|グループ|ホールディングス)")


def _assign_col(cx_ratio: float) -> str:
    for bound, col in _COL_BOUNDS:
        if cx_ratio < bound:
            return col
    return "notes"


def _extract_amount(text: str) -> Optional[int]:
    m = _AMT_PAT.search(text)
    if m:
        return _to_amount(m.group(1))
    return None


def _normalize_ocr_digits(text: str) -> str:
    """OCR 誤認識（s→5, G→6 等）を補正して数字列を正規化。"""
    # 和暦文脈で誤認識されやすいパターン
    # 例: "令和6年s月1日" → "令和6年5月1日"
    text = re.sub(r"(?<=年)[sS](?=月)", "5", text)
    text = re.sub(r"(?<=年)[Oo](?=月)", "0", text)
    # 年の前の "G" "6" 誤読
    text = re.sub(r"(?<=令和)[G](?=年)", "6", text)
    return text


def _extract_date(text: str) -> Optional[str]:
    t = _normalize_ocr_digits(text)
    m = _DATE_PAT.search(t)
    if m:
        return _to_date_str(m.group(0))
    return None


def _extract_corp(text: str) -> Optional[str]:
    m = _CORP_PAT.search(text.replace(" ", ""))
    return m.group(1) if m else None


def _is_skip_line(text: str) -> bool:
    """ヘッダー・フッター・注釈行を判定。"""
    skip_kw = [
        "公共調達", "適正化", "財計第", "情報の公表",
        "行政改革", "公益法人", "付紙様式",
        "※", "公財", "特財",
    ]
    t = text.strip()
    for kw in skip_kw:
        if kw in t:
            return True
    return False


# ---------------------------------------------------------------------------
# ページ解析
# ---------------------------------------------------------------------------

def _parse_page(ocr_results: list, img_width: int, img_height: int) -> list[dict]:
    """1 ページ分の OCR 結果を解析してレコードリストを返す。"""
    header_end_y = img_height * _HEADER_END_RATIO
    footer_start_y = img_height * _FOOTER_START_RATIO
    y_band_max = img_height * _Y_BAND_MAX_RATIO

    # OCR 結果を列分類
    items: list[tuple[str, float, float, str, float]] = []  # (col, cx, cy, text, conf)
    for bbox, text, conf in ocr_results:
        if conf < 0.3:
            continue
        t = text.strip()
        if not t or _is_skip_line(t):
            continue
        # bounding box 中心座標
        cx = (bbox[0][0] + bbox[2][0]) / 2.0
        cy = (bbox[0][1] + bbox[2][1]) / 2.0
        if cy < header_end_y or cy > footer_start_y:
            continue  # ヘッダー行・フッター注釈をスキップ
        col = _assign_col(cx / img_width)
        items.append((col, cx, cy, t, conf))

    # contract_amount 列のアイテムを anchor に使う
    anchors_raw = [(cy, t) for col, cx, cy, t, conf in items if col == "contract_amount"]
    if not anchors_raw:
        return []

    # 有効な anchor のみ（最低金額 10万以上）
    anchors = [(cy, t) for cy, t in anchors_raw
               if (_extract_amount(t) or 0) >= 100_000]
    if not anchors:
        return []

    # 隣接 anchor の midpoint をバンド境界にする
    sorted_ys = sorted(a[0] for a in anchors)

    def _band_bounds(anchor_y: float) -> tuple[float, float]:
        idx = sorted_ys.index(anchor_y)
        lo = (anchor_y + sorted_ys[idx - 1]) / 2.0 if idx > 0 else anchor_y - y_band_max
        hi = (anchor_y + sorted_ys[idx + 1]) / 2.0 if idx < len(sorted_ys) - 1 else anchor_y + y_band_max
        return lo, hi

    records = []
    for anchor_y, anchor_text in anchors:
        amt = _extract_amount(anchor_text)
        if not amt:
            continue

        lo, hi = _band_bounds(anchor_y)

        # バンド内の全アイテムを収集
        band_items = [
            (col, t) for col, cx, cy, t, conf in items
            if lo <= cy <= hi
        ]

        # 列ごとにテキストを集約
        col_texts: dict[str, list[str]] = {}
        for col, t in band_items:
            col_texts.setdefault(col, []).append(t)

        rec: dict = {"contract_amount": amt}

        # 契約日
        for t in col_texts.get("contract_date", []):
            d = _extract_date(t)
            if d:
                rec["contract_date"] = d
                break

        # 法人番号
        for t in col_texts.get("corporate_number", []):
            cn = _extract_corp(t)
            if cn:
                rec["corporate_number"] = cn
                break
        # vendor 列にあることも多い
        if "corporate_number" not in rec:
            for t in col_texts.get("vendor", []):
                cn = _extract_corp(t)
                if cn:
                    rec["corporate_number"] = cn
                    break

        # ベンダー名・住所
        vendor_texts = col_texts.get("vendor", [])
        company_lines = [t for t in vendor_texts if _COMPANY_PAT.search(t)]
        addr_lines = [t for t in vendor_texts if _ADDR_PAT.search(t) and not _COMPANY_PAT.search(t)]
        other_lines = [t for t in vendor_texts if t not in company_lines and t not in addr_lines
                       and not _extract_corp(t)]

        if company_lines:
            rec["vendor_name"] = " ".join(company_lines)[:200]
        elif other_lines:
            rec["vendor_name"] = " ".join(other_lines)[:200]
        if addr_lines:
            rec["vendor_address"] = " ".join(addr_lines)[:300]

        # 件名
        name_texts = [t for t in col_texts.get("contract_name", [])
                      if len(t) >= 3 and not _extract_date(t)]
        if name_texts:
            rec["contract_name"] = " ".join(name_texts)[:300]

        # 予定価格
        for t in col_texts.get("estimated_price", []):
            ep = _extract_amount(t)
            if ep:
                rec["estimated_price"] = ep
                break

        # 入札方式
        bid_texts = col_texts.get("bid_method", [])
        if bid_texts:
            bid_raw = " ".join(bid_texts)
            if "指名" in bid_raw:
                rec["bid_method"] = "指名競争入札"
            else:
                rec["bid_method"] = "一般競争入札"

        # FY
        fy = fy_from_date(rec.get("contract_date"))
        if fy:
            rec["fiscal_year"] = fy

        records.append(rec)

    return records


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def is_landscape_scan(pdf_bytes: bytes) -> bool:
    """PDF が landscape raw 画像（bpc=1, width>height）を持つか判定。"""
    import fitz
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        imgs = page.get_images()
        if not imgs:
            return False
        raw = doc.extract_image(imgs[0][0])
        doc.close()
        return raw["bpc"] == 1 and raw["width"] > raw["height"]
    except Exception:
        return False


def parse_tekiseika_pdf(
    pdf_bytes: bytes,
    *,
    target_fys: set[int] | None = None,
    min_conf: float = 0.3,
) -> list[dict]:
    """tekiseika 縦A4スキャン PDF を解析して契約レコードのリストを返す。

    Parameters
    ----------
    pdf_bytes:
        PDF バイト列
    target_fys:
        対象会計年度セット（None の場合フィルタなし）
    min_conf:
        OCR 信頼度の下限（デフォルト 0.3）

    Returns
    -------
    list[dict]: 契約レコードのリスト
    """
    import fitz
    from PIL import Image

    reader = _get_reader()

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning(f"PDF オープン失敗: {e}")
        return []

    page_count = doc.page_count
    logger.info(f"  tekiseika OCR 開始: {page_count}ページ")

    all_records: list[dict] = []

    for page_idx in range(page_count):
        page = doc[page_idx]
        imgs = page.get_images()
        if not imgs:
            continue

        xref = imgs[0][0]
        try:
            raw = doc.extract_image(xref)
        except Exception as e:
            logger.warning(f"  page {page_idx + 1}: 画像抽出失敗: {e}")
            continue

        img_w, img_h = raw["width"], raw["height"]
        logger.debug(f"  page {page_idx + 1}: raw {img_w}x{img_h} bpc={raw['bpc']}")

        try:
            img = Image.open(io.BytesIO(raw["image"])).convert("RGB")
            import numpy as np
            img_arr = np.array(img)
        except Exception as e:
            logger.warning(f"  page {page_idx + 1}: 画像変換失敗: {e}")
            continue

        logger.info(f"    page {page_idx + 1}/{page_count} OCR中 ({img_w}x{img_h}px)...")
        try:
            ocr_results = reader.readtext(img_arr, detail=1)
        except Exception as e:
            logger.warning(f"    page {page_idx + 1} OCR失敗: {e}")
            continue

        page_records = _parse_page(ocr_results, img_w, img_h)

        filtered: list[dict] = []
        for rec in page_records:
            fy = rec.get("fiscal_year")
            if target_fys is not None and fy is not None and fy not in target_fys:
                continue
            if not rec.get("contract_amount"):
                continue
            filtered.append(rec)

        if filtered:
            logger.info(f"    page {page_idx + 1}: {len(filtered)}件取得")

        all_records.extend(filtered)

    doc.close()
    logger.info(f"  tekiseika OCR 完了: 合計 {len(all_records)}件")
    return all_records
