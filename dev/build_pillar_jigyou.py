"""Parse defense budget PDFs to populate defense_pillar_jigyou.

Sources:
  yosan_fy2022.pdf (旧分類 → 7-pillar 明示マッピング)
  yosan_fy2023.pdf, yosan_fy2024.pdf, yosan_fy2025.pdf (7本柱+共通基盤構造)
"""
import os
import re
import sys
import sqlite3
import shutil
import unicodedata
from pathlib import Path
from typing import Iterable

import pdfplumber

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
SEISAKU_DIR = ROOT / "data" / "seisaku"
DB_REAL = ROOT / "data" / "db" / "procurement.db"
DB_TMP = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "procurement_pillar.db"


PILLAR_DEFS = [
    (1, "スタンド・オフ防衛能力"),
    (2, "統合防空ミサイル防衛能力"),
    (3, "無人アセット防衛能力"),
    (4, "領域横断作戦能力"),
    (5, "指揮統制・情報関連機能"),
    (6, "機動展開能力・国民保護"),
    (7, "持続性・強靱性"),
    (8, "早期装備化のための新たな取組"),
    (9, "防衛生産基盤の強化"),
    (10, "研究開発"),
    (11, "防衛力を支える要素"),
    (12, "日米同盟強化及び地域社会との調和に係る施策等"),
    (13, "安全保障協力の強化"),
    (14, "気候変動への取組"),
    (15, "最適化への取組"),
    (16, "自衛隊の組織編成"),
    (17, "自衛官の定員・実員"),
    (18, "事務官等の増員"),
    (19, "税制改正"),
    (20, "ＡＩ活用の推進に係る施策"),
    (21, "情報保全の強化"),
    (22, "監察体制の強化"),
    (23, "大規模災害等への対応"),  # FY2022独自セクション保存用
]
PILLAR_NAME = {pid: pn for pid, pn in PILLAR_DEFS}


# Page header prefix that some pages prepend (Roman numeral + section name)
PAGE_HEADER_RE = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧ]+\s*(?:主要事項|共通基盤|防衛関係費)\s+")

# ---- 7-pillar (主要事項) detection: yosan_fy2023/2024/2025 ----
PILLAR_PATTERNS_MAIN = [
    (1, re.compile(r"(?:^|\s)[1１]\s+スタンド[・\s]*オフ防衛能力")),
    (2, re.compile(r"(?:^|\s)[2２]\s+統合防空ミサイル防衛能力")),
    (3, re.compile(r"(?:^|\s)[3３]\s+無人アセット防衛能力")),
    (4, re.compile(r"(?:^|\s)[4４]\s+領域横断作戦能力")),
    (5, re.compile(r"(?:^|\s)[5５]\s+指揮統制[・\s]*情報関連機能")),
    (6, re.compile(r"(?:^|\s)[6６]\s+機動展開能力[・\s]*国民保護")),
    (7, re.compile(r"(?:^|\s)[7７]\s+持続性[・\s]*強靱性")),
]

# ---- 共通基盤 sub-pillars detection ----
# Patterns search after a digit prefix (allowing FY2025 page header prefix "Ⅳ 共通基盤")
PILLAR_PATTERNS_FOUNDATION = [
    (8, re.compile(r"(?:^|\s)[0-9０-９]+\s+早期装備化")),
    (9, re.compile(r"(?:^|\s)[0-9０-９]+\s+防衛生産基盤の強化")),
    (10, re.compile(r"(?:^|\s)[0-9０-９]+\s+研究開発")),
    (20, re.compile(r"(?:^|\s)[0-9０-９]+\s+ＡＩ活用")),
    (11, re.compile(r"(?:^|\s)[0-9０-９]+\s+防衛力を支える要素")),
    (12, re.compile(r"(?:^|\s)[0-9０-９]+\s+日米同盟強化")),
    (13, re.compile(r"(?:^|\s)[0-9０-９]+\s+安全保障協力の強化")),
    (14, re.compile(r"(?:^|\s)[0-9０-９]+\s+気候変動への取組")),
    (15, re.compile(r"(?:^|\s)[0-9０-９]+\s+最適化への取組")),
    (16, re.compile(r"(?:^|\s)[0-9０-９]+\s+自衛隊の組織編成")),
    (17, re.compile(r"(?:^|\s)[0-9０-９]+\s+自衛(?:官|隊)の(?:定員|実員)")),
    (18, re.compile(r"(?:^|\s)[0-9０-９]+\s+事務官等の増員")),
    (19, re.compile(r"(?:^|\s)[0-9０-９]+\s+税制改正")),
    (21, re.compile(r"(?:^|\s)[0-9０-９]+\s+情報保全の強化")),
    (22, re.compile(r"(?:^|\s)[0-9０-９]+\s+監察体制の強化")),
]

SECTION_MAIN_RE = re.compile(r"主\s*要\s*事\s*項")
SECTION_COMMON_RE = re.compile(r"共\s*通\s*基\s*盤")

PROJECT_HEAD_RE = re.compile(r"^[○●]\s*(.+)$")
PROJECT_BULLET_RE = re.compile(r"^[・･]\s*(.+)$")

# Has yen amount somewhere in line
HAS_YEN_RE = re.compile(r"[\d０-９,，]+\s*[億万千]\s*円")
KANJI_RE = re.compile(r"[一-鿿]")

# Junk filters: lines that look like body text not project headers
JUNK_RE = re.compile(
    r"^(?:こ[れの]|そ[れの]|また|さらに|ただし|なお|加えて|その他|当該|これら|"
    r"以下|上記|更に|これまで|今後|まず|次に|より|から|まで|について|"
    r"概ね|概要|状況|目的|背景|現状|課題|参照|再掲|令和|平成|"
    r"[0-9]+年度|\d+\.|（\d+）|\(\d+\))"
)

# Lines that aren't project descriptions but look ○-prefixed
NOISE_BODY_RE = re.compile(
    r"(?:中期防対象経費|歳出予算は|当初予算は|新たな大綱|防衛関係費)"
)


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


def clean_jigyou_name(raw: str) -> str:
    """Aggressive cleaning of project name."""
    s = raw
    s = re.sub(r"【再掲】", "", s)
    # Remove ALL trailing parenthesized groups iteratively
    while True:
        new = re.sub(r"\s*[（(][^)）]*[)）]\s*$", "", s)
        if new == s:
            break
        s = new
    # Remove leading bullet
    s = re.sub(r"^[○●・･]\s*", "", s)
    # Strip trailing 等, 等の継続, 取得・整備
    s = s.strip(" 　・,，")
    return s


def extract_pages_text(pdf_path: Path) -> list[str]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    return pages


def find_pillar_for_line(line: str, in_section: str | None) -> int | None:
    """Only match pillars when current_section is established (avoids TOC matches)."""
    line_n = line.strip()
    if in_section == "main":
        for pid, pat in PILLAR_PATTERNS_MAIN:
            if pat.search(line_n):
                return pid
    elif in_section == "common":
        for pid, pat in PILLAR_PATTERNS_FOUNDATION:
            if pat.search(line_n):
                return pid
    return None


def parse_yosan_modern(pdf_path: Path, fiscal_year: int) -> list[tuple]:
    """Parse FY2023-2025 PDFs with 7-pillar + 共通基盤 structure."""
    pages = extract_pages_text(pdf_path)
    records: list[tuple] = []
    seen: set[tuple[int, str]] = set()

    current_section: str | None = None
    current_pillar: int | None = None

    for page_idx, page_text in enumerate(pages):
        first_text = " ".join(page_text.split("\n")[:3])
        if SECTION_MAIN_RE.search(first_text):
            current_section = "main"
        elif SECTION_COMMON_RE.search(first_text):
            current_section = "common"

        for raw_line in page_text.split("\n"):
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            # Strip page header "Ⅳ 共通基盤" / "Ⅲ 主要事項" prefix from line
            stripped_no_hdr = PAGE_HEADER_RE.sub("", stripped, count=1).strip()

            new_pillar = find_pillar_for_line(stripped_no_hdr, current_section)
            if new_pillar:
                current_pillar = new_pillar
                continue

            if current_pillar is None:
                continue

            # When stripping the page header revealed a project line, use stripped_no_hdr
            line_to_check = stripped_no_hdr if PAGE_HEADER_RE.match(stripped) else stripped

            # Pillars where projects may not have explicit yen amounts (training, exercises, etc.)
            relax_yen = current_pillar in (12, 13, 14, 16, 17, 18, 21, 22)

            m = PROJECT_HEAD_RE.match(line_to_check)
            if m:
                if not relax_yen and not HAS_YEN_RE.search(line_to_check):
                    continue
                if NOISE_BODY_RE.search(line_to_check):
                    continue
                name = clean_jigyou_name(m.group(1))
                if (3 <= len(name) <= 50
                    and KANJI_RE.search(name)
                    and not JUNK_RE.match(name)):
                    pname = PILLAR_NAME[current_pillar]
                    key = (current_pillar, name)
                    if key not in seen:
                        seen.add(key)
                        records.append((current_pillar, pname, name, fiscal_year, pdf_path.name))
                continue

            mb = PROJECT_BULLET_RE.match(line_to_check)
            if mb and HAS_YEN_RE.search(line_to_check):
                if NOISE_BODY_RE.search(line_to_check):
                    continue
                name = clean_jigyou_name(mb.group(1))
                if (4 <= len(name) <= 50
                    and KANJI_RE.search(name)
                    and not JUNK_RE.match(name)):
                    pname = PILLAR_NAME[current_pillar]
                    key = (current_pillar, name)
                    if key not in seen:
                        seen.add(key)
                        records.append((current_pillar, pname, name, fiscal_year, pdf_path.name))

    return records


# ---- FY2022 yosan section→pillar explicit mapping ----
# yosan_fy2022.pdf section markers (header pattern → pillar_id)
FY2022_SECTION_MAP = [
    # Form: (regex pattern, pillar_id) — order matters: more specific first
    (re.compile(r"指揮統制機能の強化"), 5),
    (re.compile(r"情報収集[・\s]*分析等機能の強化"), 5),
    (re.compile(r"情報機能の強化"), 5),
    (re.compile(r"認知領域"), 5),
    (re.compile(r"宇宙領域における能力"), 4),
    (re.compile(r"サイバー領域における能力"), 4),
    (re.compile(r"電磁波領域における能力"), 4),
    (re.compile(r"領域横断作戦"), 4),
    (re.compile(r"海空領域における能力"), 4),  # 陸海空 → P4
    (re.compile(r"スタンド[・\s]*オフ防衛能力"), 1),
    (re.compile(r"総合ミサイル防空能力"), 2),
    (re.compile(r"統合防空ミサイル防衛能力"), 2),
    (re.compile(r"機動[・\s]*展開能力"), 6),
    (re.compile(r"無人機の活用[・\s]*無人機への対処"), 3),
    (re.compile(r"無人アセット"), 3),
    (re.compile(r"持続性[・\s]*強靱性"), 7),
    (re.compile(r"継続的な運用の確保"), 7),
    (re.compile(r"装備品の維持整備"), 7),
    (re.compile(r"^[０-９0-9]+\s*人的基盤の強化"), 11),
    (re.compile(r"優秀な人材確保"), 11),
    (re.compile(r"女性活躍"), 11),
    (re.compile(r"教育[・\s]*研究体制"), 11),
    (re.compile(r"予備自衛官"), 11),
    (re.compile(r"衛生機能の強化"), 11),
    (re.compile(r"防衛技術基盤"), 10),
    (re.compile(r"防衛産業基盤"), 9),
    (re.compile(r"装備調達の最適化"), 15),
    (re.compile(r"^[０-９0-9]+\s*情報機能の強化"), 5),
    (re.compile(r"大規模災害等への対応"), 23),
    (re.compile(r"日米同盟強化"), 12),
    (re.compile(r"米軍再編関係経費"), 12),
    (re.compile(r"ＳＡＣＯ関係経費"), 12),
    (re.compile(r"基地対策等の推進"), 12),
    (re.compile(r"安全保障協力の強化"), 13),
    (re.compile(r"インド太平洋"), 13),
    (re.compile(r"効率化[・\s]*合理化"), 15),
    (re.compile(r"組織[・\s]*定員の合理化"), 16),
    (re.compile(r"自衛官(?:定数|実員|定員)"), 17),
    (re.compile(r"^[０-９0-9]+\s*事務官等の増員"), 18),
]


def parse_yosan_2022(pdf_path: Path) -> list[tuple]:
    """Parse FY2022 yosan PDF with explicit section→pillar mapping."""
    pages = extract_pages_text(pdf_path)
    records: list[tuple] = []
    seen: set[tuple[int, str]] = set()
    current_pillar: int | None = None

    fiscal_year = 2022
    src = pdf_path.name

    for page_text in pages:
        for raw_line in page_text.split("\n"):
            stripped = raw_line.strip()
            if not stripped:
                continue

            # Update pillar context based on section heading
            for pat, pid in FY2022_SECTION_MAP:
                if pat.search(stripped):
                    current_pillar = pid
                    break

            if current_pillar is None:
                continue

            m = PROJECT_HEAD_RE.match(stripped)
            if m and HAS_YEN_RE.search(stripped):
                if NOISE_BODY_RE.search(stripped):
                    continue
                name = clean_jigyou_name(m.group(1))
                if (3 <= len(name) <= 50
                    and KANJI_RE.search(name)
                    and not JUNK_RE.match(name)):
                    pname = PILLAR_NAME[current_pillar]
                    key = (current_pillar, name)
                    if key not in seen:
                        seen.add(key)
                        records.append((current_pillar, pname, name, fiscal_year, src))
                continue

            mb = PROJECT_BULLET_RE.match(stripped)
            if mb and HAS_YEN_RE.search(stripped):
                if NOISE_BODY_RE.search(stripped):
                    continue
                name = clean_jigyou_name(mb.group(1))
                if (4 <= len(name) <= 50
                    and KANJI_RE.search(name)
                    and not JUNK_RE.match(name)):
                    pname = PILLAR_NAME[current_pillar]
                    key = (current_pillar, name)
                    if key not in seen:
                        seen.add(key)
                        records.append((current_pillar, pname, name, fiscal_year, src))

    return records


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS defense_pillar_jigyou (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          pillar_id INTEGER NOT NULL,
          pillar_name TEXT NOT NULL,
          jigyou_name TEXT NOT NULL,
          jigyou_name_norm TEXT NOT NULL,
          fiscal_year INTEGER NOT NULL,
          source_file TEXT NOT NULL,
          UNIQUE(pillar_id, jigyou_name, fiscal_year)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pillar_jigyou_norm ON defense_pillar_jigyou(jigyou_name_norm)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pillar_jigyou_pillar ON defense_pillar_jigyou(pillar_id, fiscal_year)"
    )


def insert_records(conn: sqlite3.Connection, records: Iterable[tuple]) -> None:
    for pid, pname, name, fy, src in records:
        norm = nfkc(name)
        conn.execute(
            "INSERT OR IGNORE INTO defense_pillar_jigyou "
            "(pillar_id, pillar_name, jigyou_name, jigyou_name_norm, fiscal_year, source_file) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, pname, name, norm, fy, src),
        )


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    if not DB_TMP.exists() or DB_TMP.stat().st_size != DB_REAL.stat().st_size:
        shutil.copy2(DB_REAL, DB_TMP)
        print(f"Copied {DB_REAL} -> {DB_TMP}")

    conn = sqlite3.connect(DB_TMP)
    ensure_table(conn)
    conn.execute("DELETE FROM defense_pillar_jigyou")

    print("--- yosan_fy2022.pdf (FY2022 explicit mapping) ---")
    recs = parse_yosan_2022(SEISAKU_DIR / "yosan_fy2022.pdf")
    print(f"  parsed {len(recs)} records")
    insert_records(conn, recs)

    for fy in (2023, 2024, 2025):
        path = SEISAKU_DIR / f"yosan_fy{fy}.pdf"
        print(f"--- {path.name} (FY{fy}) ---")
        recs = parse_yosan_modern(path, fy)
        print(f"  parsed {len(recs)} records")
        insert_records(conn, recs)

    conn.commit()

    print("\n=== Pillar coverage ===")
    cur = conn.execute(
        """
        SELECT pillar_id, pillar_name, fiscal_year, COUNT(*) AS n
        FROM defense_pillar_jigyou
        GROUP BY pillar_id, pillar_name, fiscal_year
        ORDER BY pillar_id, fiscal_year
        """
    )
    for r in cur:
        print(f"  P{r[0]:>2} {r[1][:24]:24s} FY{r[2]}: {r[3]}")

    print(f"\nTotal rows: {conn.execute('SELECT COUNT(*) FROM defense_pillar_jigyou').fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
