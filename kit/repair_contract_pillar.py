"""contract_pillar テーブルのbtree破損を修復する。

## 背景（2026-06-13 発見）
procurement.db の contract_pillar（rootpage 41182）の1ページ（page 42086）に
「Rowid out of order」破損があり、JOINや索引検索の結果が不安定になる。
フルスキャン自体は安定して113,800行を返すが、contract_id（PRIMARY KEY）が
682件重複している（破損ページにセマンティック更新前の古い行が残留）。
2026-05-10 のセマンティック更新セッション以降の全バックアップが同一破損を持つ。

## 修復方法
1. フルスキャンで全行回収（安定であることを2回スキャン+ハッシュ比較で確認済み）
2. 重複contract_idは updated_at 最新を採用（同時刻なら unclassified 以外を優先）
3. テーブルをDROP→再作成→再投入

## 実行
  python kit/repair_contract_pillar.py --check                # 破損診断のみ
  python kit/repair_contract_pillar.py --output repaired.db   # コピーを修復（元DB無変更）
  python kit/repair_contract_pillar.py --in-place             # 元DBを直接修復（要バックアップ）
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"

DDL = """CREATE TABLE contract_pillar (
            contract_id INTEGER PRIMARY KEY,
            pillar_l1_code INTEGER,
            pillar_l2_code INTEGER,
            confidence REAL,
            match_method TEXT,
            match_source TEXT,
            fiscal_year INTEGER,
            updated_at TEXT
        )"""

COLS = ("contract_id", "pillar_l1_code", "pillar_l2_code", "confidence",
        "match_method", "match_source", "fiscal_year", "updated_at")


def check(db: Path) -> bool:
    """integrity_check と重複診断。破損なしなら True。"""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    ic = con.execute("PRAGMA integrity_check").fetchall()
    ok = len(ic) == 1 and ic[0][0] == "ok"
    print(f"integrity_check: {'ok' if ok else ic[0][0][:200]}")
    try:
        total, distinct = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT contract_id) FROM contract_pillar"
        ).fetchone()
        print(f"contract_pillar: {total:,} rows / {distinct:,} distinct ids "
              f"({total - distinct} duplicates)")
    except sqlite3.DatabaseError as exc:
        print(f"contract_pillar scan error: {exc}")
        ok = False
    con.close()
    return ok


def repair(db: Path) -> None:
    """db の contract_pillar を回収→重複解消→再作成する（dbを直接書き換える）。"""
    con = sqlite3.connect(db)
    rows = con.execute(
        f"SELECT {', '.join(COLS)} FROM contract_pillar").fetchall()
    print(f"scanned: {len(rows):,} rows")

    by: dict[int, list[tuple]] = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)

    def pick(cands: list[tuple]) -> tuple:
        # updated_at 最新 → unclassified 以外を優先
        return max(cands, key=lambda r: ((r[7] or ""), r[4] != "unclassified"))

    dedup = [pick(v) for v in by.values()]
    n_dup = sum(1 for v in by.values() if len(v) > 1)
    n_diff = sum(1 for v in by.values() if len(set(v)) > 1)
    print(f"unique ids: {len(dedup):,} (duplicates resolved: {n_dup}, "
          f"differing content: {n_diff})")

    con.execute("DROP TABLE IF EXISTS contract_pillar_new")
    con.execute(DDL.replace("contract_pillar", "contract_pillar_new", 1))
    con.executemany(
        f"INSERT INTO contract_pillar_new VALUES ({','.join('?' * len(COLS))})", dedup)
    con.execute("DROP TABLE contract_pillar")
    con.execute("ALTER TABLE contract_pillar_new RENAME TO contract_pillar")
    con.commit()
    con.execute("VACUUM")

    ic = con.execute("PRAGMA integrity_check").fetchall()
    print("integrity after repair:",
          "ok" if ic[0][0] == "ok" else ic[0][0][:200])
    print("pillar:", con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT contract_id) FROM contract_pillar").fetchone())
    print("join with contracts:", con.execute(
        "SELECT COUNT(*) FROM contract_pillar t JOIN contracts c ON c.id=t.contract_id"
    ).fetchone()[0])
    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="contract_pillar btree破損の修復")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="対象DB")
    parser.add_argument("--check", action="store_true", help="診断のみ")
    parser.add_argument("--output", help="このパスにコピーしてコピー側を修復（元DB無変更）")
    parser.add_argument("--in-place", action="store_true",
                        help="元DBを直接修復（事前にbackupへコピーを取る）")
    args = parser.parse_args()

    db = Path(args.db)
    if args.check:
        sys.exit(0 if check(db) else 1)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"copy {db} -> {out}")
        shutil.copy2(db, out)
        repair(out)
    elif args.in_place:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = BACKUP_DIR / f"procurement_pre_pillar_repair_{ts}.db"
        print(f"backup -> {bak}")
        shutil.copy2(db, bak)
        repair(db)
    else:
        parser.error("--check / --output PATH / --in-place のいずれかを指定")


if __name__ == "__main__":
    main()
