"""contract_equipment マッピング生成器

equipment_master の name_ja / keywords をパターン化し、contracts.contract_name
に対して NFKC 正規化＋ファジーマッチを行う。

確信度:
  1.0 : 品目名 (name_ja) が contract_name に含まれる
  0.8 : name_ja は当たらないが、キーワードのいずれかが当たる
  0.6 : equipment_id が cat_* (大カテゴリ) で、キーワードのいずれかが当たる

ASCII のみのキーワード (F-35, DD など) は前境界 (?<![A-Za-z0-9]) を必須にして
"ASSY" 内部の "SS" のような誤マッチを抑止する。

実行: python -m pipeline.match_equipment
オプション:
  --dry-run    DB 書き込みなし
  --report-only  集計レポートのみ出力 (再マッチしない)
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

# NFKC 後に残るダッシュ系を ASCII '-' に統一
_DASH_TRANS = str.maketrans({
    "‐": "-",  # HYPHEN
    "‑": "-",  # NON-BREAKING HYPHEN
    "‒": "-",  # FIGURE DASH
    "–": "-",  # EN DASH
    "—": "-",  # EM DASH
    "―": "-",  # HORIZONTAL BAR
    "−": "-",  # MINUS SIGN
})

# 誤マッチが多すぎるキーワード (実測 0 true-positive / 23 false-positive 等)
KEYWORD_STOPLIST = {"SS"}


def normalize(text: str | None) -> str:
    if not text:
        return ""
    n = unicodedata.normalize("NFKC", str(text))
    return n.translate(_DASH_TRANS)


def _is_ascii_word(s: str) -> bool:
    return bool(s) and s.isascii() and any(c.isalnum() for c in s)


def _build_pattern(keyword: str) -> re.Pattern[str]:
    """ASCII 語は前境界を必須に、それ以外はそのまま substring 検索 (ただし Pattern 化)。"""
    esc = re.escape(keyword)
    if _is_ascii_word(keyword):
        return re.compile(r"(?<![A-Za-z0-9])" + esc)
    return re.compile(esc)


def load_equipment_patterns(con: sqlite3.Connection):
    """Returns list of dicts:
        {equipment_id, name_ja, name_norm, name_pat, kw_pats, is_cat}
    """
    cur = con.cursor()
    cur.execute("SELECT equipment_id, name_ja, keywords FROM equipment_master")
    out = []
    for eid, name_ja, kw_csv in cur.fetchall():
        is_cat = "_cat_" in eid
        name_norm = normalize(name_ja)
        name_pat = _build_pattern(name_norm) if name_norm else None

        raw_kws = [k.strip() for k in (kw_csv or "").split(",") if k.strip()]
        seen = set()
        if name_norm:
            seen.add(name_norm)
        kw_pats: list[tuple[str, re.Pattern[str]]] = []
        for k in raw_kws:
            nk = normalize(k)
            if not nk or nk in seen or nk in KEYWORD_STOPLIST:
                continue
            seen.add(nk)
            kw_pats.append((nk, _build_pattern(nk)))

        out.append({
            "equipment_id": eid,
            "name_ja": name_ja,
            "name_norm": name_norm,
            "name_pat": name_pat,
            "kw_pats": kw_pats,
            "is_cat": is_cat,
        })
    return out


def match_one(text_norm: str, patterns: list[dict]) -> dict[str, float]:
    """Returns {equipment_id: confidence}."""
    if not text_norm:
        return {}
    out: dict[str, float] = {}
    for p in patterns:
        eid = p["equipment_id"]
        if p["is_cat"]:
            # cat_* : name_ja もキーワード扱い、当たれば 0.6
            if p["name_pat"] and p["name_pat"].search(text_norm):
                out[eid] = 0.6
                continue
            for _, pat in p["kw_pats"]:
                if pat.search(text_norm):
                    out[eid] = 0.6
                    break
        else:
            # 具体機種: name_ja=1.0、その他キーワード=0.8
            if p["name_pat"] and p["name_pat"].search(text_norm):
                out[eid] = 1.0
                continue
            for _, pat in p["kw_pats"]:
                if pat.search(text_norm):
                    out[eid] = 0.8
                    break
    return out


def run_matching(con: sqlite3.Connection, dry_run: bool = False) -> dict:
    patterns = load_equipment_patterns(con)
    print(f"[load] equipment patterns: {len(patterns)} (cat_*: "
          f"{sum(1 for p in patterns if p['is_cat'])})")

    cur = con.cursor()
    cur.execute("SELECT id, contract_name FROM contracts")
    rows = cur.fetchall()
    total = len(rows)
    print(f"[scan] contracts: {total:,}")

    inserts: list[tuple[int, str, float]] = []
    matched_contracts = 0
    eq_counts: Counter[str] = Counter()
    conf_counts: Counter[float] = Counter()

    progress_step = max(total // 20, 1)
    for i, (cid, cname) in enumerate(rows):
        norm = normalize(cname)
        m = match_one(norm, patterns)
        if m:
            matched_contracts += 1
            for eid, conf in m.items():
                inserts.append((cid, eid, conf))
                eq_counts[eid] += 1
                conf_counts[conf] += 1
        if (i + 1) % progress_step == 0 or (i + 1) == total:
            pct = (i + 1) * 100.0 / total
            print(f"  [{i + 1:>7,}/{total:,}] {pct:5.1f}%  "
                  f"matched={matched_contracts:,} rows={len(inserts):,}",
                  file=sys.stderr)

    print(f"[result] matched_contracts={matched_contracts:,} "
          f"({matched_contracts * 100.0 / total:.2f}%)  "
          f"insert_rows={len(inserts):,}")

    if not dry_run:
        cur.execute("DELETE FROM contract_equipment")
        cur.executemany(
            "INSERT INTO contract_equipment (contract_id, equipment_id, confidence) VALUES (?,?,?)",
            inserts,
        )
        con.commit()
        print(f"[db] DELETE+INSERT committed ({len(inserts):,} rows)")
    else:
        print("[db] dry-run: 書き込みスキップ")

    return {
        "total_contracts": total,
        "matched_contracts": matched_contracts,
        "insert_rows": len(inserts),
        "eq_counts": dict(eq_counts),
        "conf_counts": dict(conf_counts),
    }


def report_per_equipment(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("""
        SELECT em.equipment_id, em.name_ja, em.branch, em.category,
               COUNT(*)                              AS hits,
               COALESCE(SUM(c.contract_amount),0)/1e8 AS total_oku,
               AVG(ce.confidence)                    AS avg_conf
        FROM contract_equipment ce
        JOIN equipment_master em ON em.equipment_id = ce.equipment_id
        JOIN contracts c        ON c.id            = ce.contract_id
        GROUP BY em.equipment_id
        ORDER BY hits DESC
    """)
    rows = cur.fetchall()
    print("\n=== 機種別マッチ件数 ===")
    print(f"{'equipment_id':<28} {'name_ja':<22} {'branch':<5} {'hits':>7} {'金額(億)':>10} {'avg_conf':>8}")
    print("-" * 90)
    for eid, name, branch, cat, hits, oku, avg in rows:
        nm = (name or "")[:20]
        print(f"{eid:<28} {nm:<22} {branch or '':<5} {hits:>7,} {oku:>10,.1f} {avg:>8.2f}")


def report_match_rate(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM contracts")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT contract_id) FROM contract_equipment")
    matched = cur.fetchone()[0]
    print("\n=== 全体マッチ率 ===")
    print(f"  total contracts : {total:,}")
    print(f"  matched         : {matched:,}  ({matched * 100.0 / total:.2f}%)")
    cur.execute("SELECT COUNT(*) FROM contract_equipment")
    rows = cur.fetchone()[0]
    print(f"  contract_equipment rows: {rows:,}")


def report_confidence_distribution(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("""
        SELECT confidence, COUNT(*) FROM contract_equipment
        GROUP BY confidence ORDER BY confidence DESC
    """)
    print("\n=== 確信度分布 ===")
    for conf, n in cur.fetchall():
        print(f"  {conf:.1f}: {n:>8,} 件")


def report_low_confidence(con: sqlite3.Connection, limit: int = 30) -> None:
    """0.5–0.8 (中位確信度) の代表サンプル top N を、契約金額降順で抜粋。
    Percy 確認フローのベース。"""
    cur = con.cursor()
    cur.execute("""
        SELECT ce.contract_id, ce.equipment_id, ce.confidence,
               em.name_ja, c.contract_name, c.contract_amount, c.fiscal_year, c.agency_id
        FROM contract_equipment ce
        JOIN equipment_master em ON em.equipment_id = ce.equipment_id
        JOIN contracts c        ON c.id            = ce.contract_id
        WHERE ce.confidence >= 0.5 AND ce.confidence < 0.8
        ORDER BY COALESCE(c.contract_amount, 0) DESC, ce.contract_id
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    print(f"\n=== 中位確信度 (0.5-0.8) Top {limit} (Percy 確認用) ===")
    if not rows:
        print("  該当なし")
        return
    for cid, eid, conf, name, cname, amt, fy, aid in rows:
        oku = (amt or 0) / 1e8
        cn = (cname or "")[:60]
        print(f"  cid={cid:<7} conf={conf:.1f} {eid:<24} ({name}) "
              f"FY{fy} {aid:<14} {oku:>8,.1f}億  {cn}")


def main() -> int:
    parser = argparse.ArgumentParser(description="contract_equipment マッピング生成")
    parser.add_argument("--dry-run", action="store_true", help="DB 書き込みなし")
    parser.add_argument("--report-only", action="store_true",
                        help="マッチ実行をスキップして集計レポートのみ表示")
    parser.add_argument("--low-conf-limit", type=int, default=30,
                        help="低確信度サンプル数 (default: 30)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DB が見つからない: {DB_PATH}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB_PATH)
    try:
        if not args.report_only:
            run_matching(con, dry_run=args.dry_run)
            if args.dry_run:
                print("\n(dry-run のため集計レポートはスキップ)")
                return 0
        report_match_rate(con)
        report_confidence_distribution(con)
        report_per_equipment(con)
        report_low_confidence(con, limit=args.low_conf_limit)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
