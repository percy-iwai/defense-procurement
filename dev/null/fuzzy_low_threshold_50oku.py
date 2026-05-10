"""Low-threshold fuzzy matching for fallback_atla >= 50億円 contracts.

Approach:
  1) Load choutatsuyotei (49k entries) and build per-norm org distribution.
  2) For each target contract, compute character-bigram Jaccard similarity against
     every choutatsuyotei entry. Take top-k.
  3) Aggregate per-org evidence with similarity-weighted votes.
  4) Report candidates with margin and FY-delta for human review.

This is a recommender, NOT an auto-applier. We log everything; downstream code
applies overrides only when both (a) margin is clear and (b) the answer makes
domain sense given vendor/keywords.
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
sys.path.insert(0, str(PROJECT_ROOT / "dev"))
from fill_requesting_org_fy2022_2024 import normalize_item_name  # noqa: E402


def bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Targets
    targets = [
        dict(r)
        for r in con.execute(
            """SELECT c.id, c.fiscal_year, c.contract_name, c.vendor_name,
                      c.contract_amount, c.contract_date
               FROM contracts c
               JOIN contract_requesting_org r ON c.id = r.contract_id
               WHERE r.match_source = 'fallback_atla'
                 AND c.contract_amount >= 5000000000
               ORDER BY c.contract_amount DESC"""
        ).fetchall()
    ]
    print(f"Targets: {len(targets)}")

    # Load all choutatsuyotei
    chy_rows = con.execute(
        "SELECT id, fiscal_year, requesting_org, item_name, item_name_norm "
        "FROM choutatsuyotei"
    ).fetchall()
    print(f"choutatsuyotei rows: {len(chy_rows):,}")

    # Pre-compute bigrams per chy entry
    chy_bigrams = []
    for r in chy_rows:
        norm = r["item_name_norm"] or ""
        if len(norm) < 3:
            continue
        chy_bigrams.append((r["id"], r["fiscal_year"], r["requesting_org"],
                            r["item_name"], norm, bigrams(norm)))
    print(f"chy with norm>=3: {len(chy_bigrams):,}")

    out: list[dict] = []
    for t in targets:
        tnorm = normalize_item_name(t["contract_name"])
        tb = bigrams(tnorm)
        scored: list[tuple[float, int, int, str, str, str]] = []
        for chy_id, fy, org, item, norm, b in chy_bigrams:
            j = jaccard(tb, b)
            if j >= 0.20:
                scored.append((j, chy_id, fy, org, item, norm))
        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[:10]

        # Aggregate per-org weighted votes (top-k only)
        weighted = defaultdict(float)
        for j, _id, _fy, org, _it, _nm in top:
            weighted[org] += j
        # Normalize
        total_w = sum(weighted.values()) or 1.0
        ranked = sorted(
            ((o, w / total_w, w) for o, w in weighted.items()),
            key=lambda x: -x[1],
        )

        out.append({
            "contract_id": t["id"],
            "fy": t["fiscal_year"],
            "amount": t["contract_amount"],
            "name": t["contract_name"],
            "vendor": t["vendor_name"],
            "norm": tnorm,
            "top_candidates": [
                {
                    "score": round(j, 3),
                    "chy_id": cid,
                    "fy": fy,
                    "org": org,
                    "item": item,
                }
                for j, cid, fy, org, item, _ in top
            ],
            "org_ranking": [
                {"org": o, "share": round(s, 3), "weight": round(w, 3)}
                for o, s, w in ranked
            ],
        })

    out_path = PROJECT_ROOT / "dev" / "null" / "fuzzy_low_threshold_50oku.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {out_path}")

    # Print readable summary
    print("\n=== SUMMARY ===")
    for o in out:
        print(f"\n#{o['contract_id']:>6}  FY{o['fy']}  {o['amount']:>14,}円")
        print(f"   契約名: {o['name'][:80]}")
        print(f"   業者:   {o['vendor']}")
        if not o["org_ranking"]:
            print("   → no candidates above threshold (J>=0.30)")
            continue
        print(f"   top-org rank: " + ", ".join(
            f"{r['org']}({r['share']:.2f})" for r in o["org_ranking"]
        ))
        for c in o["top_candidates"][:5]:
            print(f"   J={c['score']:.2f} chy#{c['chy_id']} FY{c['fy']} "
                  f"{c['org']}: {c['item'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
