"""Load 防衛力整備計画の概要 (plan_outline.pdf) into pillar_mapping_sources.

source_type = 'seibi_keikaku_gaiyou'
Amount unit: 兆円 in PDF -> 億円 stored (* 10000)
fiscal_year: NULL (amounts are 5-year totals FY2023-2027)
"""
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pdfplumber
import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT     = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
DB_REAL  = ROOT / "data" / "db" / "defense_pillar.db"
DB_TMP   = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "defense_pillar_gaiyou.db"
PDF_CACHE = ROOT / "data" / "raw" / "seibi_keikaku" / "plan_outline.pdf"
PDF_URL  = "https://www.mod.go.jp/j/policy/agenda/guideline/plan/pdf/plan_outline.pdf"
SOURCE_TYPE = "seibi_keikaku_gaiyou"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

# Page number (1-based) -> (L1 pillar_id, L1 name, L2 pillar_id or None, L2 name or None)
# Based on PDF inspection:
PAGE_PILLAR_MAP: dict[int, tuple[int, str, int | None, str | None]] = {
    4:  (1, "スタンド・オフ防衛能力",        None, None),
    5:  (2, "統合防空ミサイル防衛能力",      None, None),
    6:  (3, "無人アセット防衛能力",          None, None),
    7:  (4, "領域横断作戦能力",              41,   "宇宙"),
    8:  (4, "領域横断作戦能力",              42,   "サイバー"),
    9:  (4, "領域横断作戦能力",              None, None),   # 電磁波（L2なし）
    10: (4, "領域横断作戦能力",              43,   "車両・艦船・航空機等"),
    11: (6, "機動展開能力・国民保護",        None, None),
    12: (5, "指揮統制・情報関連機能",        None, None),
    13: (7, "持続性・強靱性",               71,   "弾薬・誘導弾"),
    14: (7, "持続性・強靱性",               72,   "装備品等の維持、整備費"),
    15: (7, "持続性・強靱性",               73,   "施設の強靱化"),
    16: (8, "防衛生産基盤強化・研究開発等",  82,   "研究開発"),
    17: (8, "防衛生産基盤強化・研究開発等",  81,   "防衛生産基盤の強化"),
    18: (8, "防衛生産基盤強化・研究開発等",  84,   "教育訓練費・燃料費等"),
}

# 兆円 pattern: 約?[0-9.０-９.]+兆円
TYOKU_RE = re.compile(r"約?\s*([\d０-９.．]+)\s*兆円")
# 億円 pattern (for any that appear)
OKU_RE   = re.compile(r"約?\s*([\d０-９,，]+)\s*億円")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


def to_half(s: str) -> str:
    """Convert fullwidth digits/dots to ASCII."""
    return nfkc(s)


def parse_tyoku_yen(text: str) -> float | None:
    """Sum all 兆円 amounts in the text and return total in 億円."""
    vals = TYOKU_RE.findall(text)
    if not vals:
        # Try 億円 directly
        ovals = OKU_RE.findall(text)
        if ovals:
            total = sum(float(nfkc(v).replace(",", "")) for v in ovals)
            return total
        return None
    total = 0.0
    for v in vals:
        v_norm = nfkc(v).replace(",", "")
        try:
            total += float(v_norm) * 10000  # 兆円 → 億円
        except ValueError:
            pass
    return round(total, 2) if total > 0 else None


def clean_name(raw: str) -> str:
    """Strip amount parentheses and leading bullets from a project name."""
    s = nfkc(raw)
    # Remove leading bullets
    s = re.sub(r"^[・●○▲▶■□→➤]\s*", "", s)
    # Truncate at section markers like " (6)次期戦闘機" (two-column artifact)
    s = re.sub(r"\s+[（(]\d+[）)][^（(（(]*$", "", s)
    # Remove internal amount parentheses e.g. （0.01兆円）
    s = re.sub(r"[（(]\s*(?:約\s*)?[\d０-９.．,，]+\s*(?:兆円|億円)\s*[）)]", "", s)
    # Iteratively remove trailing parenthesised groups that contain amounts
    for _ in range(5):
        new = re.sub(r"\s*[（(][^)）]*(?:兆円|億円)[^)）]*[)）]\s*$", "", s)
        if new == s:
            break
        s = new
    # Remove trailing image/figure labels: e.g. "向上型(" or "SM-3" after space
    s = re.sub(r"\s+\S{2,15}\($", "", s)   # unmatched open paren near end
    # Remove 【再掲】 and similar brackets
    s = re.sub(r"【[^】]*】", "", s)
    return s.strip(" 　・・,，。：:")


def split_multi_bullet(line: str) -> list[str]:
    """Split '・A（X兆円） ・B（Y兆円）' -> ['・A（X兆円）', '・B（Y兆円）']."""
    # Split at interior bullet that follows a space
    parts = re.split(r"(?<=\s)[・●](?=\S)", line)
    if len(parts) > 1:
        # Add bullet back to all but first
        return [parts[0]] + ["・" + p for p in parts[1:]]
    return [line]


def is_valid_name(name: str) -> bool:
    if len(name) < 3 or len(name) > 80:
        return False
    # Must contain kanji or katakana
    if not re.search(r"[一-鿿ァ-ヶ]", name):
        return False
    # Skip obvious non-project lines
    if re.match(r"^(?:主な事業|必要性|整備の方向性|2027年度|概ね|計数精査|参考|区\s*分|分\s*野|合\s*計)", name):
        return False
    return True


def extract_page_projects(text: str, page_num: int) -> list[dict]:
    """Extract ・-prefixed project lines from a pillar page."""
    pillar_info = PAGE_PILLAR_MAP.get(page_num)
    if pillar_info is None:
        return []

    l1_id, l1_name, l2_id, l2_name = pillar_info
    records = []
    lines = text.split("\n")

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Only process lines starting with ・ or containing a project
        if not (stripped.startswith("・") or stripped.startswith("●")):
            continue

        # Handle two-column layouts: "・A（X兆円） ・B（Y兆円）"
        sub_lines = split_multi_bullet(stripped)

        for sub in sub_lines:
            sub = sub.strip()
            if not (sub.startswith("・") or sub.startswith("●")):
                continue
            # Extract amount
            amount = parse_tyoku_yen(sub)
            # Extract name
            name_raw = clean_name(sub)
            if not is_valid_name(name_raw):
                continue
            records.append({
                "pillar_id":         l1_id,
                "pillar_name":       l1_name,
                "legacy_pillar_id":  l2_id,
                "jigyou_name":       name_raw,
                "jigyou_name_norm":  nfkc(name_raw),
                "fiscal_year":       None,
                "amount_hyoku_yen":  amount,
                "source_url":        PDF_URL,
                "source_file":       f"plan_outline.pdf#p{page_num}",
                "raw_context":       sub[:200],
                "confidence":        0.90,
                "notes":             "seibi_keikaku_5year_total",
            })

    return records


def ensure_amount_column(conn: sqlite3.Connection) -> None:
    """Add amount_hyoku_yen column if not present."""
    cur = conn.execute("PRAGMA table_info(pillar_mapping_sources)")
    cols = [r[1] for r in cur.fetchall()]
    if "amount_hyoku_yen" not in cols:
        conn.execute(
            "ALTER TABLE pillar_mapping_sources ADD COLUMN amount_hyoku_yen REAL"
        )
        conn.commit()
        print("  Added column: amount_hyoku_yen REAL")


def insert_records(conn: sqlite3.Connection, records: list[dict]) -> int:
    inserted = 0
    for rec in records:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO pillar_mapping_sources
                   (source_type, fiscal_year, pillar_id, pillar_name,
                    jigyou_name, jigyou_name_norm, legacy_pillar_id,
                    source_url, source_file, raw_context,
                    confidence, notes, amount_hyoku_yen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    SOURCE_TYPE,
                    rec["fiscal_year"],
                    rec["pillar_id"],
                    rec["pillar_name"],
                    rec["jigyou_name"],
                    rec["jigyou_name_norm"],
                    rec["legacy_pillar_id"],
                    rec["source_url"],
                    rec["source_file"],
                    rec["raw_context"],
                    rec["confidence"],
                    rec["notes"],
                    rec["amount_hyoku_yen"],
                ),
            )
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except sqlite3.IntegrityError:
            pass
    return inserted


def download_pdf() -> Path:
    if PDF_CACHE.exists():
        print(f"Using cached PDF: {PDF_CACHE}")
        return PDF_CACHE
    PDF_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {PDF_URL} ...")
    r = requests.get(PDF_URL, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    PDF_CACHE.write_bytes(r.content)
    print(f"  -> {len(r.content) // 1024} KB saved")
    return PDF_CACHE


def main(dry_run: bool = False) -> None:
    pdf_path = download_pdf()

    all_records: list[dict] = []
    print("\n=== Parsing PDF ===")
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"Total pages: {total_pages}")
        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1
            if page_num not in PAGE_PILLAR_MAP:
                continue
            text = page.extract_text() or ""
            recs = extract_page_projects(text, page_num)
            l1_id, l1_name, l2_id, l2_name = PAGE_PILLAR_MAP[page_num]
            sec_label = f"P{l1_id}{'/' + str(l2_id) if l2_id else ''}"
            print(f"  Page {page_num:2d} [{sec_label}] {l2_name or l1_name}: {len(recs)} items")
            for r in recs:
                amt = f"{r['amount_hyoku_yen']:.0f}億" if r["amount_hyoku_yen"] else "—"
                print(f"    {r['jigyou_name'][:50]:50s}  {amt}")
            all_records.extend(recs)

    print(f"\nTotal extracted: {len(all_records)} records")

    if dry_run:
        print("=== DRY RUN: no DB writes ===")
        return

    # Copy DB to tmp
    shutil.copy2(DB_REAL, DB_TMP)
    print(f"\nCopied {DB_REAL.name} -> {DB_TMP}")

    conn = sqlite3.connect(DB_TMP)
    try:
        ensure_amount_column(conn)
        inserted = insert_records(conn, all_records)
        conn.commit()
        print(f"Inserted: {inserted} new rows")

        print("\n=== source_type distribution ===")
        for row in conn.execute(
            "SELECT source_type, COUNT(*) FROM pillar_mapping_sources "
            "GROUP BY source_type ORDER BY COUNT(*) DESC"
        ):
            print(f"  {row[0]}: {row[1]}")

        print("\n=== seibi_keikaku_gaiyou by pillar ===")
        for row in conn.execute(
            "SELECT pillar_id, pillar_name, legacy_pillar_id, COUNT(*), "
            "       ROUND(SUM(COALESCE(amount_hyoku_yen,0))) "
            "FROM pillar_mapping_sources WHERE source_type=? "
            "GROUP BY pillar_id, legacy_pillar_id ORDER BY pillar_id, legacy_pillar_id",
            (SOURCE_TYPE,),
        ):
            print(f"  P{row[0]}/{row[2] or '-'} {row[1]}: {row[3]}件 {row[4]:.0f}億円")
    finally:
        conn.close()

    # Copy back
    shutil.copy2(DB_TMP, DB_REAL)
    print(f"\nCopied back -> {DB_REAL}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN ===")
    main(dry_run=dry)
