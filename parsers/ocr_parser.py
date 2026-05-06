"""画像スキャン PDF を easyocr で解析して契約レコードを返すパーサー。

三沢基地 FY2024 等、テキストレイヤーのない画像 PDF に対応。

使用例:
    from parsers.ocr_parser import parse_ocr_records
    records = parse_ocr_records(pdf_bytes, target_fys={2024})
"""
from __future__ import annotations

import io
import re
from typing import Optional

from loguru import logger

# ---------------------------------------------------------------------------
# easyocr Reader シングルトン（初回のみモデルロード）
# ---------------------------------------------------------------------------
_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        logger.info("easyocr Reader を初期化中（初回のみ）...")
        _reader = easyocr.Reader(["ja", "en"], gpu=False, verbose=False)
        logger.info("easyocr Reader 初期化完了")
    return _reader


# ---------------------------------------------------------------------------
# ヘルパー: pdf_table.py と同じロジックを再実装（依存を最小化）
# ---------------------------------------------------------------------------

def _to_amount(text) -> Optional[int]:
    """金額文字列を整数（円）に変換。"""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        try:
            return int(round(float(text)))
        except (OverflowError, ValueError):
            return None
    s = str(text).replace(",", "").replace("，", "").replace("円", "").replace("¥", "").strip()
    s = re.sub(r"[^\d\.\-]", "", s)
    if not s:
        return None
    try:
        return int(round(float(s)))
    except (ValueError, OverflowError):
        return None


def _to_date_str(text) -> Optional[str]:
    """和暦 / 西暦テキストを YYYYMMDD に変換。

    OCR 誤認識（「令和G年」「R6．4」等）に対してベストエフォートで処理。
    """
    if not text:
        return None
    s = str(text).strip()
    # 和暦: 令和6年4月1日 / R6.4.1 / R6/4/1 / 令和6.4.1
    m = re.search(r"(?:令和|[Rr])\s*(\d{1,2})\s*[./年]\s*(\d{1,2})\s*[./月]\s*(\d{1,2})", s)
    if m:
        ry, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= ry <= 20 and 1 <= mo <= 12 and 1 <= dd <= 31:
            return f"{2018 + ry}{mo:02d}{dd:02d}"
    # 西暦
    m = re.search(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})", s)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return None


def fy_from_date(yyyymmdd: Optional[str]) -> Optional[int]:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    y, m = int(yyyymmdd[:4]), int(yyyymmdd[4:6])
    return y if m >= 4 else y - 1


# ---------------------------------------------------------------------------
# OCR 結果を行にグループ化するロジック
# ---------------------------------------------------------------------------

def _group_into_lines(ocr_results: list, y_tolerance: int = 10) -> list[list[tuple]]:
    """OCR 結果を y 座標でグループ化し、行ごとのリストを返す。

    各要素: (x_left, y_top, text, conf)
    行内は x 座標順にソート済み。
    """
    # conf >= 0.4 のみ採用
    items = []
    for bbox, text, conf in ocr_results:
        if conf < 0.4:
            continue
        # bbox: [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
        x_left = bbox[0][0]
        y_top = bbox[0][1]
        items.append((x_left, y_top, text.strip(), conf))

    if not items:
        return []

    # y でソート
    items.sort(key=lambda t: t[1])

    lines: list[list[tuple]] = []
    current_line: list[tuple] = [items[0]]
    current_y = items[0][1]

    for item in items[1:]:
        if abs(item[1] - current_y) <= y_tolerance:
            current_line.append(item)
        else:
            # x でソートしてから確定
            current_line.sort(key=lambda t: t[0])
            lines.append(current_line)
            current_line = [item]
            current_y = item[1]

    if current_line:
        current_line.sort(key=lambda t: t[0])
        lines.append(current_line)

    return lines


def _line_text(line: list[tuple]) -> str:
    """行内の各要素を結合してテキストにする（スペース区切り）。"""
    return " ".join(t[2] for t in line)


# ---------------------------------------------------------------------------
# レコード抽出ロジック
# ---------------------------------------------------------------------------

# 金額パターン: カンマ区切りの数字（100万以上）
_AMT_PAT = re.compile(r"\b(\d{1,3}(?:[,，]\d{3})+)\b")
# 法人番号: 13桁数字
_CORP_PAT = re.compile(r"\b(\d{13})\b")
# 日付パターン（和暦・西暦）
_DATE_PAT = re.compile(
    r"(?:令和|[Rr])\s*\d{1,2}\s*[./年]\s*\d{1,2}\s*[./月]\s*\d{1,2}"
    r"|"
    r"\d{4}[/\-年]\d{1,2}[/\-月]\d{1,2}"
)
# 非公表パターン（金額セルに出てくる場合）
_HIKO_PAT = re.compile(r"非公表")


def _extract_amounts_from_line(line_text: str) -> list[int]:
    """行テキストから全金額候補を抽出。"""
    results = []
    for m in _AMT_PAT.finditer(line_text):
        amt = _to_amount(m.group(1))
        if amt and amt >= 100_000:  # 最低10万円以上
            results.append(amt)
    return results


def _extract_date_from_line(line_text: str) -> Optional[str]:
    """行テキストから最初に見つかった日付を抽出。"""
    m = _DATE_PAT.search(line_text)
    if m:
        return _to_date_str(m.group(0))
    return None


def _extract_corp_number(text: str) -> Optional[str]:
    """テキストから法人番号（13桁）を抽出。"""
    m = _CORP_PAT.search(text.replace(" ", ""))
    return m.group(1) if m else None


def _is_header_like(text: str) -> bool:
    """ヘッダー行・タイトル行など非データ行を除外。"""
    # 単語レベルのキーワード（これらだけ含んでいればヘッダー確定）
    definite_keywords = [
        "公共調達", "適正化", "情報の公表",
        "に基づく競争入札", "公表（物品",
    ]
    # 列ヘッダーそのもの（短い行で使われるケース）
    column_headers = [
        "件名", "名称", "契約金額", "落札金額", "業者名", "法人番号",
        "入札方式", "落札率", "予定価格", "締結日", "契約日",
    ]
    # 組み合わせキーワード（これらを含む「短い」行）
    short_header_keywords = [
        "様式", "航空自衛隊", "会計隊",
        "ページ", "合計", "小計",
    ]
    t = text.strip()
    for kw in definite_keywords:
        if kw in t:
            return True
    # 列ヘッダー行: テキストが短くてカラム名のみ含む場合
    if len(t) <= 40:
        for kw in column_headers:
            if kw in t:
                return True
        for kw in short_header_keywords:
            if kw in t:
                return True
    # 長い行でも "随意契約" / "競争入札" だけの行はヘッダー系
    if t in ("随意契約", "競争入札", "一般競争入札", "指名競争入札", "公共工事"):
        return True
    return False


# ---------------------------------------------------------------------------
# ページ単位のレコード抽出
# ---------------------------------------------------------------------------

def _extract_records_from_page(lines: list[list[tuple]]) -> list[dict]:
    """1ページ分の行リストからレコードを抽出する。

    戦略:
    - 金額を含む行を「アンカー行」とみなす
    - 同じアンカー行に日付があれば contract_date を取得
    - 上下数行からベンダー名・法人番号・住所を補完
    - 1金額 → 1レコード
    """
    records: list[dict] = []

    line_texts = [_line_text(ln) for ln in lines]

    for i, ltxt in enumerate(line_texts):
        if _is_header_like(ltxt):
            continue

        amounts = _extract_amounts_from_line(ltxt)
        if not amounts:
            continue

        # アンカー行確定
        anchor_text = ltxt

        # 同行から日付を探す
        contract_date = _extract_date_from_line(anchor_text)

        # 同行から法人番号を探す
        corp_num = _extract_corp_number(anchor_text)

        # 周辺行（±4行）を走査してベンダー名・日付・法人番号を補完
        context_lines = []
        for j in range(max(0, i - 4), min(len(line_texts), i + 5)):
            if j != i:
                context_lines.append(line_texts[j])

        if not contract_date:
            for ctxt in context_lines:
                d = _extract_date_from_line(ctxt)
                if d:
                    contract_date = d
                    break

        if not corp_num:
            for ctxt in context_lines:
                cn = _extract_corp_number(ctxt)
                if cn:
                    corp_num = cn
                    break

        # ベンダー名候補: 法人番号の直後行、または金額行の前後から
        vendor_name = None
        vendor_address = None

        # 法人番号行を探してその前後のテキストからベンダー名を推定
        corp_line_idx: Optional[int] = None
        for j, ctxt in enumerate(line_texts):
            if corp_num and corp_num in ctxt.replace(" ", ""):
                corp_line_idx = j
                break

        if corp_line_idx is not None:
            # 法人番号の直前行をベンダー名候補に
            for offset in (-1, -2, 1, 2):
                j2 = corp_line_idx + offset
                if 0 <= j2 < len(line_texts):
                    candidate = line_texts[j2].strip()
                    if candidate and not _is_header_like(candidate) and len(candidate) >= 3:
                        # 金額・日付・数字のみ行は除外
                        if not _AMT_PAT.search(candidate) and not _DATE_PAT.search(candidate):
                            if not re.match(r"^[\d\s,，\.]+$", candidate):
                                vendor_name = candidate[:200]
                                break

        # ベンダー名が取れなかった場合: 金額行の前1〜2行を候補にする
        if not vendor_name:
            for offset in (-1, -2):
                j2 = i + offset
                if 0 <= j2 < len(line_texts):
                    candidate = line_texts[j2].strip()
                    if candidate and not _is_header_like(candidate) and len(candidate) >= 3:
                        if not _AMT_PAT.search(candidate) and not _DATE_PAT.search(candidate):
                            if not re.match(r"^[\d\s,，\.]+$", candidate):
                                vendor_name = candidate[:200]
                                break

        # 住所（都道府県を含む行）
        addr_pat = re.compile(r"(?:都|道|府|県|市|区|町|村)")
        for ctxt in context_lines:
            if addr_pat.search(ctxt) and not _is_header_like(ctxt):
                if not _AMT_PAT.search(ctxt):
                    vendor_address = ctxt.strip()[:300]
                    break

        # 件名候補（アンカー行の前5行以内で長いテキスト行）
        contract_name = None
        for offset in range(-5, 0):
            j2 = i + offset
            if 0 <= j2 < len(line_texts):
                candidate = line_texts[j2].strip()
                if (candidate and len(candidate) >= 5
                        and not _is_header_like(candidate)
                        and not _AMT_PAT.search(candidate)
                        and not _DATE_PAT.search(candidate)
                        and not re.match(r"^[\d\s,，\.]+$", candidate)):
                    # ある程度長い行を件名候補とする
                    if len(candidate) >= 8:
                        contract_name = candidate[:300]
                        break

        for amt in amounts:
            rec: dict = {
                "contract_amount": amt,
            }
            if contract_date:
                rec["contract_date"] = contract_date
            if corp_num:
                rec["corporate_number"] = corp_num
            if vendor_name:
                rec["vendor_name"] = vendor_name
            if vendor_address:
                rec["vendor_address"] = vendor_address
            if contract_name:
                rec["contract_name"] = contract_name

            # FY
            fy = fy_from_date(contract_date)
            if fy is not None:
                rec["fiscal_year"] = fy

            records.append(rec)

    return records


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def parse_ocr_records(
    data: bytes,
    *,
    target_fys: set[int] | None = None,
    dpi: int = 200,
    y_tolerance: int = 10,
) -> list[dict]:
    """画像 PDF を easyocr で解析して契約レコードのリストを返す。

    Parameters
    ----------
    data:
        PDF バイト列
    target_fys:
        対象会計年度セット（None の場合フィルタなし）
    dpi:
        ラスタライズ解像度（デフォルト 200dpi）
    y_tolerance:
        同行グループ化の y 座標許容誤差（px）

    Returns
    -------
    list[dict]: 契約レコードのリスト（contract_amount 必須、他はベストエフォート）
    """
    import fitz
    import numpy as np
    from PIL import Image

    reader = _get_reader()
    records: list[dict] = []

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        logger.warning(f"PDF オープン失敗: {e}")
        return []

    page_count = doc.page_count
    logger.info(f"  OCR開始: {page_count}ページ")

    for page_idx in range(page_count):
        page = doc[page_idx]

        # ページを PNG に変換
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")

        img_np = np.array(Image.open(io.BytesIO(img_bytes)))

        logger.info(f"    page {page_idx + 1}/{page_count} OCR中 ({img_np.shape[1]}x{img_np.shape[0]}px)...")

        try:
            ocr_results = reader.readtext(img_np, detail=1)
        except Exception as e:
            logger.warning(f"    page {page_idx + 1} OCR失敗: {e}")
            continue

        lines = _group_into_lines(ocr_results, y_tolerance=y_tolerance)
        page_records = _extract_records_from_page(lines)

        # FY フィルタ
        filtered: list[dict] = []
        for rec in page_records:
            fy = rec.get("fiscal_year")
            if target_fys is not None and fy is not None and fy not in target_fys:
                continue
            # contract_amount が必須
            if not rec.get("contract_amount"):
                continue
            filtered.append(rec)

        if filtered:
            logger.info(f"    page {page_idx + 1}: {len(filtered)}件取得")

        records.extend(filtered)

    doc.close()
    logger.info(f"  OCR完了: 合計 {len(records)}件")
    return records
