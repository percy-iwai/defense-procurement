"""引っ越しキット用エクスポート（現環境で実行）。

procurement.db から「データを持ち歩かずに別環境でDBを再現する」ために必要な
最小セットを kit/exports/ に出力する:

  urls_replay.csv                 全 source_url の再ダウンロード用リスト+期待値
  enrichments_pillar.jsonl.gz     contract_pillar 全行（拡張自然キー付き）
  enrichments_requesting_org.jsonl.gz  contract_requesting_org 全行（同上）
  enrichments_equipment.jsonl.gz  contract_equipment + equipment_master
  contracts_ocr.jsonl.gz          source_type='ocr_pdf' の契約行そのもの（OCR再実行不要化）
  tables_small.jsonl.gz           kenkyuu_hyouka / fy_budget / choutatsuyotei
  manual_overrides_natural.json   rowidベース手動修正の自然キー変換（監査証跡）
  expected_state.json             再構築後の突合基準（件数・金額の期待値）
  schema_full.sql                 現DBの全DDL（contract_pillar 等を含む）

拡張自然キー = (agency_id, fiscal_year, contract_name, vendor_name,
                contract_amount, contract_date, bid_method, source_url)
+ dup_ordinal（同一キー内の id 昇順序数。UNIQUE制約がNULLを重複排除しないため必要）

実行:
  python kit/export_kit_data.py            # 全エクスポート
  python kit/export_kit_data.py --only urls,expected  # 一部のみ
  python kit/export_kit_data.py --db path/to/other.db # 別DB（修復済みコピー等）から
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"  # --db で上書き可
OUT_DIR = PROJECT_ROOT / "kit" / "exports"

# 拡張自然キー（contracts の UNIQUE制約 + NULL重複対策の補助列）
NK_FIELDS = [
    "agency_id", "fiscal_year", "contract_name", "vendor_name",
    "contract_amount", "contract_date", "bid_method", "source_url",
]
NK_COLS = ", ".join(f"c.{f}" for f in NK_FIELDS)
NK_PARTITION = ", ".join(f"c.{f}" for f in NK_FIELDS)


def _connect_ro() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _write_jsonl_gz(path: Path, meta: dict, rows_iter) -> int:
    """1行目=メタ、以降1行1レコードのJSONL.gzを書く。行数を返す。"""
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for row in rows_iter:
            f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
            n += 1
    return n


# ── 1. URLリプレイリスト ──────────────────────────────────────────────────────

def export_urls_replay(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT source_url AS url,
               GROUP_CONCAT(DISTINCT source_type) AS source_types,
               GROUP_CONCAT(DISTINCT agency_id)   AS agency_ids,
               MIN(agency_name)                   AS agency_name,
               MIN(agency_category)               AS agency_category,
               MIN(fiscal_year)                   AS fy_min,
               MAX(fiscal_year)                   AS fy_max,
               COUNT(*)                           AS expected_rows
        FROM contracts c
        GROUP BY source_url
        ORDER BY (source_url LIKE 'https://warp.ndl.go.jp/%'
                  OR source_url LIKE 'https://web.archive.org/%') DESC,
                 agency_ids, url
        """
    ).fetchall()
    out = OUT_DIR / "urls_replay.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "source_types", "agency_ids", "agency_name",
                    "agency_category", "fy_min", "fy_max", "expected_rows"])
        for r in rows:
            w.writerow([r["url"], r["source_types"], r["agency_ids"], r["agency_name"],
                        r["agency_category"], r["fy_min"], r["fy_max"], r["expected_rows"]])
    print(f"urls_replay.csv: {len(rows):,} URLs")


# ── 2-3. enrichments（pillar / requesting_org）──────────────────────────────

_NK_SELECT = f"""
    SELECT {NK_COLS},
           ROW_NUMBER() OVER (PARTITION BY {NK_PARTITION} ORDER BY c.id) AS dup_ordinal,
           %s
    FROM %s
    JOIN contracts c ON c.id = t.contract_id
"""


def export_enrichments_pillar(con: sqlite3.Connection) -> None:
    sql = _NK_SELECT % (
        "t.pillar_l1_code, t.pillar_l2_code, t.confidence, t.match_method, "
        "t.match_source, t.updated_at",
        "contract_pillar t",
    )
    n = _write_jsonl_gz(
        OUT_DIR / "enrichments_pillar.jsonl.gz",
        {"kind": "contract_pillar", "nk_fields": NK_FIELDS,
         "exported_at": datetime.now().isoformat()},
        con.execute(sql),
    )
    print(f"enrichments_pillar.jsonl.gz: {n:,} rows")


def export_enrichments_requesting_org(con: sqlite3.Connection) -> None:
    sql = _NK_SELECT % (
        "t.requesting_org, t.match_source, t.confidence, "
        "ch.fiscal_year AS chy_fiscal_year, ch.source_file AS chy_source_file, "
        "ch.source_row AS chy_source_row",
        "contract_requesting_org t "
        "LEFT JOIN choutatsuyotei ch ON ch.id = t.choutatsuyotei_id",
    )
    n = _write_jsonl_gz(
        OUT_DIR / "enrichments_requesting_org.jsonl.gz",
        {"kind": "contract_requesting_org", "nk_fields": NK_FIELDS,
         "chy_nk": ["chy_fiscal_year", "chy_source_file", "chy_source_row"],
         "exported_at": datetime.now().isoformat()},
        con.execute(sql),
    )
    print(f"enrichments_requesting_org.jsonl.gz: {n:,} rows")


def export_enrichments_equipment(con: sqlite3.Connection) -> None:
    sql = _NK_SELECT % (
        "t.equipment_id, t.confidence",
        "contract_equipment t",
    )
    path = OUT_DIR / "enrichments_equipment.jsonl.gz"
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        meta = {"kind": "contract_equipment+equipment_master", "nk_fields": NK_FIELDS,
                "exported_at": datetime.now().isoformat()}
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for row in con.execute("SELECT * FROM equipment_master"):
            f.write(json.dumps({"_table": "equipment_master", **dict(row)},
                               ensure_ascii=False) + "\n")
            n += 1
        for row in con.execute(sql):
            f.write(json.dumps({"_table": "contract_equipment", **dict(row)},
                               ensure_ascii=False) + "\n")
            n += 1
    print(f"enrichments_equipment.jsonl.gz: {n:,} rows")


# ── 4. OCR由来契約行（全列）────────────────────────────────────────────────

def export_contracts_ocr(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT * FROM contracts WHERE source_type = 'ocr_pdf' ORDER BY id"
    )
    n = _write_jsonl_gz(
        OUT_DIR / "contracts_ocr.jsonl.gz",
        {"kind": "contracts_ocr", "note": "source_type='ocr_pdf' 全列。"
         "新環境ではOCRを再実行せずこの行をINSERTする（idは捨てる）",
         "exported_at": datetime.now().isoformat()},
        rows,
    )
    print(f"contracts_ocr.jsonl.gz: {n:,} rows")


# ── 5. 小テーブル ─────────────────────────────────────────────────────────────

def export_small_tables(con: sqlite3.Connection) -> None:
    path = OUT_DIR / "tables_small.jsonl.gz"
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        meta = {"kind": "small_tables",
                "tables": ["fy_budget", "kenkyuu_hyouka", "choutatsuyotei"],
                "exported_at": datetime.now().isoformat()}
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for table in ("fy_budget", "kenkyuu_hyouka", "choutatsuyotei"):
            for row in con.execute(f"SELECT * FROM {table}"):
                f.write(json.dumps({"_table": table, **dict(row)},
                                   ensure_ascii=False) + "\n")
                n += 1
    print(f"tables_small.jsonl.gz: {n:,} rows")


# ── 6. rowidベース手動修正の自然キー変換 ─────────────────────────────────────

def _nk_of_contract(con: sqlite3.Connection, contract_id: int) -> dict | None:
    row = con.execute(
        f"""
        SELECT {NK_COLS},
               (SELECT COUNT(*) FROM contracts c2
                WHERE c2.agency_id IS c.agency_id
                  AND c2.fiscal_year IS c.fiscal_year
                  AND c2.contract_name IS c.contract_name
                  AND c2.vendor_name IS c.vendor_name
                  AND c2.contract_amount IS c.contract_amount
                  AND c2.contract_date IS c.contract_date
                  AND c2.bid_method IS c.bid_method
                  AND c2.source_url IS c.source_url
                  AND c2.id <= c.id) AS dup_ordinal
        FROM contracts c WHERE c.id = ?
        """,
        (contract_id,),
    ).fetchone()
    return dict(row) if row else None


def export_manual_overrides(con: sqlite3.Connection) -> None:
    out: dict = {"exported_at": datetime.now().isoformat(),
                 "note": "rowidベースだった手動修正を拡張自然キーに変換した監査証跡。"
                         "再構築時の適用は enrichments_*.jsonl.gz 経由で行われるため"
                         "通常このファイルの直接インポートは不要。",
                 "pillar_manual_corrections": [],
                 "fallback_50oku_apply": [],
                 "unresolved_ids": []}

    snap_path = PROJECT_ROOT / "data" / "manual" / "manual_corrections_snapshot.json"
    if snap_path.exists():
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        for rowid_str, (l1, l2) in snap.items():
            nk = _nk_of_contract(con, int(rowid_str))
            if nk is None:
                out["unresolved_ids"].append(
                    {"origin": "manual_corrections_snapshot", "contract_id": int(rowid_str)})
                continue
            out["pillar_manual_corrections"].append(
                {**nk, "pillar_l1_code": l1, "pillar_l2_code": l2,
                 "origin_contract_id": int(rowid_str)})

    try:
        from dev.apply_fallback_50oku import APPLY  # 定数のみ（run()はガード済み）
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: apply_fallback_50oku import失敗: {exc}")
        APPLY = []
    for cid, org, conf, src, evidence in APPLY:
        nk = _nk_of_contract(con, cid)
        if nk is None:
            out["unresolved_ids"].append(
                {"origin": "apply_fallback_50oku", "contract_id": cid})
            continue
        out["fallback_50oku_apply"].append(
            {**nk, "requesting_org": org, "confidence": conf,
             "match_source": src, "evidence": evidence, "origin_contract_id": cid})

    path = OUT_DIR / "manual_overrides_natural.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manual_overrides_natural.json: pillar {len(out['pillar_manual_corrections'])} / "
          f"50oku {len(out['fallback_50oku_apply'])} / unresolved {len(out['unresolved_ids'])}")


# ── 7. 期待値（突合基準）──────────────────────────────────────────────────────

def export_expected_state(con: sqlite3.Connection) -> None:
    state: dict = {"generated_at": datetime.now().isoformat(),
                   "db_path": str(DB_PATH)}

    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall()]
    state["table_counts"] = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    state["agency_fy"] = [dict(r) for r in con.execute(
        """SELECT agency_id, fiscal_year,
                  COUNT(*) AS rows, SUM(contract_amount) AS amount_sum
           FROM contracts GROUP BY agency_id, fiscal_year""")]

    state["source_type"] = {r[0] or "NULL": r[1] for r in con.execute(
        "SELECT source_type, COUNT(*) FROM contracts GROUP BY source_type")}

    state["pillar_match_method"] = {r[0]: r[1] for r in con.execute(
        "SELECT match_method, COUNT(*) FROM contract_pillar GROUP BY match_method")}

    state["requesting_org_match_source"] = {r[0]: r[1] for r in con.execute(
        "SELECT match_source, COUNT(*) FROM contract_requesting_org GROUP BY match_source")}

    state["url_rows"] = {r[0]: r[1] for r in con.execute(
        "SELECT source_url, COUNT(*) FROM contracts GROUP BY source_url")}

    state["agencies"] = {r[0]: {"agency_name": r[1], "agency_category": r[2]}
                         for r in con.execute(
        """SELECT agency_id, MIN(agency_name), MIN(agency_category)
           FROM contracts GROUP BY agency_id""")}

    state["url_agency_rows"] = [dict(r) for r in con.execute(
        """SELECT source_url, agency_id, COUNT(*) AS rows
           FROM contracts GROUP BY source_url, agency_id""")]

    state["totals"] = dict(con.execute(
        """SELECT COUNT(*) AS contracts_rows,
                  SUM(contract_amount) AS contracts_amount_sum
           FROM contracts""").fetchone())

    # 孤児行（contractsに親が居ない enrichment 行）はエクスポート対象外のため、
    # 再構築後の突合は JOIN 後の件数を基準にする
    state["enrichment_joined_counts"] = {
        t: con.execute(
            f"SELECT COUNT(*) FROM {t} t JOIN contracts c ON c.id = t.contract_id"
        ).fetchone()[0]
        for t in ("contract_pillar", "contract_requesting_org", "contract_equipment")}

    path = OUT_DIR / "expected_state.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"expected_state.json: contracts {state['totals']['contracts_rows']:,} rows / "
          f"{(state['totals']['contracts_amount_sum'] or 0) / 1e8:,.0f} 億円")


# ── 8. スキーマ ───────────────────────────────────────────────────────────────

def export_schema(con: sqlite3.Connection) -> None:
    ddls = [r[0] for r in con.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name")]
    text = "-- procurement.db full DDL (exported by kit/export_kit_data.py)\n\n"
    text += ";\n\n".join(ddls) + ";\n"
    (OUT_DIR / "schema_full.sql").write_text(text, encoding="utf-8")
    print(f"schema_full.sql: {len(ddls)} DDL statements")


# ── main ─────────────────────────────────────────────────────────────────────

EXPORTERS = {
    "urls":      export_urls_replay,
    "pillar":    export_enrichments_pillar,
    "org":       export_enrichments_requesting_org,
    "equipment": export_enrichments_equipment,
    "ocr":       export_contracts_ocr,
    "small":     export_small_tables,
    "manual":    export_manual_overrides,
    "expected":  export_expected_state,
    "schema":    export_schema,
}


def main() -> None:
    global DB_PATH
    parser = argparse.ArgumentParser(description="引っ越しキット用エクスポート")
    parser.add_argument("--only", help="カンマ区切りで一部のみ実行: "
                        + ",".join(EXPORTERS))
    parser.add_argument("--db", help="エクスポート元DB（既定: data/db/procurement.db）")
    args = parser.parse_args()
    if args.db:
        DB_PATH = Path(args.db).resolve()

    targets = list(EXPORTERS)
    if args.only:
        targets = [t.strip() for t in args.only.split(",") if t.strip()]
        unknown = [t for t in targets if t not in EXPORTERS]
        if unknown:
            parser.error(f"unknown exporter: {unknown}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = _connect_ro()
    try:
        for t in targets:
            EXPORTERS[t](con)
    finally:
        con.close()
    print("export done.")


if __name__ == "__main__":
    main()
