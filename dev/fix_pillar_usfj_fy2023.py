"""
FY2023 contract_pillar 米軍再編・SACO 分離修正

① defense_pillar_master (defense_pillar.db) に P9/P91/P92/P93/P94 を追加
② contract_pillar (procurement.db) の P73 契約を P9x サブコードへ移動
   - P91（普天間移設・辺野古関係）: シュワブ / 辺野古 / 普天間 / 嘉手納以南 / 代替施設
   - P92（馬毛島・FCLP施設整備）: 馬毛島 / FCLP / 空母艦載機
   - P93（SACO関係経費）: SACO
   - P94（その他再編経費）: グアム移転 / 再編連絡 / 再編関連措置
③ P71 個別修正:
   - id=67014（嘉手納弾薬庫地区賃貸借 102億）→ P83（基地対策）
   - id=66843（シュワブ海上警備業務 82億）→ P92（普天間・辺野古関係）

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

BASE         = Path(__file__).resolve().parent.parent
DB_PROC      = BASE / "data/db/procurement.db"
DB_PILLAR    = BASE / "data/db/defense_pillar.db"
TMP_DIR      = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp")
DB_PROC_TMP  = TMP_DIR / "procurement_fix_usfj.db"
DB_PILLAR_TMP = TMP_DIR / "defense_pillar_fix_usfj.db"

FY = 2023

sys.stdout.reconfigure(encoding="utf-8")

# ─── P9 マスタ定義 ──────────────────────────────────────────────────────────────
P9_MASTER = [
    # (pillar_id, level, name, parent_id, display_order)
    (9,  1, "米軍再編・SACO・共通基盤",         None, 90),
    (91, 2, "普天間移設・辺野古関係",            9,    91),
    (92, 2, "馬毛島（FCLP・空母艦載機施設）",   9,    92),
    (93, 2, "SACO関係経費",                     9,    93),
    (94, 2, "その他再編経費（グアム・訓練移転等）", 9,  94),
]

# ─── キーワード → P9サブコード ────────────────────────────────────────────────
# 優先順位: P92 > P91 > P93 > P94（後のUPDATEほど上書き負け＝先にUPDATEしたほうが確定）
# ただし各条件は実質 mutually exclusive なので順序に依存しない
USFJ_RULES: list[tuple[int, list[str]]] = [
    (91, ["シュワブ", "辺野古", "普天間", "嘉手納以南", "代替施設", "V字形"]),
    (92, ["馬毛島", "FCLP", "空母艦載機"]),
    (93, ["SACO"]),
    (94, ["グアム移転", "再編連絡", "再編関連措置"]),
]

# P71 個別修正 (contract_id → (new_l1, new_l2, comment))
P71_FIXES = {
    67014: (8, 83, "嘉手納弾薬庫地区賃貸借→P83基地対策"),
    66843: (9, 92, "シュワブ海上警備業務→P92馬毛島・辺野古"),
}


def _kw_cond(kws: list[str]) -> str:
    return " OR ".join(f"c.contract_name LIKE '%{kw}%'" for kw in kws)


def _count_target(cur: sqlite3.Cursor, l2_code: int, kws: list[str]) -> tuple[int, float]:
    cur.execute(f"""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount), 0) / 1e8, 1)
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ? AND cp.pillar_l2_code = ?
          AND ({_kw_cond(kws)})
    """, (FY, l2_code))
    cnt, oku = cur.fetchone()
    return cnt or 0, oku or 0.0


def _count_p9(cur: sqlite3.Cursor) -> None:
    print("\n=== P9 内訳（更新後）===")
    for sub, kws in [(91, "P91 普天間・辺野古"), (92, "P92 馬毛島"), (93, "P93 SACO"), (94, "P94 その他")]:
        cur.execute("""
            SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
            FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
            WHERE cp.fiscal_year=? AND cp.pillar_l1_code=9 AND cp.pillar_l2_code=?
        """, (FY, sub))
        cnt, oku = cur.fetchone()
        print(f"  {kws}: {cnt:,}件 / {oku:,.1f}億")
    cur.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l1_code=9
    """, (FY,))
    cnt, oku = cur.fetchone()
    print(f"  P9 合計: {cnt:,}件 / {oku:,.1f}億")


def main(dry_run: bool) -> None:
    print(f"{'=== DRY RUN ===' if dry_run else '=== 本番実行 ==='}")

    # ── 事前確認 ─────────────────────────────────────────────────────────────────
    conn_r = sqlite3.connect(str(DB_PROC))
    cur_r = conn_r.cursor()

    print("\n--- P73 から P9x へ移動予定 ---")
    total_cnt = total_oku = 0
    for l2_sub, kws in USFJ_RULES:
        cnt, oku = _count_target(cur_r, 73, kws)
        if cnt:
            print(f"  P{l2_sub}: {cnt:,}件 / {oku:,.1f}億  [{', '.join(kws[:3])}...]")
            total_cnt += cnt
            total_oku += oku

    # 重複チェック（複数ルールにヒットする件数）
    all_kws = [kw for _, kws in USFJ_RULES for kw in kws]
    all_cond = " OR ".join(f"c.contract_name LIKE '%{kw}%'" for kw in all_kws)
    cur_r.execute(f"""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l2_code=73 AND ({all_cond})
    """, (FY,))
    uniq_cnt, uniq_oku = cur_r.fetchone()
    print(f"  重複除去合計: {uniq_cnt:,}件 / {uniq_oku:,.1f}億")

    print("\n--- P73 修正後の見込み ---")
    cur_r.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l2_code=73
    """, (FY,))
    p73_cnt, p73_oku = cur_r.fetchone()
    print(f"  P73 現在: {p73_cnt:,}件 / {p73_oku:,.1f}億")
    print(f"  P73 修正後（純施設強靱化）: {p73_cnt - uniq_cnt:,}件 / {p73_oku - uniq_oku:,.1f}億")

    print("\n--- P71 個別修正対象 ---")
    for cid, (new_l1, new_l2, comment) in P71_FIXES.items():
        cur_r.execute("""
            SELECT cp.pillar_l1_code, cp.pillar_l2_code,
                   ROUND(COALESCE(c.contract_amount,0)/1e8,2), c.contract_name
            FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
            WHERE cp.contract_id=?
        """, (cid,))
        row = cur_r.fetchone()
        if row:
            cur_l1, cur_l2, oku, name = row
            print(f"  id={cid}: P{cur_l2}→P{new_l2} {oku:.2f}億  {str(name)[:50]}")
            print(f"          ({comment})")
        else:
            print(f"  id={cid}: NOT FOUND")

    conn_r.close()

    if dry_run:
        print("\n[DRY RUN] DB書き込みはスキップ。")
        return

    # ── defense_pillar.db に P9 追加 ─────────────────────────────────────────────
    print(f"\nPillar DB コピー中: {DB_PILLAR.name} → {DB_PILLAR_TMP.name}")
    shutil.copy2(DB_PILLAR, DB_PILLAR_TMP)

    conn_p = sqlite3.connect(str(DB_PILLAR_TMP))
    # 既存行があれば SKIP（べき等）
    for row in P9_MASTER:
        pid, lv, name, par, disp = row
        conn_p.execute("""
            INSERT OR IGNORE INTO defense_pillar_master
              (pillar_id, level, name, parent_id, display_order)
            VALUES (?, ?, ?, ?, ?)
        """, (pid, lv, name, par, disp))
    conn_p.commit()

    # 確認
    cur_p = conn_p.cursor()
    cur_p.execute("SELECT pillar_id, level, name FROM defense_pillar_master WHERE pillar_id >= 9 ORDER BY pillar_id")
    print("\n追加されたマスタ行:")
    for r in cur_p.fetchall():
        print(f"  {r}")
    conn_p.close()

    print(f"コピーバック: {DB_PILLAR_TMP.name} → {DB_PILLAR.name}")
    shutil.copy2(DB_PILLAR_TMP, DB_PILLAR)
    DB_PILLAR_TMP.unlink(missing_ok=True)

    # ── procurement.db 更新 ──────────────────────────────────────────────────────
    print(f"\nProcurement DB コピー中: {DB_PROC.name} → {DB_PROC_TMP.name}")
    shutil.copy2(DB_PROC, DB_PROC_TMP)

    conn_w = sqlite3.connect(str(DB_PROC_TMP))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    total_changed = 0

    # ── ① P73 → P9x（各サブコード別 UPDATE）────────────────────────────────────
    for l2_sub, kws in USFJ_RULES:
        cond = _kw_cond(kws)
        conn_w.execute(f"""
            UPDATE contract_pillar
            SET pillar_l1_code = 9,
                pillar_l2_code = {l2_sub},
                match_method   = 'keyword_rule_fix',
                match_source   = 'usfj_p73→P{l2_sub}',
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
        changed = conn_w.execute("SELECT changes()").fetchone()[0]
        total_changed += changed
        print(f"  P73→P{l2_sub}: {changed:,}件")

    # ── ② P71 個別修正 ───────────────────────────────────────────────────────────
    p71_fixed = 0
    for cid, (new_l1, new_l2, comment) in P71_FIXES.items():
        conn_w.execute("""
            UPDATE contract_pillar
            SET pillar_l1_code = ?,
                pillar_l2_code = ?,
                match_method   = 'keyword_rule_fix',
                match_source   = ?,
                updated_at     = ?
            WHERE contract_id = ?
        """, [new_l1, new_l2, comment, now_iso, cid])
        chg = conn_w.execute("SELECT changes()").fetchone()[0]
        p71_fixed += chg
        print(f"  id={cid}: {chg}件更新 → P{new_l2}")

    conn_w.commit()
    total_changed += p71_fixed

    # ── 事後確認 ─────────────────────────────────────────────────────────────────
    cur_w = conn_w.cursor()
    _count_p9(cur_w)

    # P73 残存確認
    cur_w.execute("""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount),0)/1e8,1)
        FROM contract_pillar cp JOIN contracts c ON cp.contract_id=c.id
        WHERE cp.fiscal_year=? AND cp.pillar_l2_code=73
    """, (FY,))
    p73_cnt, p73_oku = cur_w.fetchone()
    print(f"\nP73 残存（純施設強靱化）: {p73_cnt:,}件 / {p73_oku:,.1f}億")

    conn_w.close()

    print(f"\nコピーバック: {DB_PROC_TMP.name} → {DB_PROC.name}")
    shutil.copy2(DB_PROC_TMP, DB_PROC)
    DB_PROC_TMP.unlink(missing_ok=True)

    print(f"\n完了: 合計 {total_changed:,}件更新")
    print(f"  P73→P9x: {total_changed - p71_fixed:,}件")
    print(f"  P71個別修正: {p71_fixed:,}件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="米軍再編・SACO P9カテゴリ分離 (FY2023)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
