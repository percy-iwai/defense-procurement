"""ATLA中央調達契約 30,659件の要求元を新ロジックで全件再評価する。

優先順位:
  1. agency_rule              (非ATLA agency_id 確定 / ATLAは対象外)
  2. agency_subrule           (ATLAサブ機関 → 全部 ATLA 仮処置, conf=0.5)
  3. choutatsuyotei_exact     (NFKC正規化完全一致 + 単一org, conf=0.9)
  4a. choutatsuyotei_fuzzy    同一FY (conf=0.90)
  4b. choutatsuyotei_fuzzy    Δ1 FY  (conf=0.80)
  4c. choutatsuyotei_fuzzy    Δ2+ FY (conf=0.65)
  4d. manual_analysis         (手動オーバーライド辞書, conf=0.85)
  6. collision_month          (exact複数org → 契約月一致, conf=0.7)
  7. collision_majority       (exact複数org → 多数決, conf=0.5)
  7.5. equipment_master_branch (装備品 branch が GSDF/MSDF/ASDF, conf=0.7)
                               JOINT は要求元不明扱いでスキップ
  8. fms_vendor_heuristic     (米陸/海/空 → GSDF/MSDF/ASDF, conf=0.5)
  8.5a. name_keyword          (契約名キーワード → 各軍種/情報本部/統幕, conf=0.70-0.75)
  8.5b. joint_equipment_explicit (JOINT装備品IDの明示的org割当, conf=0.65-0.70)
  9. fallback_atla            (残存, conf=0.3)

廃止: vendor_majority（重工は要求元べったりではない）

使い方:
    python dev/recompute_atla_requesting_org.py --dry-run --workers 14
    python dev/recompute_atla_requesting_org.py --workers 14
    python dev/recompute_atla_requesting_org.py --skip-backup --workers 14
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pickle
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "db" / "backup"
LOG_DIR = PROJECT_ROOT / "logs"

sys.path.insert(0, str(PROJECT_ROOT / "dev"))
from fill_requesting_org_fy2022_2024 import (  # noqa: E402
    AGENCY_RULES,
    _PUNCT_RE,
    _resolve_agency,
    normalize_item_name,
)
from manual_atla_overrides import find_manual_override  # noqa: E402

# ─── FMS ベンダー前方一致 → 軍種推定 ────────────────────────────────────────
FMS_VENDOR_PREFIX: tuple[tuple[str, str], ...] = (
    ("米陸軍省", "GSDF"),
    ("米海軍省", "MSDF"),
    ("米空軍省", "ASDF"),
)

# ─── 8.5a: 契約名 直接証拠キーワード → org ──────────────────────────────────
# 組織名・部隊名が契約名に「明示」されている場合。「運用者」推論ではない直接証拠。
# source='name_keyword', conf=0.75
NAME_EXPLICIT_ORG_RULES: list[tuple[str, list[str]]] = [
    ("MSDF", ["海上自衛隊", "海幕", "海自"]),
    ("GSDF", ["陸上自衛隊", "陸幕", "陸自"]),
    ("ASDF", ["航空自衛隊", "空幕", "空自"]),
    ("JS",   ["統合指揮", "統幕"]),
    ("DIH",  ["情報本部"]),
]
_NAME_EXPLICIT_NORM: list[tuple[str, list[str]]] = [
    (org, [unicodedata.normalize("NFKC", kw) for kw in kws])
    for org, kws in NAME_EXPLICIT_ORG_RULES
]

# ─── 8.5b: 契約名 推論キーワード → org ──────────────────────────────────────
# 「システム名/装備品名 → 運用者 → 要求元」の間接推論。
# 運用者≠要求元の場合があることを承知の上で適用（特にJOINT系・FMS系は要注意）。
# source='ref_url_inference', conf=0.50
NAME_INFERRED_ORG_RULES: list[tuple[str, list[str]]] = [
    # MSDF: MSII（海自主要情報処理システム）・艦艇系
    ("MSDF", ["MSII", "艦艇搭載", "非貫通式潜望鏡", "潜水艦", "護衛艦"]),
    # GSDF: 陸上装備品
    ("GSDF", ["地対艦誘導弾", "地対地誘導弾", "10式戦車", "16式機動戦闘車"]),
    # ASDF: JADGE・宇宙関連（宇宙は要求元が統幕・情報本部の可能性あり）
    ("ASDF", ["自動警戒管制", "JADGE", "宇宙状況監視", "宇宙状況把握", "空対艦", "空対地"]),
    # JS: 統幕管理インフラ（DII・中央クラウド・サイバー防衛）
    ("JS", ["サイバー防衛", "サイバー演習", "サイバー防護分析",
            "防衛セキュリティゲートウェイ", "中央クラウド", "防衛情報通信基盤",
            "中央指揮システム", "Xバンド防衛通信衛星"]),
    # DIH: 地理空間・情報収集（情報本部との紐付けはchoutatsuyotei確認済み）
    ("DIH", ["地理空間情報支援", "総合解析システム", "総合解析装置",
             "次期電子情報収集機", "GRQ"]),
]
_NAME_INFERRED_NORM: list[tuple[str, list[str]]] = [
    (org, [unicodedata.normalize("NFKC", kw) for kw in kws])
    for org, kws in NAME_INFERRED_ORG_RULES
]

# ─── 8.5c: JOINT equipment_id → org（運用者→要求元 推論）────────────────────
# 全て「運用者から要求元を推論」する間接推論。
# source='ref_url_inference', conf=0.50
# 運用者≠要求元となる可能性があるもの（特に宇宙系・通信衛星系）は注意。
JOINT_EQUIPMENT_INFERRED_ORG: dict[str, str] = {
    "joint_jadge":          "ASDF",  # JADGE = 空自自動警戒管制（要求元=空幕）
    "joint_ssa":            "ASDF",  # SSA衛星 = 空自宇宙作戦群（要求元が統幕の可能性あり）
    "joint_geospatial":     "DIH",   # 地理空間情報支援 = 情報本部（確認済み）
    "joint_sogo_kaiseki":   "DIH",   # 総合解析 = 情報本部
    "joint_dics":           "DIH",   # 情報本部共通基盤
    "joint_sec_gw":         "JS",    # セキュリティGW = 統幕サイバー
    "joint_cyber_def":      "JS",    # サイバー防護分析 = 統幕
    "joint_cyber_sim":      "JS",    # サイバー演習 = 統幕
    "joint_ccs":            "JS",    # 中央指揮システム = 統幕
    "joint_xband_kirameki": "JS",    # Xバンド通信衛星きらめき = 統幕
}

# ─── ATLA agency_id 判定 ────────────────────────────────────────────────────
def _is_atla_agency(aid: str | None) -> bool:
    if not aid:
        return False
    a = aid.lower()
    return a == "atla" or a.startswith("atla_")


# ─── データクラス ────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ChyEntry:
    chy_id: int
    org: str
    fiscal_year: int
    contract_month: Optional[int]


@dataclass(frozen=True, slots=True)
class Contract:
    cid: int
    name: str
    vendor: Optional[str]
    contract_date: Optional[str]
    fiscal_year: int
    agency_id: str


# ─── index 構築 ──────────────────────────────────────────────────────────────
def _load_chy_global_index(con: sqlite3.Connection) -> dict[str, list[ChyEntry]]:
    """全FYのchoutatsuyoteiを norm → list[ChyEntry] にindex化。"""
    idx: dict[str, list[ChyEntry]] = {}
    for cid, norm, org, fy, month in con.execute(
        "SELECT id, item_name_norm, requesting_org, fiscal_year, contract_month "
        "FROM choutatsuyotei"
    ):
        if not norm:
            continue
        idx.setdefault(norm, []).append(
            ChyEntry(chy_id=cid, org=org, fiscal_year=fy, contract_month=month)
        )
    return idx


def _build_fuzzy_index(
    chy_idx: dict[str, list[ChyEntry]],
) -> list[tuple[str, str, tuple[int, ...], int]]:
    """list[(norm, org, fys_tuple, sample_chy_id)]。

    全FY横断で単一orgの norm のみ採用（誤マッチ防止）。
    fys_tuple は その norm が登場する全FYのソート済みタプル（→FY-delta算出用）。
    norm 長さ降順にソート。
    """
    out: list[tuple[str, str, tuple[int, ...], int]] = []
    for norm, entries in chy_idx.items():
        if len(norm) < 4:
            continue
        orgs = {e.org for e in entries}
        if len(orgs) != 1:
            continue  # 全FY横断で複数org → fuzzy には使わない
        org = next(iter(orgs))
        fys = tuple(sorted({e.fiscal_year for e in entries}))
        sample_id = entries[0].chy_id
        out.append((norm, org, fys, sample_id))
    out.sort(key=lambda x: -len(x[0]))
    return out


def _load_equipment_branch_map(con: sqlite3.Connection) -> dict[int, str]:
    """contract_id → equipment branch（GSDF/MSDF/ASDF のみ、JOINT は除外）。
    1契約に複数 equipment_id が紐付く場合は branch 多数決。
    """
    rows = con.execute(
        """SELECT ce.contract_id, em.branch
           FROM contract_equipment ce
           JOIN equipment_master em ON em.equipment_id = ce.equipment_id
           WHERE em.branch IN ('GSDF', 'MSDF', 'ASDF')"""
    ).fetchall()
    by_cid: dict[int, Counter] = {}
    for cid, branch in rows:
        by_cid.setdefault(cid, Counter())[branch] += 1
    return {cid: cnt.most_common(1)[0][0] for cid, cnt in by_cid.items()}


def _load_joint_equipment_inferred_map(
    con: sqlite3.Connection,
) -> dict[int, str]:
    """contract_id → org for JOINT equipment_ids with operator-inferred org.

    全て「運用者→要求元」の間接推論。conf=0.50, source='ref_url_inference'。
    1契約に複数のJOINT equipmentが紐付く場合、全org一致のときのみ採用。
    """
    eq_ids = list(JOINT_EQUIPMENT_INFERRED_ORG.keys())
    if not eq_ids:
        return {}
    placeholders = ",".join("?" * len(eq_ids))
    rows = con.execute(
        f"SELECT contract_id, equipment_id FROM contract_equipment "
        f"WHERE equipment_id IN ({placeholders})",
        eq_ids,
    ).fetchall()
    by_cid: dict[int, list[str]] = {}
    for cid, eq_id in rows:
        if eq_id in JOINT_EQUIPMENT_INFERRED_ORG:
            by_cid.setdefault(cid, []).append(JOINT_EQUIPMENT_INFERRED_ORG[eq_id])
    result: dict[int, str] = {}
    for cid, orgs_list in by_cid.items():
        orgs = set(orgs_list)
        if len(orgs) == 1:
            result[cid] = next(iter(orgs))
    return result


def _load_atla_contracts(con: sqlite3.Connection) -> list[Contract]:
    rows = con.execute(
        """SELECT id, contract_name, vendor_name, contract_date, fiscal_year, agency_id
           FROM contracts
           WHERE agency_id = 'atla' OR agency_id LIKE 'atla\\_%' ESCAPE '\\'"""
    ).fetchall()
    return [
        Contract(cid=r[0], name=r[1] or "", vendor=r[2], contract_date=r[3],
                 fiscal_year=r[4], agency_id=r[5])
        for r in rows
    ]


# ─── マッチング関数（ワーカー側で呼ぶ純粋関数） ────────────────────────────
def _contract_month_fy(contract_date: str | None) -> tuple[int | None, int | None]:
    """(暦月, 会計月) を返す。"""
    if not contract_date or len(contract_date) < 6:
        return (None, None)
    s = contract_date.replace("-", "").replace("/", "")
    try:
        m = int(s[4:6])
        return (m, m if m >= 4 else m + 12)
    except (ValueError, IndexError):
        return (None, None)


def _match_chy_exact(norm: str, idx: dict[str, list[ChyEntry]]) -> tuple[str, int] | None:
    """全FY統合 norm 完全一致 + 単一org → (org, chy_id)。"""
    if not norm or norm not in idx:
        return None
    cands = idx[norm]
    orgs = {c.org for c in cands}
    if len(orgs) == 1:
        return (next(iter(orgs)), cands[0].chy_id)
    return None


def _match_chy_fuzzy(
    norm: str,
    fuzzy_index: list[tuple[str, str, tuple[int, ...], int]],
    contract_fy: int,
) -> tuple[str, int, float, int] | None:
    """全FY横断で単一org判定済みの index に対し substring fuzzy 探索。
    最初のヒットの最近傍FYで confidence を決定。
    Returns (org, chy_id, conf, matched_fy)。
    """
    if not norm or len(norm) < 4:
        return None
    for chy_norm, chy_org, chy_fys, chy_id in fuzzy_index:
        if chy_norm in norm or norm in chy_norm:
            min_delta = min(abs(fy - contract_fy) for fy in chy_fys)
            matched_fy = min(chy_fys, key=lambda f: abs(f - contract_fy))
            if min_delta == 0:
                conf = 0.90
            elif min_delta == 1:
                conf = 0.80
            else:
                conf = 0.65
            return (chy_org, chy_id, conf, matched_fy)
    return None


def _match_collision(
    norm: str,
    idx: dict[str, list[ChyEntry]],
    contract_date: str | None,
) -> tuple[str, str, int, float] | None:
    """exact複数org の場合に collision_month → collision_majority で解消。
    Returns (org, source, chy_id, conf)。
    """
    if not norm or norm not in idx:
        return None
    cands = idx[norm]
    orgs = {c.org for c in cands}
    if len(orgs) < 2:
        return None  # collision ではない

    cm, cm_fy = _contract_month_fy(contract_date)
    if cm_fy is not None:
        month_match = [c for c in cands
                       if c.contract_month is not None and c.contract_month == cm_fy]
        if not month_match and cm is not None:
            month_match = [c for c in cands
                           if c.contract_month is not None and c.contract_month == cm]
        if month_match:
            mo = {c.org for c in month_match}
            if len(mo) == 1:
                return (next(iter(mo)), "collision_month", month_match[0].chy_id, 0.7)

    org_counts = Counter(c.org for c in cands)
    top_org, _ = org_counts.most_common(1)[0]
    sample = next(c for c in cands if c.org == top_org)
    return (top_org, "collision_majority", sample.chy_id, 0.5)


def _match_fms(vendor_name: str | None) -> str | None:
    if not vendor_name:
        return None
    v = unicodedata.normalize("NFKC", vendor_name).strip()
    for prefix, org in FMS_VENDOR_PREFIX:
        if v.startswith(prefix):
            return org
    return None


def _match_name_explicit(name: str) -> tuple[str, str] | None:
    """Tier 1: 組織名・部隊名が契約名に明示 → (org, matched_kw)。

    直接証拠。source='name_keyword', conf=0.75。
    """
    if not name:
        return None
    norm = unicodedata.normalize("NFKC", name)
    for org, kws in _NAME_EXPLICIT_NORM:
        for kw in kws:
            if kw in norm:
                return (org, kw)
    return None


def _match_name_inferred(name: str) -> tuple[str, str] | None:
    """Tier 2: システム名→運用者→要求元の間接推論 → (org, matched_kw)。

    source='ref_url_inference', conf=0.50。
    運用者≠要求元の場合があるため、ダッシュボード等で別途表示推奨。
    """
    if not name:
        return None
    norm = unicodedata.normalize("NFKC", name)
    for org, kws in _NAME_INFERRED_NORM:
        for kw in kws:
            if kw in norm:
                return (org, kw)
    return None


# ─── 1契約に対する判定（優先順位ロジック本体） ──────────────────────────────
def _assign_contract(
    c: Contract,
    chy_idx: dict[str, list[ChyEntry]],
    fuzzy_idx: list[tuple[str, str, tuple[int, ...], int]],
    equipment_branch_map: dict[int, str] | None = None,
    joint_equipment_inferred_map: dict[int, str] | None = None,
) -> tuple[str, str, float, int | None]:
    """1契約に対し優先順位 1→9 を順次評価。
    Returns (org, source, conf, chy_id)。
    """
    # 1. agency_rule（ATLA は対象外。ここに来てるのは全部ATLA）
    if not _is_atla_agency(c.agency_id):
        org = _resolve_agency(c.agency_id)
        if org:
            return (org, "agency_rule", 1.0, None)
        # 不明な agency → fallback
        return ("ATLA", "fallback_atla", 0.3, None)

    # 2. agency_subrule（仮処置: ATLAサブ機関は全部 ATLA）
    aid = c.agency_id.lower()
    if aid != "atla" and aid.startswith("atla_"):
        return ("ATLA", "agency_subrule", 0.5, None)

    # 3. choutatsuyotei_exact（単一org）
    norm = normalize_item_name(c.name)
    exact = _match_chy_exact(norm, chy_idx)
    if exact is not None:
        org, chy_id = exact
        return (org, "choutatsuyotei_exact", 0.9, chy_id)

    # 4a-4c. choutatsuyotei_fuzzy（FY-delta グラデーション）
    fuzzy = _match_chy_fuzzy(norm, fuzzy_idx, c.fiscal_year)
    if fuzzy is not None:
        org, chy_id, conf, _src_fy = fuzzy
        return (org, "choutatsuyotei_fuzzy", conf, chy_id)

    # 4d. manual_analysis（大型案件オーバーライド）
    manual = find_manual_override(c.name)
    if manual is not None:
        org, _note = manual
        return (org, "manual_analysis", 0.85, None)

    # 6/7. collision_month → collision_majority
    coll = _match_collision(norm, chy_idx, c.contract_date)
    if coll is not None:
        org, source, chy_id, conf = coll
        return (org, source, conf, chy_id)

    # 7.5. equipment_master_branch（GSDF/MSDF/ASDF のみ、JOINT は除外）
    if equipment_branch_map is not None:
        eb = equipment_branch_map.get(c.cid)
        if eb is not None:
            return (eb, "equipment_master_branch", 0.7, None)

    # 8. fms_vendor_heuristic
    fms_org = _match_fms(c.vendor)
    if fms_org is not None:
        return (fms_org, "fms_vendor_heuristic", 0.5, None)

    # 8.5a. name_keyword（契約名に組織名が明示 → 直接証拠, conf=0.75）
    explicit = _match_name_explicit(c.name)
    if explicit is not None:
        org, _kw = explicit
        return (org, "name_keyword", 0.75, None)

    # 8.5b. ref_url_inference（システム名→運用者→要求元 間接推論, conf=0.50）
    # 運用者≠要求元の可能性があることを承知の上で適用。
    inferred = _match_name_inferred(c.name)
    if inferred is not None:
        org, _kw = inferred
        return (org, "ref_url_inference", 0.50, None)

    # 8.5c. joint_equipment_inferred（JOINT装備品IDの運用者→要求元 推論, conf=0.50）
    if joint_equipment_inferred_map is not None:
        ji = joint_equipment_inferred_map.get(c.cid)
        if ji is not None:
            return (ji, "ref_url_inference", 0.50, None)

    # 9. fallback_atla
    return ("ATLA", "fallback_atla", 0.3, None)


# ─── multiprocessing ワーカー ────────────────────────────────────────────────
_WORKER_STATE: dict = {}


def _init_worker(payload_bytes: bytes) -> None:
    """各ワーカープロセスで1回だけ呼ばれ、index をグローバルに展開。"""
    global _WORKER_STATE
    payload = pickle.loads(payload_bytes)
    _WORKER_STATE["chy_idx"] = payload["chy_idx"]
    _WORKER_STATE["fuzzy_idx"] = payload["fuzzy_idx"]
    _WORKER_STATE["equipment_branch_map"] = payload["equipment_branch_map"]
    _WORKER_STATE["joint_equipment_inferred_map"] = payload["joint_equipment_inferred_map"]


def _worker_assign(chunk: list[Contract]) -> list[tuple]:
    chy_idx = _WORKER_STATE["chy_idx"]
    fuzzy_idx = _WORKER_STATE["fuzzy_idx"]
    equipment_branch_map = _WORKER_STATE["equipment_branch_map"]
    joint_equipment_inferred_map = _WORKER_STATE["joint_equipment_inferred_map"]
    out = []
    for c in chunk:
        org, source, conf, chy_id = _assign_contract(
            c, chy_idx, fuzzy_idx, equipment_branch_map, joint_equipment_inferred_map,
        )
        out.append((c.cid, org, source, conf, chy_id))
    return out


# ─── メイン: バックアップ → atomic 再評価 → 検証 → COMMIT ───────────────────
def _take_backup(db_path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"procurement_pre_recompute_{ts}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _chunked(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def report(con: sqlite3.Connection) -> dict:
    cur = con.cursor()
    by_source = dict(cur.execute(
        """SELECT cro.match_source, COUNT(*)
           FROM contract_requesting_org cro
           JOIN contracts c ON c.id = cro.contract_id
           WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'
           GROUP BY cro.match_source ORDER BY 2 DESC"""
    ).fetchall())
    by_org = dict(cur.execute(
        """SELECT cro.requesting_org, COUNT(*)
           FROM contract_requesting_org cro
           JOIN contracts c ON c.id = cro.contract_id
           WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'
           GROUP BY cro.requesting_org ORDER BY 2 DESC"""
    ).fetchall())
    total_amount = cur.execute(
        """SELECT COALESCE(SUM(c.contract_amount), 0)
           FROM contracts c
           WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'"""
    ).fetchone()[0]
    total_contracts = cur.execute(
        """SELECT COUNT(*) FROM contracts
           WHERE agency_id = 'atla' OR agency_id LIKE 'atla\\_%' ESCAPE '\\'"""
    ).fetchone()[0]
    mapped = cur.execute(
        """SELECT COUNT(DISTINCT cro.contract_id)
           FROM contract_requesting_org cro
           JOIN contracts c ON c.id = cro.contract_id
           WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'"""
    ).fetchone()[0]
    return {
        "total_contracts": total_contracts,
        "mapped": mapped,
        "total_amount_oku": round((total_amount or 0) / 1e8),
        "by_source": by_source,
        "by_org": by_org,
    }


def verify_invariants(before: dict, after: dict) -> tuple[bool, list[str]]:
    errors = []
    if before["total_contracts"] != after["total_contracts"]:
        errors.append(
            f"ATLA契約総件数が変動: {before['total_contracts']} → {after['total_contracts']}"
        )
    if before["total_amount_oku"] != after["total_amount_oku"]:
        errors.append(
            f"ATLA契約総額(億)が変動: {before['total_amount_oku']} → {after['total_amount_oku']}"
        )
    if after["mapped"] != after["total_contracts"]:
        errors.append(
            f"未マップ残あり: mapped={after['mapped']} / total={after['total_contracts']}"
        )
    return (len(errors) == 0, errors)


def recompute_all(
    db_path: Path,
    dry_run: bool = False,
    workers: int = 14,
    skip_backup: bool = False,
) -> dict:
    print(f"[1/6] DB接続: {db_path}")
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = OFF")

    print("[2/6] before レポート取得...")
    before = report(con)
    print(f"  ATLA総件数: {before['total_contracts']:,}件 / "
          f"{before['total_amount_oku']:,}億")
    print(f"  match_source 分布: {before['by_source']}")

    print("[3/6] choutatsuyotei index 構築...")
    chy_idx = _load_chy_global_index(con)
    fuzzy_idx = _build_fuzzy_index(chy_idx)
    equipment_branch_map = _load_equipment_branch_map(con)
    joint_equipment_inferred_map = _load_joint_equipment_inferred_map(con)
    print(f"  exact候補: {len(chy_idx):,} norm / "
          f"fuzzy候補: {len(fuzzy_idx):,} entries (全FY横断単一org)")
    print(f"  equipment_branch map: {len(equipment_branch_map):,} contracts")
    print(f"  joint_equipment_inferred map: {len(joint_equipment_inferred_map):,} contracts")

    print("[4/6] ATLA契約 ロード...")
    contracts = _load_atla_contracts(con)
    print(f"  {len(contracts):,}件")

    print(f"[5/6] 並列再判定 (workers={workers})...")
    payload_bytes = pickle.dumps(
        {
            "chy_idx": chy_idx,
            "fuzzy_idx": fuzzy_idx,
            "equipment_branch_map": equipment_branch_map,
            "joint_equipment_inferred_map": joint_equipment_inferred_map,
        },
        protocol=5,
    )
    print(f"  payload サイズ: {len(payload_bytes) / 1e6:.1f} MB")

    chunk_size = max(50, len(contracts) // (workers * 8))
    chunks = list(_chunked(contracts, chunk_size))
    print(f"  chunk数: {len(chunks)} (chunk_size={chunk_size})")

    results: list[tuple] = []
    t_start = datetime.now()
    with mp.Pool(
        processes=workers,
        initializer=_init_worker,
        initargs=(payload_bytes,),
    ) as pool:
        done = 0
        for chunk_result in pool.imap_unordered(_worker_assign, chunks):
            results.extend(chunk_result)
            done += len(chunk_result)
            if done % 5000 == 0 or done == len(contracts):
                elapsed = (datetime.now() - t_start).total_seconds()
                print(f"  進捗: {done:,}/{len(contracts):,} ({elapsed:.1f}秒)")
    elapsed = (datetime.now() - t_start).total_seconds()
    print(f"  完了: {len(results):,}件 / {elapsed:.1f}秒")

    # 集計
    src_dist = Counter(r[2] for r in results)
    org_dist = Counter(r[1] for r in results)
    print(f"  予測 by_source: {dict(src_dist.most_common())}")
    print(f"  予測 by_org: {dict(org_dist.most_common())}")

    if dry_run:
        print("[6/6] dry-run のため DB書き込みスキップ")
        con.close()
        return {"dry_run": True, "before": before,
                "predicted_source": dict(src_dist),
                "predicted_org": dict(org_dist), "elapsed_sec": elapsed}

    # バックアップ
    if not skip_backup:
        print("[6/6a] バックアップ取得...")
        backup_path = _take_backup(db_path)
        print(f"  保存先: {backup_path}")
    else:
        print("[6/6a] バックアップスキップ (--skip-backup)")
        backup_path = None

    # atomic 書き込み
    print("[6/6b] atomic 書き込み開始...")
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        # 手動判定 match_source はrecompute対象外（上書き保護）
        _PROTECTED_SOURCES = (
            "manual_analysis", "mod_search", "mod_research",
            "fuzzy_lowthreshold", "kenkyuu_hyouka", "jigyou_review",
        )
        placeholders = ",".join("?" * len(_PROTECTED_SOURCES))
        cur.execute(
            f"""DELETE FROM contract_requesting_org
               WHERE contract_id IN (
                 SELECT id FROM contracts
                 WHERE agency_id = 'atla' OR agency_id LIKE 'atla\\_%' ESCAPE '\\'
               )
               AND match_source NOT IN ({placeholders})""",
            _PROTECTED_SOURCES,
        )
        deleted = cur.rowcount
        print(f"  既存ATLA行 DELETE: {deleted:,}件（保護済みソース除外）")

        rows_to_insert = [
            (cid, org, source, chy_id, conf)
            for (cid, org, source, conf, chy_id) in results
        ]
        cur.executemany(
            """INSERT OR IGNORE INTO contract_requesting_org
               (contract_id, requesting_org, match_source, choutatsuyotei_id, confidence)
               VALUES (?, ?, ?, ?, ?)""",
            rows_to_insert,
        )
        print(f"  新規 INSERT: {len(rows_to_insert):,}件")

        # 検証
        after_partial = report(con)
        ok, errors = verify_invariants(before, after_partial)
        if not ok:
            print(f"  検証失敗: {errors}")
            con.rollback()
            print("  ROLLBACK しました")
            con.close()
            return {"success": False, "errors": errors, "backup": str(backup_path) if backup_path else None}

        cur.execute("COMMIT")
        print("  COMMIT 完了")
    except Exception as e:
        con.rollback()
        print(f"  例外発生 → ROLLBACK: {e!r}")
        con.close()
        raise

    after = report(con)
    print(f"\n[完了] ATLA総件数: {after['total_contracts']:,}件 / "
          f"{after['total_amount_oku']:,}億")
    print(f"  by_source: {after['by_source']}")
    print(f"  by_org: {after['by_org']}")

    # ログ保存
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"recompute_atla_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "elapsed_sec": elapsed,
            "workers": workers,
            "backup": str(backup_path) if backup_path else None,
            "before": before, "after": after,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"  ログ保存: {log_path}")

    con.close()
    return {"success": True, "before": before, "after": after,
            "elapsed_sec": elapsed, "backup": str(backup_path) if backup_path else None}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--workers", type=int, default=14)
    p.add_argument("--skip-backup", action="store_true",
                   help="バックアップをスキップ（dry-run連続時のみ推奨）")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB が見つからない: {db_path}", file=sys.stderr)
        return 1

    result = recompute_all(
        db_path, dry_run=args.dry_run, workers=args.workers,
        skip_backup=args.skip_backup,
    )
    if result.get("success") is False:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
