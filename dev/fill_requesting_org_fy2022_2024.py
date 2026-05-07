"""FY2022–2024 contracts に requesting_org マッピングを構築（旧ロジック）。

⚠️ ATLA中央調達分は 2026-05-08 以降、`recompute_atla_requesting_org.py`
   へ移管された（vendor_majority 廃止・全FY横断 fuzzy・装備品マスター
   branch 推定・FMSヒューリスティック等を導入）。
   詳細は CLAUDE.md の「Phase 7: 要求元判定ロジック改訂」を参照。

このスクリプト本体は非ATLA agency_rule の初期投入や、共通ヘルパー
（normalize_item_name, _resolve_agency, AGENCY_RULES 等）の import 元
として温存。直接実行する場合は、ATLA分は recompute スクリプトで
上書きされることに注意。

前提:
  - choutatsuyotei に FY2022/2023/2024 データ投入済み
    (dev/load_choutatsuyotei_pdf.py --fy 2022 2023 2024)
  - FY2025 は既に 100% マップ済み (serene-jepsen / bold-grothendieck で実施)

ロジック (旧 FY2025 と同じ 5 フェーズ):
  1. agency_rule        : agency_id プレフィックスで確定 (非ATLA, confidence=1.0)
  2. choutatsuyotei_exact: 品名完全一致 (ATLA系, confidence=0.9)
  3. phase_a_collisions : 同品名複数org → 契約月一致 (0.7) / 多数決 (0.5)
  4. phase_b_absent     : 品目表に不在 → subrule (0.7) / fuzzy (0.6) /
                          vendor_majority (0.5) / fallback_atla (0.3)

使い方:
  python dev/fill_requesting_org_fy2022_2024.py --fy 2022 2023 2024
  python dev/fill_requesting_org_fy2022_2024.py --fy 2024 --reset
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

# agency_id プレフィックス → 要求元（非ATLA用）
AGENCY_RULES: list[tuple[str, str]] = [
    ("gsdf_",           "GSDF"),
    ("msdf_",           "MSDF"),
    ("asdf_",           "ASDF"),
    ("rdb_",            "RDB"),
    ("hokubu_kaikei",   "GSDF"),
    ("tohoku_kaikei",   "GSDF"),
    ("ndmc",            "NDMC"),
    ("nda",             "NDA"),
    ("dih",             "DIH"),
    ("js",              "JS"),
    ("naikyoku_kaikei", "NAIKYOKU"),
    ("nids",            "NIDS"),
    ("igo",             "KANSATSU"),
]

# ATLA系サブ機関ルール（agency_subrule）
ATLA_SUB_RULES: dict[str, str] = {
    "atla_riku":       "GSDF",
    "atla_koukuu":     "ASDF",
    "atla_kantei":     "MSDF",
    "atla_chitose":    "ASDF",
    "atla_gifu":       "ASDF",
    "atla_shimokita":  "ATLA",
    "atla_kanbo":      "ATLA",
    "atla_shinsedai":  "ATLA",
    "atla_disti":      "ATLA",
}

_PUNCT_RE = re.compile(r"[\s　，、,．。・／/＿_\-－‐ー（）()「」『』【】［］\[\]]+")


def normalize_item_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = _PUNCT_RE.sub("", s)
    return s.strip().lower()


def _resolve_agency(agency_id: str | None) -> str | None:
    if not agency_id:
        return None
    aid = agency_id.lower()
    if aid == "atla" or aid.startswith("atla_"):
        return None
    for prefix, org in AGENCY_RULES:
        if prefix.endswith("_"):
            if aid.startswith(prefix):
                return org
        else:
            if aid == prefix:
                return org
    return None


# ─── Phase 1: agency_rule ───────────────────────────────────────────────────

def match_agency_rules(con: sqlite3.Connection, fiscal_year: int) -> dict:
    """非ATLA contracts に agency_id ベースで確定マッピング。"""
    cur = con.cursor()
    rows = cur.execute(
        "SELECT id, agency_id FROM contracts WHERE fiscal_year = ?",
        (fiscal_year,),
    ).fetchall()

    inserted = skipped = 0
    with con:
        for cid, aid in rows:
            org = _resolve_agency(aid)
            if not org:
                skipped += 1
                continue
            cur.execute(
                """INSERT OR IGNORE INTO contract_requesting_org
                   (contract_id, requesting_org, match_source, confidence)
                   VALUES (?, ?, 'agency_rule', 1.0)""",
                (cid, org),
            )
            if cur.rowcount == 1:
                inserted += 1

    return {"agency_rule_inserted": inserted, "agency_rule_skipped_atla": skipped}


# ─── Phase 2: choutatsuyotei_exact ──────────────────────────────────────────

def match_atla_exact(con: sqlite3.Connection, fiscal_year: int) -> dict:
    """ATLA系契約を品名の正規化完全一致で choutatsuyotei とリンク。"""
    cur = con.cursor()

    norm_map: dict[str, set[tuple[int, str]]] = {}
    for row in cur.execute(
        "SELECT id, item_name_norm, requesting_org FROM choutatsuyotei WHERE fiscal_year = ?",
        (fiscal_year,),
    ):
        norm_map.setdefault(row[1], set()).add((row[0], row[2]))

    unique_orgs: dict[str, tuple[int, str]] = {}
    for norm, candidates in norm_map.items():
        orgs = {org for _, org in candidates}
        if len(orgs) == 1:
            unique_orgs[norm] = (next(iter(candidates))[0], next(iter(orgs)))

    rows = cur.execute(
        """SELECT id, contract_name FROM contracts
           WHERE fiscal_year = ? AND (agency_id = 'atla' OR agency_id LIKE 'atla\\_%' ESCAPE '\\')""",
        (fiscal_year,),
    ).fetchall()

    inserted = collisions = unmatched = 0
    matched_per_org: dict[str, int] = {}
    with con:
        for cid, cname in rows:
            norm = normalize_item_name(cname)
            if not norm:
                unmatched += 1
                continue
            if norm in unique_orgs:
                chy_id, org = unique_orgs[norm]
                cur.execute(
                    """INSERT OR IGNORE INTO contract_requesting_org
                       (contract_id, requesting_org, match_source, choutatsuyotei_id, confidence)
                       VALUES (?, ?, 'choutatsuyotei_exact', ?, 0.9)""",
                    (cid, org, chy_id),
                )
                if cur.rowcount == 1:
                    inserted += 1
                    matched_per_org[org] = matched_per_org.get(org, 0) + 1
            elif norm in norm_map:
                collisions += 1
            else:
                unmatched += 1

    return {
        "atla_exact_inserted": inserted,
        "atla_exact_collisions": collisions,
        "atla_exact_unmatched": unmatched,
        "atla_total_contracts": len(rows),
        "matched_per_org": matched_per_org,
    }


# ─── Phase 3: collision resolution ──────────────────────────────────────────

def _load_chy_index(con: sqlite3.Connection, fiscal_year: int) -> dict[str, list[tuple]]:
    """item_name_norm → list of (id, requesting_org, contract_month, tantou_office)。"""
    idx: dict[str, list[tuple]] = {}
    for r in con.execute(
        "SELECT id, item_name_norm, requesting_org, contract_month, tantou_office "
        "FROM choutatsuyotei WHERE fiscal_year = ?",
        (fiscal_year,),
    ):
        idx.setdefault(r[1], []).append((r[0], r[2], r[3], r[4]))
    return idx


def _contract_month(contract_date: str | None) -> int | None:
    """contract_date 'YYYYMMDD' or 'YYYY-MM-DD' → 暦月 (1-12)。"""
    if not contract_date or len(contract_date) < 6:
        return None
    s = contract_date.replace("-", "").replace("/", "")
    try:
        return int(s[4:6])
    except ValueError:
        return None


def _resolve_collision(
    candidates: list[tuple], contract_date: str | None
) -> tuple[int | None, str, str, float]:
    cm = _contract_month(contract_date)
    cm_fy = None
    if cm is not None:
        cm_fy = cm if cm >= 4 else cm + 12

    if cm_fy is not None:
        month_match = [c for c in candidates if c[2] is not None and c[2] == cm_fy]
        if not month_match and cm is not None:
            month_match = [c for c in candidates if c[2] is not None and c[2] == cm]
        if month_match:
            orgs = {c[1] for c in month_match}
            if len(orgs) == 1:
                return (month_match[0][0], next(iter(orgs)), "collision_month", 0.7)

    org_counts = Counter(c[1] for c in candidates)
    top_org, _ = org_counts.most_common(1)[0]
    sample_id = next(c[0] for c in candidates if c[1] == top_org)
    return (sample_id, top_org, "collision_majority", 0.5)


def phase_a_collisions(con: sqlite3.Connection, fiscal_year: int) -> dict:
    chy_idx = _load_chy_index(con, fiscal_year)
    cur = con.cursor()

    rows = cur.execute(
        """SELECT c.id, c.contract_name, c.contract_date
           FROM contracts c
           LEFT JOIN contract_requesting_org cro ON cro.contract_id = c.id
           WHERE c.fiscal_year = ? AND cro.contract_id IS NULL""",
        (fiscal_year,),
    ).fetchall()

    inserted_month = inserted_majority = skipped = 0
    with con:
        for cid, cname, cdate in rows:
            n = normalize_item_name(cname)
            cands = chy_idx.get(n, [])
            orgs = {c[1] for c in cands}
            if len(orgs) <= 1:
                skipped += 1
                continue
            chy_id, org, source, conf = _resolve_collision(cands, cdate)
            cur.execute(
                """INSERT OR IGNORE INTO contract_requesting_org
                   (contract_id, requesting_org, match_source, choutatsuyotei_id, confidence)
                   VALUES (?, ?, ?, ?, ?)""",
                (cid, org, source, chy_id, conf),
            )
            if cur.rowcount == 1:
                if source == "collision_month":
                    inserted_month += 1
                else:
                    inserted_majority += 1
    return {
        "phase_a_inserted_month": inserted_month,
        "phase_a_inserted_majority": inserted_majority,
        "phase_a_skipped_not_collision": skipped,
    }


# ─── Phase 4: absent resolution ─────────────────────────────────────────────

def _build_vendor_majority(con: sqlite3.Connection) -> dict[str, str]:
    """全FYの既マップ contracts からベンダー別最多org を返す。"""
    rows = con.execute(
        """SELECT c.vendor_name, cro.requesting_org
           FROM contracts c
           JOIN contract_requesting_org cro ON cro.contract_id = c.id
           WHERE c.vendor_name IS NOT NULL AND TRIM(c.vendor_name) != ''"""
    ).fetchall()
    vendor_counter: dict[str, Counter] = {}
    for v, org in rows:
        vendor_counter.setdefault(v, Counter())[org] += 1
    return {v: cnt.most_common(1)[0][0] for v, cnt in vendor_counter.items()}


def _build_fuzzy_index(chy_idx: dict[str, list[tuple]]) -> list[tuple[str, str]]:
    fuzzy = []
    for n, cands in chy_idx.items():
        orgs = {c[1] for c in cands}
        if len(orgs) == 1 and len(n) >= 4:
            fuzzy.append((n, next(iter(orgs))))
    fuzzy.sort(key=lambda x: -len(x[0]))
    return fuzzy


def phase_b_absent(con: sqlite3.Connection, fiscal_year: int) -> dict:
    chy_idx = _load_chy_index(con, fiscal_year)
    fuzzy_index = _build_fuzzy_index(chy_idx)
    cur = con.cursor()

    # subrule 先付け
    rows = cur.execute(
        """SELECT c.id, c.agency_id
           FROM contracts c
           LEFT JOIN contract_requesting_org cro ON cro.contract_id = c.id
           WHERE c.fiscal_year = ? AND cro.contract_id IS NULL""",
        (fiscal_year,),
    ).fetchall()

    inserted_subrule = 0
    with con:
        for cid, aid in rows:
            org = ATLA_SUB_RULES.get(aid or "")
            if org:
                cur.execute(
                    """INSERT OR IGNORE INTO contract_requesting_org
                       (contract_id, requesting_org, match_source, confidence)
                       VALUES (?, ?, 'agency_subrule', 0.7)""",
                    (cid, org),
                )
                if cur.rowcount == 1:
                    inserted_subrule += 1

    # fuzzy / vendor_majority / fallback
    rows = cur.execute(
        """SELECT c.id, c.contract_name, c.vendor_name
           FROM contracts c
           LEFT JOIN contract_requesting_org cro ON cro.contract_id = c.id
           WHERE c.fiscal_year = ? AND cro.contract_id IS NULL""",
        (fiscal_year,),
    ).fetchall()

    vendor_majority = _build_vendor_majority(con)
    inserted_fuzzy = inserted_vendor = inserted_fallback = 0
    with con:
        for cid, cname, vname in rows:
            n = normalize_item_name(cname)
            chosen_org: str | None = None
            chosen_source: str | None = None
            chosen_conf: float = 0.3

            if n and len(n) >= 4:
                for chy_norm, chy_org in fuzzy_index:
                    if chy_norm in n or n in chy_norm:
                        chosen_org = chy_org
                        chosen_source = "fuzzy"
                        chosen_conf = 0.6
                        break

            if chosen_org is None and vname:
                org = vendor_majority.get(vname.strip())
                if org:
                    chosen_org = org
                    chosen_source = "vendor_majority"
                    chosen_conf = 0.5

            if chosen_org is None:
                chosen_org = "ATLA"
                chosen_source = "fallback_atla"
                chosen_conf = 0.3

            cur.execute(
                """INSERT OR IGNORE INTO contract_requesting_org
                   (contract_id, requesting_org, match_source, confidence)
                   VALUES (?, ?, ?, ?)""",
                (cid, chosen_org, chosen_source, chosen_conf),
            )
            if cur.rowcount == 1:
                if chosen_source == "fuzzy":
                    inserted_fuzzy += 1
                elif chosen_source == "vendor_majority":
                    inserted_vendor += 1
                else:
                    inserted_fallback += 1

    return {
        "phase_b_inserted_subrule": inserted_subrule,
        "phase_b_inserted_fuzzy": inserted_fuzzy,
        "phase_b_inserted_vendor_majority": inserted_vendor,
        "phase_b_inserted_fallback_atla": inserted_fallback,
    }


# ─── Reporting ───────────────────────────────────────────────────────────────

def report(con: sqlite3.Connection, fiscal_year: int) -> dict:
    cur = con.cursor()
    total = cur.execute(
        "SELECT COUNT(*) FROM contracts WHERE fiscal_year = ?", (fiscal_year,)
    ).fetchone()[0]
    mapped = cur.execute(
        """SELECT COUNT(DISTINCT cro.contract_id)
           FROM contract_requesting_org cro
           JOIN contracts c ON c.id = cro.contract_id
           WHERE c.fiscal_year = ?""",
        (fiscal_year,),
    ).fetchone()[0]
    by_source = dict(cur.execute(
        """SELECT cro.match_source, COUNT(*)
           FROM contract_requesting_org cro
           JOIN contracts c ON c.id = cro.contract_id
           WHERE c.fiscal_year = ?
           GROUP BY cro.match_source ORDER BY 2 DESC""",
        (fiscal_year,),
    ).fetchall())
    by_org = dict(cur.execute(
        """SELECT cro.requesting_org, COUNT(DISTINCT cro.contract_id)
           FROM contract_requesting_org cro
           JOIN contracts c ON c.id = cro.contract_id
           WHERE c.fiscal_year = ?
           GROUP BY cro.requesting_org ORDER BY 2 DESC""",
        (fiscal_year,),
    ).fetchall())
    return {
        "total": total, "mapped": mapped, "gap": total - mapped,
        "pct": f"{100 * mapped / total:.1f}%" if total else "n/a",
        "by_source": by_source, "by_org": by_org,
    }


# ─── Main ────────────────────────────────────────────────────────────────────

def run_fy(con: sqlite3.Connection, fiscal_year: int, reset: bool = False) -> None:
    cur = con.cursor()
    if reset:
        cur.execute(
            """DELETE FROM contract_requesting_org
               WHERE contract_id IN (SELECT id FROM contracts WHERE fiscal_year = ?)""",
            (fiscal_year,),
        )
        con.commit()
        print(f"[reset] FY{fiscal_year} mappings deleted")

    before = report(con, fiscal_year)
    print(f"\n=== FY{fiscal_year} (before) total={before['total']} "
          f"mapped={before['mapped']} gap={before['gap']}")

    s1 = match_agency_rules(con, fiscal_year)
    print(f"  [1] agency_rule     inserted={s1['agency_rule_inserted']:>6}  "
          f"skipped_atla={s1['agency_rule_skipped_atla']}")

    s2 = match_atla_exact(con, fiscal_year)
    print(f"  [2] chy_exact       inserted={s2['atla_exact_inserted']:>6}  "
          f"collisions={s2['atla_exact_collisions']}  unmatched={s2['atla_exact_unmatched']}")
    if s2["matched_per_org"]:
        for org, cnt in sorted(s2["matched_per_org"].items(), key=lambda x: -x[1]):
            print(f"       {org:<10} {cnt}")

    s3 = phase_a_collisions(con, fiscal_year)
    print(f"  [3] collision       month={s3['phase_a_inserted_month']:>6}  "
          f"majority={s3['phase_a_inserted_majority']}")

    s4 = phase_b_absent(con, fiscal_year)
    print(f"  [4] absent          subrule={s4['phase_b_inserted_subrule']:>6}  "
          f"fuzzy={s4['phase_b_inserted_fuzzy']}  "
          f"vendor={s4['phase_b_inserted_vendor_majority']}  "
          f"fallback={s4['phase_b_inserted_fallback_atla']}")

    after = report(con, fiscal_year)
    print(f"  === FY{fiscal_year} (after)  mapped={after['mapped']}/{after['total']} "
          f"({after['pct']}) gap={after['gap']}")
    print(f"  by_org: {after['by_org']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fy", nargs="+", type=int, default=[2022, 2023, 2024],
                   choices=[2022, 2023, 2024])
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--reset", action="store_true",
                   help="指定FYの既存マッピングを削除してから再実行")
    args = p.parse_args()

    con = sqlite3.connect(args.db)
    try:
        for fy in sorted(set(args.fy)):
            run_fy(con, fy, reset=args.reset)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
