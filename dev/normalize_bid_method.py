"""
A-3: bid_method 正規化
1. bid_method_raw 列追加（原文保持）
2. 正規化ルールを適用して bid_method を上書き
"""
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db" / "procurement.db"

# 随意契約理由文のパターン（会計法/技術的理由文等）
_ZUII_REASON_PREFIXES = (
    "会計法", "技術的", "競争に適しない", "競争に付することが", "特定の者", "緊急", "秘密",
    "工事", "国家安全", "外国", "その性質又は目的",
)
_ZUII_LONG = 30  # 30文字超で随意契約理由文とみなす


def normalize_bid_method(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip().replace("　", " ").replace("\n", " ").replace("\r", "").strip()

    if s == "〃":
        return None

    # スペース除去後の正規化判定
    s_compact = re.sub(r"\s+", "", s)

    # 一般競争入札系
    if s_compact in ("一般", "一般競争", "一般競争入札", "一般入札", "一般契約",
                     "一般競争（最低価格落札方式）", "一般競争（総合評価落札方式）"):
        return "一般競争入札"
    if s_compact == "総合評価落札方式":
        return "一般競争入札"
    if re.match(r"^一般競争入札", s_compact):
        return "一般競争入札"

    # 随意契約系
    if s_compact in ("随意契約", "随契", "ずいけい"):
        return "随意契約"
    if any(s.startswith(p) for p in _ZUII_REASON_PREFIXES):
        return "随意契約"
    if len(s) > _ZUII_LONG and re.match(r"^(第|令|財|内|規|省|政|国|地|別)", s):
        return "随意契約"

    # 指名競争入札系
    if s_compact in ("指名競争入札", "指名競争", "指名競争（最低価格落札方式）"):
        return "指名競争入札"

    # FMS（有償援助）
    if s_compact in ("ＦＭＳ", "FMS", "有償援助"):
        return "FMS"

    # 個別判断が必要なもの → NULL でログ
    if s_compact in ("市場価格方式", "オープンカウンタ", "市場調査"):
        return None

    return s  # その他はそのまま返す（正規化不要 or 未知パターン）


def run() -> None:
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # bid_method_raw 列追加（既存チェック）
    cur.execute("PRAGMA table_info(contracts)")
    columns = {row[1] for row in cur.fetchall()}
    if "bid_method_raw" not in columns:
        cur.execute("ALTER TABLE contracts ADD COLUMN bid_method_raw TEXT")
        conn.commit()
        print("bid_method_raw 列追加")
    else:
        print("bid_method_raw 列: 既存")

    # 現在の bid_method を raw に保存（まだ保存されていない行のみ）
    cur.execute("""
        UPDATE contracts SET bid_method_raw = bid_method
        WHERE bid_method_raw IS NULL AND bid_method IS NOT NULL
    """)
    saved = cur.rowcount
    conn.commit()
    print(f"bid_method_raw に保存: {saved}件")

    # 正規化前分布
    print("\n=== 正規化前 bid_method 分布（上位30）===")
    cur.execute("""
        SELECT bid_method, COUNT(*) as cnt
        FROM contracts GROUP BY 1 ORDER BY 2 DESC LIMIT 30
    """)
    before_dist = cur.fetchall()
    for bm, cnt in before_dist:
        print(f"  {cnt:7d}  {repr(bm)[:60]}")

    # 全件取得して正規化
    cur.execute("SELECT id, bid_method FROM contracts")
    rows = cur.fetchall()

    updates: list[tuple[str | None, int]] = []
    null_log: list[tuple] = []

    for cid, bm in rows:
        normalized = normalize_bid_method(bm)
        if normalized != bm:
            updates.append((normalized, cid))
            if normalized is None and bm is not None:
                null_log.append((cid, bm))

    cur.executemany(
        "UPDATE contracts SET bid_method = ? WHERE id = ?", updates
    )
    conn.commit()
    print(f"\n正規化更新: {len(updates)}件")

    if null_log:
        print(f"\n→ NULL化した個別判断対象: {len(null_log)}件")
        for cid, bm in null_log[:20]:
            print(f"  #{cid}: {repr(bm)[:80]}")

    # 正規化後分布
    print("\n=== 正規化後 bid_method 分布 ===")
    cur.execute("""
        SELECT bid_method, COUNT(*) as cnt
        FROM contracts GROUP BY 1 ORDER BY 2 DESC
    """)
    for bm, cnt in cur.fetchall():
        print(f"  {cnt:7d}  {repr(bm)[:60]}")

    conn.close()
    print("\n完了。")


if __name__ == "__main__":
    run()
