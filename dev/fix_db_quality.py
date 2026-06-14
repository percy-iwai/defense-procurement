"""
DB品質修正: B-4孤児行削除 / B-1 corporate_number無効NULL化 /
           B-2 award_rate補完 / C-1 金額異常値記録
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db" / "procurement.db"
DOCS = Path(__file__).parent.parent / "docs"


def run_all() -> None:
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # ── B-4: 孤児行 DELETE ──────────────────────────────────────────────────
    print("\n=== B-4: 孤児行 DELETE ===")
    cur.execute(
        "DELETE FROM contract_requesting_org WHERE contract_id NOT IN (SELECT id FROM contracts)"
    )
    deleted_org = cur.rowcount
    cur.execute(
        "DELETE FROM contract_equipment WHERE contract_id NOT IN (SELECT id FROM contracts)"
    )
    deleted_eq = cur.rowcount
    conn.commit()
    print(f"  contract_requesting_org: {deleted_org}件削除")
    print(f"  contract_equipment:      {deleted_eq}件削除")

    # ── B-1: corporate_number 形式不正 NULL化 ───────────────────────────────
    print("\n=== B-1: corporate_number 形式不正 NULL化 ===")
    cur.execute("""
        UPDATE contracts
        SET corporate_number = NULL
        WHERE corporate_number IS NOT NULL
          AND corporate_number NOT GLOB
            '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
    """)
    b1_count = cur.rowcount
    conn.commit()
    print(f"  NULL化: {b1_count}件")

    # ── B-2: award_rate 補完 ───────────────────────────────────────────────
    print("\n=== B-2: award_rate 補完 ===")
    cur.execute("""
        UPDATE contracts
        SET award_rate = ROUND(1.0 * contract_amount / estimated_price, 4)
        WHERE award_rate IS NULL
          AND contract_amount > 0
          AND estimated_price > 0
    """)
    b2_count = cur.rowcount
    conn.commit()
    print(f"  補完: {b2_count}件")

    # ── C-1: 負値 記録 ─────────────────────────────────────────────────────
    print("\n=== C-1: 負値 記録 ===")
    cur.execute("""
        SELECT id, agency_id, contract_name, contract_amount, contract_date
        FROM contracts
        WHERE contract_amount < 0
    """)
    negatives = cur.fetchall()
    print(f"  負値: {len(negatives)}件")

    neg_md = "# C-1 負値金額レコード（確認待ち・修正未実施）\n\n"
    neg_md += "| id | agency_id | contract_name | contract_amount | contract_date |\n"
    neg_md += "|---|---|---|---|---|\n"
    for row in negatives:
        neg_md += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |\n"
    (DOCS / "audit_c1_negative.md").write_text(neg_md, encoding="utf-8")
    print(f"  → docs/audit_c1_negative.md に保存")

    # ── C-1: 1〜100円 記録 ────────────────────────────────────────────────
    print("\n=== C-1: 1〜100円 記録 ===")
    cur.execute("""
        SELECT id, agency_id, contract_name, contract_amount, contract_date, vendor_name
        FROM contracts
        WHERE contract_amount BETWEEN 1 AND 100
        ORDER BY contract_amount
    """)
    smalls = cur.fetchall()
    print(f"  1〜100円: {len(smalls)}件")

    small_md = "# C-1 金額1〜100円レコード（確認待ち・修正未実施）\n\n"
    small_md += "| id | agency_id | contract_name | contract_amount | contract_date | vendor_name |\n"
    small_md += "|---|---|---|---|---|---|\n"
    for row in smalls:
        small_md += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} |\n"
    (DOCS / "audit_c1_small_amounts.md").write_text(small_md, encoding="utf-8")
    print(f"  → docs/audit_c1_small_amounts.md に保存")

    conn.close()
    print("\n完了。")


if __name__ == "__main__":
    run_all()
