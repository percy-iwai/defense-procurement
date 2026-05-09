"""
NDMC（防衛医科大学校）の semantic_embedding 誤分類修正

問題:
  assign_pillar_semantic.py 実行後、NDMC（agency_id='ndmc'）の契約が
  P43（電磁波・艦船・航空機）や P82（研究開発）に誤分類されている。
  これらは医療器材・病院業務サービスであり、7本柱に対応する防衛コードが存在しない。

確認結果（defense_pillar_master 照合）:
  - P7 に「衛生」サブコードは存在しない（P71:弾薬 / P72:維持整備 / P73:施設）
  - P8 に「技術基盤」専用サブコードは存在しない（P81:防衛生産 / P82:研究開発 / P83:基地対策 / P84:燃料訓練）
  → 正しい分類先なし → unclassified に戻す

対象:
  - agency_id = 'ndmc' (防衛医科大学校)
  - match_method = 'semantic_embedding'
  - pillar_l1_code = 4  (P43: バンドループ型電極 外44品目 など 医療電極→誤分類)
  - pillar_l1_code = 8, pillar_l2_code = 82  (P82: 人工呼吸器点検 / 検体処理業務 など→誤分類)

Usage:
    python dev/fix_ndmc_pillar.py --dry-run   # 確認のみ
    python dev/fix_ndmc_pillar.py              # 本番実行
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE    = Path(__file__).resolve().parent.parent
DB_REAL = BASE / "data/db/procurement.db"
DB_TMP  = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "procurement_fix_ndmc.db"

sys.stdout.reconfigure(encoding="utf-8")

# NDMC 系 agency_id のリスト（現時点では ndmc のみ）
NDMC_AGENCY_IDS = ("ndmc",)

# 修正対象ピラー条件: (pillar_l1_code, pillar_l2_code or None)
# None は l2 を問わず l1 だけで判定
TARGET_PILLARS: list[tuple[int, int | None]] = [
    (4,  43),   # P43: 電磁波・艦船・航空機 → 医療電極等が誤混入
    (8,  82),   # P82: 研究開発 → 病院業務・医療器材点検が誤混入
]


def fetch_targets(cur: sqlite3.Cursor) -> list[tuple]:
    """修正対象レコードを返す: [(contract_id, l1, l2, name, agency_id), ...]"""
    agency_placeholders = ",".join("?" * len(NDMC_AGENCY_IDS))
    results = []
    for l1, l2 in TARGET_PILLARS:
        if l2 is not None:
            cur.execute(f"""
                SELECT cp.contract_id, cp.pillar_l1_code, cp.pillar_l2_code,
                       c.contract_name, c.agency_id
                FROM contract_pillar cp
                JOIN contracts c ON cp.contract_id = c.id
                WHERE cp.fiscal_year = 2023
                  AND cp.match_method = 'semantic_embedding'
                  AND cp.pillar_l1_code = ?
                  AND cp.pillar_l2_code = ?
                  AND c.agency_id IN ({agency_placeholders})
            """, (l1, l2, *NDMC_AGENCY_IDS))
        else:
            cur.execute(f"""
                SELECT cp.contract_id, cp.pillar_l1_code, cp.pillar_l2_code,
                       c.contract_name, c.agency_id
                FROM contract_pillar cp
                JOIN contracts c ON cp.contract_id = c.id
                WHERE cp.fiscal_year = 2023
                  AND cp.match_method = 'semantic_embedding'
                  AND cp.pillar_l1_code = ?
                  AND c.agency_id IN ({agency_placeholders})
            """, (l1, *NDMC_AGENCY_IDS))
        results.extend(cur.fetchall())
    return results


def main(dry_run: bool) -> None:
    print(f"{'=== DRY RUN ===' if dry_run else '=== 本番実行 ==='}")
    print(f"対象機関: {NDMC_AGENCY_IDS}")
    print(f"対象ピラー: {TARGET_PILLARS}")
    print()

    conn_r = sqlite3.connect(str(DB_REAL))
    cur_r  = conn_r.cursor()

    # ── 事前確認: defense_pillar_master の P7/P8 サブコード ──────────────────
    pillar_db = BASE / "data/db/defense_pillar.db"
    conn_p = sqlite3.connect(str(pillar_db))
    cur_p  = conn_p.cursor()
    cur_p.execute("SELECT pillar_id, name FROM defense_pillar_master WHERE parent_id IN (7,8) ORDER BY pillar_id")
    p7_p8_subs = cur_p.fetchall()
    conn_p.close()
    print("defense_pillar_master P7/P8 サブコード一覧:")
    for pid, name in p7_p8_subs:
        print(f"  {pid}: {name}")
    print()
    print("→ 衛生サブコード（P7）: 存在しない")
    print("→ 技術基盤サブコード（P8）: 存在しない")
    print("→ 修正方針: unclassified に戻す")
    print()

    # ── 修正対象抽出 ─────────────────────────────────────────────────────────
    targets = fetch_targets(cur_r)
    conn_r.close()

    if not targets:
        print("修正対象なし。終了。")
        return

    print(f"修正対象: {len(targets)} 件")
    for cid, l1, l2, name, aid in targets:
        print(f"  [{aid}] P{l1}/{l2} → unclassified | {name[:55]}")

    if dry_run:
        print("\n[DRY RUN] DB書き込みはスキップ。")
        return

    # ── DB コピー → UPDATE → コピーバック ────────────────────────────────────
    print(f"\nDBコピー中: {DB_REAL.name} → {DB_TMP.name}")
    shutil.copy2(DB_REAL, DB_TMP)

    conn_w = sqlite3.connect(str(DB_TMP))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    contract_ids = [row[0] for row in targets]
    id_placeholders = ",".join("?" * len(contract_ids))

    conn_w.execute(f"""
        UPDATE contract_pillar
        SET pillar_l1_code = NULL,
            pillar_l2_code = NULL,
            confidence     = 0.0,
            match_method   = 'unclassified',
            match_source   = NULL,
            updated_at     = ?
        WHERE contract_id IN ({id_placeholders})
          AND match_method = 'semantic_embedding'
    """, (now_iso, *contract_ids))
    conn_w.commit()

    changed = conn_w.execute("SELECT changes()").fetchone()[0]

    # ── 事後確認 ─────────────────────────────────────────────────────────────
    cur_w = conn_w.cursor()
    cur_w.execute("""
        SELECT match_method, COUNT(*) FROM contract_pillar
        WHERE fiscal_year = 2023 GROUP BY match_method ORDER BY COUNT(*) DESC
    """)
    print("\n=== 更新後 FY2023 match_method 分布 ===")
    for method, cnt in cur_w.fetchall():
        print(f"  {method:25s}: {cnt:6,}件")

    conn_w.close()
    print(f"\nコピーバック: {DB_TMP.name} → {DB_REAL.name}")
    shutil.copy2(DB_TMP, DB_REAL)
    DB_TMP.unlink(missing_ok=True)
    print(f"完了: {changed}件を unclassified に更新。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NDMC P43/P82 誤分類修正")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
