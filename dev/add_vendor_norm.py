"""
A-5: vendor_name_norm 列追加 + NFKC正規化
全角英数→半角、㈱/（株）/(株) → 株式会社 など
"""
import sqlite3
import unicodedata
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db" / "procurement.db"


def normalize_vendor(name: str | None) -> str | None:
    if name is None:
        return None
    s = unicodedata.normalize("NFKC", name)
    s = s.replace("㈱", "株式会社")
    s = s.replace("（株）", "株式会社")
    s = s.replace("(株)", "株式会社")
    s = s.replace("㈲", "有限会社")
    s = s.replace("（有）", "有限会社")
    s = s.replace("(有)", "有限会社")
    return s.strip()


def run() -> None:
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # 列追加（既存チェック）
    cur.execute("PRAGMA table_info(contracts)")
    columns = {row[1] for row in cur.fetchall()}
    if "vendor_name_norm" not in columns:
        cur.execute("ALTER TABLE contracts ADD COLUMN vendor_name_norm TEXT")
        conn.commit()
        print("vendor_name_norm 列追加")
    else:
        print("vendor_name_norm 列: 既存")

    cur.execute("SELECT id, vendor_name FROM contracts")
    rows = cur.fetchall()

    updates: list[tuple[str | None, int]] = []
    changed_samples: list[tuple] = []

    for cid, vname in rows:
        norm = normalize_vendor(vname)
        updates.append((norm, cid))
        if norm != vname and len(changed_samples) < 20:
            changed_samples.append((vname, norm))

    cur.executemany(
        "UPDATE contracts SET vendor_name_norm = ? WHERE id = ?", updates
    )
    conn.commit()
    print(f"更新: {len(updates)}件")

    print(f"\n=== 正規化サンプル（変化あり上位20件）===")
    for orig, normed in changed_samples:
        print(f"  {repr(orig)[:40]:42s} → {repr(normed)[:40]}")

    conn.close()
    print("\n完了。")


if __name__ == "__main__":
    run()
