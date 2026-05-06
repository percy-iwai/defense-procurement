"""Excel公表ファイルの汎用パーサー。

ATLA・近畿中部・naikyokuなど、公表様式に類似したExcelに対応。
ヘッダー行を自動検出し、列ヘッダーのキーワードからDBカラムへマッピングする。
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

# ヘッダーキーワード → DBカラム名（最初に当たった列を採用）
HEADER_KEYWORDS: list[tuple[str, str]] = [
    ("件名", "contract_name"),
    ("名称", "contract_name"),               # 物品役務等の名称 / 工事の名称
    ("相手方の商号", "vendor_name"),
    ("相手方の名称", "vendor_name"),
    ("締結した日", "contract_date"),
    ("締結日", "contract_date"),
    ("法人番号", "corporate_number"),
    ("予定価格", "estimated_price"),
    ("契約金額", "contract_amount"),
    ("落札率", "award_rate"),
    ("入札・指名", "bid_method"),
    ("入札方式", "bid_method"),
    ("の別", "bid_method"),                  # 「...の別（総合評価...）」
    ("数量", "quantity"),
    ("単位", "unit_measure"),
    ("根拠条文", "zuii_reason"),
    ("随意契約の根拠", "zuii_reason"),
    ("担当官", "contract_officer"),
]

BID_METHOD_MAP: dict[str, str] = {
    "一般競争入札": "一般競争入札",
    "一般競争": "一般競争入札",
    "公告": "一般競争入札",
    "総合評価": "総合評価落札方式",
    "指名競争": "指名競争入札",
    "随意契約": "随意契約",
    "随意": "随意契約",
    "プロポーザル": "公募型プロポーザル",
    "見積合わせ": "見積合わせ",
}


def normalize_bid_method(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip()
    for k, v in BID_METHOD_MAP.items():
        if k in t:
            return v
    return t[:30] or None


def to_date_str(val) -> Optional[str]:
    """日付値を YYYYMMDD に変換。datetime/Timestamp/Excelシリアル/和暦/西暦に対応。"""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(val).strftime("%Y%m%d")
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(val))
            return ts.strftime("%Y%m%d")
        except Exception:
            return None
    s = str(val).strip()
    if not s or s == "nan":
        return None
    # 和暦短縮: "6.4.1" / "R6.4.1"  ※西暦より先に判定
    m = re.match(r"^[Rr令和]*\s*(\d{1,2})[\.年/](\d{1,2})[\.月/](\d{1,2})", s)
    if m:
        ry, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= ry <= 20 and 1 <= mo <= 12 and 1 <= dd <= 31:
            return f"{2018 + ry}{mo:02d}{dd:02d}"
    # 西暦
    m = re.match(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", s)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    if re.fullmatch(r"\d{8}", s):
        return s
    return None


def fy_from_date(yyyymmdd: Optional[str]) -> Optional[int]:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    y, m = int(yyyymmdd[:4]), int(yyyymmdd[4:6])
    return y if m >= 4 else y - 1


def _to_int_amount(val) -> Optional[int]:
    """金額値を整数（円）に変換。Excel float の精度ノイズ対策で round() してから int 化する。"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    # 数値型は直接 round → int（"525800000.00000006" のようなfloat精度ノイズを吸収）
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            return int(round(float(val)))
        except (OverflowError, ValueError):
            return None
    s = str(val).replace(",", "").replace("，", "").replace("円", "").replace("¥", "").strip()
    # 小数点を残してパースし、最後に丸める（"525800000.00000006" → 525800000）
    s = re.sub(r"[^\d\.\-]", "", s)
    if not s:
        return None
    try:
        return int(round(float(s)))
    except (ValueError, OverflowError):
        return None


def _find_header_row(df: pd.DataFrame) -> int:
    for i in range(min(15, len(df))):
        text = " ".join(str(v) for v in df.iloc[i] if str(v) != "nan")
        if "契約金額" in text and ("名称" in text or "件名" in text):
            return i
        # FY2022 財計第2017号 3行見出し: 契約金額 が i 行, 名称 が i+1 行に分かれている
        if "契約金額" in text and i + 1 < len(df):
            next_text = " ".join(str(v) for v in df.iloc[i + 1] if str(v) != "nan")
            if "名称" in next_text or "件名" in next_text:
                return i
    return 1


def _merge_header_rows(row1: pd.Series, row2: pd.Series) -> pd.Series:
    """2行分割ヘッダーを1行に結合する（FY2022 財計第2017号 3行見出し対応）。"""
    merged = []
    for v1, v2 in zip(row1, row2):
        s1 = "" if (isinstance(v1, float) and pd.isna(v1)) or str(v1) == "nan" else str(v1).strip()
        s2 = "" if (isinstance(v2, float) and pd.isna(v2)) or str(v2) == "nan" else str(v2).strip()
        combined = s1 + s2
        merged.append(combined if combined else float("nan"))
    return pd.Series(merged, index=row1.index)


def _map_columns(header_row: pd.Series) -> dict[str, int]:
    col_map: dict[str, int] = {}
    for idx, val in enumerate(header_row):
        cell = str(val).replace("\n", "")
        for keyword, field in HEADER_KEYWORDS:
            if keyword in cell and field not in col_map:
                # "予定価格の計算方式" は estimated_price 列でない
                if keyword == "予定価格" and "計算方式" in cell:
                    continue
                col_map[field] = idx
                break
    return col_map


def parse_excel_bytes(
    data: bytes,
    *,
    is_xls: bool = False,
    sheet: int | str = 0,
) -> tuple[pd.DataFrame, int, dict[str, int]]:
    """Excelをロードし (df, header_idx, col_map) を返す。"""
    engine = "xlrd" if is_xls else "openpyxl"
    df = pd.read_excel(io.BytesIO(data), header=None, engine=engine, sheet_name=sheet)
    if isinstance(df, dict):
        # 複数シートの場合は最初の非空を使う
        for v in df.values():
            if not v.empty:
                df = v
                break
    if df.empty:
        return df, 0, {}
    header_idx = _find_header_row(df)
    header_row = df.iloc[header_idx]

    # FY2022 3行見出し検出: 契約金額 が header_idx 行にあるが 名称/件名 がない場合、
    # 次行に 名称/件名 があれば2行を結合して col_map を作成し、header_idx を +2 する
    # （data_start = header_idx + 1 = original + 3 で3行目の見出しもスキップ）
    header_text = " ".join(str(v) for v in header_row if str(v) != "nan")
    if "契約金額" in header_text and "名称" not in header_text and "件名" not in header_text:
        if header_idx + 1 < len(df):
            next_text = " ".join(str(v) for v in df.iloc[header_idx + 1] if str(v) != "nan")
            if "名称" in next_text or "件名" in next_text:
                header_row = _merge_header_rows(header_row, df.iloc[header_idx + 1])
                header_idx = header_idx + 2

    col_map = _map_columns(header_row)
    return df, header_idx, col_map


def iter_records(
    df: pd.DataFrame,
    header_idx: int,
    col_map: dict[str, int],
    *,
    target_fy: int,
    fy_guard: bool = True,
) -> Iterable[dict]:
    """データ行をDB投入用 dict にして yield する。

    target_fy と契約日FYが不一致なら除外（ローリングExcel・WARPの混入対策）。
    contract_date が無い場合は target_fy を採用。
    """
    if "contract_amount" not in col_map and "vendor_name" not in col_map:
        return

    # ATLAは header_idx+2 から（補助ヘッダー1行をスキップ）。一般化のため自動検出
    data_start = header_idx + 1
    if data_start < len(df):
        # 直下の行も非データ的なら +1 する（"応札者数" などの補助ヘッダー）
        first = df.iloc[data_start]
        first_text = " ".join(str(v) for v in first if str(v) != "nan")
        if any(k in first_text for k in ("応札者", "備考", "者数")) and "件名" not in first_text:
            data_start += 1

    for i in range(data_start, len(df)):
        row = df.iloc[i]
        if all(pd.isna(v) or str(v).strip() in ("", "nan") for v in row):
            continue

        rec: dict = {}

        # 業者名・住所（"名前\n住所\n..." → 分離）
        if "vendor_name" in col_map:
            v = row.iloc[col_map["vendor_name"]]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                lines = [l.strip() for l in str(v).split("\n") if l.strip()]
                if lines:
                    rec["vendor_name"] = lines[0][:300]
                    if len(lines) > 1:
                        rec["vendor_address"] = " / ".join(lines[1:])[:500]

        # 件名
        if "contract_name" in col_map:
            v = row.iloc[col_map["contract_name"]]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                s = str(v).split("\n")[0].strip()
                if s and s != "nan":
                    rec["contract_name"] = s[:500]

        # 金額
        if "contract_amount" in col_map:
            rec["contract_amount"] = _to_int_amount(row.iloc[col_map["contract_amount"]])
        if "estimated_price" in col_map:
            rec["estimated_price"] = _to_int_amount(row.iloc[col_map["estimated_price"]])

        # 単価契約フォールバック1: いずれかのセルに「予定調達総額X円」
        if not rec.get("contract_amount"):
            for v in row:
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                m = re.search(r"予定調達総額[^\d]*([\d,]+)\s*円", str(v))
                if m:
                    try:
                        rec["contract_amount"] = int(m.group(1).replace(",", ""))
                    except ValueError:
                        pass
                    break

        # 単価契約フォールバック2: contract_amountがNULLで予定価格がある場合（単価契約等）
        if not rec.get("contract_amount") and rec.get("estimated_price"):
            rec["contract_amount"] = rec["estimated_price"]

        # 落札率
        if "award_rate" in col_map:
            v = row.iloc[col_map["award_rate"]]
            try:
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    r = float(str(v).replace("%", "").strip())
                    rec["award_rate"] = round(r * 100, 2) if r <= 1.0 else round(r, 2)
            except (ValueError, TypeError):
                pass

        # 入札方式
        if "bid_method" in col_map:
            v = row.iloc[col_map["bid_method"]]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                rec["bid_method"] = normalize_bid_method(str(v))

        # 契約日
        if "contract_date" in col_map:
            rec["contract_date"] = to_date_str(row.iloc[col_map["contract_date"]])

        # その他
        for f in ("corporate_number", "quantity", "unit_measure", "zuii_reason", "contract_officer"):
            if f in col_map:
                v = row.iloc[col_map[f]]
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    s = str(v).strip()
                    if s and s != "nan":
                        rec[f] = s[:500]

        # 業者名も金額もない → スキップ
        if not rec.get("vendor_name") and not rec.get("contract_amount"):
            continue
        # 件名も金額もない → 住所続き行
        if not rec.get("contract_name") and not rec.get("contract_amount"):
            continue

        # FY汚染チェック
        cd_fy = fy_from_date(rec.get("contract_date"))
        if cd_fy is not None and fy_guard and cd_fy != target_fy:
            continue
        rec["fiscal_year"] = target_fy

        yield rec
