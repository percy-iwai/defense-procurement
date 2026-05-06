"""PDF表形式の調達公表データから契約レコードを抽出。

対応書式:
- 防衛局月次PDF（北関東/南関東/東北/中国四国/九州/沖縄等）
- 公表標準様式（件名/業者/契約金額/入札方式/法人番号/落札率/締結日）
"""
from __future__ import annotations

import io
import re
from typing import Iterable, Optional

from loguru import logger

import pdfplumber

# 列ヘッダー → DBカラム名（最初に当たった列を採用）
HEADER_KEYWORDS: list[tuple[str, str]] = [
    ("件名", "contract_name"),
    ("名称", "contract_name"),
    ("工事名", "contract_name"),
    ("業務名", "contract_name"),
    ("品名", "contract_name"),
    ("相手方の商号", "vendor_name"),
    ("相手方の名称", "vendor_name"),
    ("契約相手", "vendor_name"),
    ("業者名", "vendor_name"),
    ("落札業者", "vendor_name"),
    ("受注者", "vendor_name"),
    ("締結した日", "contract_date"),
    ("締結日", "contract_date"),
    ("契約日", "contract_date"),
    ("法人番号", "corporate_number"),
    ("予定価格", "estimated_price"),
    ("契約金額", "contract_amount"),
    ("落札金額", "contract_amount"),
    ("落札価格", "contract_amount"),
    ("落札率", "award_rate"),
    ("入札方式", "bid_method"),
    ("入札・指名", "bid_method"),
    ("一般競争入札", "bid_method"),  # ヘッダーで区分名そのものが書かれているケース
    ("競争等の区分", "bid_method"),  # aasch系: "一般競争等の区分等"
    ("数量", "quantity"),
    ("単位", "unit_measure"),
    ("根拠条文", "zuii_reason"),
    ("随意契約の根拠", "zuii_reason"),
    ("担当官", "contract_officer"),
]

BID_METHOD_MAP = {
    "一般競争": "一般競争入札",
    "総合評価": "総合評価落札方式",
    "指名競争": "指名競争入札",
    "随意契約": "随意契約",
    "随意": "随意契約",
    "プロポーザル": "公募型プロポーザル",
    "見積合わせ": "見積合わせ",
}


def _normalize_bid(text: str) -> Optional[str]:
    if not text:
        return None
    t = str(text).strip()
    for k, v in BID_METHOD_MAP.items():
        if k in t:
            return v
    return t[:30] or None


def _to_amount(text) -> Optional[int]:
    """金額文字列/数値を整数（円）に変換。Excel float の精度ノイズも吸収。"""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        try:
            return int(round(float(text)))
        except (OverflowError, ValueError):
            return None
    s = str(text).replace(",", "").replace("，", "").replace("円", "").replace("¥", "").strip()
    # Split on whitespace to avoid concatenating multiple values in one cell
    # (e.g. gsdf_buki PDFs store tax-excl and tax-incl side by side; take the last = tax-incl)
    tokens = re.split(r"[\s\n\r]+", s)
    for token in reversed(tokens):
        clean = re.sub(r"[^\d\.\-]", "", token)
        if clean:
            try:
                return int(round(float(clean)))
            except (ValueError, OverflowError):
                continue
    return None


def _to_rate(text) -> Optional[float]:
    if text is None:
        return None
    s = str(text).replace("%", "").replace("％", "").strip()
    try:
        v = float(s)
        return round(v * 100, 2) if v <= 1.0 else round(v, 2)
    except (ValueError, TypeError):
        return None


def _to_date_str(text) -> Optional[str]:
    """和暦 R6.4.1 / 令和6年4月1日 / 西暦 → YYYYMMDD。"""
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    # 和暦短縮: R6.4.1 / R6/4/1 / 令和6年4月1日 / 令和6.4.1
    m = re.search(r"(?:令和|R)\s*(\d{1,2})[./年](\d{1,2})[./月](\d{1,2})", s)
    if m:
        ry, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= ry <= 20 and 1 <= mo <= 12 and 1 <= dd <= 31:
            return f"{2018 + ry}{mo:02d}{dd:02d}"
    # 西暦
    m = re.search(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})", s)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    # ピリオド3組（和暦と判定）スペースありも対応: "6 . 4 . 1" → 令和6年4月1日
    m = re.match(r"^(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})$", s)
    if m:
        ry = int(m.group(1))
        if 1 <= ry <= 20:
            mo, dd = int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= dd <= 31:
                return f"{2018 + ry}{mo:02d}{dd:02d}"
    return None


def fy_from_date(yyyymmdd: Optional[str]) -> Optional[int]:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    y, m = int(yyyymmdd[:4]), int(yyyymmdd[4:6])
    return y if m >= 4 else y - 1


def _find_header_idx(rows: list[list[str]]) -> int:
    for i, row in enumerate(rows[:6]):
        # Remove spaces/newlines before keyword matching to handle split cells like "契約\n金額"
        text_raw = " ".join(str(c).replace("\n", " ") for c in row if c)
        text_nospace = "".join(str(c).replace("\n", "").replace(" ", "").replace("　", "") for c in row if c)
        if "契約金額" in text_nospace or "落札金額" in text_nospace or "落札価格" in text_nospace:
            if any(k in text_nospace for k in ("名称", "件名", "工事", "業務", "品名", "数量")):
                return i
        # fallback: space-normalised text
        if "契約金額" in text_raw or "落札金額" in text_raw:
            if any(k in text_raw for k in ("名称", "件名", "工事", "業務", "品名")):
                return i
    return -1


def _map_columns(header: list[str]) -> dict[str, int]:
    col_map: dict[str, int] = {}
    for i, cell in enumerate(header):
        if not cell:
            continue
        c = str(cell).replace("\n", "").replace(" ", "")
        for keyword, field in HEADER_KEYWORDS:
            if keyword in c and field not in col_map:
                col_map[field] = i
                break
    return col_map


def _parse_words_records(page, target_fys: set[int]) -> list[dict]:
    """extract_words ベースで契約レコードを抽出（罫線なし PDF 向け第3段フォールバック）。

    新田原基地等、pdfplumber テーブル抽出が機能しないが extract_words で
    テキストが取れる PDF に対応。1件の契約が複数 y 行にまたがる構造を処理する。
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    if len(words) < 5:
        return []

    # y クラスタリング（同じ行の単語を y ±6px でグループ化）
    y_tol = 6
    y_groups: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w['top']):
        placed = False
        for grp in y_groups:
            if abs(grp[0]['top'] - w['top']) <= y_tol:
                grp.append(w)
                placed = True
                break
        if not placed:
            y_groups.append([w])
    for grp in y_groups:
        grp.sort(key=lambda w: w['x0'])

    if len(y_groups) < 3:
        return []

    # ヘッダー行の特定（最初12行内で contract_amount + 件名系キーワードが共存）
    # 連続する最大3行を結合して探す
    header_words: list[dict] = []
    header_end_idx = -1
    for start in range(min(12, len(y_groups))):
        for end in range(start, min(start + 3, len(y_groups))):
            candidate = []
            for idx in range(start, end + 1):
                candidate.extend(y_groups[idx])
            nospace = "".join(w['text'] for w in candidate).replace(" ", "").replace("　", "")
            if (("契約金額" in nospace or "落札金額" in nospace) and
                    any(k in nospace for k in ("件名", "名称", "工事", "数量", "品名"))):
                header_words = candidate
                header_end_idx = end
                break
        if header_end_idx >= 0:
            break

    if not header_words:
        return []

    # ヘッダーから各フィールドの x 中心座標を決定
    field_x: dict[str, float] = {}
    for w in header_words:
        text_ns = w['text'].replace(" ", "").replace("　", "")
        for keyword, field in HEADER_KEYWORDS:
            if keyword in text_ns and field not in field_x:
                field_x[field] = (w['x0'] + w['x1']) / 2
                break

    if 'contract_amount' not in field_x:
        return []

    amt_x = field_x['contract_amount']
    x_tol = 28  # 列割り当て tolerance

    def _nearest_field(x_center: float) -> Optional[str]:
        best_field, best_dist = None, float('inf')
        for f, fx in field_x.items():
            d = abs(x_center - fx)
            if d < best_dist:
                best_dist = d
                best_field = f
        return best_field if best_dist <= x_tol * 2 else None

    def _row_field_val(row_words: list[dict], target_x: float) -> str:
        parts = [w['text'] for w in row_words
                 if abs((w['x0'] + w['x1']) / 2 - target_x) <= x_tol]
        return ' '.join(parts)

    # データ行走査: contract_amount 列に数値がある行を anchor として
    # その前の最大5行（y 差 ≤ 90px）を同じ契約ブロックにまとめる
    data_groups = y_groups[header_end_idx + 1:]
    records: list[dict] = []

    for i, anchor_grp in enumerate(data_groups):
        anchor_y = anchor_grp[0]['top']
        amt_text = _row_field_val(anchor_grp, amt_x)
        amt_val = _to_amount(amt_text)
        if not amt_val or amt_val <= 0:
            continue

        # ブロック構築
        block: list[dict] = []
        for j in range(max(0, i - 5), i + 1):
            if data_groups[j][0]['top'] >= anchor_y - 90:
                block.extend(data_groups[j])

        rec: dict = {}
        rec['contract_amount'] = amt_val

        for field, fx in field_x.items():
            if field == 'contract_amount':
                continue
            val = _row_field_val(block, fx)
            if val:
                rec[field] = val

        # contract_name: 最も左の列（既知フィールド x の最小より左側）
        min_known_x = min(field_x.values())
        left_parts = [w['text'] for w in block if (w['x0'] + w['x1']) / 2 < min_known_x - 5]
        if left_parts and not rec.get('contract_name'):
            # 重複単語を除去しつつ結合
            seen: set[str] = set()
            unique_parts = []
            for t in left_parts:
                if t not in seen:
                    seen.add(t)
                    unique_parts.append(t)
            rec['contract_name'] = ' '.join(unique_parts)[:500]

        # 後処理: 文字列フィールドをパース
        if 'contract_date' in rec:
            rec['contract_date'] = _to_date_str(rec['contract_date'])
        if 'estimated_price' in rec:
            rec['estimated_price'] = _to_amount(rec['estimated_price'])
        if 'award_rate' in rec:
            rec['award_rate'] = _to_rate(rec['award_rate'])
        if 'bid_method' in rec:
            rec['bid_method'] = _normalize_bid(rec['bid_method'])

        # FY チェック
        cd_fy = fy_from_date(rec.get('contract_date'))
        if cd_fy is not None:
            if cd_fy not in target_fys:
                continue
            rec['fiscal_year'] = cd_fy

        # 必須チェック
        if not rec.get('contract_amount'):
            continue
        if not rec.get('vendor_name') and not rec.get('contract_name'):
            continue

        records.append(rec)

    return records


def parse_pdf_records(
    data: bytes,
    *,
    target_fys: set[int] | None = None,
) -> Iterable[dict]:
    """PDFのbytesから契約レコード dict を yield。

    target_fys を指定すると contract_date FY がそこに含まれるもののみ採用。
    """
    target_fys = target_fys or {2022, 2023, 2024, 2025}
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                # 第1段: デフォルト（罫線ベース）でテーブル抽出
                tables = page.extract_tables() or []
                # 第2段フォールバック: 罫線なしテーブル対策（asdf_nyutabaru tekiseika2311+ 等）
                # 文字座標ベースで再抽出
                if not tables:
                    try:
                        tables = page.extract_tables(table_settings={
                            "vertical_strategy": "text",
                            "horizontal_strategy": "text",
                            "intersection_y_tolerance": 8,
                            "intersection_x_tolerance": 8,
                        }) or []
                    except Exception:
                        tables = []

                # 第3段フォールバック: extract_words ベース（第1・第2段で0件の場合のみ）
                if not tables:
                    for rec in _parse_words_records(page, target_fys):
                        yield rec
                    continue

                for tbl in tables:
                    if not tbl or len(tbl) < 2:
                        continue
                    # 各行の None セルを '' に置換
                    norm = [[c if c is not None else "" for c in row] for row in tbl]
                    h_idx = _find_header_idx(norm)
                    if h_idx < 0:
                        continue
                    col_map = _map_columns(norm[h_idx])
                    if "contract_amount" not in col_map:
                        continue

                    _prev_bid: Optional[str] = None  # 〃 キャリーフォワード用

                    for row in norm[h_idx + 1:]:
                        if not any(str(c).strip() for c in row):
                            continue

                        rec: dict = {}

                        if "vendor_name" in col_map and col_map["vendor_name"] < len(row):
                            v = row[col_map["vendor_name"]]
                            if v:
                                lines = [l.strip() for l in str(v).split("\n") if l.strip()]
                                if lines:
                                    rec["vendor_name"] = lines[0][:300]
                                    if len(lines) > 1:
                                        rec["vendor_address"] = " / ".join(lines[1:])[:500]

                        if "contract_name" in col_map and col_map["contract_name"] < len(row):
                            v = row[col_map["contract_name"]]
                            if v:
                                s = str(v).replace("\n", " ").strip()
                                if s:
                                    rec["contract_name"] = s[:500]

                        if "contract_amount" in col_map:
                            rec["contract_amount"] = _to_amount(row[col_map["contract_amount"]])
                        if "estimated_price" in col_map and col_map["estimated_price"] < len(row):
                            rec["estimated_price"] = _to_amount(row[col_map["estimated_price"]])

                        if "award_rate" in col_map and col_map["award_rate"] < len(row):
                            rec["award_rate"] = _to_rate(row[col_map["award_rate"]])

                        if "bid_method" in col_map and col_map["bid_method"] < len(row):
                            raw_bid = str(row[col_map["bid_method"]]).strip()
                            if raw_bid in ("〃", "〝", "ditto", "同上"):
                                rec["bid_method"] = _prev_bid
                            else:
                                bm = _normalize_bid(row[col_map["bid_method"]])
                                rec["bid_method"] = bm
                                if bm:
                                    _prev_bid = bm

                        if "contract_date" in col_map and col_map["contract_date"] < len(row):
                            rec["contract_date"] = _to_date_str(row[col_map["contract_date"]])

                        for f in ("corporate_number", "quantity", "unit_measure",
                                  "zuii_reason", "contract_officer"):
                            if f in col_map and col_map[f] < len(row):
                                v = row[col_map[f]]
                                if v:
                                    s = str(v).replace("\n", " ").strip()
                                    if s:
                                        rec[f] = s[:500]

                        # 必須: 業者名 or 件名 + 金額
                        if not rec.get("contract_amount"):
                            continue
                        if not rec.get("vendor_name") and not rec.get("contract_name"):
                            continue

                        cd_fy = fy_from_date(rec.get("contract_date"))
                        if cd_fy is not None and cd_fy not in target_fys:
                            continue
                        # contract_date が無い場合は呼び出し側で fiscal_year を埋めるためここでは未設定
                        if cd_fy is not None:
                            rec["fiscal_year"] = cd_fy

                        yield rec
    except Exception as e:
        logger.warning(f"PDF解析エラー: {e}")
