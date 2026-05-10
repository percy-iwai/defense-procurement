"""fallback_atla の50億円以上案件に対する解決マッピングを適用する。

対象は事前調査済の17件中、明確な根拠が得られた12件のみ。
残り5件はATLA研究開発として fallback のまま残す（log として記録）。

根拠:
  - fuzzy_lowthreshold (7件): bigram Jaccard >= 0.50 の choutatsuyotei 単一org一致
  - mod_search (5件): mod.go.jp / Web 検索で軍種が確認できた案件
    - PW4062 = KC-46A engine = ASDF（mod.go.jp/asdf/equipment/kc-46a.html 確認）
    - CF6-80C2K1F = KC-767 engine = ASDF（fuzzy 0.71 同一型番搭載用 ASDF）
    - ACI マルチレベルセキュリティ = 「空自クラウド」要件（NJSS 入札詳細）
    - J/ASN-12 EGI = F-15能力向上用 EGI（chy#38912 ASDF FY2024）

実行:
  python dev/apply_fallback_50oku.py --dry-run
  python dev/apply_fallback_50oku.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCUREMENT_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"
LOG_DIR = PROJECT_ROOT / "logs"
TMP_DB = Path("C:/tmp/procurement_fallback50_work.db")

# ─── 適用マッピング ──────────────────────────────────────────────────────────
# (contract_id, new_org, conf, match_source, evidence)
APPLY: list[tuple[int, str, float, str, str]] = [
    # ── fuzzy_lowthreshold (J>=0.50 or single-org top with consistent pattern)
    (14572,  "ATLA", 0.70, "fuzzy_lowthreshold",
     "J=0.75 chy#24399 FY2026 ATLA 「ＧＰＩの共同開発（その２）」"),
    (17609,  "JS",   0.65, "fuzzy_lowthreshold",
     "J=0.56 chy#24624 FY2026 JS 「民間船舶の運航・管理事業（コンテナ船）」"),
    (15744,  "ASDF", 0.70, "fuzzy_lowthreshold",
     "J=0.71 chy ASDF 「ＣＦ６－８０Ｃ２Ｋ１Ｆ推進システム（搭載用）」 FY2015-2019複数"),
    (6774,   "ATLA", 0.75, "fuzzy_lowthreshold",
     "J=0.80 chy#39338 FY2024 ATLA 「ＦＴＢ化試改修（その２）」"),
    (23531,  "ATLA", 0.70, "fuzzy_lowthreshold",
     "J=0.71 chy#1510 FY2025 ATLA 「次世代防衛技術実証衛星の製造（その１）」"),
    (7956,   "ATLA", 0.80, "fuzzy_lowthreshold",
     "J=0.84 chy#32087 FY2023 ATLA 「研究開発支援システムの機器借上（０５換装）」"),
    (418587, "ATLA", 0.55, "fuzzy_lowthreshold",
     "top-5 全候補ATLA 「研究試作」シリーズ（chy#1476 FY2025 等）"),

    # ── mod_search: mod.go.jp / NJSS / chy 補助情報で軍種が確認できた案件
    (23133, "ASDF", 0.70, "mod_search",
     "PW4062 = KC-46A pengine; KC-46A = 航空自衛隊 (mod.go.jp/asdf/equipment/kc-46a.html)"),
    (17889, "ASDF", 0.70, "mod_search",
     "PW4062 = KC-46A engine; KC-46A = 航空自衛隊"),
    (17885, "ASDF", 0.70, "mod_search",
     "PW4062 = KC-46A engine; KC-46A = 航空自衛隊"),
    (10063, "ASDF", 0.65, "mod_search",
     "ACI マルチレベルセキュリティ 入札要件「空自クラウドの機能・構成等に関する専門的知識」(NJSS)"),
    (17120, "ASDF", 0.75, "mod_search",
     "Ｊ／ＡＳＮ－１２ EGI: chy#38912 FY2024 ASDF「Ｆ－１５能力向上用ＥＧＩ」と同シリーズ"),
]

# 解決を見送る5件（fallback_atla のまま残す）— ログ用
NOT_APPLIED: list[tuple[int, str]] = [
    (8736,  "アッパーステージ能力向上に関する研究 — startup R&D, 軍種要求元なし → ATLA fallback 維持"),
    (5438,  "即応型マルチミッション実証衛星 — 防衛省全体R&D, J=0.21 弱マッチ → ATLA fallback 維持"),
    (16182, "機動対応宇宙システム実証機の試作 — SDA研究, 単一軍種要求元なし → ATLA fallback 維持"),
    (8620,  "宇宙領域...衛星の試作（QPS） — chy#31749 NAIKYOKU は J=0.33 で弱、適用見送り"),
    (17605, "製造工程効率化に係る特定取組 — ATLA「特定取組」費用低減プログラム → ATLA fallback 正"),
]


def run(dry_run: bool = False) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"procurement_pre_fallback50_{ts}.db"
        shutil.copy2(PROCUREMENT_DB, backup_path)
        TMP_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROCUREMENT_DB, TMP_DB)
        work_db = TMP_DB
        print(f"backup: {backup_path}")
        print(f"work:   {work_db}")
    else:
        backup_path = None
        work_db = PROCUREMENT_DB

    con = sqlite3.connect(work_db)
    cur = con.cursor()

    # Pre-state
    cur.execute(
        "SELECT requesting_org, match_source FROM contract_requesting_org "
        "WHERE contract_id = ?",
        (APPLY[0][0],),
    )
    print(f"sample pre-state #{APPLY[0][0]}: {cur.fetchone()}")

    # Verify all targets are currently fallback_atla
    target_ids = [c[0] for c in APPLY]
    placeholders = ",".join("?" * len(target_ids))
    rows = cur.execute(
        f"SELECT contract_id, requesting_org, match_source "
        f"FROM contract_requesting_org WHERE contract_id IN ({placeholders})",
        target_ids,
    ).fetchall()
    actual = {r[0]: (r[1], r[2]) for r in rows}

    drift = []
    for cid, _new_org, _conf, _src, _ev in APPLY:
        if cid not in actual:
            drift.append((cid, "missing"))
            continue
        org, src = actual[cid]
        if src != "fallback_atla":
            drift.append((cid, f"current={src}/{org}"))

    if drift:
        print("WARN: 一部対象が fallback_atla でない（既に再判定済み？）:")
        for d in drift:
            print(f"  {d}")
        print("→ それらは更新スキップします")

    apply_filtered = [
        a for a in APPLY
        if a[0] in actual and actual[a[0]][1] == "fallback_atla"
    ]
    print(f"\nApplying {len(apply_filtered)}/{len(APPLY)} updates...")

    if not dry_run and apply_filtered:
        cur.execute("BEGIN IMMEDIATE")
        for cid, new_org, conf, src, _ev in apply_filtered:
            cur.execute(
                """UPDATE contract_requesting_org
                   SET requesting_org = ?, match_source = ?, confidence = ?
                   WHERE contract_id = ? AND match_source = 'fallback_atla'""",
                (new_org, src, conf, cid),
            )
            if cur.rowcount != 1:
                print(f"  WARN cid={cid} rowcount={cur.rowcount}")
        con.execute("COMMIT")

    # Post snapshot
    cur.execute(
        "SELECT match_source, COUNT(*) FROM contract_requesting_org "
        "GROUP BY match_source ORDER BY 2 DESC"
    )
    by_source = dict(cur.fetchall())
    cur.execute(
        "SELECT requesting_org, COUNT(*) FROM contract_requesting_org "
        "GROUP BY requesting_org ORDER BY 2 DESC"
    )
    by_org = dict(cur.fetchall())

    # Verify after-state for the applied ones
    after_state = {}
    if apply_filtered:
        ids2 = [a[0] for a in apply_filtered]
        ph2 = ",".join("?" * len(ids2))
        for cid, org, src, conf in cur.execute(
            f"SELECT contract_id, requesting_org, match_source, confidence "
            f"FROM contract_requesting_org WHERE contract_id IN ({ph2})",
            ids2,
        ).fetchall():
            after_state[cid] = {"org": org, "src": src, "conf": conf}

    con.close()

    if not dry_run and apply_filtered:
        shutil.copy2(TMP_DB, PROCUREMENT_DB)
        TMP_DB.unlink(missing_ok=True)
        print(f"copied {TMP_DB} → {PROCUREMENT_DB}")

    result = {
        "dry_run": dry_run,
        "applied_count": len(apply_filtered),
        "applied": [
            {
                "cid": a[0], "org": a[1], "conf": a[2],
                "match_source": a[3], "evidence": a[4],
                "after": after_state.get(a[0]),
            }
            for a in apply_filtered
        ],
        "skipped_drift": drift,
        "not_applied_log": [
            {"cid": cid, "reason": reason} for cid, reason in NOT_APPLIED
        ],
        "by_source": by_source,
        "by_org": by_org,
        "backup_path": str(backup_path) if backup_path else None,
    }

    if not dry_run:
        log_path = LOG_DIR / f"apply_fallback50_{datetime.now():%Y%m%d_%H%M%S}.json"
        log_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nlog: {log_path}")

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}=== 結果 ===")
    print(f"  applied: {len(apply_filtered)}")
    fb_now = by_source.get("fallback_atla", 0)
    if dry_run:
        print(f"  fallback_atla (現在): {fb_now}  → 適用後想定: {fb_now - len(apply_filtered)}")
    else:
        print(f"  fallback_atla: {fb_now}  ({len(apply_filtered)}件 解決)")
    print(f"  by_source 全体: {by_source}")

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not PROCUREMENT_DB.exists():
        print(f"DB not found: {PROCUREMENT_DB}", file=sys.stderr)
        return 1
    run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
