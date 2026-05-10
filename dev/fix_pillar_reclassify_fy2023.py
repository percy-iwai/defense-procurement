"""
FY2023 contract_pillar 再分類修正

① P73（施設強靱化）→ P83（基地対策）
  - rdb系機関 AND 賃貸|防音|騒音|補償|移転料 を含む契約名
  - 根拠: 基地賃貸借料・騒音補償は P83（基地対策）が正しい
  - 確認: P73-rdb のうち工事系 8,113億は正当、賃貸・防音系 1,189億が P83 候補

② P43（車両・艦船・航空機等）→ P72（装備品等維持整備費）
  - 修理 or オーバーホール を含む AND 建造|製造|取得 を含まない
  - 根拠: P43 = 取得、P72 = 維持整備。修理・OH は維持整備が正しい
  - ※ OH単独は OH-1 等のモデル名と衝突するため除外（オーバーホール のみ使用）

Usage:
    python dev/fix_pillar_reclassify_fy2023.py --dry-run
    python dev/fix_pillar_reclassify_fy2023.py
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE    = Path(__file__).resolve().parent.parent
DB_REAL = BASE / "data/db/procurement.db"
DB_TMP  = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "procurement_fix_reclassify.db"

sys.stdout.reconfigure(encoding="utf-8")

FY = 2023

# ① P73→P83 対象キーワード（rdb系機関限定）
P73_P83_KWS = ["賃貸", "防音", "騒音", "補償", "移転料"]


def _p73_p83_cte(fy: int) -> tuple[str, list]:
    """P73→P83 修正対象の contract_id を返す CTE SQL と params を返す."""
    kw_cond = " OR ".join(f"c.contract_name LIKE ?" for _ in P73_P83_KWS)
    kw_params = [f"%{kw}%" for kw in P73_P83_KWS]
    sql = f"""
        SELECT cp.contract_id
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.pillar_l2_code = 73
          AND c.agency_id LIKE 'rdb%'
          AND ({kw_cond})
    """
    return sql, [fy] + kw_params


def _p43_p72_cte(fy: int) -> tuple[str, list]:
    """P43→P72 修正対象の contract_id を返す CTE SQL と params を返す."""
    sql = f"""
        SELECT cp.contract_id
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.pillar_l2_code = 43
          AND (c.contract_name LIKE '%修理%'
            OR c.contract_name LIKE '%オーバーホール%')
          AND c.contract_name NOT LIKE '%建造%'
          AND c.contract_name NOT LIKE '%製造%'
          AND c.contract_name NOT LIKE '%取得%'
    """
    return sql, [fy]


def fetch_preview(cur: sqlite3.Cursor, cte_sql: str, params: list, limit: int = 8) -> list:
    """修正対象のサンプル行を返す."""
    cur.execute(f"""
        SELECT c.agency_id,
               ROUND(COALESCE(c.contract_amount, 0) / 1e8, 2) AS oku,
               c.contract_name,
               cp.pillar_l2_code,
               cp.match_method
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.contract_id IN ({cte_sql})
        ORDER BY c.contract_amount DESC NULLS LAST
        LIMIT ?
    """, params + [limit])
    return cur.fetchall()


def main(dry_run: bool) -> None:
    print(f"{'=== DRY RUN ===' if dry_run else '=== 本番実行 ==='}")
    print()

    conn_r = sqlite3.connect(str(DB_REAL))
    cur_r = conn_r.cursor()

    # ── 対象カウント ─────────────────────────────────────────────────────────
    cte1, p1 = _p73_p83_cte(FY)
    cur_r.execute(f"""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount), 0) / 1e8, 1)
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.contract_id IN ({cte1})
    """, p1)
    cnt1, oku1 = cur_r.fetchone()
    print(f"① P73→P83 対象: {cnt1:,}件 / {oku1:,.1f}億")

    rows1 = fetch_preview(cur_r, cte1, p1)
    for agency, oku, name, code, method in rows1:
        print(f"   [{agency:<12}] P{code} {oku:>7.2f}億  {method:<18} {str(name)[:50]}")

    print()
    cte2, p2 = _p43_p72_cte(FY)
    cur_r.execute(f"""
        SELECT COUNT(*), ROUND(COALESCE(SUM(c.contract_amount), 0) / 1e8, 1)
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.contract_id IN ({cte2})
    """, p2)
    cnt2, oku2 = cur_r.fetchone()
    print(f"② P43→P72 対象: {cnt2:,}件 / {oku2:,.1f}億")

    rows2 = fetch_preview(cur_r, cte2, p2)
    for agency, oku, name, code, method in rows2:
        print(f"   [{agency:<12}] P{code} {oku:>7.2f}億  {method:<18} {str(name)[:50]}")

    conn_r.close()

    if dry_run:
        print("\n[DRY RUN] DB書き込みはスキップ。")
        return

    # ── DB コピー → UPDATE → コピーバック ────────────────────────────────────
    print(f"\nDBコピー中: {DB_REAL.name} → {DB_TMP.name}")
    shutil.copy2(DB_REAL, DB_TMP)

    conn_w = sqlite3.connect(str(DB_TMP))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ① P73→P83
    # params順: now_iso, FY(outer), *p1(= [FY, kw1..kw5] CTE内 ?)
    conn_w.execute(f"""
        UPDATE contract_pillar
        SET pillar_l1_code = 8,
            pillar_l2_code = 83,
            match_method   = 'keyword_rule_fix',
            match_source   = 'rdb_kichi_kousaku→P83',
            updated_at     = ?
        WHERE fiscal_year = ?
          AND pillar_l2_code = 73
          AND contract_id IN ({cte1})
    """, [now_iso, FY] + p1)
    changed1 = conn_w.execute("SELECT changes()").fetchone()[0]

    # ② P43→P72
    # params順: now_iso, FY(outer), *p2(= [FY] CTE内 ?)
    conn_w.execute(f"""
        UPDATE contract_pillar
        SET pillar_l1_code = 7,
            pillar_l2_code = 72,
            match_method   = 'keyword_rule_fix',
            match_source   = 'p43_maintenance→P72',
            updated_at     = ?
        WHERE fiscal_year = ?
          AND pillar_l2_code = 43
          AND contract_id IN ({cte2})
    """, [now_iso, FY] + p2)
    changed2 = conn_w.execute("SELECT changes()").fetchone()[0]

    conn_w.commit()

    # ── 事後確認 ─────────────────────────────────────────────────────────────
    cur_w = conn_w.cursor()
    cur_w.execute("""
        SELECT cp.pillar_l2_code,
               COUNT(*),
               ROUND(COALESCE(SUM(c.contract_amount), 0) / 1e8, 1)
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.pillar_l2_code IN (43, 71, 72, 73, 83)
        GROUP BY cp.pillar_l2_code
        ORDER BY cp.pillar_l2_code
    """, (FY,))
    print("\n=== 更新後 P43/P71/P72/P73/P83 内訳 ===")
    labels = {43: "P43 車両・艦船・航空機", 71: "P71 弾薬・誘導弾",
              72: "P72 装備品維持整備費",   73: "P73 施設強靱化",
              83: "P83 基地対策"}
    for code, cnt, oku in cur_w.fetchall():
        print(f"  {labels.get(code, f'P{code}'):<22}: {cnt:>6,}件 / {oku:>9,.1f}億")

    conn_w.close()

    print(f"\nコピーバック: {DB_TMP.name} → {DB_REAL.name}")
    shutil.copy2(DB_TMP, DB_REAL)
    DB_TMP.unlink(missing_ok=True)

    print(f"\n完了:")
    print(f"  ① P73→P83: {changed1:,}件更新")
    print(f"  ② P43→P72: {changed2:,}件更新")
    print(f"  合計:       {changed1 + changed2:,}件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P73/P83・P43/P72 再分類修正 (FY2023)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
