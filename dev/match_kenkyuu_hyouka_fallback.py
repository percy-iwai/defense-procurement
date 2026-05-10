"""fallback_atla 残存契約を kenkyuu_hyouka テーブルの事業名で追加解決する。

政策評価書の担当部局は全件 ATLA（防衛装備庁）のため、
要求元（GSDF/MSDF/ASDF/JS/DIH）は事業名キーワードから推定する
（match_jigyou_review_fallback.py と同じ _infer_org_from_project() を利用）。

2段階アプローチ:
  1. 全文部分一致: 事業名 ⊆ 契約名 (or vice versa)
  2. キーワード抽出: 事業名から装備品名を抽出して照合

match_source = 'kenkyuu_hyouka', confidence = 0.70 でUPDATE。

使い方:
    python dev/match_kenkyuu_hyouka_fallback.py --dry-run
    python dev/match_kenkyuu_hyouka_fallback.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加（スクリプト直接実行時）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# match_jigyou_review_fallback から共通ロジックを再利用
from dev.match_jigyou_review_fallback import (
    nfkc,
    _extract_project_terms,
    _build_keyword_index,
    match_contracts,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCUREMENT_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"
LOG_DIR = PROJECT_ROOT / "logs"
TMP_DB = Path("C:/tmp/procurement_kenkyuu_work.db")

CONFIDENCE = 0.70
MATCH_SOURCE = "kenkyuu_hyouka"


def load_kenkyuu_projects() -> list[dict]:
    """kenkyuu_hyouka テーブルから事業を読み込む。

    tantou_org を DB から直接使用する。ATLA / NAIKYOKU は fallback_atla の
    要求元を変えないため除外。NULL も除外。
    """
    con = sqlite3.connect(PROCUREMENT_DB)
    rows = con.execute(
        """SELECT jigyou_name, jigyou_name_norm, tantou_org
           FROM kenkyuu_hyouka
           WHERE tantou_org IS NOT NULL
             AND tantou_org NOT IN ('ATLA', 'NAIKYOKU')"""
    ).fetchall()
    con.close()

    projects: list[dict] = []
    for jigyou_name, jigyou_name_norm, tantou_org in rows:
        if not jigyou_name:
            continue
        name_n = nfkc(jigyou_name)
        if len(name_n) < 6:
            continue
        terms = _extract_project_terms(name_n)
        projects.append({
            "name": jigyou_name,
            "name_norm": name_n,
            "org": tantou_org,
            "conf": CONFIDENCE,
            "terms": terms,
        })

    projects.sort(key=lambda p: len(p["name_norm"]), reverse=True)
    return projects


def run(dry_run: bool = False) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"procurement_pre_kenkyuu_{ts}.db"
        shutil.copy2(PROCUREMENT_DB, backup_path)
        TMP_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROCUREMENT_DB, TMP_DB)
        work_db = TMP_DB
    else:
        work_db = PROCUREMENT_DB

    con = sqlite3.connect(work_db)

    contracts: list[tuple[int, str, int]] = con.execute(
        """
        SELECT c.id, c.contract_name, COALESCE(c.fiscal_year, 0)
        FROM contracts c
        JOIN contract_requesting_org cro ON c.id = cro.contract_id
        WHERE cro.match_source = 'fallback_atla'
        """
    ).fetchall()

    before_count = len(contracts)
    projects = load_kenkyuu_projects()
    kw_index = _build_keyword_index(projects)
    matches = match_contracts(contracts, projects)

    org_counter: Counter[str] = Counter(m[1] for m in matches)
    method_counter: Counter[str] = Counter(m[3].split(":")[0] for m in matches)

    if not dry_run and matches:
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        for contract_id, org, conf, _desc in matches:
            cur.execute(
                """
                UPDATE contract_requesting_org
                SET requesting_org = ?, match_source = ?, confidence = ?
                WHERE contract_id = ? AND match_source = 'fallback_atla'
                """,
                (org, MATCH_SOURCE, conf, contract_id),
            )
        con.execute("COMMIT")

    con.close()

    if not dry_run and matches:
        shutil.copy2(TMP_DB, PROCUREMENT_DB)
        TMP_DB.unlink(missing_ok=True)

    # サンプルリスト（全マッチ）
    p2 = sqlite3.connect(PROCUREMENT_DB)
    match_details = []
    for cid, org, conf, desc in matches:
        row = p2.execute(
            "SELECT contract_name, fiscal_year FROM contracts WHERE id=?", (cid,)
        ).fetchone()
        if row:
            match_details.append({
                "contract_id": cid,
                "contract_name": row[0],
                "fiscal_year": row[1],
                "org": org,
                "conf": conf,
                "match_desc": desc,
            })
    p2.close()

    result = {
        "dry_run": dry_run,
        "before_fallback_atla": before_count,
        "resolved": len(matches),
        "remaining_fallback_atla": before_count - len(matches),
        "org_breakdown": dict(org_counter),
        "method_breakdown": dict(method_counter),
        "kenkyuu_projects_with_inferred_org": len(projects),
        "kw_index_size": len(kw_index),
        "match_details": match_details,
    }

    if not dry_run:
        log_path = LOG_DIR / f"match_kenkyuu_hyouka_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ログ: {log_path}")

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}kenkyuu_hyouka マッチング結果")
    print(f"  fallback_atla 件数 (前): {before_count}")
    print(f"  解決件数             : {len(matches)}")
    print(f"  残存 fallback_atla   : {before_count - len(matches)}")
    print(f"  要求元内訳: {dict(org_counter)}")
    print(f"  手法内訳: {dict(method_counter)}")
    print(f"  kenkyuu org推定可能事業数: {len(projects)}")
    print(f"  キーワードindex size: {len(kw_index)}")

    if match_details:
        detail_path = LOG_DIR / "kenkyuu_hyouka_matches_latest.json"
        detail_path.write_text(
            json.dumps(match_details, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n  全マッチ詳細 → {detail_path}")
        print("\n  マッチ一覧:")
        for d in match_details:
            print(f"    [{d['org']}] FY{d['fiscal_year']} {d['contract_name']!r}")
            print(f"      ← {d['match_desc']!r}")

    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="DB に書き込まない")
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
