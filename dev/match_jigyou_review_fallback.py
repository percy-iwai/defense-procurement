"""fallback_atla 残存契約を jigyou_review.db の事業名で追加解決する。

2段階アプローチ:
  1. 全文部分一致: jigyou_review 事業名 ⊆ 契約名 (or vice versa)
  2. キーワード抽出: 事業名から具体的なシステム名を抽出して照合

match_source = 'jigyou_review', confidence = 0.70 でUPDATE。

使い方:
    python dev/match_jigyou_review_fallback.py --dry-run
    python dev/match_jigyou_review_fallback.py
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCUREMENT_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
JIGYOU_DB = PROJECT_ROOT / "data" / "db" / "jigyou_review.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"
LOG_DIR = PROJECT_ROOT / "logs"
TMP_DB = Path("/tmp/procurement_jigyou_work.db")

CONFIDENCE = 0.70

# ─── 要求元推定キーワード ──────────────────────────────────────────────────────

NAME_ABBR: list[tuple[str, str, float]] = [
    ("（海自）", "MSDF", 0.85), ("（海上）", "MSDF", 0.85),
    ("（陸自）", "GSDF", 0.85), ("（陸上）", "GSDF", 0.85),
    ("（空自）", "ASDF", 0.85), ("（航空）", "ASDF", 0.85),
    ("（統幕）", "JS",   0.85),
]

ORG_NAME_HINTS: list[tuple[str, str, float]] = [
    ("艦船担当", "MSDF", 0.75),
]

NAME_KEYWORDS: list[tuple[str, str, float]] = [
    ("護衛艦",     "MSDF", 0.75), ("潜水艦",      "MSDF", 0.75),
    ("掃海",       "MSDF", 0.75), ("哨戒機",      "MSDF", 0.72),
    ("P-1",        "MSDF", 0.75), ("SH-60",       "MSDF", 0.75),
    ("MCH-101",    "MSDF", 0.75), ("ＭＣＨ－１０１", "MSDF", 0.75),
    ("ＵＳ－２",   "MSDF", 0.75), ("US-2",        "MSDF", 0.75),
    ("戦車",       "GSDF", 0.75), ("自走砲",      "GSDF", 0.75),
    ("火砲",       "GSDF", 0.72), ("地対艦誘導弾", "GSDF", 0.75),
    ("地対空誘導弾", "GSDF", 0.75), ("対戦車",    "GSDF", 0.72),
    ("装甲車",     "GSDF", 0.72),
    ("戦闘機",     "ASDF", 0.75), ("F-35",        "ASDF", 0.80),
    ("Ｆ－３５",   "ASDF", 0.80), ("F-15",        "ASDF", 0.80),
    ("Ｆ－１５",   "ASDF", 0.80), ("JADGE",       "ASDF", 0.80),
    ("自動警戒管制", "ASDF", 0.78), ("警戒管制レーダー", "ASDF", 0.75),
    ("防衛情報通信基盤", "JS", 0.80), ("DII",      "JS",   0.75),
    ("統合指揮",   "JS",   0.72),  ("サイバー防衛", "JS",  0.72),
    ("情報本部",   "DIH",  0.80),  ("地理空間情報", "DIH", 0.75),
]

TEXT_KEYWORDS: dict[str, list[str]] = {
    "GSDF": ["陸上自衛隊", "陸幕", "陸自", "陸上部隊"],
    "MSDF": ["海上自衛隊", "海幕", "海自", "海上部隊"],
    "ASDF": ["航空自衛隊", "空幕", "空自", "航空部隊"],
    "JS":   ["統合幕僚", "統幕"],
    "DIH":  ["情報本部"],
}

# 事業名から抽出するキーワードの除外パターン（汎用語）
_GENERIC_RE = re.compile(
    r"^(諸器材|武器|通信|車両|施設|弾薬|修理|整備|購入|取得|開発|研究|試験|評価|"
    r"支援|運用|訓練|費|経費|等|用品|需品|部品|器材|ハイレベル|政策|交流|対話|"
    r"オーバーホール|システム|装置|機器|アウトソーシング|委託|更新|維持|借上|借料|"
    r"再資源化|廃棄|予託金|措置|態勢|管理|経緯|実動|実施|演習|その他|"
    # 以下は複数軍種・機関に共通するため除外
    r"能力向上|情報収集|技術|分析|調査|検討|計画|実証|実験|事業|機能|体制|基盤)$"
)

# jigyou_review 事業名から具体キーワードを抽出
_SPLIT_RE = re.compile(r"[（）()/／・\s、。\n]")


def nfkc(s: str | None) -> str:
    return unicodedata.normalize("NFKC", s or "")


def _extract_project_terms(name_norm: str) -> list[str]:
    """事業名から具体的な装備品・システム名の候補を抽出する。"""
    # 一般的な末尾句を削除
    for suffix in [
        "の取得", "の整備", "の修理", "の開発", "の研究試作", "の研究",
        "の調達", "の製造", "の換装", "のオーバーホール", "に関する研究",
        "に係る調査", "関連経費", "等費", "費",
    ]:
        name_norm = name_norm.replace(nfkc(suffix), " ")
    # 括弧・記号で分割
    parts = _SPLIT_RE.split(name_norm)
    result: list[str] = []
    for part in parts:
        part = part.strip()
        if len(part) < 4:
            continue
        if _GENERIC_RE.match(part):
            continue
        result.append(part)
    return result


def _infer_org_from_project(
    name: str,
    overview: str | None,
    purpose: str | None,
    organization_name: str | None,
) -> tuple[str | None, float]:
    name_n = nfkc(name)
    combined_text = nfkc((overview or "")[:800] + " " + (purpose or "")[:400])
    org_name = organization_name or ""

    for abbr, org, conf in NAME_ABBR:
        if nfkc(abbr) in name_n:
            return org, conf

    for hint, org, conf in ORG_NAME_HINTS:
        if hint in org_name:
            return org, conf

    matched_by_name: list[tuple[str, float]] = [
        (org, conf) for kw, org, conf in NAME_KEYWORDS if nfkc(kw) in name_n
    ]
    if matched_by_name:
        orgs_in_name = {o for o, _ in matched_by_name}
        if len(orgs_in_name) == 1:
            return max(matched_by_name, key=lambda x: x[1])

    scores: Counter[str] = Counter()
    for org, keywords in TEXT_KEYWORDS.items():
        for kw in keywords:
            if nfkc(kw) in combined_text:
                scores[org] += 1

    if scores:
        top_two = scores.most_common(2)
        if len(top_two) == 1 or top_two[0][1] > top_two[1][1]:
            return top_two[0][0], 0.65

    return None, 0.0


def load_jigyou_projects() -> list[dict]:
    con = sqlite3.connect(JIGYOU_DB)
    rows = con.execute(
        "SELECT name, overview, purpose, organization_name FROM projects"
    ).fetchall()
    con.close()

    projects: list[dict] = []
    for name, overview, purpose, org_name in rows:
        if not name:
            continue
        org, conf = _infer_org_from_project(name, overview, purpose, org_name)
        if org is None:
            continue
        name_n = nfkc(name)
        if len(name_n) < 6:
            continue
        terms = _extract_project_terms(name_n)
        projects.append({
            "name": name,
            "name_norm": name_n,
            "org": org,
            "conf": conf,
            "terms": terms,
        })

    projects.sort(key=lambda p: len(p["name_norm"]), reverse=True)
    return projects


def _build_keyword_index(projects: list[dict]) -> dict[str, str]:
    """事業名から抽出したキーワード → org のマッピングを構築する。
    複数 org に属するキーワードは除外（曖昧）。
    """
    kw_orgs: dict[str, set[str]] = defaultdict(set)
    for proj in projects:
        for term in proj["terms"]:
            kw_orgs[term].add(proj["org"])

    return {
        kw: next(iter(orgs))
        for kw, orgs in kw_orgs.items()
        if len(orgs) == 1
    }


def match_contracts(
    contracts: list[tuple[int, str, int]],
    projects: list[dict],
) -> list[tuple[int, str, float, str]]:
    """fallback_atla 契約を jigyou_review 事業に突合する。

    手法 1: 事業名が契約名の部分列 (or vice versa)
    手法 2: 事業名から抽出したキーワードが契約名に含まれ、org 一意

    Returns: [(contract_id, org, confidence, match_description), ...]
    """
    kw_index = _build_keyword_index(projects)

    results: list[tuple[int, str, float, str]] = []

    for contract_id, contract_name, _fy in contracts:
        cn = nfkc(contract_name)

        # ─── 手法 1: 部分一致 ──────────────────────────────────────────────
        full_matched: list[dict] = []
        for proj in projects:
            pn = proj["name_norm"]
            if pn in cn or (len(cn) >= 6 and cn in pn):
                full_matched.append(proj)

        if full_matched:
            orgs = {m["org"] for m in full_matched}
            if len(orgs) == 1:
                best = max(full_matched, key=lambda m: (m["conf"], len(m["name_norm"])))
                results.append((contract_id, best["org"], CONFIDENCE, f"full_match:{best['name']}"))
                continue

        # ─── 手法 2: キーワード照合 ───────────────────────────────────────
        kw_hits: Counter[str] = Counter()
        kw_hit_names: dict[str, str] = {}
        for kw, org in kw_index.items():
            if kw in cn:
                kw_hits[org] += 1
                kw_hit_names[org] = kw

        if kw_hits:
            top_two = kw_hits.most_common(2)
            if len(top_two) == 1 or top_two[0][1] > top_two[1][1]:
                org = top_two[0][0]
                kw = kw_hit_names[org]
                results.append((contract_id, org, CONFIDENCE, f"kw_match:{kw}"))

    return results


def run(dry_run: bool = False) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"procurement_pre_jigyou_{ts}.db"
        shutil.copy2(PROCUREMENT_DB, backup_path)
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
    projects = load_jigyou_projects()
    kw_index = _build_keyword_index(projects)
    matches = match_contracts(contracts, projects)

    org_counter: Counter[str] = Counter(m[1] for m in matches)
    method_counter: Counter[str] = Counter(
        m[3].split(":")[0] for m in matches
    )

    if not dry_run and matches:
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        for contract_id, org, conf, _desc in matches:
            cur.execute(
                """
                UPDATE contract_requesting_org
                SET requesting_org = ?, match_source = 'jigyou_review', confidence = ?
                WHERE contract_id = ? AND match_source = 'fallback_atla'
                """,
                (org, conf, contract_id),
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
        row = p2.execute("SELECT contract_name, fiscal_year FROM contracts WHERE id=?", (cid,)).fetchone()
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
        "jigyou_projects_with_org": len(projects),
        "kw_index_size": len(kw_index),
        "match_details": match_details,
    }

    if not dry_run:
        log_path = LOG_DIR / f"match_jigyou_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ログ: {log_path}")

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}jigyou_review マッチング結果")
    print(f"  fallback_atla 件数 (前): {before_count}")
    print(f"  解決件数             : {len(matches)}")
    print(f"  残存 fallback_atla   : {before_count - len(matches)}")
    print(f"  要求元内訳: {dict(org_counter)}")
    print(f"  手法内訳: {dict(method_counter)}")
    print(f"  jigyou_review 有効事業数: {len(projects)}")
    print(f"  キーワードindex size: {len(kw_index)}")

    # 全マッチを詳細表示
    if match_details:
        # 結果をファイルに保存
        detail_path = LOG_DIR / "jigyou_review_matches_latest.json"
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
