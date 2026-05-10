"""Load bukai PDF project names and hakusho HTML into pillar_mapping_sources.

Sources:
  A. Bukai PDFs in data/raw/drastic/*.pdf
     Two page formats handled:
       fmt1: "○ [name] (XX億円)" on same line (bukai_siryo03_01 style)
       fmt2: "[name](XX億円)" standalone line, ○ on separate line (bukai_siryo04_02 style)
  B. 防衛白書 HTML (FY2022-2025)
     Tries http:// fallback when https fails
"""
import io
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pdfplumber
import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
DRASTIC_DIR = ROOT / "data" / "raw" / "drastic"
DB_REAL = ROOT / "data" / "db" / "defense_pillar.db"
DB_TMP  = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "defense_pillar_sources.db"
MANIFEST_PATH = DRASTIC_DIR / "manifest.json"
BUKAI_BASE_URL = "https://www.mod.go.jp/j/policy/agenda/meeting/drastic-reinforcement/pdf/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

# ── Pillar name -> (pillar_id, canonical_name) ───────────────────────────
PILLAR_MAP = {
    "スタンド・オフ防衛能力":    (1, "スタンド・オフ防衛能力"),
    "スタンドオフ防衛能力":      (1, "スタンド・オフ防衛能力"),
    "統合防空ミサイル防衛能力":  (2, "統合防空ミサイル防衛能力"),
    "無人アセット防衛能力":      (3, "無人アセット防衛能力"),
    "領域横断作戦能力":          (4, "領域横断作戦能力"),
    "指揮統制・情報関連機能":    (5, "指揮統制・情報関連機能"),
    "指揮統制情報関連機能":      (5, "指揮統制・情報関連機能"),
    "機動展開能力・国民保護":    (6, "機動展開能力・国民保護"),
    "機動展開能力":              (6, "機動展開能力・国民保護"),
    "持続性・強靱性":            (7, "持続性・強靱性"),
    "持続性強靱性":              (7, "持続性・強靱性"),
    "弾薬の確保":                (71, "弾薬・誘導弾"),
    "弾薬・誘導弾の確保":        (71, "弾薬・誘導弾"),
    "弾薬確保":                  (71, "弾薬・誘導弾"),
    "装備品の維持整備":          (72, "装備品等の維持、整備費"),
    "施設の強靱化":              (73, "施設の強靱化"),
}

# ----- Regex patterns -------------------------------------------------------
# Pattern A: "主な事業：[pillar]" or "主な事業（[pillar]）"  (pillar after 主な事業)
MAIN_JIGYOU_AFTER_RE = re.compile(
    r"主な事業[：:：：]\s*([^\n（(（(]{4,30})",
    re.MULTILINE
)
# Pattern B: "[pillar]（令和X年度予算における主な事業）"  (pillar before 主な事業)
MAIN_JIGYOU_BEFORE_RE = re.compile(
    r"^([^\s（(【]{3,20})(?:（令和\d+年度予算(?:案)?(?:における)?主な事業|【令和\d+年度)",
    re.MULTILINE
)
# Pattern C: standalone pillar header line
PILLAR_ALONE_RE = re.compile(
    r"(?:^|\n)\s*(?:\d[\s.、]*)?"
    r"(スタンド[・]?オフ防衛能力|統合防空ミサイル防衛能力|無人アセット防衛能力"
    r"|領域横断作戦能力|指揮統制[・\s]?情報関連機能|機動展開能力[・\s]?国民保護"
    r"|持続性[・\s]?強靱性|弾薬の確保|弾薬・誘導弾|施設の強靱化|装備品の維持整備)"
    r"\s*(?:$|\n)",
)
# Yen amount detector
YEN_RE = re.compile(r"[（(（(]\s*([\d０-９,，]+)\s*億円\s*[）)）)]")
# FY detector (令和X年度)
REIWA_RE = re.compile(r"令和(\d+)年度")
REIWA_MAP = {r: 2018 + r for r in range(1, 12)}
KANJI_RE = re.compile(r"[一-鿿]")
# Noise filter: skip lines starting with these
NOISE_RE = re.compile(
    r"^(?:こ[れの]|そ[れの]|また|さらに|ただし|なお|概ね|参照|令和|平成"
    r"|これら|これ|なお|国家防衛|防衛力を|以下|今後|これまで|新たな|等の|上記)"
)
# Lines that are definitely section sub-headers, not project names
SECTION_HDR_RE = re.compile(
    r"^(?:○の強化|指揮統制機能|情報収集|防衛駐在|宇宙システム|サイバー防衛|"
    r"電磁波領域|海・空・陸|体制・態勢|弾薬の確保の取組|施設の強靱化の取組"
    r"|維持整備能力|将来構想|課題認識|主要な弾薬|参考)"
)


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


def detect_pillar_from_text(text: str) -> tuple[int, str] | None:
    """Return (pillar_id, pillar_name) if found in page text."""
    # Try pattern A: pillar after 主な事業
    for m in MAIN_JIGYOU_AFTER_RE.finditer(text):
        label = nfkc(m.group(1).strip())
        for key, val in PILLAR_MAP.items():
            if key in label or label in key:
                return val
    # Try pattern B: pillar before 主な事業
    for m in MAIN_JIGYOU_BEFORE_RE.finditer(text):
        label = nfkc(m.group(1).strip())
        for key, val in PILLAR_MAP.items():
            if key in label or label in key:
                return val
    # Try pattern C: standalone pillar name line
    m3 = PILLAR_ALONE_RE.search(text)
    if m3:
        label = nfkc(m3.group(1))
        for key, val in PILLAR_MAP.items():
            if key in label or label in key:
                return val
    return None


def extract_fy_from_page(text: str) -> int | None:
    matches = [int(x) for x in REIWA_RE.findall(text)]
    if not matches:
        return None
    cnt = Counter(matches)
    reiwa = cnt.most_common(1)[0][0]
    return REIWA_MAP.get(reiwa)


def clean_name(raw: str) -> str:
    s = nfkc(raw)
    # Remove 【再掲】
    s = re.sub(r"【再掲】", "", s)
    # Remove ALL trailing parenthesized groups
    while True:
        new = re.sub(r"\s*[（(][^)）]*[)）]\s*$", "", s)
        if new == s:
            break
        s = new
    s = s.strip(" 　・,，。")
    return s


def extract_projects_from_page(text: str) -> list[tuple[str, str]]:
    """Return [(jigyou_name, raw_context), ...] from page.

    Two formats:
    fmt1: "○ [name] (XX億円)" on same line
    fmt2: "[name](XX億円)" standalone line, ○ on separate line
    """
    results = []
    lines = text.split("\n")
    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        # ── fmt1: ○-prefixed line with yen ──────────────────────────────
        if (line.startswith("○") or line.startswith("●")) and YEN_RE.search(line):
            # name is everything between bullet and first yen paren
            m = re.match(r"^[○●]\s*(.+?)(?=[（(（(]\s*[\d０-９,，]+\s*億円)", line)
            if m:
                name = clean_name(m.group(1))
                if _is_valid_name(name):
                    results.append((name, line[:150]))
            continue

        # ── fmt2: standalone line "name(XX億円)" without ○ prefix ────────
        if YEN_RE.search(line) and not (line.startswith("○") or line.startswith("●")):
            # Must not look like a summary/total line
            if re.search(r"^(?:合計|総計|小計|約|Ｒ\d|R\d|令和|平成|\d+年度|　　　)", line):
                continue
            if re.search(r"他分野を除くと|約[\d０-９,，]+億円$", line):
                continue
            # Extract name = everything before the LAST yen parenthesis
            m = re.search(r"^(.+?)(?=[（(（(]\s*[\d０-９,，]+\s*億円)", line)
            if m:
                name = clean_name(m.group(1))
                # Check if previous or next line has ○ (confirms this is a project line)
                prev = lines[i-1].strip() if i > 0 else ""
                nxt  = lines[i+1].strip() if i < len(lines)-1 else ""
                has_bullet = prev in ("○", "●") or nxt in ("○", "●")
                # Also accept if it looks like a project name with yen
                if _is_valid_name(name) and (has_bullet or len(name) >= 4):
                    results.append((name, line[:150]))

    return results


def _is_valid_name(name: str) -> bool:
    if len(name) < 3 or len(name) > 60:
        return False
    if not KANJI_RE.search(name):
        return False
    if NOISE_RE.match(name):
        return False
    if SECTION_HDR_RE.match(name):
        return False
    return True


# ── Bukai PDF parser ────────────────────────────────────────────────────────
def parse_bukai_pdf(pdf_path: Path, source_url: str) -> list[dict]:
    records = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            current_pillar: tuple[int, str] | None = None
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if not text.strip():
                    continue
                p = detect_pillar_from_text(text)
                if p:
                    current_pillar = p
                if current_pillar is None:
                    continue
                fy = extract_fy_from_page(text)
                for name, ctx in extract_projects_from_page(text):
                    records.append({
                        "pillar_id":   current_pillar[0],
                        "pillar_name": current_pillar[1],
                        "jigyou_name": name,
                        "fiscal_year": fy,
                        "source_url":  source_url,
                        "source_file": f"{pdf_path.name}#p{page_idx+1}",
                        "raw_context": ctx,
                        "confidence":  0.85,
                        "notes":       "bukai_yen_parse",
                    })
    except Exception as e:
        print(f"  ERROR parsing {pdf_path.name}: {e}")
    return records


# ── Download missing PDFs from manifest and index ───────────────────────────
def sync_pdfs(dry_run: bool) -> None:
    if not MANIFEST_PATH.exists():
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest:
        fname = entry.get("file", "")
        url   = entry.get("url", "")
        local = DRASTIC_DIR / fname
        if not fname or local.exists():
            continue
        print(f"  Downloading: {fname}")
        if dry_run:
            continue
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
            if r.status_code == 200:
                local.write_bytes(r.content)
                print(f"    -> {len(r.content)//1024}KB")
        except Exception as e:
            print(f"    -> ERROR: {e}")

    # Also check live index for NEW PDFs not in manifest
    known_files = {e.get("file", "") for e in manifest}
    try:
        r = requests.get(
            "https://www.mod.go.jp/j/policy/agenda/meeting/drastic-reinforcement/",
            headers={"User-Agent": UA}, timeout=30
        )
        all_links = re.findall(r'href="(?:pdf/)?([^"]+\.pdf)"', r.text, re.IGNORECASE)
        for link in dict.fromkeys(all_links):
            fname = Path(link).name
            if fname in known_files or fname.endswith("_en.pdf"):
                continue
            local = DRASTIC_DIR / fname
            if local.exists():
                continue
            url = BUKAI_BASE_URL + fname
            print(f"  New PDF from index: {fname}")
            if dry_run:
                continue
            try:
                r2 = requests.get(url, headers={"User-Agent": UA}, timeout=120)
                if r2.status_code == 200:
                    local.write_bytes(r2.content)
                    print(f"    -> {len(r2.content)//1024}KB")
            except Exception as e:
                print(f"    -> ERROR: {e}")
    except Exception as e:
        print(f"  Index check failed: {e}")


# ── Hakusho HTML ─────────────────────────────────────────────────────────────
# Equipment names to extract from section narrative text.
# Format: (regex_pattern, pillar_id, canonical_name)
# Only items not already captured via yosan PDFs or bukai PDFs.
_NARRATIVE_KEYWORDS: list[tuple[str, int, str]] = [
    (r"目標観測弾", 1, "目標観測弾"),
    (r"新型レーダー[（(（(]LTAMDS[）)）)]", 2, "新型レーダー（LTAMDS）"),
    (r"揚陸支援システム", 6, "揚陸支援システム（研究）"),
    (r"輸送車両[（(（(]コンテナトレーラー[）)）)]", 6, "輸送車両（コンテナトレーラー）"),
    (r"荷役器材[（(（(][^）)）)]+[）)）)]", 6, "荷役器材（大型クレーン・フォークリフト等）"),
    (r"指向性エネルギー", 4, "指向性エネルギー兵器（小型UAV対処）"),
]
_SECTION_HEADS = [
    (1, "スタンド・オフ防衛能力"),
    (2, "統合防空ミサイル防衛能力"),
    (3, "無人アセット防衛能力"),
    (4, "領域横断作戦能力"),
    (5, "指揮統制・情報関連機能"),
    (6, "機動展開能力・国民保護"),
    (7, "持続性・強靱性"),
]


def fetch_hakusho(fy: int) -> tuple[bytes | None, str | None]:
    """Returns (content_bytes, source_url) or (None, None)."""
    # User-specified fixed filename: n240103000.html in each year folder.
    # FY2023 confirmed accessible; other years return 404 (different URL scheme).
    urls = [
        f"https://www.clearing.mod.go.jp/hakusho_data/{fy}/html/n240103000.html",
        f"http://www.clearing.mod.go.jp/hakusho_data/{fy}/html/n240103000.html",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                print(f"  FY{fy}: OK {url}")
                return r.content, url
            else:
                print(f"  FY{fy}: HTTP {r.status_code} {url}")
        except Exception as e:
            print(f"  FY{fy}: {type(e).__name__} {url}")
    print(f"  FY{fy}: unreachable")
    return None, None


def parse_hakusho_html(html_bytes: bytes, fy: int, source_url: str) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  bs4 not available")
        return []
    for enc in ("utf-8", "shift_jis", "euc-jp"):
        try:
            text = html_bytes.decode(enc, errors="strict")
            break
        except UnicodeDecodeError:
            pass
    else:
        text = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    full = soup.get_text(separator="\n")
    records = []

    # --- Pass 1: bullet-point format (○●◎▶ prefix) ---
    current_pillar: tuple[int, str] | None = None
    for line in full.split("\n"):
        line = line.strip()
        if not line:
            continue
        for key, val in PILLAR_MAP.items():
            if key in line:
                current_pillar = val
                break
        if current_pillar is None:
            continue
        m = re.match(r"^[○●◎▶▸➤■□・]\s*(.+)", line)
        if not m:
            continue
        name = clean_name(m.group(1))
        if not _is_valid_name(name):
            continue
        records.append({
            "pillar_id": current_pillar[0], "pillar_name": current_pillar[1],
            "jigyou_name": name, "fiscal_year": fy,
            "source_url": source_url, "source_file": None,
            "raw_context": line[:150], "confidence": 0.9,
            "notes": "hakusho_bullet",
        })

    # --- Pass 2: narrative section format (n240103000.html style) ---
    # Split text into per-pillar sections and extract named programs
    section_texts: dict[int, str] = {}
    for i, (pid, pname) in enumerate(_SECTION_HEADS):
        start = full.find(pname)
        if start < 0:
            continue
        end = len(full)
        for j in range(i + 1, len(_SECTION_HEADS)):
            nxt = full.find(_SECTION_HEADS[j][1])
            if nxt > start:
                end = nxt
                break
        section_texts[pid] = full[start:end]

    if section_texts:
        seen_names = {nfkc(r["jigyou_name"]) for r in records}
        for pat, pid, canonical in _NARRATIVE_KEYWORDS:
            # Find the section this keyword belongs to
            target_pid = pid
            sec = section_texts.get(target_pid, "")
            if not sec:
                # Also search entire text
                sec = full
            m = re.search(pat, sec)
            if not m:
                continue
            norm = nfkc(canonical)
            if norm in seen_names:
                continue
            seen_names.add(norm)
            # Get pillar name from _SECTION_HEADS
            pname = next((n for p, n in _SECTION_HEADS if p == pid), str(pid))
            records.append({
                "pillar_id": pid, "pillar_name": pname,
                "jigyou_name": canonical, "fiscal_year": fy,
                "source_url": source_url, "source_file": None,
                "raw_context": m.group(0)[:150], "confidence": 0.75,
                "notes": "hakusho_narrative",
            })

    return records


# ── DB insertion ────────────────────────────────────────────────────────────
def insert_sources(conn: sqlite3.Connection, records: list[dict], source_type: str) -> int:
    inserted = 0
    for rec in records:
        norm = nfkc(rec["jigyou_name"])
        try:
            conn.execute(
                """INSERT OR IGNORE INTO pillar_mapping_sources
                   (source_type, fiscal_year, pillar_id, pillar_name,
                    jigyou_name, jigyou_name_norm, source_url, source_file,
                    raw_context, confidence, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (source_type, rec.get("fiscal_year"), rec["pillar_id"],
                 rec["pillar_name"], rec["jigyou_name"], norm,
                 rec.get("source_url"), rec.get("source_file"),
                 rec.get("raw_context"), rec.get("confidence", 0.8),
                 rec.get("notes"))
            )
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except sqlite3.IntegrityError:
            pass
    return inserted


# ── Main ────────────────────────────────────────────────────────────────────
def main(dry_run: bool = False):
    if not dry_run:
        shutil.copy2(DB_REAL, DB_TMP)
        print(f"Copied {DB_REAL.name} -> {DB_TMP.name}")
        conn = sqlite3.connect(DB_TMP)
    else:
        conn = sqlite3.connect(DB_REAL)

    print("\n=== A: Bukai PDFs ===")
    sync_pdfs(dry_run)

    pdf_files = sorted(DRASTIC_DIR.glob("*.pdf"))
    print(f"Found {len(pdf_files)} local PDFs")

    url_map: dict[str, str] = {}
    if MANIFEST_PATH.exists():
        for e in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")):
            url_map[e.get("file", "")] = e.get("url", "")

    total_bukai = 0
    for pdf_path in pdf_files:
        url = url_map.get(pdf_path.name, BUKAI_BASE_URL + pdf_path.name)
        recs = parse_bukai_pdf(pdf_path, url)
        if recs:
            print(f"  {pdf_path.name}: {len(recs)} items")
            for r in recs[:3]:
                print(f"    P{r['pillar_id']} FY{r.get('fiscal_year')} {r['jigyou_name']!r}")
            if not dry_run:
                n = insert_sources(conn, recs, "bukai")
                total_bukai += n
                print(f"    -> {n} new")

    if not dry_run:
        conn.commit()
        print(f"\nTotal bukai new: {total_bukai}")

    print("\n=== B: Hakusho HTML ===")
    total_hak = 0
    for fy in (2022, 2023, 2024, 2025):
        data, src_url = fetch_hakusho(fy)
        if data:
            recs = parse_hakusho_html(data, fy, src_url)
            print(f"  FY{fy}: {len(recs)} records parsed")
            if not dry_run and recs:
                n = insert_sources(conn, recs, "hakusho")
                total_hak += n
                print(f"  -> {n} new")
        else:
            print(f"  FY{fy}: unreachable")

    if not dry_run:
        conn.commit()
        print(f"\nTotal hakusho new: {total_hak}")

    print("\n=== Source distribution ===")
    for row in conn.execute(
        "SELECT source_type, COUNT(*) FROM pillar_mapping_sources "
        "GROUP BY source_type ORDER BY source_type"
    ):
        print(f"  {row[0]}: {row[1]}")

    conn.close()
    if not dry_run:
        shutil.copy2(DB_TMP, DB_REAL)
        print(f"\nCopied back -> {DB_REAL.name}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN ===")
    main(dry_run=dry)
