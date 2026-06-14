"""エクスポート済み判定結果を再構築DBへインポートする（新環境・GPU不要）。

kit/exports/ の以下を投入する:
  contracts_ocr.jsonl.gz            OCR由来契約行（easyocr再実行の代替）
  tables_small.jsonl.gz             fy_budget / kenkyuu_hyouka / choutatsuyotei
  enrichments_pillar.jsonl.gz       contract_pillar（semantic_embedding 含む全行）
  enrichments_requesting_org.jsonl.gz  contract_requesting_org 全行
  enrichments_equipment.jsonl.gz    equipment_master + contract_equipment

contract_id は旧環境の rowid なのでそのままは使えない。
拡張自然キー (agency_id, fiscal_year, contract_name, vendor_name,
contract_amount, contract_date, bid_method, source_url) + dup_ordinal で
新DBの contracts.id に再リンクする。

  - キー一意       → そのまま適用
  - キー重複・同値 → グループ全行に適用
  - キー重複・異値 → dup_ordinal（id昇順序数）で対応付け
  - 対応不能       → kit/exports/import_ambiguous.json へ
  - 契約行が新DBに無い → kit/exports/import_unmatched.json へ

冪等（INSERT OR REPLACE / OR IGNORE）。--dry-run で書き込みなし確認可。

実行:
  python kit/import_enrichments.py --dry-run
  python kit/import_enrichments.py
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
EXPORTS = PROJECT_ROOT / "kit" / "exports"

NK_FIELDS = ["agency_id", "fiscal_year", "contract_name", "vendor_name",
             "contract_amount", "contract_date", "bid_method", "source_url"]

CONTRACT_COLS = [
    "agency_id", "agency_name", "agency_category", "fiscal_year", "contract_type",
    "contract_name", "vendor_name", "vendor_address", "corporate_number",
    "contract_amount", "estimated_price", "award_rate", "bid_method", "zuii_reason",
    "contract_date", "contract_officer", "quantity", "unit_measure",
    "source_url", "source_type", "category_large", "category_mid", "category_small",
]


def read_jsonl_gz(path: Path):
    """(meta, rows_iterator)。"""
    f = gzip.open(path, "rt", encoding="utf-8")
    meta = json.loads(f.readline())

    def rows():
        with f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
    return meta, rows()


def nk_key(rec: dict) -> tuple:
    return tuple(rec[k] for k in NK_FIELDS)


# ── 自然キー索引 ─────────────────────────────────────────────────────────────

def build_nk_index(con: sqlite3.Connection) -> dict[tuple, list[int]]:
    idx: dict[tuple, list[int]] = defaultdict(list)
    cols = ", ".join(NK_FIELDS)
    for row in con.execute(f"SELECT id, {cols} FROM contracts ORDER BY id"):
        idx[tuple(row[1:])].append(row[0])
    return idx


# ── 各インポーター ───────────────────────────────────────────────────────────

def import_ocr_contracts(con: sqlite3.Connection) -> dict:
    meta, rows = read_jsonl_gz(EXPORTS / "contracts_ocr.jsonl.gz")
    cols = ", ".join(CONTRACT_COLS)
    ph = ",".join("?" * len(CONTRACT_COLS))
    n_in = n_new = 0
    for rec in rows:
        n_in += 1
        con.execute(f"INSERT OR IGNORE INTO contracts ({cols}) VALUES ({ph})",
                    [rec.get(c) for c in CONTRACT_COLS])
        n_new += con.execute("SELECT changes()").fetchone()[0]
    return {"read": n_in, "inserted": n_new}


def import_small_tables(con: sqlite3.Connection) -> dict:
    meta, rows = read_jsonl_gz(EXPORTS / "tables_small.jsonl.gz")
    counts: dict[str, int] = defaultdict(int)
    for rec in rows:
        table = rec.pop("_table")
        cols = list(rec.keys())
        ph = ",".join("?" * len(cols))
        verb = "INSERT OR REPLACE" if table == "fy_budget" else "INSERT OR IGNORE"
        con.execute(f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({ph})",
                    [rec[c] for c in cols])
        counts[table] += con.execute("SELECT changes()").fetchone()[0]
    return dict(counts)


def _resolve_ids(group_rows: list[dict], ids: list[int], payload_keys: list[str],
                 ambiguous: list, unmatched: list) -> list[tuple[int, dict]]:
    """自然キーグループ内の enrichment 行を新IDに対応付ける。"""
    if not ids:
        unmatched.extend(group_rows)
        return []

    payloads = [tuple(r.get(k) for k in payload_keys) for r in group_rows]
    if len(ids) == 1:
        if len(group_rows) == 1:
            return [(ids[0], group_rows[0])]
        # 旧DBで重複していたが新DBでは1行 → 最新(dup_ordinal最大)を採用
        best = max(group_rows, key=lambda r: r.get("dup_ordinal", 1))
        return [(ids[0], best)]

    if len(set(payloads)) == 1:
        # 全行同値 → 新DBの全該当行に適用
        return [(i, group_rows[0]) for i in ids]

    # 異値 → dup_ordinal で位置対応
    out: list[tuple[int, dict]] = []
    for r in group_rows:
        o = r.get("dup_ordinal", 1)
        if 1 <= o <= len(ids):
            out.append((ids[o - 1], r))
        else:
            ambiguous.append(r)
    return out


def _import_nk_table(con: sqlite3.Connection, nk_idx: dict, path: Path,
                     payload_keys: list[str], apply_fn) -> dict:
    """自然キー付き enrichment を読み、apply_fn(contract_id, rec) で投入する。"""
    meta, rows = read_jsonl_gz(path)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    n_read = 0
    for rec in rows:
        groups[nk_key(rec)].append(rec)
        n_read += 1

    ambiguous: list[dict] = []
    unmatched: list[dict] = []
    n_applied = 0
    for key, group_rows in groups.items():
        ids = nk_idx.get(key, [])
        for cid, rec in _resolve_ids(group_rows, ids, payload_keys,
                                     ambiguous, unmatched):
            apply_fn(cid, rec)
            n_applied += 1
    return {"read": n_read, "applied": n_applied,
            "unmatched": unmatched, "ambiguous": ambiguous}


def import_pillar(con: sqlite3.Connection, nk_idx: dict) -> dict:
    keys = ["pillar_l1_code", "pillar_l2_code", "confidence", "match_method",
            "match_source", "updated_at"]

    def apply(cid: int, r: dict) -> None:
        con.execute(
            """INSERT OR REPLACE INTO contract_pillar
               (contract_id, pillar_l1_code, pillar_l2_code, confidence,
                match_method, match_source, fiscal_year, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (cid, r.get("pillar_l1_code"), r.get("pillar_l2_code"),
             r.get("confidence"), r.get("match_method"), r.get("match_source"),
             r.get("fiscal_year"), r.get("updated_at")))

    return _import_nk_table(con, nk_idx, EXPORTS / "enrichments_pillar.jsonl.gz",
                            keys, apply)


def import_requesting_org(con: sqlite3.Connection, nk_idx: dict) -> dict:
    keys = ["requesting_org", "match_source", "confidence"]

    # choutatsuyotei 自然キー → 新DBの id
    chy: dict[tuple, int] = {}
    for cid, fy, sf, sr in con.execute(
            "SELECT id, fiscal_year, source_file, source_row FROM choutatsuyotei"):
        chy[(fy, sf, sr)] = cid

    def apply(cid: int, r: dict) -> None:
        chy_id = None
        if r.get("chy_source_file") is not None:
            chy_id = chy.get((r.get("chy_fiscal_year"), r.get("chy_source_file"),
                              r.get("chy_source_row")))
        con.execute(
            """INSERT OR REPLACE INTO contract_requesting_org
               (contract_id, requesting_org, match_source, choutatsuyotei_id,
                confidence)
               VALUES (?,?,?,?,?)""",
            (cid, r.get("requesting_org"), r.get("match_source"), chy_id,
             r.get("confidence")))

    return _import_nk_table(con, nk_idx,
                            EXPORTS / "enrichments_requesting_org.jsonl.gz",
                            keys, apply)


def import_equipment(con: sqlite3.Connection, nk_idx: dict) -> dict:
    meta, rows = read_jsonl_gz(EXPORTS / "enrichments_equipment.jsonl.gz")
    groups: dict[tuple, list[dict]] = defaultdict(list)
    n_master = n_read = 0
    for rec in rows:
        table = rec.pop("_table")
        if table == "equipment_master":
            cols = list(rec.keys())
            con.execute(
                f"INSERT OR REPLACE INTO equipment_master ({', '.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [rec[c] for c in cols])
            n_master += 1
        else:
            groups[nk_key(rec)].append(rec)
            n_read += 1

    ambiguous: list[dict] = []
    unmatched: list[dict] = []
    n_applied = 0
    for key, group_rows in groups.items():
        ids = nk_idx.get(key, [])
        for cid, rec in _resolve_ids(group_rows, ids,
                                     ["equipment_id", "confidence"],
                                     ambiguous, unmatched):
            con.execute(
                "INSERT OR REPLACE INTO contract_equipment "
                "(contract_id, equipment_id, confidence) VALUES (?,?,?)",
                (cid, rec.get("equipment_id"), rec.get("confidence")))
            n_applied += 1
    return {"read": n_read, "master": n_master, "applied": n_applied,
            "unmatched": unmatched, "ambiguous": ambiguous}


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="判定結果のインポート")
    parser.add_argument("--dry-run", action="store_true",
                        help="トランザクションをロールバック（書き込みなし）")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")

    all_unmatched: dict[str, list] = {}
    all_ambiguous: dict[str, list] = {}

    print("=== 1/5 OCR由来契約行 ===")
    r = import_ocr_contracts(con)
    print(f"  read={r['read']} inserted={r['inserted']}")

    print("=== 2/5 小テーブル（fy_budget/kenkyuu_hyouka/choutatsuyotei）===")
    r = import_small_tables(con)
    print(f"  {r}")

    print("=== 自然キー索引構築 ===")
    nk_idx = build_nk_index(con)
    print(f"  contracts {sum(len(v) for v in nk_idx.values()):,}行 / "
          f"{len(nk_idx):,}キー")

    print("=== 3/5 contract_pillar ===")
    r = import_pillar(con, nk_idx)
    print(f"  read={r['read']:,} applied={r['applied']:,} "
          f"unmatched={len(r['unmatched'])} ambiguous={len(r['ambiguous'])}")
    all_unmatched["pillar"] = r["unmatched"]
    all_ambiguous["pillar"] = r["ambiguous"]

    print("=== 4/5 contract_requesting_org ===")
    r = import_requesting_org(con, nk_idx)
    print(f"  read={r['read']:,} applied={r['applied']:,} "
          f"unmatched={len(r['unmatched'])} ambiguous={len(r['ambiguous'])}")
    all_unmatched["requesting_org"] = r["unmatched"]
    all_ambiguous["requesting_org"] = r["ambiguous"]

    print("=== 5/5 equipment ===")
    r = import_equipment(con, nk_idx)
    print(f"  master={r['master']} read={r['read']:,} applied={r['applied']:,} "
          f"unmatched={len(r['unmatched'])} ambiguous={len(r['ambiguous'])}")
    all_unmatched["equipment"] = r["unmatched"]
    all_ambiguous["equipment"] = r["ambiguous"]

    if args.dry_run:
        con.rollback()
        print("[DRY-RUN] ロールバックしました（DB無変更）")
    else:
        con.commit()
    con.close()

    (EXPORTS / "import_unmatched.json").write_text(
        json.dumps({"ts": datetime.now().isoformat(),
                    **{k: v for k, v in all_unmatched.items()}},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (EXPORTS / "import_ambiguous.json").write_text(
        json.dumps({"ts": datetime.now().isoformat(),
                    **{k: v for k, v in all_ambiguous.items()}},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    n_un = sum(len(v) for v in all_unmatched.values())
    n_am = sum(len(v) for v in all_ambiguous.values())
    print(f"SUMMARY unmatched={n_un} ambiguous={n_am} "
          f"(詳細: kit/exports/import_unmatched.json / import_ambiguous.json)")
    sys.exit(0)


if __name__ == "__main__":
    main()
