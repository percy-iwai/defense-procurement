"""月次更新（編集者の環境＝ローカルPC or Cowork で手動実行）。

運用: 編集者ローカルの既存 procurement.db に、今月の新規公表分だけ追記(増分)
→ 7本柱分類 → 配布用 Excel/CSV を出力。出力した xlsx だけを SharePoint/Teams に
手動アップロード（DBはローカル保持。SharePointへ戻さない）。

【前提】data/db/procurement.db が「先月の状態」として編集者ローカルに在ること
        （なければ初回のみ kit/rebuild_all.py でフル構築）

実行:
  python kit/update_monthly.py                 # 当年度を対象に増分収集→分類→出力
  python kit/update_monthly.py --fy 2026        # 対象年度を明示
  python kit/update_monthly.py --deep           # 要求元の再計算(recompute)も実施(重い)
  python kit/update_monthly.py --collect-only    # 収集だけ（出力しない）

各ステップは INSERT OR IGNORE で冪等。途中で止めても再実行で続きから。
出力: kit/out/防衛調達ダッシュボード.xlsx / contracts.csv
終了コード: 0=成功 / 1=失敗ステップあり（logs/monthly/ 参照）
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"
LOG_DIR = PROJECT_ROOT / "logs" / "monthly"
PY = sys.executable


def current_fy() -> int:
    t = date.today()
    return t.year if t.month >= 4 else t.year - 1


def contracts_count() -> int:
    with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as c:
        return c.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]


def run(name: str, cmd: list[str]) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"{name}.log"
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    import os
    full_env = {**os.environ, **env}
    with log.open("w", encoding="utf-8", errors="replace") as f:
        rc = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=f,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=full_env).returncode
    print(f"  [{'OK ' if rc == 0 else 'FAIL'}] {name} -> {log.name}")
    return rc


def main() -> None:
    ap = argparse.ArgumentParser(description="月次増分更新")
    ap.add_argument("--fy", type=int, default=current_fy())
    ap.add_argument("--deep", action="store_true", help="要求元recomputeも実施(重い)")
    ap.add_argument("--collect-only", action="store_true")
    args = ap.parse_args()
    fy = args.fy

    if not DB.exists():
        sys.exit("procurement.db がありません。SharePointから配置するか、"
                 "初回は kit/rebuild_all.py を実行してください。")

    before = contracts_count()
    print(f"開始: contracts={before:,} 件 / 対象年度 FY{fy}")

    # 安全バックアップ（追記前）
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    bak = BACKUP_DIR / f"procurement_pre_monthly_{datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(DB, bak)
    print(f"バックアップ: {bak.name}")

    failed: list[str] = []

    # ── 1. 増分収集（ライブから新規公表分。INSERT OR IGNORE で既存はスキップ）──
    print("== 収集（増分・ライブ）==")
    collectors = [
        ("load_atla", [PY, "-m", "pipeline.load_atla", "--fy", str(fy)]),
        ("load_atla_sub", [PY, "-m", "pipeline.load_atla_sub"]),
        ("load_msdf", [PY, "-m", "pipeline.load_msdf"]),
        ("load_gsdf", [PY, "-m", "pipeline.load_gsdf"]),
        ("load_asdf", [PY, "-m", "pipeline.load_asdf"]),
        ("load_rdb", [PY, "-m", "pipeline.load_rdb"]),
        ("load_misc", [PY, "-m", "pipeline.load_misc"]),
        ("crawl_warp_fy", [PY, "-m", "pipeline.crawl_warp_fy", "--all", "--fy", str(fy)]),
    ]
    for name, cmd in collectors:
        if run(name, cmd) != 0:
            failed.append(name)

    after_collect = contracts_count()
    print(f"収集後: contracts={after_collect:,} 件（+{after_collect - before:,}）")

    if args.collect_only:
        _finish(before, after_collect, failed, skipped_export=True)
        return

    # ── 2. 7本柱分類（キーワード・CPU。新規行も含め再付与）──
    print("== 7本柱分類 ==")
    if run("assign_pillar", [PY, "dev/assign_pillar_fy2023.py", "--fy", str(fy)]) != 0:
        failed.append("assign_pillar")

    # ── 3. 要求元（任意・重い）──
    if args.deep:
        print("== 要求元 recompute（deep）==")
        if run("recompute_org", [PY, "dev/recompute_atla_requesting_org.py"]) != 0:
            failed.append("recompute_org")

    # ── 4. pillar 健全性チェック（破損検知）──
    rc = subprocess.run([PY, "kit/repair_contract_pillar.py", "--check"],
                        cwd=PROJECT_ROOT).returncode
    if rc != 0:
        print("  ⚠️ contract_pillar に破損の疑い → kit/repair_contract_pillar.py --in-place を検討")

    # ── 5. 配布用 出力 ──
    print("== 出力（Excel/CSV）==")
    if run("export_tables", [PY, "kit/export_tables.py"]) != 0:
        failed.append("export_tables")
    if run("dashboard", [PY, "kit/make_dashboard_xlsx.py"]) != 0:
        failed.append("dashboard")

    _finish(before, contracts_count(), failed)


def _finish(before: int, after: int, failed: list[str], skipped_export=False) -> None:
    print("=" * 56)
    print(f"SUMMARY before={before} after={after} added={after - before} "
          f"failed={failed or 'なし'}")
    if not skipped_export:
        print("成果物: kit/out/防衛調達ダッシュボード.xlsx, kit/out/contracts.csv")
    print("→ 次の手順: kit/out のxlsxだけ SharePoint/Teams に上書きアップロード。")
    print("  procurement.db は編集者ローカルに置いたままでOK（次月もここから増分）。")
    print("  ※たまにDBをSharePoint等へ安全コピーしておくと、PC故障時も安心。")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
