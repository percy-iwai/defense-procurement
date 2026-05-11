"""中央調達実績PDFから品目データを抽出してchuou_chotatsu.dbに投入する。

新規テーブル:
  chuou_chotatsu_company_items  -- 上位20社 × 主な調達品 (H19-R06 / FY2007-2024)
  chuou_chotatsu_main_items     -- 年度別 主要調達品目一覧 (H19-R06 / FY2007-2024)

既存テーブルへのカラム追加:
  chuou_chotatsu_summary.method_competition_cnt/100m
  chuou_chotatsu_summary.method_zuii_cnt/100m
  chuou_chotatsu_summary.method_fms_cnt/100m  (R03-R06のみ)
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import NamedTuple

import pdfplumber

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "chuou_chotatsu.db"
PDF_DIR = PROJECT_ROOT / "data" / "raw" / "chuou_chotatsu_jisseki"


# ── ユーティリティ ─────────────────────────────────────────────────

def _d(s: str) -> str:
    """PDF garbled Latin-1 → CP932 decode. 失敗時は元の文字列を返す。"""
    if not isinstance(s, str):
        return str(s) if s is not None else ""
    try:
        return unicodedata.normalize("NFKC", s.encode("latin-1").decode("cp932"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        return unicodedata.normalize("NFKC", s)


def _parse_amount(s: str) -> float | None:
    """'1,234' または '1234' → float。失敗時 None。"""
    s = s.replace(",", "").replace("，", "").strip()
    # 先頭の数字だけ抜き出す（"1,047 三菱重工業..." のような混在に対応）
    m = re.match(r"^([\d,]+)", s.replace(",", ""))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _page_words(pdf_path: Path, page_idx: int) -> list[dict]:
    """pdfplumber で指定ページの単語リストを取得してデコードする。"""
    with pdfplumber.open(str(pdf_path)) as pdf:
        if page_idx >= len(pdf.pages):
            return []
        page = pdf.pages[page_idx]
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
    for w in words:
        w["text"] = _d(w["text"])
    return words


def _group_by_y(words: list[dict], bucket: int = 5) -> dict[int, list[dict]]:
    """単語を y 座標でグルーピング (bucket pt 単位)。"""
    rows: dict[int, list[dict]] = {}
    for w in words:
        y_key = round(w["top"] / bucket) * bucket
        rows.setdefault(y_key, []).append(w)
    for y_key in rows:
        rows[y_key].sort(key=lambda w: w["x0"])
    return rows


# ──────────────────────────────────────────────────────────────────
# DB 初期化
# ──────────────────────────────────────────────────────────────────

def init_tables(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS chuou_chotatsu_company_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fiscal_year     INTEGER NOT NULL,
            company_rank    INTEGER NOT NULL,
            company_name    TEXT    NOT NULL,
            item_name       TEXT    NOT NULL,
            item_order      INTEGER NOT NULL DEFAULT 1,
            source_file     TEXT,
            UNIQUE(fiscal_year, company_rank, item_order)
        );

        CREATE TABLE IF NOT EXISTS chuou_chotatsu_main_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fiscal_year     INTEGER NOT NULL,
            requesting_org  TEXT,
            item_name       TEXT    NOT NULL,
            quantity_str    TEXT,
            amount_100m     REAL,
            vendor_name     TEXT,
            source_file     TEXT,
            UNIQUE(fiscal_year, item_name, amount_100m)
        );
    """)
    # summary テーブルへカラム追加（既存でなければ）
    existing = {row[1] for row in con.execute("PRAGMA table_info(chuou_chotatsu_summary)")}
    for col, col_type in [
        ("method_competition_cnt", "INTEGER"),
        ("method_competition_100m", "REAL"),
        ("method_zuii_cnt",         "INTEGER"),
        ("method_zuii_100m",        "REAL"),
        ("method_fms_cnt",          "INTEGER"),
        ("method_fms_100m",         "REAL"),
    ]:
        if col not in existing:
            con.execute(f"ALTER TABLE chuou_chotatsu_summary ADD COLUMN {col} {col_type}")
    con.commit()


# ──────────────────────────────────────────────────────────────────
# PDF ファイルマッピング
# ──────────────────────────────────────────────────────────────────

# (fiscal_year, pdf_filename, top20_page_idx, items_page_idx, org_page_idx)
# top20_page_idx = None means no per-company items page available
PDF_MAP: list[tuple[int, str, int | None, int | None, int | None]] = [
    # FY, filename, top20_page, main_items_page, org_method_page
    (2024, "r06_chotatsu_jisseki.pdf",    2, 1, 0),
    (2023, "r05_chotatsu_jisseki.pdf",    2, 1, 0),
    (2022, "r04_jisseki_r05_mikomi.pdf",  2, 1, 0),
    (2021, "r03_jisseki_r04_mikomi.pdf",  2, 1, 0),
    (2020, "r02_jisseki_mikomi.pdf",   2, 1, 3),
    (2019, "r01_jisseki_mikomi.pdf",   2, 1, 3),
    (2018, "h30_jisseki_mikomi.pdf",   2, 1, 3),
    (2017, "h29_jisseki_mikomi.pdf",   2, 1, 3),
    (2016, "h28_jisseki_mikomi.pdf",   2, 1, 3),
    (2015, "h27_jisseki_mikomi.pdf",   2, 1, 3),
    (2014, "h26_chotatsu_jisseki.pdf", 2, 1, 0),
    (2013, "h25_chotatsu_jisseki.pdf", 2, 1, 0),
    (2012, "h24_chotatsu_jisseki.pdf", 2, 1, 0),
    (2011, "h23_chotatsu_jisseki.pdf", 2, 1, 0),
    (2010, "h22_chotatsu_jisseki.pdf", 2, 1, 0),
    (2009, "h21_chotatsu_jisseki.pdf", 2, 1, 0),
    (2008, "h20_chotatsu_jisseki.pdf", 2, 1, 0),
    (2007, "h19_chotatsu_jisseki.pdf", 2, 1, 0),
    (2005, "h17_jisseki_mikomi.pdf",   None, 1, 0),
]


# ──────────────────────────────────────────────────────────────────
# 上位20社の主な調達品抽出
# ──────────────────────────────────────────────────────────────────

def _is_rank_line(text: str) -> bool:
    """行テキストが '1三菱重工業...' / '1 三菱重工業...' の形か判定。"""
    return bool(re.match(r"^\d{1,2}[\s　]?[　-鿿a-zA-Z（(]", text))


def extract_company_items_r05_r06(
    words: list[dict], fiscal_year: int, fname: str
) -> list[tuple]:
    """R05/R06形式（items が 1行ずつ）の上位20社主な調達品を抽出する。

    通常は "1三菱重工業株式会社" のように rank+company 連結。
    東芝インフラシステムズ等は rank 数字のみ → 隣接行に会社名。

    Returns list of (fiscal_year, rank, company_name, item_name, item_order, source_file).
    """
    rows = _group_by_y(words, bucket=5)
    ys = sorted(rows.keys())
    ITEM_X_MIN = 200

    # 企業行の検出（連結型 + 単独ランク数字型）
    company_rows: list[dict] = []
    for y in ys:
        row_words = rows[y]
        leftmost = min(row_words, key=lambda w: w["x0"])
        if leftmost["x0"] >= 200:
            continue
        if _is_rank_line(leftmost["text"]):
            co_words = [w for w in row_words if w["x0"] < ITEM_X_MIN]
            co_text = "".join(w["text"] for w in co_words).strip()
            m = re.match(r"^(\d{1,2})\s*(.*)", co_text)
            if m:
                company_rows.append({
                    "y": y, "rank": int(m.group(1)),
                    "company": m.group(2).strip(), "solo": False,
                })
        elif re.match(r"^\d{1,2}$", leftmost["text"]):
            rank = int(leftmost["text"])
            if 1 <= rank <= 20:
                company_rows.append({"y": y, "rank": rank, "company": "", "solo": True})

    # 単独型の会社名: ランク行より上の行（y < rank_y）から収集
    all_y_set = {info["y"] for info in company_rows}
    for info in company_rows:
        if not info["solo"]:
            continue
        cy = info["y"]
        co_parts = []
        for y in ys:
            if y >= cy or abs(y - cy) > 20:
                continue
            if y in all_y_set:
                continue
            for w in sorted(rows[y], key=lambda w: w["x0"]):
                if w["x0"] < ITEM_X_MIN:
                    t = w["text"]
                    if not re.match(r"^[\d,，\s%]+$", t) and "法人番号" not in t:
                        co_parts.append(t)
        info["company"] = "".join(co_parts).strip()

    company_rows.sort(key=lambda x: x["rank"])

    results: list[tuple] = []
    for i, info in enumerate(company_rows):
        cy = info["y"]
        rank = info["rank"]
        company_name = info["company"]

        prev_cy = company_rows[i - 1]["y"] if i > 0 else cy - 100
        next_cy = company_rows[i + 1]["y"] if i + 1 < len(company_rows) else max(ys) + 100

        range_start = int((prev_cy + cy) / 2)
        range_end   = int((cy + next_cy) / 2)

        item_order = 1
        for y in sorted(ys):
            if not (range_start <= y <= range_end):
                continue
            item_words = [w for w in rows[y] if w["x0"] >= ITEM_X_MIN]
            if not item_words:
                continue
            item_text = "".join(w["text"] for w in item_words).strip()
            if re.match(r"^[\d,，\s%]+$", item_text):
                continue
            if any(kw in item_text for kw in ("順位", "件数", "金額", "主な調達品", "法人番号", "年度")):
                continue
            # 先頭の「件数+金額」数値列を除去: "23814,56712式地対艦誘導弾" → "12式地対艦誘導弾"
            item_text = re.sub(r"^\d{3,6}[,，]\d{3}\s*", "", item_text).strip()
            if len(item_text) < 2:
                continue
            results.append((fiscal_year, rank, company_name, item_text, item_order, fname))
            item_order += 1
            if item_order > 5:
                break

    return results


def extract_company_items_h19_r02(
    words: list[dict], fiscal_year: int, fname: str
) -> list[tuple]:
    """H19-R02 (FY2007-2020) の上位20社主な調達品を抽出する。

    H19-H26 (3ページ形式): ランク数字と会社名が同一y行またはy±数pt以内
    H27-R02 (5ページ形式): 会社名がランク行の上に来ることが多い
    共通: items は x≈260-460, hist_ranks は x≈460+

    Returns list of (fiscal_year, rank, company_name, item_name, item_order, source_file).
    """
    rows = _group_by_y(words, bucket=2)
    ys = sorted(rows.keys())

    RANK_X_MAX    = 100  # ランク数字の x 最大値（H25は x=86）
    CO_X_MIN      = 58   # 会社名文字の x 最小値
    CO_X_MAX      = 215  # 会社名文字の x 最大値
    ITEM_X_MIN    = 258  # 調達品テキストの x 最小値
    # 過去順位列の上限は設けず numeric filter で除外（H27 x=467〜、H25 x=492〜で差異あり）
    CO_SEARCH_WIN = 16   # 会社名を探すランク行からの y 幅

    # Step 1: ランク数字行を検出
    # 「3 平成27年度上位20社の概要」のような章番号を除外するため、
    # 近傍 (±20pt) に金額列 (x > 150) が存在することを検証する
    seen_ranks: dict[int, int] = {}
    for y in ys:
        rw = rows[y]
        rank_words = [
            w for w in rw
            if w["x0"] < RANK_X_MAX and re.match(r"^\d{1,2}$", w["text"])
        ]
        if not rank_words:
            continue
        rank_num = int(rank_words[0]["text"])
        if not (1 <= rank_num <= 20):
            continue
        # 近傍行に数値データがあることを検証（章番号・脚注を排除）
        has_amount = any(
            w["x0"] > 150 and re.match(r"^\d[\d,\.]+$", w["text"])
            for y2 in ys if abs(y2 - y) <= 20
            for w in rows[y2]
        )
        if not has_amount:
            continue
        if rank_num not in seen_ranks or y < seen_ranks[rank_num]:
            seen_ranks[rank_num] = y

    sorted_rank_ys = sorted(seen_ranks.items())  # [(rank, y), ...]
    if not sorted_rank_ys:
        return []

    # Step 2: 各ランク行の会社名を収集（ランク行の ±CO_SEARCH_WIN pt 以内）
    def _collect_company(rank_y: int) -> str:
        co_parts = []
        for y in ys:
            if abs(y - rank_y) > CO_SEARCH_WIN:
                continue
            for w in sorted(rows[y], key=lambda w: w["x0"]):
                if CO_X_MIN <= w["x0"] <= CO_X_MAX:
                    t = w["text"]
                    # 数字・カンマ・%・小数点のみは除外（金額・件数・順位）
                    if re.match(r"^[\d,，\s%\.]+$", t):
                        continue
                    # 法人番号・その数字部分（13桁数字 + 末尾かっこ）を除外
                    if "法人番号" in t or re.match(r"^\d{10,}[\)）]?$", t):
                        continue
                    if t.startswith("(注") or t.startswith("（注"):
                        continue
                    co_parts.append(t)
        return "".join(co_parts).strip()

    # Step 3: ミッドポイント境界で items を収集
    header_end = sorted_rank_ys[0][1] - 30
    page_end   = max(ys) + 100

    results: list[tuple] = []
    for i, (rank, ry) in enumerate(sorted_rank_ys):
        company_name = _collect_company(ry)

        prev_ry = sorted_rank_ys[i - 1][1] if i > 0 else header_end
        next_ry = sorted_rank_ys[i + 1][1] if i + 1 < len(sorted_rank_ys) else page_end

        range_start = int((prev_ry + ry) / 2)
        range_end   = int((ry + next_ry) / 2)

        # items: x ≥ ITEM_X_MIN（hist_ranks は単数字なので numeric filter で除外）
        item_parts: list[str] = []
        for y in ys:
            if not (range_start <= y <= range_end):
                continue
            for w in sorted(rows[y], key=lambda w: w["x0"]):
                if w["x0"] < ITEM_X_MIN:
                    continue
                t = w["text"]
                if "法人番号" in t:
                    continue
                # 過去順位数字（"1"〜"20"）または純数字・%は除外
                if re.match(r"^[\d,，\s%\.]+$", t):
                    continue
                item_parts.append(t)

        item_text = "".join(item_parts).strip()

        for hdr in ("主な調達品", "主要調達品目", "品目名", "調達品目"):
            if item_text.startswith(hdr):
                item_text = item_text[len(hdr):].strip()

        if not item_text or len(item_text) < 3:
            continue

        # 読点・句点で分割
        items = [s.strip() for s in re.split(r"[、,，。]", item_text) if s.strip()]
        items = [it for it in items if len(it) >= 3 and not re.match(r"^[\d\s%\.\-]+$", it)]

        for order, it in enumerate(items[:5], start=1):
            results.append((fiscal_year, rank, company_name, it, order, fname))

    return results


def extract_company_items_r03_r04(
    words: list[dict], fiscal_year: int, fname: str
) -> list[tuple]:
    """R03/R04形式（rank・会社名が別ワード、items が読点区切り・折り返しあり）の主な調達品を抽出する。

    R03/R04 のレイアウト:
      y=165: 1@75 | 三菱重工業株式会社@82 | 121@264 | ... | 次期戦闘機(その3)...@348 | 1@447...
      y=170: (法人番号)@201  ← スキップ
      y=175: 900トン型)@348  ← items 継続
    """
    rows = _group_by_y(words, bucket=5)
    ys = sorted(rows.keys())

    RANK_X_MAX    = 115   # rank 数字の x 最大値
    CO_X_MIN      = 80    # company name の x 最小値
    CO_X_MAX      = 210
    ITEM_X_MIN    = 335   # items (x >= ITEM_X_MIN かつ x < HIST_RANK_X_MIN)
    HIST_X_MIN    = 430   # 過去の順位列（除外対象）

    company_ys: list[int] = []
    for y in ys:
        row_words = rows[y]
        rank_words = [w for w in row_words if w["x0"] <= RANK_X_MAX
                      and re.match(r"^\d{1,2}$", w["text"])]
        co_words_at_y = [w for w in row_words if CO_X_MIN <= w["x0"] <= CO_X_MAX
                         and not re.match(r"^[\d\(\)\s]+$", w["text"])
                         and "法人番号" not in w["text"]]
        if rank_words and co_words_at_y:
            company_ys.append(y)

    results: list[tuple] = []
    for i, cy in enumerate(company_ys):
        next_cy = company_ys[i + 1] if i + 1 < len(company_ys) else max(ys) + 100

        row_words = rows[cy]
        rank_words = [w for w in row_words if w["x0"] <= RANK_X_MAX
                      and re.match(r"^\d{1,2}$", w["text"])]
        co_words_at_y = sorted(
            [w for w in row_words if CO_X_MIN <= w["x0"] <= CO_X_MAX
             and not re.match(r"^[\d\(\)\s]+$", w["text"])
             and "法人番号" not in w["text"]],
            key=lambda w: w["x0"],
        )
        if not rank_words or not co_words_at_y:
            continue
        rank = int(rank_words[0]["text"])
        company_name = "".join(w["text"] for w in co_words_at_y).strip()

        # items: x >= ITEM_X_MIN かつ x < HIST_X_MIN
        # 範囲: 直前の会社行との中点〜次の会社行との中点（R03/R04 は items が company 行の前後に現れる）
        prev_cy = company_ys[i - 1] if i > 0 else 0
        range_start = int((prev_cy + cy) / 2) if i > 0 else 0
        range_end   = int((cy + next_cy) / 2) if i + 1 < len(company_ys) else max(ys) + 100

        item_parts: list[str] = []
        for y in sorted(ys):
            if not (range_start < y <= range_end):
                continue
            for w in rows[y]:
                if ITEM_X_MIN <= w["x0"] < HIST_X_MIN:
                    item_parts.append(w["text"])

        item_text = "".join(item_parts).strip()
        if not item_text or re.match(r"^[\d,，\s%\-]+$", item_text):
            continue

        # ヘッダー文字列が先頭に混入している場合は除去
        for hdr in ("主な調達品", "主要調達品目", "品目名"):
            if item_text.startswith(hdr):
                item_text = item_text[len(hdr):].strip()

        if not item_text:
            continue

        # 読点・句点で分割
        items = [s.strip() for s in re.split(r"[、,，。]", item_text) if s.strip()]
        items = [it for it in items if len(it) >= 3 and not re.match(r"^[\d\s%]+$", it)]

        for order, it in enumerate(items[:5], start=1):
            results.append((fiscal_year, rank, company_name, it, order, fname))

    return results


# ──────────────────────────────────────────────────────────────────
# 主要調達品目（page 2）抽出
# ──────────────────────────────────────────────────────────────────

def extract_main_items_modern(
    words: list[dict], fiscal_year: int, fname: str
) -> list[tuple]:
    """R03-R06 / H27-R02 形式の主要調達品目を抽出する。

    フォーマット: item_name@~102 | qty@~348-361 | amount@~371-391 | vendor@~392+

    Returns list of (fiscal_year, org, item_name, quantity_str, amount_100m, vendor_name, source_file).
    """
    rows = _group_by_y(words, bucket=5)
    ys = sorted(rows.keys())

    # ヘッダー行から列 x 座標を推定
    ITEM_X_MIN, ITEM_X_MAX = 60, 310
    QTY_X_MIN,  QTY_X_MAX  = 310, 380
    AMT_X_MIN,  AMT_X_MAX  = 355, 430
    VND_X_MIN               = 370

    current_org = ""
    results: list[tuple] = []

    for y in ys:
        row_words = rows[y]
        # org header: 陸幕/海幕/空幕/装備庁/技本 など (x < 100, 短いテキスト)
        org_candidates = [w for w in row_words if w["x0"] < 100 and len(w["text"]) <= 8
                          and not re.match(r"^[\d,，\s]+$", w["text"])
                          and not any(kw in w["text"] for kw in ("単位", "年度", "区分", "過去", "注", "（", "※"))]
        if org_candidates:
            # 複数文字を連結して幕/庁のラベルとして解釈
            cand_text = "".join(w["text"] for w in org_candidates).strip()
            if re.search(r"[幕庁]|内局|統幕|防大|防医大|防研|技本|情本|装本|装備庁", cand_text):
                current_org = cand_text
                continue

        # item 行: x ≈ ITEM_X_MIN範囲に item_name がある行
        item_words = [w for w in row_words if ITEM_X_MIN <= w["x0"] <= ITEM_X_MAX
                      and not re.match(r"^[\d,，\s.]+$", w["text"])]
        qty_words   = [w for w in row_words if QTY_X_MIN  <= w["x0"] <= QTY_X_MAX]
        amt_words   = [w for w in row_words if AMT_X_MIN  <= w["x0"] < VND_X_MIN + 30
                       and re.match(r"^[\d,，]+$", w["text"].replace(" ", ""))]
        vnd_words   = [w for w in row_words if w["x0"] >= VND_X_MIN
                       and not re.match(r"^[\d,，\-\s.]+$", w["text"])]

        if not item_words:
            continue

        item_name = "".join(w["text"] for w in item_words).strip()
        # ヘッダー行や脚注を除外
        if any(kw in item_name for kw in ("品目", "要求機関", "区分", "令和", "平成", "（注", "（金額", "主要調達")):
            continue
        if len(item_name) < 2:
            continue

        qty_str  = "".join(w["text"] for w in qty_words).strip() or None
        amt_str  = "".join(w["text"] for w in amt_words).strip()
        vnd_name = "".join(w["text"] for w in vnd_words).strip() or None
        # vendor に法人番号だけの場合は除外
        if vnd_name and re.match(r"^\d{13}$", vnd_name.replace(" ", "")):
            vnd_name = None
        # 金額: 先頭の数字列を抽出
        amount = _parse_amount(amt_str) if amt_str else None
        # 億円 or 百万円の判定は FY によって異なるが、後処理で対応（ここでは raw）
        results.append((fiscal_year, current_org, item_name, qty_str, amount, vnd_name, fname))

    return results


def extract_main_items_old(
    words: list[dict], fiscal_year: int, fname: str
) -> list[tuple]:
    """H19-H26 形式の主要調達品目を抽出する。

    フォーマット: item_name@~214 | qty@~381-384 | amount+vendor@~414-417 (混在)
    """
    rows = _group_by_y(words, bucket=5)
    ys = sorted(rows.keys())

    ITEM_X_MIN, ITEM_X_MAX = 130, 330
    QTY_X_MIN,  QTY_X_MAX  = 330, 430
    AMT_VND_X_MIN           = 380

    current_org = ""
    results: list[tuple] = []

    for y in ys:
        row_words = rows[y]
        org_candidates = [w for w in row_words if w["x0"] < 80 and len(w["text"]) <= 8
                          and not re.match(r"^[\d,，\s]+$", w["text"])]
        if org_candidates:
            cand_text = "".join(w["text"] for w in org_candidates).strip()
            if re.search(r"[幕庁]|内局|統幕|防大|防医大|防研|技本|情本|装本", cand_text):
                current_org = cand_text
                continue

        item_words = [w for w in row_words if ITEM_X_MIN <= w["x0"] <= ITEM_X_MAX
                      and not re.match(r"^[\d,，\s.]+$", w["text"])]
        qty_words   = [w for w in row_words if QTY_X_MIN <= w["x0"] <= QTY_X_MAX]
        amtvnd_words = [w for w in row_words if w["x0"] >= AMT_VND_X_MIN]

        if not item_words:
            continue

        item_name = "".join(w["text"] for w in item_words).strip()
        if any(kw in item_name for kw in ("品目", "要求機関", "区分", "令和", "平成", "（注", "（金額", "件数")):
            continue
        if len(item_name) < 2:
            continue

        qty_str = "".join(w["text"] for w in qty_words).strip() or None
        # amount+vendor は混在 e.g. "184日本電気(株)" → 先頭の数字が amount, 残りが vendor
        amtvnd_text = "".join(w["text"] for w in amtvnd_words).strip()
        amount: float | None = None
        vnd_name: str | None = None
        if amtvnd_text:
            m = re.match(r"^([\d,，]+)\s*(.*)$", amtvnd_text.replace("，", ","))
            if m:
                amount   = _parse_amount(m.group(1))
                vnd_name = m.group(2).strip() or None

        results.append((fiscal_year, current_org, item_name, qty_str, amount, vnd_name, fname))

    return results


# ──────────────────────────────────────────────────────────────────
# 契約方式別データ（page 1）抽出
# ──────────────────────────────────────────────────────────────────

def extract_contract_method(words: list[dict], fiscal_year: int) -> dict | None:
    """R03-R06 の page 1 から契約方式別データを抽出する。

    Returns dict with keys:
      competition_cnt, competition_100m, zuii_cnt, zuii_100m, fms_cnt, fms_100m
      (単位: 億円)
    """
    rows = _group_by_y(words, bucket=5)
    ys = sorted(rows.keys())

    # 「件数」「金額」の2行から数値を取得
    # R03: 単位 百万円 → 億円変換が必要
    is_hyakuman = False
    for y in ys:
        texts = [w["text"] for w in rows[y]]
        line = "".join(texts)
        if "百万円" in line:
            is_hyakuman = True
        if "億円" in line:
            is_hyakuman = False

    # 「件数」行と「金額」行を見つける
    cnt_row: list[float] = []
    amt_row: list[float] = []

    for y in ys:
        row_words = rows[y]
        leftmost_text = row_words[0]["text"] if row_words else ""
        nums = []
        for w in row_words:
            n = _parse_amount(w["text"])
            if n is not None:
                nums.append(n)
        if "件数" in leftmost_text and len(nums) >= 3:
            cnt_row = nums
        elif "金額" in leftmost_text and len(nums) >= 3:
            amt_row = nums

    if not cnt_row or not amt_row:
        return None

    # 列順: 一般競争, 指名競争(0), 随意, FMS, 計
    # cnt_row / amt_row は [一般競争, 指名競争(0 or なし), 随意, FMS, 計] の順
    # ただし指名競争がない年度もある → 数値の数で判断
    def _pick(row: list[float], idx_if4: int, idx_if5: int) -> float | None:
        if len(row) >= 5:
            return row[idx_if5]
        if len(row) >= 4:
            return row[idx_if4]
        return None

    competition_cnt = _pick(cnt_row, 0, 0)
    zuii_cnt        = _pick(cnt_row, 1, 2)  # 指名競争が間に入る場合は idx2
    fms_cnt         = _pick(cnt_row, 2, 3)
    competition_100m = _pick(amt_row, 0, 0)
    zuii_100m        = _pick(amt_row, 1, 2)
    fms_100m         = _pick(amt_row, 2, 3)

    if is_hyakuman:
        # 百万円 → 億円
        def _conv(v: float | None) -> float | None:
            return round(v / 100, 2) if v is not None else None
        competition_100m = _conv(competition_100m)
        zuii_100m        = _conv(zuii_100m)
        fms_100m         = _conv(fms_100m)

    return dict(
        competition_cnt=int(competition_cnt) if competition_cnt is not None else None,
        competition_100m=competition_100m,
        zuii_cnt=int(zuii_cnt) if zuii_cnt is not None else None,
        zuii_100m=zuii_100m,
        fms_cnt=int(fms_cnt) if fms_cnt is not None else None,
        fms_100m=fms_100m,
    )


# ──────────────────────────────────────────────────────────────────
# 百万円 / 億円 判定ヘルパー
# ──────────────────────────────────────────────────────────────────

def _is_hyakuman_page(words: list[dict]) -> bool:
    """ページに '百万円' があれば True。"""
    for w in words:
        if "百万円" in w["text"]:
            return True
    return False


def _to_100m(amount: float | None, is_hyakuman: bool) -> float | None:
    if amount is None:
        return None
    if is_hyakuman:
        return round(amount / 100, 2)
    return amount


# ──────────────────────────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────────────────────────

def process_all(dry_run: bool = False) -> None:
    con = sqlite3.connect(str(DB_PATH))
    init_tables(con)

    total_company_items = 0
    total_main_items = 0
    total_method_updates = 0

    for fy, fname, top20_pi, items_pi, org_pi in PDF_MAP:
        pdf_path = PDF_DIR / fname
        if not pdf_path.exists():
            print(f"  SKIP {fname} (not found)")
            continue

        print(f"\n=== FY{fy} {fname} ===")

        # ① 上位20社の主な調達品
        if top20_pi is not None:
            words = _page_words(pdf_path, top20_pi)
            if fy >= 2023:
                company_items = extract_company_items_r05_r06(words, fy, fname)
            elif fy >= 2021:
                company_items = extract_company_items_r03_r04(words, fy, fname)
            else:  # FY2007-2020 (H19-R02)
                company_items = extract_company_items_h19_r02(words, fy, fname)

            print(f"  company_items: {len(company_items)} rows")
            if not dry_run and company_items:
                # 既存データを削除して再挿入
                con.execute(
                    "DELETE FROM chuou_chotatsu_company_items WHERE fiscal_year=?", (fy,)
                )
                con.executemany(
                    "INSERT OR REPLACE INTO chuou_chotatsu_company_items "
                    "(fiscal_year, company_rank, company_name, item_name, item_order, source_file) "
                    "VALUES (?,?,?,?,?,?)",
                    company_items,
                )
                con.commit()
            total_company_items += len(company_items)

        # ② 主要調達品目
        if items_pi is not None:
            words_items = _page_words(pdf_path, items_pi)
            is_hm = _is_hyakuman_page(words_items)

            if fy >= 2015:
                raw_items = extract_main_items_modern(words_items, fy, fname)
            else:
                raw_items = extract_main_items_old(words_items, fy, fname)

            # 単位変換
            main_items = [
                (fy, org, name, qty, _to_100m(amt, is_hm), vnd, src)
                for fy, org, name, qty, amt, vnd, src in raw_items
                if name  # item_name が空でないもの
            ]
            print(f"  main_items: {len(main_items)} rows")
            if not dry_run and main_items:
                con.execute("DELETE FROM chuou_chotatsu_main_items WHERE fiscal_year=?", (fy,))
                con.executemany(
                    "INSERT OR IGNORE INTO chuou_chotatsu_main_items "
                    "(fiscal_year, requesting_org, item_name, quantity_str, amount_100m, vendor_name, source_file) "
                    "VALUES (?,?,?,?,?,?,?)",
                    main_items,
                )
                con.commit()
            total_main_items += len(main_items)

        # ③ 契約方式別（R03-R06のみ）
        if org_pi is not None and fy >= 2021:
            words_org = _page_words(pdf_path, org_pi)
            method = extract_contract_method(words_org, fy)
            if method:
                print(f"  contract_method: {method}")
                if not dry_run:
                    con.execute(
                        """UPDATE chuou_chotatsu_summary
                           SET method_competition_cnt=?, method_competition_100m=?,
                               method_zuii_cnt=?, method_zuii_100m=?,
                               method_fms_cnt=?, method_fms_100m=?
                           WHERE fiscal_year=?""",
                        (method["competition_cnt"], method["competition_100m"],
                         method["zuii_cnt"], method["zuii_100m"],
                         method["fms_cnt"], method["fms_100m"],
                         fy),
                    )
                    con.commit()
                    total_method_updates += 1

    con.close()
    print(f"\n=== 完了 ===")
    print(f"  company_items: {total_company_items} rows")
    print(f"  main_items:    {total_main_items} rows")
    print(f"  method_updates: {total_method_updates} rows")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    if dry:
        print("[DRY RUN] DBには書き込みません")
    process_all(dry_run=dry)
