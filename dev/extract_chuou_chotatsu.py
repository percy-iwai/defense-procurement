#!/usr/bin/env python3
"""
中央調達実績 PDF / HTML → SQLite DB 抽出スクリプト
対象: H11(1999)〜R06(2024)

Usage:
    python dev/extract_chuou_chotatsu.py           # 本番実行
    python dev/extract_chuou_chotatsu.py --dry-run # DB書き込みなし
    python dev/extract_chuou_chotatsu.py --debug <pdf_path>  # 単一PDFのデバッグ出力
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber が未インストールです: pip install pdfplumber")

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("requests/beautifulsoup4 が未インストールです: pip install requests beautifulsoup4 lxml")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JISSEKI_DIR = PROJECT_ROOT / "data" / "raw" / "chuou_chotatsu_jisseki"
GAIKYO_DIR = PROJECT_ROOT / "data" / "raw" / "chuou_chotatsu_gaikyo"
DB_PATH = PROJECT_ROOT / "data" / "chuou_chotatsu.db"

# ── 確定値（一次資料に基づく）──────────────────────────────────────
# data_type = 'jisseki': 実績値（PDF/HTMLより確認）
# data_type = 'seed': 既知の信頼できる値（README/CLAUDE.md）
# data_type = 'estimate': 傾向線による推計（ダッシュボードで明示）
_KNOWN_SUMMARY: dict[int, dict] = {
    # ── HTML 確認済み（H12-H16）──────────────────────────────────
    # 注: HTMLスクレイピングが成功した場合はそちらを優先
    # ── seed ─────────────────────────────────────────────────────
    2006: {"total": 13226, "data_type": "seed"},
    2011: {"total": 14716, "data_type": "seed"},
    2012: {"total": 15287, "data_type": "seed"},
    2021: {"total": 18031, "data_type": "seed"},
    2022: {"total": 17208, "data_type": "seed"},
    2023: {"total": 55737, "data_type": "seed"},
    2024: {"total": 57943, "army": 13861, "navy": 20380,
           "airforce": 14003, "other": 9699, "data_type": "seed"},
    # ── 傾向線推計（欠落年度の補完、ダッシュボードで明示）──────────
    1999: {"total": 12200, "data_type": "estimate"},  # H11 (HTML失敗)
    2007: {"total": 13500, "data_type": "estimate"},  # H19
    2008: {"total": 13300, "data_type": "estimate"},  # H20
    2009: {"total": 13100, "data_type": "estimate"},  # H21
    2010: {"total": 13000, "data_type": "estimate"},  # H22
    2013: {"total": 14500, "data_type": "estimate"},  # H25
    2014: {"total": 14800, "data_type": "estimate"},  # H26
    2015: {"total": 15000, "data_type": "estimate"},  # H27
    2016: {"total": 15300, "data_type": "estimate"},  # H28
    2017: {"total": 15800, "data_type": "estimate"},  # H29
    2018: {"total": 16200, "data_type": "estimate"},  # H30
    2019: {"total": 17000, "data_type": "estimate"},  # R01
    2020: {"total": 17200, "data_type": "estimate"},  # R02
}

# ── H11-H16 Wayback URL マッピング ───────────────────────────────
_HTML_SOURCES: dict[int, dict[str, list[str]]] = {
    1999: {
        "summary_urls": [
            "https://web.archive.org/web/20010411184238/http://www.jda-cco.go.jp/kakuteichi-11nendo-1.htm",
        ],
        "company_urls": [
            "https://web.archive.org/web/20010411184238/http://www.jda-cco.go.jp/kakuteichi-11nendo-3.htm",
        ],
    },
    2000: {
        "summary_urls": [
            "https://web.archive.org/web/20020206195044/http://www.jda-cco.go.jp/12_kakuteichi/1_12_choutatsu__jisshi.htm",
        ],
        "company_urls": [
            "https://web.archive.org/web/20020206195044/http://www.jda-cco.go.jp/12_kakuteichi/3_12_joi_20sha.htm",
        ],
    },
    2001: {
        "summary_urls": [
            "https://web.archive.org/web/20020804055608/http://www.jda-cco.go.jp/13_jisseki/1_13gaiyou.htm",
        ],
        "company_urls": [
            "https://web.archive.org/web/20020804055608/http://www.jda-cco.go.jp/13_jisseki/3_13jyoui20sha.htm",
        ],
    },
    2002: {
        "summary_urls": [
            "https://web.archive.org/web/20031002005953/http://www.jda-cco.go.jp/14jisseki15mikomi/14jisseki15mikomi.htm",
        ],
        "company_urls": [
            "https://web.archive.org/web/20031002005953/http://www.jda-cco.go.jp/14jisseki15mikomi/14jisseki15mikomi.htm",
        ],
    },
    2003: {
        "summary_urls": [
            "https://web.archive.org/web/20040804023836/http://www.cco.jda.go.jp/supply/jisseki/jisseki_mikomi.html",
        ],
        "company_urls": [
            "https://web.archive.org/web/20040804023836/http://www.cco.jda.go.jp/supply/jisseki/jisseki_mikomi.html",
        ],
    },
    2004: {
        "summary_urls": [
            "https://web.archive.org/web/20060420062419/http://www.cco.jda.go.jp/supply/jisseki/jisseki_mikomi.html",
        ],
        "company_urls": [
            "https://web.archive.org/web/20060420062419/http://www.cco.jda.go.jp/supply/jisseki/jisseki_mikomi.html",
        ],
    },
}

# ── 上位企業 確定値（R05/R06, 出典: 中央調達実績PDF / CLAUDE.md）────────────
_KNOWN_COMPANIES: dict[int, list[dict]] = {
    2023: [  # R05 - r05_chotatsu_jisseki.pdf 上位4社（PDF page3 table から抽出）
        {"rank": 1,  "company_name": "三菱重工業(株)",   "amount_100m": 16803, "share_pct": None},
        {"rank": 2,  "company_name": "三菱電機(株)",     "amount_100m": 3886,  "share_pct": None},
        {"rank": 3,  "company_name": "日本電気(株)",     "amount_100m": 2954,  "share_pct": None},
        {"rank": 4,  "company_name": "三菱重機(株)",     "amount_100m": 2685,  "share_pct": None},
        {"rank": 5,  "company_name": "川崎重工業(株)",   "amount_100m": 2096,  "share_pct": None},
    ],
    2024: [  # R06 - r06_chotatsu_jisseki.pdf (出典: CLAUDE.md / 中央調達実績PDF)
        {"rank": 1,  "company_name": "三菱重工業(株)",   "amount_100m": 14567, "share_pct": 25.1},
        {"rank": 2,  "company_name": "川崎重工業(株)",   "amount_100m": 6383,  "share_pct": 11.0},
        {"rank": 3,  "company_name": "三菱電機(株)",     "amount_100m": 4956,  "share_pct": 8.6},
        {"rank": 4,  "company_name": "日本電気(株)",     "amount_100m": 3117,  "share_pct": 5.4},
    ],
}

# ── ユーティリティ ────────────────────────────────────────────────

def _z2h(s: str) -> str:
    return unicodedata.normalize("NFKC", s)

def _normalize_num(s: str | None) -> float | None:
    """文字列を float に変換。数値以外はNone。上限なし（単位変換は別途実施）"""
    if not s:
        return None
    s = _z2h(str(s)).replace(",", "").replace("，", "").replace(" ", "").strip()
    s = re.sub(r"[億件円以上未満約〜～\s]+.*$", "", s)
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return None
    try:
        val = float(s)
        # 完全に非現実的な値（1京円超 = 1e16円以上）は除外
        return val if val < 1e13 else None
    except ValueError:
        return None

def _coerce_okuyen(raw: float | None, check_fn) -> float | None:
    """
    単位を自動判定して億円に変換。
    変換試順: 億円(÷1) → 百万円(÷100) → 千円(÷100000)
    """
    if raw is None:
        return None
    for div in [1.0, 100.0, 100_000.0]:
        v = raw / div
        if check_fn(v):
            return v
    return None

def _is_plausible_total(val: float | None) -> bool:
    """防衛省中央調達の年間総額として妥当: 5,000〜100,000 億円"""
    return val is not None and 5_000 <= val <= 100_000

def _is_plausible_org(val: float | None, total: float | None = None) -> bool:
    """機関別金額として妥当: 100〜70,000 億円 かつ total の 95% 未満"""
    if val is None:
        return False
    if not (100 <= val <= 70_000):
        return False
    if total is not None and val >= total * 0.95:
        return False
    return True

def _fy_label(year: int) -> str:
    if year >= 2019:
        return f"令和{year - 2018}年度"
    return f"平成{year - 1988}年度"

def _filename_to_fy(fname: str) -> int | None:
    m = re.match(r"^(h|r)(\d+)", Path(fname).name.lower())
    if not m:
        return None
    era, num = m.group(1), int(m.group(2))
    return 1988 + num if era == "h" else 2018 + num

def _cells(row: list) -> list[str]:
    return [_z2h(str(c or "")).strip() for c in row]

def _log(status: str, msg: str) -> None:
    prefix = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(status, f"[{status}]")
    print(f"{prefix} {msg}")

# ── DB 初期化 ─────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS chuou_chotatsu_summary (
    fiscal_year   INTEGER PRIMARY KEY,
    total_100m    REAL,
    army_100m     REAL,
    navy_100m     REAL,
    airforce_100m REAL,
    other_100m    REAL,
    data_type     TEXT,
    source_file   TEXT
);

CREATE TABLE IF NOT EXISTS chuou_chotatsu_companies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_year   INTEGER,
    rank          INTEGER,
    company_name  TEXT,
    contracts_cnt INTEGER,
    amount_100m   REAL,
    share_pct     REAL,
    source_file   TEXT,
    UNIQUE(fiscal_year, rank)
);
"""

def init_db(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
    con.commit()

def upsert_summary(con: sqlite3.Connection, fy: int, d: dict, source: str, dry_run: bool) -> None:
    if dry_run:
        return
    con.execute(
        """INSERT OR REPLACE INTO chuou_chotatsu_summary
           (fiscal_year, total_100m, army_100m, navy_100m, airforce_100m, other_100m, data_type, source_file)
           VALUES (?,?,?,?,?,?,?,?)""",
        (fy, d.get("total"), d.get("army"), d.get("navy"), d.get("airforce"), d.get("other"),
         d.get("data_type", "jisseki"), source),
    )
    con.commit()

def upsert_companies(con: sqlite3.Connection, fy: int, rows: list[dict], source: str, dry_run: bool) -> None:
    if dry_run or not rows:
        return
    con.executemany(
        """INSERT OR REPLACE INTO chuou_chotatsu_companies
           (fiscal_year, rank, company_name, contracts_cnt, amount_100m, share_pct, source_file)
           VALUES (?,?,?,?,?,?,?)""",
        [(fy, r["rank"], r["company_name"], r.get("contracts_cnt"), r.get("amount_100m"),
          r.get("share_pct"), source)
         for r in rows],
    )
    con.commit()

def _merge_with_seed(fy: int, extracted: dict) -> dict:
    """
    seed 値とマージ。total はseed優先。org は seed に値があればseed優先。
    抽出値がseedと5%以上乖離する場合は seed_corrected に。
    estimate は抽出成功時に上書きしない（一次資料を優先）。
    """
    known = _KNOWN_SUMMARY.get(fy, {})
    if not known:
        return extracted

    result = dict(extracted)
    known_dtype = known.get("data_type", "seed")

    # estimate は抽出値が存在する場合は上書きしない
    if known_dtype == "estimate" and result.get("total"):
        return result

    # total: seed/jisseki/seed_corrected は常に優先
    if known.get("total"):
        ext_total = result.get("total")
        result["total"] = known["total"]
        if ext_total and abs(ext_total - known["total"]) / known["total"] > 0.05:
            result["data_type"] = "seed_corrected"
        else:
            result["data_type"] = known_dtype

    # org: seed に値があれば優先
    for key in ("army", "navy", "airforce", "other"):
        if known.get(key) is not None:
            result[key] = known[key]

    # seed 適用後に org の整合性を再チェック
    final_total = result.get("total")
    if final_total:
        org_sum = sum(result.get(k, 0) or 0 for k in ("army", "navy", "airforce", "other"))
        if org_sum > final_total * 1.05:
            for k in ("army", "navy", "airforce", "other"):
                result.pop(k, None)
        else:
            for k in ("army", "navy", "airforce", "other"):
                v = result.get(k)
                if v is not None and not _is_plausible_org(v, final_total):
                    result.pop(k, None)

    return result

# ── HTML スクレイピング ───────────────────────────────────────────

def fetch_html(url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=40)
            resp.raise_for_status()
            enc = (resp.encoding or "").lower()
            if enc in ("shift_jis", "shift-jis", "sjis", "ms932", "cp932"):
                resp.encoding = "shift_jis"
            elif enc in ("euc-jp", "euc_jp", "eucjp"):
                resp.encoding = "euc-jp"
            else:
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                _log("FAIL", f"HTTP失敗 {url}: {e}")
                return None

def _parse_html_tables(html: str) -> list[list[list[str]]]:
    soup = BeautifulSoup(html, "lxml")
    # ふりがな（<rt>）を除去して企業名を正規化
    for rt in soup.find_all("rt"):
        rt.decompose()
    result = []
    for tbl in soup.find_all("table"):
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [_z2h(td.get_text(separator="", strip=True)) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            result.append(rows)
    return result

_ORG_KW = {
    "army":     ["陸上", "陸幕", "陸自"],
    "navy":     ["海上", "海幕", "海自"],
    "airforce": ["航空", "空幕", "空自"],
}

def _match_org(cell: str) -> str | None:
    """機関名を識別。複数の機関キーワードを含む合計行はNone"""
    matches = [org for org, kws in _ORG_KW.items() if any(k in cell for k in kws)]
    return matches[0] if len(matches) == 1 else None

def _extract_summary_from_rows(rows: list[list[str]]) -> dict:
    """テーブル行リストからサマリーを抽出"""
    result: dict = {}

    for row in rows:
        if not row:
            continue
        # 合計行
        if any("合計" in c for c in row) and "total" not in result:
            nums = [_normalize_num(c) for c in row if _normalize_num(c) is not None]
            if nums:
                total = _coerce_okuyen(max(nums), _is_plausible_total)
                if total:
                    result["total"] = total
        # 機関行
        org = _match_org(row[0])
        if org and org not in result:
            nums = [_normalize_num(c) for c in row[1:] if _normalize_num(c) is not None]
            if nums:
                org_raw = max(nums)
                current_total = result.get("total")
                for div in [1.0, 100.0, 100_000.0]:
                    v = org_raw / div
                    if _is_plausible_org(v, current_total):
                        result[org] = v
                        break

    # org 合計が total を超えている場合は全 org を破棄
    total = result.get("total")
    if total:
        org_sum = sum(result.get(k, 0) or 0 for k in ("army", "navy", "airforce", "other"))
        if org_sum > total * 1.05:
            for k in ("army", "navy", "airforce", "other"):
                result.pop(k, None)

    return result

def parse_html_summary(html: str) -> dict:
    tables = _parse_html_tables(html)
    result: dict = {}
    for rows in tables:
        d = _extract_summary_from_rows(rows)
        if d.get("total"):
            result.update(d)
            if result.get("total"):
                break
    return result

def _extract_rank_and_data(row: list[str]) -> tuple[int, str, list[float]] | None:
    """行から（順位, 企業名, 数値リスト）を抽出。複数カラム配置に対応。"""
    # 順位セルを探す（1〜20の整数のみのセル）
    rank_col = -1
    rank_val = -1
    for ci, cell in enumerate(row):
        s = _z2h(cell).strip()
        if not s or len(s) > 8:
            continue
        only_digits = re.sub(r"[^\d]", "", s)
        if not only_digits or not (1 <= int(only_digits) <= 20):
            continue
        if str(int(only_digits)) != only_digits:
            continue
        # セル中の非数字・非記号文字が多い場合は除外（"平成12年度" 等を防ぐ）
        non_num = re.sub(r"[\d\s.,\(\)（）、。\-]", "", s)
        if len(non_num) <= 2:
            rank_col = ci
            rank_val = int(only_digits)
            break
    if rank_col == -1:
        return None
    rank = rank_val

    # 企業名セルを探す（rank_col の後にある最初の非数字・非空テキスト）
    name = ""
    name_col = -1
    for ci, cell in enumerate(row[rank_col + 1:], rank_col + 1):
        s = cell.strip()
        if s and not re.match(r"^\d[\d,\.%]*$", s):
            name = s
            name_col = ci
            break
    if not name:
        return None

    # 数値は名前列の後のセルからのみ収集（rank 番号自体を除外）
    after_name = row[name_col + 1:] if name_col >= 0 else row[rank_col + 2:]
    nums = [n for c in after_name if _is_numeric_cell(str(c or "")) and (n := _normalize_num(c)) is not None]
    return (rank, name, nums)


def parse_html_companies(html: str) -> list[dict]:
    tables = _parse_html_tables(html)
    candidates: dict[int, dict] = {}

    for tbl in tables:
        if len(tbl) < 3:
            continue
        # ヘッダー行を探す（あれば）
        header_idx = -1
        for i, row in enumerate(tbl):
            joined = "".join(row)
            if (("順位" in joined or "位" in joined) and
                    ("企業" in joined or "相手" in joined or "会社" in joined)):
                header_idx = i
                break

        data_start = header_idx + 1 if header_idx >= 0 else 0

        # テーブル単位の divisor: 全セルを直接スキャン（rank検出不要）
        tbl_divisor = 1.0
        for _pr in tbl[data_start:data_start + 10]:
            for _cell in (_pr or []):
                if _is_numeric_cell(str(_cell or "")):
                    _n = _normalize_num(_cell)
                    if _n and _n > 20_000:
                        tbl_divisor = 100.0
                        break
            if tbl_divisor == 100.0:
                break

        for row in tbl[data_start:]:
            if not row:
                continue
            parsed = _extract_rank_and_data(row)
            if parsed is None:
                continue
            rank, name, nums = parsed
            if rank not in candidates:
                cnt, amt, pct = _extract_company_nums(nums[:3], tbl_divisor)
                candidates[rank] = {
                    "rank": rank, "company_name": name,
                    "contracts_cnt": cnt, "amount_100m": amt, "share_pct": pct,
                }

    return sorted(candidates.values(), key=lambda r: r["rank"])

# ── PDF パース（汎用）────────────────────────────────────────────

def _extract_all_tables(pdf_path: Path) -> list[tuple[int, list[list[str]]]]:
    results = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables() or []
                for tbl in tables:
                    rows = [_cells(row) for row in tbl
                            if any(c for c in row if str(c or "").strip())]
                    if rows:
                        results.append((i + 1, rows))
    except Exception as e:
        _log("FAIL", f"pdfplumber エラー {pdf_path.name}: {e}")
    return results

def _extract_text_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text() or ""
                if t.strip():
                    results.append((i + 1, _z2h(t)))
    except Exception:
        pass
    return results

def parse_pdf_summary(pdf_path: Path, debug: bool = False) -> dict:
    tables = _extract_all_tables(pdf_path)
    result: dict = {}

    for pg, rows in tables:
        d = _extract_summary_from_rows(rows)
        if debug:
            print(f"  page {pg}: {d}")
        if d.get("total"):
            result.update(d)
            # org を再チェック: total を取得後
            for key in ("army", "navy", "airforce", "other"):
                v = result.get(key)
                if v and not _is_plausible_org(v, result["total"]):
                    result.pop(key, None)
            break

    # テキストフォールバック
    if not result.get("total"):
        texts = _extract_text_pages(pdf_path)
        full_text = "\n".join(t for _, t in texts)
        if debug:
            print(f"  fulltext[:500]: {full_text[:500]}")
        # 合計パターン（キーワードあり）
        for pat in [
            r"合計[^\n]{0,30}?(\d{1,3}(?:,\d{3}){1,5})\s*(?:億|百万)?",
            r"総額[^\n]{0,30}?(\d{1,3}(?:,\d{3}){1,3})\s*(?:億|百万)?",
        ]:
            m = re.search(pat, full_text)
            if m and not result.get("total"):
                val = _coerce_okuyen(_normalize_num(m.group(1)), _is_plausible_total)
                if val:
                    result["total"] = val

        # 最初出現フォールバック（日本語キーワードが文字化けで検出不能な場合）
        # 注: 前年比較表は後ページに現れるため先頭出現を使う
        if not result.get("total"):
            for m in re.finditer(r'\d{1,3}(?:,\d{3}){2,6}', full_text):
                raw = _normalize_num(m.group())
                val = _coerce_okuyen(raw, _is_plausible_total)
                if val:
                    result["total"] = val
                    break

    return result

def _is_numeric_cell(cell: str) -> bool:
    """セルが数値として解釈可能か（品目欄等の長い文字列は除外）"""
    s = _z2h(str(cell or "")).strip()
    if not s or len(s) > 20:
        return False
    non_num = sum(1 for c in s if not (c.isdigit() or c in ",.% .-+（）()"))
    return non_num / len(s) < 0.4


def _is_garbled(s: str) -> bool:
    """Latin-1 解釈の Shift-JIS バイトを多く含む（文字化け）場合 True"""
    if not s:
        return False
    return sum(1 for c in s if 0x80 <= ord(c) <= 0xFF) / len(s) > 0.3


def _extract_company_nums(raw_nums: list, tbl_divisor: float = 1.0) -> tuple:
    """[件数, 金額(億円), 構成比(%)] をリストから推定。テーブル単位 divisor を適用。"""
    cnt, amt, pct = None, None, None
    if tbl_divisor != 1.0:
        # 単位が百万円など: 最大値をそのまま割るだけ（coerce不要）
        non_pct = [n for n in raw_nums if n > 100]  # 件数・金額候補
        # 構成比は小数点ありの値のみ（件数=整数と区別）
        pct_cands = [n for n in raw_nums if 0 < n <= 100 and not float(n).is_integer()]
        pct = pct_cands[0] if pct_cands else None
        if non_pct:
            best = max(non_pct)
            amt = round(best / tbl_divisor, 2)
            for n in non_pct:
                if n != best and n == int(n) and n < 5000:
                    cnt = int(n)
                    break
    else:
        amt_cands = [n for n in raw_nums if _coerce_okuyen(n, lambda v: 1 <= v <= 20_000)]
        if amt_cands:
            best_amt = max(amt_cands)
            amt = _coerce_okuyen(best_amt, lambda v: 1 <= v <= 20_000)
            remaining = [n for n in raw_nums if n != best_amt]
        else:
            remaining = list(raw_nums)
        for n in sorted(remaining):
            if n is None:
                continue
            if pct is None and 0 < n <= 100:
                pct = n
            elif cnt is None and n == int(n) and n < 5000:
                cnt = int(n)
    return cnt, amt, pct


def parse_pdf_companies(pdf_path: Path) -> list[dict]:
    tables = _extract_all_tables(pdf_path)
    candidates: dict[int, dict] = {}

    for _pg, rows in tables:
        header_idx = None
        for i, row in enumerate(rows):
            joined = "".join(c or "" for c in row)
            if ("順位" in joined or "位" in joined) and (
                    "企業" in joined or "相手" in joined or "会社" in joined):
                header_idx = i
                break
        # フォールバック1: ヘッダー行なし（行0が直接ランク1）
        if header_idx is None and rows and re.match(r"^[1１]$", (rows[0][0] or "").strip()):
            header_idx = -1
        # フォールバック2: ヘッダーが文字化け（行i='1'、行i+1='2' の連番）
        if header_idx is None:
            for i, row in enumerate(rows):
                if not row or not row[0]:
                    continue
                if re.sub(r"[^\d]", "", row[0].strip()) == "1":
                    nxt = rows[i + 1] if i + 1 < len(rows) else []
                    if nxt and re.sub(r"[^\d]", "", (nxt[0] or "").strip()) == "2":
                        # 名前列(col1)が非数字であることを確認
                        if len(row) > 1 and row[1] and not re.match(r"^\d+$", row[1].strip()):
                            header_idx = i - 1  # data_start = i
                            break
        if header_idx is None:
            continue

        data_start = header_idx + 1 if header_idx >= 0 else 0

        # テーブルの単位を先頭行から判定（百万円 vs 億円）
        # 先頭行の最大数値が >20000 なら百万円単位 → 全行で /100 を適用
        tbl_divisor = 1.0
        for _pr in rows[data_start:data_start + 5]:
            if not _pr or not (_pr[0] or "").strip():
                continue
            _raw = [_normalize_num(c) for c in _pr[2:] if _is_numeric_cell(str(c or "")) and _normalize_num(c) is not None]
            if _raw and max(_raw[:3], default=0) > 20_000:
                tbl_divisor = 100.0
                break

        for row in rows[data_start:]:
            if not row:
                continue
            rank_str = re.sub(r"[^\d]", "", (row[0] or "").strip())
            if not rank_str:
                continue
            rank = int(rank_str)
            if rank < 1 or rank > 20:
                continue
            name_raw = (row[1] or "").strip() if len(row) > 1 else ""
            if not name_raw or re.match(r"^\d+$", name_raw):
                continue
            # 文字化け名称はプレースホルダーに置換（金額等は保持）
            name = f"(企業{rank}位)" if _is_garbled(name_raw) else name_raw
            if rank not in candidates:
                # 数値セル判定後、最初の3値のみ（品目欄・過去順位等を排除）
                raw_all = [
                    _normalize_num(c) for c in row[2:]
                    if _is_numeric_cell(str(c or "")) and _normalize_num(c) is not None
                ]
                raw_nums = raw_all[:3]
                cnt, amt, pct = _extract_company_nums(raw_nums, tbl_divisor)
                candidates[rank] = {
                    "rank": rank, "company_name": name,
                    "contracts_cnt": cnt, "amount_100m": amt, "share_pct": pct,
                }

    # フォールバック: 全カラムが cell[0] にまとめられた PDF（R05/R06 等）
    # パターン: \n{rank}{garbled_name} {cnt} {amount}
    if not candidates:
        for _pg, rows in tables:
            found_any = False
            for i, row in enumerate(rows[1:], 1):  # row 0 はヘッダー
                if not row or all(not c for c in row[1:]):
                    cell = unicodedata.normalize("NFKC", str(row[0] or ""))
                    # パターンA: \n{rank}{name}{cnt} {amount}（名称あり）
                    # パターンB: \n{rank} {cnt} {amount}（名称なし・直後に数字）
                    _AMT = r'(\d{1,3}(?:,\d{3})+|\d{1,5})(?![,\d])'
                    _PATTERNS = [
                        r'(?:^|\n)(\d{1,2})([^\d\n][^\n]{0,40}?)\s{1,3}(\d{1,4})\s+' + _AMT,
                        r'(?:^|\n)(\d{1,2})\s+(\d{1,4})\s+' + _AMT,
                    ]
                    for _pat in _PATTERNS:
                        for m in re.finditer(_pat, cell):
                            g = m.groups()
                            if len(g) == 4:
                                rank_s, name_raw2, cnt_s, amt_s = g
                            else:
                                rank_s, cnt_s, amt_s = g
                                name_raw2 = ""
                            rank = int(rank_s)
                            if rank < 1 or rank > 20:
                                continue
                            name = f"(企業{rank}位)" if _is_garbled(name_raw2) else (name_raw2.strip() or f"(企業{rank}位)")
                            cnt = int(cnt_s) if cnt_s.isdigit() else None
                            amt_raw = _normalize_num(amt_s)
                            amt = _coerce_okuyen(amt_raw, lambda v: 1 <= v <= 25_000)
                            if rank not in candidates:
                                candidates[rank] = {
                                    "rank": rank, "company_name": name,
                                    "contracts_cnt": cnt, "amount_100m": amt,
                                    "share_pct": None,
                                }
                            found_any = True
            if found_any and len(candidates) >= 10:
                break

    return sorted(candidates.values(), key=lambda r: r["rank"])

# ── PDF ファイル一覧 ──────────────────────────────────────────────

def _get_pdf_files() -> dict[int, tuple[Path, str]]:
    """同一年度は jisseki ファイルを優先"""
    fy_files: dict[int, list[tuple[Path, str]]] = {}
    for fpath in JISSEKI_DIR.glob("*.pdf"):
        fy = _filename_to_fy(fpath.name)
        if fy is None:
            continue
        dtype = "mikomi" if "mikomi" in fpath.name.lower() else "jisseki"
        fy_files.setdefault(fy, []).append((fpath, dtype))

    result: dict[int, tuple[Path, str]] = {}
    for fy, files in fy_files.items():
        jisseki = [(f, d) for f, d in files if d == "jisseki"]
        result[fy] = jisseki[0] if jisseki else files[0]
    return result

# ── メイン処理 ────────────────────────────────────────────────────

def debug_pdf(pdf_path_str: str) -> None:
    """単一PDFのデバッグ出力"""
    pdf_path = Path(pdf_path_str)
    print(f"=== DEBUG: {pdf_path.name} ===")
    result = parse_pdf_summary(pdf_path, debug=True)
    print(f"summary: {result}")
    companies = parse_pdf_companies(pdf_path)
    print(f"companies: {len(companies)}社")
    for c in companies[:5]:
        print(f"  {c}")

def main(dry_run: bool = False) -> None:
    print(f"中央調達実績 DB 構築 {'(dry-run)' if dry_run else ''}")
    print(f"DB: {DB_PATH}")
    print("=" * 60)

    con = sqlite3.connect(DB_PATH) if not dry_run else sqlite3.connect(":memory:")
    init_db(con)

    summary_inserted = 0
    companies_inserted = 0

    # ── H11-H16: HTML スクレイピング ─────────────────────────────
    print("\n--- HTML ソース (H11-H16) ---")
    for fy in sorted(_HTML_SOURCES.keys()):
        src = _HTML_SOURCES[fy]
        label = _fy_label(fy)
        sum_data: dict = {}
        co_data: list[dict] = []
        source_tag = f"html_wayback_{fy}"

        # サマリー
        html_cache: dict[str, str] = {}
        for url in src["summary_urls"]:
            html = fetch_html(url)
            if html:
                html_cache[url] = html
                d = parse_html_summary(html)
                sum_data.update(d)
                time.sleep(1)
            if sum_data.get("total"):
                break

        # 企業
        for url in src["company_urls"]:
            html = html_cache.get(url) or fetch_html(url)
            if html:
                if url not in html_cache:
                    time.sleep(1)
                co_data = parse_html_companies(html)
            if co_data:
                break

        # seed マージ
        sum_data = _merge_with_seed(fy, sum_data)
        if not sum_data.get("total"):
            known = _KNOWN_SUMMARY.get(fy)
            if known:
                sum_data = dict(known)
                source_tag = f"seed_{fy}"

        if sum_data.get("total"):
            sum_data.setdefault("data_type", "jisseki")
            upsert_summary(con, fy, sum_data, source_tag, dry_run)
            summary_inserted += 1
            _log("OK", f"{label} → {sum_data['total']:,.0f}億, companies ({len(co_data)}社) [{sum_data.get('data_type')}]")
        else:
            _log("WARN", f"{label} HTML → summary 抽出失敗")

        if co_data:
            upsert_companies(con, fy, co_data, source_tag, dry_run)
            companies_inserted += len(co_data)

    # ── H18 特殊フォーマット ─────────────────────────────────────
    print("\n--- H18 特殊フォーマット PDF ---")
    h18_path = JISSEKI_DIR / "h18_chotatsu_jisseki.pdf"
    if h18_path.exists():
        # P6 の企業ランキング（全ページから探す）
        all_tables = _extract_all_tables(h18_path)
        # P6 以降を優先
        p6_tables = [(pg, rows) for pg, rows in all_tables if pg >= 5]
        co_data = parse_pdf_companies(h18_path)

        h18_sum = {**_KNOWN_SUMMARY.get(2006, {"total": 13226})}
        upsert_summary(con, 2006, h18_sum, "h18_chotatsu_jisseki.pdf", dry_run)
        summary_inserted += 1

        if co_data:
            upsert_companies(con, 2006, co_data, "h18_chotatsu_jisseki.pdf", dry_run)
            companies_inserted += len(co_data)
        _log("OK", f"H18(2006) → {h18_sum.get('total', 13226):,}億 [{h18_sum.get('data_type','seed')}], companies ({len(co_data)}社)")
    else:
        _log("WARN", "h18_chotatsu_jisseki.pdf が見つかりません → seed のみ")
        h18_sum = {**_KNOWN_SUMMARY.get(2006, {"total": 13226})}
        upsert_summary(con, 2006, h18_sum, "seed_2006", dry_run)
        summary_inserted += 1

    # ── H17, H19〜R06: PDF ──────────────────────────────────────
    print("\n--- PDF ソース (H17〜R06) ---")
    pdf_files = _get_pdf_files()

    for fy in sorted(pdf_files.keys()):
        if fy == 2006:
            continue
        fpath, dtype = pdf_files[fy]
        label = _fy_label(fy)

        sum_data = parse_pdf_summary(fpath)
        co_data = parse_pdf_companies(fpath)

        # seed マージ
        sum_data = _merge_with_seed(fy, sum_data)
        if not sum_data.get("total"):
            known = _KNOWN_SUMMARY.get(fy)
            if known:
                sum_data = dict(known)
                dtype = known.get("data_type", "seed")

        if sum_data.get("total"):
            sum_data.setdefault("data_type", dtype)
            upsert_summary(con, fy, sum_data, fpath.name, dry_run)
            summary_inserted += 1
            total_str = f"{sum_data['total']:,.0f}億"
            org_parts = []
            for k, lbl in [("army", "陸"), ("navy", "海"), ("airforce", "空")]:
                if sum_data.get(k):
                    org_parts.append(f"{lbl}{sum_data[k]:,.0f}")
            org_str = f" ({' / '.join(org_parts)})" if org_parts else ""
            _log("OK", f"{label} {fpath.name} → {total_str}{org_str}, companies ({len(co_data)}社) [{sum_data.get('data_type', dtype)}]")
        else:
            _log("FAIL", f"{label} {fpath.name} → summary なし・seed なし")

        if co_data:
            upsert_companies(con, fy, co_data, fpath.name, dry_run)
            companies_inserted += len(co_data)

    # ── 企業シードデータ（PDFから抽出できなかった年度を補完）────────
    for fy, co_list in sorted(_KNOWN_COMPANIES.items()):
        if dry_run:
            continue
        cnt = con.execute(
            "SELECT count(*) FROM chuou_chotatsu_companies WHERE fiscal_year=?", (fy,)
        ).fetchone()[0]
        if cnt >= len(co_list):
            continue  # 既に十分なデータあり
        upsert_companies(con, fy, co_list, f"seed_companies_{fy}", dry_run)
        companies_inserted += len(co_list)
        _log("OK", f"{_fy_label(fy)} 企業シード追加 ({len(co_list)}社)")

    # ── シードデータ最終補完（未挿入年度のみ）────────────────────
    print("\n--- シードデータ補完（未挿入年度のみ）---")
    for fy, known in sorted(_KNOWN_SUMMARY.items()):
        if dry_run:
            continue
        row = con.execute(
            "SELECT total_100m FROM chuou_chotatsu_summary WHERE fiscal_year=?", (fy,)
        ).fetchone()
        if row and row[0]:
            continue  # 既にデータあり
        d = dict(known)
        upsert_summary(con, fy, d, f"seed_{fy}", dry_run)
        summary_inserted += 1
        dtype = known.get("data_type", "seed")
        _log("OK", f"{_fy_label(fy)} → {known.get('total'):,.0f}億 [{dtype}]（補完）")

    # ── バリデーション: 1社で総額の60%超は不正値 → NULL化 ──────────
    if not dry_run:
        cur = con.cursor()
        cur.execute("""
            UPDATE chuou_chotatsu_companies
            SET amount_100m = NULL
            WHERE amount_100m > (
                SELECT total_100m * 0.6
                FROM chuou_chotatsu_summary s
                WHERE s.fiscal_year = chuou_chotatsu_companies.fiscal_year
            )
        """)
        con.commit()
        nulled = cur.rowcount
        if nulled:
            print(f"[INFO] 不正金額 NULL化: {nulled}件")

    con.close()

    print("\n" + "=" * 60)
    print(f"完了: summary {summary_inserted}件, companies {companies_inserted}件")
    if not dry_run:
        print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB に書き込まない")
    parser.add_argument("--debug", metavar="PDF", help="単一PDFのデバッグ出力")
    args = parser.parse_args()

    if args.debug:
        debug_pdf(args.debug)
    else:
        main(dry_run=args.dry_run)
