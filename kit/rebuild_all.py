"""新環境でのDB再構築オーケストレーター。

前提:
  1. kit/downloader.py --replay 済み（data/raw/_cache/ が温まっている）
     → 各ローダーはキャッシュヒットでオフライン再生される
  2. data/db/url_matrix.db / data/manual/ が存在する（git同梱）

実行順:
  各ステップを subprocess で隔離実行し、logs/rebuild/<step>.log に出力を保存、
  ステップ前後の contracts 行数を kit/exports/rebuild_log.json に記録する。
  途中で落ちても再実行すれば INSERT OR IGNORE により安全に継続できる（冪等）。

使い方:
  python kit/rebuild_all.py                  # 全ステップ
  python kit/rebuild_all.py --list           # ステップ一覧表示
  python kit/rebuild_all.py --steps 1,2,5    # 指定ステップのみ
  python kit/rebuild_all.py --from-step 6    # 6以降を実行

終了コード: 0=全ステップ成功 / 1=失敗ステップあり（ログ参照）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
SCHEMA = PROJECT_ROOT / "kit" / "exports" / "schema_full.sql"
LOG_DIR = PROJECT_ROOT / "logs" / "rebuild"
REBUILD_LOG = PROJECT_ROOT / "kit" / "exports" / "rebuild_log.json"

PY = sys.executable

# (番号, 名前, コマンド, 説明)
STEPS: list[tuple[int, str, list[str], str]] = [
    (1, "init_schema", [], "schema_full.sql で空DBを作成（既存DBがあればスキップ）"),
    (2, "load_atla", [PY, "-m", "pipeline.load_atla",
                      "--fy", "2022", "2023", "2024", "2025"],
     "防衛装備庁 中央調達"),
    (3, "load_atla_sub", [PY, "-m", "pipeline.load_atla_sub"], "装備庁サブ機関"),
    (4, "load_msdf", [PY, "-m", "pipeline.load_msdf"], "海上自衛隊"),
    (5, "load_gsdf", [PY, "-m", "pipeline.load_gsdf"], "陸上自衛隊"),
    (6, "load_asdf", [PY, "-m", "pipeline.load_asdf"], "航空自衛隊"),
    (7, "load_rdb", [PY, "-m", "pipeline.load_rdb"], "地方防衛局"),
    (8, "load_misc", [PY, "-m", "pipeline.load_misc"],
     "内局・統幕・情報本部・防衛医大・研究所・防衛大"),
    (9, "load_igo", [PY, "-m", "pipeline.load_igo"], "防衛監察本部等"),
    (10, "load_eadep_nadep_warp", [PY, "-m", "pipeline.load_eadep_nadep_warp"],
     "東北方面/北海道補給処 WARP"),
    (11, "crawl_warp_fy", [PY, "-m", "pipeline.crawl_warp_fy",
                           "--all", "--fy", "2022", "2023", "2024", "2025"],
     "url_matrix起点のFY横断クロール（キャッシュ再生）"),
    (12, "load_from_urlmatrix", [PY, "-m", "pipeline.load_from_urlmatrix"],
     "url_matrix未収録URLの汎用収集"),
    (13, "replay_load_gaps", [PY, "kit/replay_load.py"],
     "期待値に満たないURLの直接リプレイ（ギャップフィル）"),
    (14, "import_enrichments", [PY, "kit/import_enrichments.py"],
     "pillar/要求元/装備品/OCR契約/小テーブルのインポート"),
    (15, "load_equipment_master", [PY, "-m", "pipeline.load_equipment_master"],
     "装備品マスター（import済みならスキップ可）"),
    (16, "verify", [PY, "kit/verify_rebuild.py"], "期待値との突合"),
    (17, "export_tables", [PY, "kit/export_tables.py"],
     "CSV/XLSX 出力（kit/out/。スタンドアロン成果物）"),
]

# OCR系ローダー（load_asdf_ocr / load_misawa_ocr）は意図的に含めない。
# OCR由来415件は import_enrichments が contracts_ocr.jsonl.gz から投入する。


def contracts_count() -> int | None:
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as con:
            return con.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    except sqlite3.DatabaseError:
        return None


def init_schema() -> tuple[bool, str]:
    if DB_PATH.exists() and (contracts_count() or 0) > 0:
        return True, "既存DBあり → スキップ（作り直す場合はDBファイルを退避してから再実行）"
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    sql = SCHEMA.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(sql)
    return True, f"created {DB_PATH}"


def run_step(num: int, name: str, cmd: list[str]) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{num:02d}_{name}.log"
    before = contracts_count()
    t0 = time.monotonic()

    if name == "init_schema":
        ok, msg = init_schema()
        log_file.write_text(msg, encoding="utf-8")
        rc = 0 if ok else 1
    else:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        with log_file.open("w", encoding="utf-8", errors="replace") as lf:
            proc = subprocess.run(
                cmd, cwd=PROJECT_ROOT, stdout=lf, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env)
            rc = proc.returncode

    after = contracts_count()
    rec = {
        "step": num, "name": name, "returncode": rc,
        "contracts_before": before, "contracts_after": after,
        "added": (after - before) if (after is not None and before is not None) else None,
        "elapsed_sec": round(time.monotonic() - t0, 1),
        "log": str(log_file),
        "ts": datetime.now().isoformat(),
    }
    status = "OK " if rc == 0 else "FAIL"
    print(f"[{status}] step {num:2d} {name:<24} +{rec['added'] or 0:>7,}行 "
          f"({rec['elapsed_sec']:.0f}s) -> {log_file.name}")
    return rec


def main() -> None:
    parser = argparse.ArgumentParser(description="DB再構築オーケストレーター")
    parser.add_argument("--steps", help="カンマ区切りのステップ番号（例: 1,2,5）")
    parser.add_argument("--from-step", type=int, help="この番号以降を実行")
    parser.add_argument("--list", action="store_true", help="ステップ一覧を表示")
    args = parser.parse_args()

    if args.list:
        for num, name, _, desc in STEPS:
            print(f"  {num:2d}. {name:<24} {desc}")
        return

    selected = STEPS
    if args.steps:
        nums = {int(s) for s in args.steps.split(",")}
        selected = [s for s in STEPS if s[0] in nums]
    elif args.from_step:
        selected = [s for s in STEPS if s[0] >= args.from_step]

    results: list[dict] = []
    if REBUILD_LOG.exists():
        try:
            results = json.loads(REBUILD_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = []

    failed: list[str] = []
    for num, name, cmd, _desc in selected:
        rec = run_step(num, name, cmd)
        results.append(rec)
        REBUILD_LOG.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        if rec["returncode"] != 0:
            failed.append(name)

    total = contracts_count()
    print(f"\nSUMMARY contracts={total:,} failed_steps={failed or 'なし'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
