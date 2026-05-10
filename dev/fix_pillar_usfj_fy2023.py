"""
FY2023 contract_pillar 米軍再編・SACO 分離修正

① defense_pillar_master (defense_pillar.db) に P85「米軍再編関係経費等」を追加
   （P8「防衛生産基盤強化・研究開発等」の中項目、pillar_id=85）
② contract_pillar (procurement.db) の P73 契約を P85 へ移動
   - 普天間 / 辺野古 / シュワブ / 嘉手納以南 / 代替施設 / V字形滑走路
   - 馬毛島 / FCLP / 空母艦載機
   - SACO / 沖合展開 / 楚辺通信所
   - グアム移転 / 再編関連措置 / 再編連絡
③ P71 個別修正:
   - id=67014（嘉手納弾薬庫地区賃貸借 102億）→ P83（基地対策）
   - id=66843（シュワブ海上警備業務 82億）→ P85

参考予算額:
  FY2023: 米軍再編 6,090億 + SACO 152億 = 6,242億
  FY2024: 米軍再編 3,061億 + SACO（含む）
  FY2025: 米軍再編 3,445億 + SACO 119億

Usage:
    python dev/fix_pillar_usfj_fy2023.py --dry-run
    python dev/fix_pillar_usfj_fy2023.py
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE          = Path(__file__).resolve().parent.parent
DB_PROC       = BASE / "data/db/procurement.db"
DB_PILLAR     = BASE / "data/db/defense_pillar.db"
TMP_DIR       = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp")
DB_PROC_TMP   = TMP_DIR / "procurement_fix_usfj.db"
DB_PILLAR_TMP = TMP_DIR / "defense_pillar_fix_usfj.db"

FY = 2023

sys.stdout.reconfigure(encoding="utf-8")

# ─── P85 マスタ定義 ─────────────────────────────────────────────────────────────
P85_MASTER = [
    # (pillar_id, level, name, parent_id, display_order)
    (85, 2, "米軍再編関係経費等", 8, 85),
]

# ─── P73 → P85 のキーワード ──────────────────────────────────────────────────
USFJ_KWS = [
    "シュワブ", "辺野古", "普天間", "嘉手納以南", "代替施設", "V字形",
    "馬毛島", "FCLP", "空母艦載機",
    "SACO", "沖合展開", "楚辺通信所",
    "グアム移転", "再編関連措置", "再編連絡",
]

# ─── P71 個別修正 (contract_id → (new_l1, new_l2, comment)) ─────────────────
P71_FIXES = {
    67014: (8, 83, "嘉手納弾薬庫地区賃貸借→P83基地対策"),
    66843: (8, 85, "シュワブ海上警備業務→P85米軍再編"),
}


def _kw_cond(kws: list[str]) -> str:
    return " OR ".join(f"c.contract_name LIKE '%{kw}%'" for kw in kws)


def main(dry_run: bool) -> None:
    print(f"{'=== DRY RUN ===' if dry_run else '=== 本番実行 ==='}")

    # ── 事前確認 ─────────────────────────────────────────────────────────────────
    conn_r = sqlite3.connect(str(DB_PROC))
    cur_r = conn_r.cursor()

    cond = _kw_cond(USFJ_KWS)
    cur_r.execute(f"""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l2_code=73 AND ({cond})
    """, (FY,))
    cnt, oku = cur_r.fetchone()
    print(f"\nP73→P85 移動対象: {cnt:,}件 / {oku:,.1f}億")

    # 既存P85確認
    cur_r.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.pillar_l2_code=85
    """)
    p85_cnt, p85_oku = cur_r.fetchone()
    print(f"P85 既存: {p85_cnt:,}件 / {p85_oku:,.1f}億")

    print("\n--- P71 個別修正対象 ---")
    for cid, (new_l1, new_l2, comment) in P71_FIXES.items():
        cur_r.execute("""
            SELECT cp.pillar_l2_code,
                   ROUND(COALESCE(c.contract_amount,0)/1e8,2), c.contract_name
            FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
            WHERE cp.contract_id=?
        """, (cid,))
        row = cur_r.fetchone()
        if row:
            cur_l2, amount, name = row
            print(f"  id={cid}: P{cur_l2}→P{new_l2} {amount:.2f}億  {str(name)[:50]}")
        else:
            print(f"  id={cid}: NOT FOUND")

    cur_r.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l2_code=73
    """, (FY,))
    p73_cnt, p73_oku = cur_r.fetchone()
    print(f"\nP73 現在: {p73_cnt:,}件 / {p73_oku:,.1f}億")
    print(f"P73 修正後（純施設強靱化）: {p73_cnt - cnt:,}件 / {p73_oku - oku:,.1f}億")

    conn_r.close()

    if dry_run:
        print("\n[DRY RUN] DB書き込みはスキップ。")
        return

    # ── defense_pillar.db: P85 挿入（既存なら SKIP）─────────────────────────────
    print(f"\nPillar DB コピー中: {DB_PILLAR.name} → {DB_PILLAR_TMP.name}")
    shutil.copy2(DB_PILLAR, DB_PILLAR_TMP)

    conn_p = sqlite3.connect(str(DB_PILLAR_TMP))
    for pid, lv, name, par, disp in P85_MASTER:
        conn_p.execute("""
            INSERT OR IGNORE INTO defense_pillar_master
              (pillar_id, level, name, parent_id, display_order)
            VALUES (?, ?, ?, ?, ?)
        """, (pid, lv, name, par, disp))
    conn_p.commit()
    cur_p = conn_p.cursor()
    cur_p.execute("SELECT pillar_id, name FROM defense_pillar_master WHERE pillar_id=85")
    print(f"  追加確認: {cur_p.fetchone()}")
    conn_p.close()

    shutil.copy2(DB_PILLAR_TMP, DB_PILLAR)
    DB_PILLAR_TMP.unlink(missing_ok=True)

    # ── procurement.db 更新 ──────────────────────────────────────────────────────
    print(f"\nProcurement DB コピー中: {DB_PROC.name} → {DB_PROC_TMP.name}")
    shutil.copy2(DB_PROC, DB_PROC_TMP)

    conn_w = sqlite3.connect(str(DB_PROC_TMP))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # P73→P85
    conn_w.execute(f"""
        UPDATE contract_pillar
        SET pillar_l1_code = 8,
            pillar_l2_code = 85,
            match_method   = 'keyword_rule_fix',
            match_source   = 'usfj_p73→P85',
            updated_at     = ?
        WHERE fiscal_year = ?
          AND pillar_l2_code = 73
          AND contract_id IN (
            SELECT cp.contract_id
            FROM contract_pillar cp
            JOIN contracts c ON cp.contract_id = c.id
            WHERE cp.fiscal_year = ? AND cp.pillar_l2_code = 73
              AND ({cond})
          )
    """, [now_iso, FY, FY])
    changed_p73 = conn_w.execute("SELECT changes()").fetchone()[0]
    print(f"  P73→P85: {changed_p73:,}件")

    # P71 個別修正
    p71_fixed = 0
    for cid, (new_l1, new_l2, comment) in P71_FIXES.items():
        conn_w.execute("""
            UPDATE contract_pillar
            SET pillar_l1_code=?, pillar_l2_code=?,
                match_method='keyword_rule_fix', match_source=?, updated_at=?
            WHERE contract_id=?
        """, [new_l1, new_l2, comment, now_iso, cid])
        chg = conn_w.execute("SELECT changes()").fetchone()[0]
        p71_fixed += chg
        print(f"  id={cid}: {chg}件更新 → P{new_l2}")

    conn_w.commit()

    # 事後確認
    cur_w = conn_w.cursor()
    cur_w.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.pillar_l2_code=85
    """)
    p85_cnt, p85_oku = cur_w.fetchone()
    print(f"\nP85 合計（更新後）: {p85_cnt:,}件 / {p85_oku:,.1f}億")

    cur_w.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l2_code=73
    """, (FY,))
    p73_cnt, p73_oku = cur_w.fetchone()
    print(f"P73 残存（純施設強靱化）: {p73_cnt:,}件 / {p73_oku:,.1f}億")
    conn_w.close()

    shutil.copy2(DB_PROC_TMP, DB_PROC)
    DB_PROC_TMP.unlink(missing_ok=True)

    print(f"\n完了: {changed_p73 + p71_fixed:,}件更新")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="米軍再編・SACO P85カテゴリ分離 (FY2023)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
