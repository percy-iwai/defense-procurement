"""
FY2023 契約への7本柱コード付与パイロット
Usage:
    python dev/assign_pillar_fy2023.py --dry-run   # ドライラン（上位マッチ20件表示）
    python dev/assign_pillar_fy2023.py              # 本番実行
"""

import argparse
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz, process

# ─── パス定義 ───────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
DB_PROCUREMENT = BASE / "data/db/procurement.db"
DB_PILLAR      = BASE / "data/db/defense_pillar.db"
TARGET_FY      = 2023

# ─── L1/L2コード導出ヘルパー ─────────────────────────────────────────────────
def pillar_l1_l2(pillar_id: int) -> tuple[int, int | None]:
    """pillar_id から (l1_code, l2_code) を返す."""
    if pillar_id <= 8:
        return pillar_id, None
    return pillar_id // 10, pillar_id

# ─── agency_id → org_key ─────────────────────────────────────────────────────
def agency_to_org(agency_id: str | None) -> str:
    if not agency_id:
        return "UNKNOWN"
    a = agency_id.lower()
    if a.startswith("gsdf"):   return "GSDF"
    if a.startswith("msdf"):   return "MSDF"
    if a.startswith("asdf"):   return "ASDF"
    if a.startswith("atla"):   return "ATLA"
    if a.startswith("rdb"):    return "RDB"
    if a.startswith("js"):     return "JS"
    if a.startswith("dih"):    return "DIH"
    if a.startswith("nids"):   return "NIDS"
    if a.startswith("ndmc"):   return "NDMC"
    if a.startswith("nda"):    return "NDA"
    if a.startswith("naikyoku"): return "NAIKYOKU"
    return "OTHER"

# ─── NFKC 正規化 ─────────────────────────────────────────────────────────────
def norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s)

# ─── キーワードルール辞書（raw）──────────────────────────────────────────────────
# (キーワードリスト, pillar_l1, pillar_l2, confidence[, org_filter: set[str]])
# org_filter: 指定したorgキーのみ適用。省略 or None = 全機関に適用。
# NOTE: キーワードは起動時に NFKC 正規化済みリストに変換される（全角英数に対応）
_KEYWORD_RULES_RAW: list[tuple] = [

    # ── P1 スタンド・オフ防衛能力 ──────────────────────────────────────────────
    # 対艦・対地長射程ミサイル、反撃能力関連
    (["スタンドオフ", "スタンド・オフ", "高速滑空弾", "トマホーク", "極超音速",
      "12式地対艦", "島嶼防衛用", "反撃能力", "長射程", "スタンドインジャマー",
      "スタンド・イン・ジャマー", "VLS搭載潜水艦",
      # 追加: 装備品名（全角→NFKC後はこの半角で照合される）
      "JSM", "JASSM", "LRASM", "93式空対艦", "スタンドオフ"],
     1, None, 0.82),

    # 空対空ミサイル（スタンドオフ AAM）
    (["AIM-120", "AIM120", "AAM-4", "AAM-5", "AAM4", "AAM5"],
     1, None, 0.75),

    # ── P2 統合防空ミサイル防衛能力 ─────────────────────────────────────────────
    # 迎撃システム・防空レーダ・戦闘機（邀撃任務）
    (["イージス", "統合防空", "PAC-3", "SM-3", "SM-6", "ペトリオット",
      "LTAMDS", "FCネットワーク", "共同交戦能力", "CEC",
      "警戒管制レーダ", "地対空誘導弾", "高出力レーザ", "高出力マイクロ波",
      "HPM", "防空ミサイル",
      # 追加: 戦闘機・早期警戒機（防空任務）
      "F-35", "F35", "E-2D", "E2D", "F-15", "F15", "F-2",
      "戦闘機", "早期警戒機"],
     2, None, 0.82),

    # ── P3 無人アセット防衛能力 ──────────────────────────────────────────────────
    (["無人機", "UAV", "UUV", "USV", "UGV", "ドローン", "無人水中",
      "無人水上", "無人地上", "滞空型無人", "無人アセット", "無人航走",
      "偵察用無人", "攻撃用無人",
      # 追加
      "RQ-4", "シーガーディアン"],
     3, None, 0.78),

    # ── P41 宇宙 ─────────────────────────────────────────────────────────────
    (["宇宙", "衛星", "SSA", "宇宙作戦", "SDA", "宇宙状況把握",
      "宇宙領域把握", "コンステレーション", "宇宙航空"],
     4, 41, 0.82),

    # ── P42 サイバー ─────────────────────────────────────────────────────────
    (["サイバー", "ゼロトラスト", "RMF", "能動的サイバー",
      "防衛情報通信基盤", "DII", "セキュリティ強化", "ネットワーク防衛",
      "サイバー防衛"],
     4, 42, 0.78),

    # ── P43 電磁波・陸海空装備（高信頼: 機体名・艦艇名・電子戦装備） ────────────
    (["電磁波", "電子戦", "EW", "電磁妨害", "NEWS",
      "スタンドオフ電子戦機", "信号探知", "電磁パルス", "EMP",
      "次期戦闘機", "GCAP",
      # 艦艇
      "護衛艦", "哨戒艦", "潜水艦", "イージス艦", "FFM",
      # 航空機（回転翼・固定翼・多用途）
      "哨戒機", "固定翼哨戒", "P-1",
      "SH-60", "SH60", "UH-60", "UH60", "CH-47", "CH47",
      "AH-64", "AH64", "OH-1", "OH1", "V-22", "V22",
      "E-767", "E767",
      # センサ・電子機器（ソナー/ソーナーの表記ゆれ対応）
      "レーダ", "ソナー", "ソーナー", "水中聴音", "音響探知",
      "HPS-", "FPS-", "機上電波", "電波測定",
      # 推進機関（艦艇・航空機の主機）
      "ガスタービン機関", "エンジン搭載用"],
     4, 43, 0.75),

    # ── P5 指揮統制・情報関連機能 ────────────────────────────────────────────
    (["指揮統制", "C4I", "統合作戦", "統合司令", "JADGE",
      "自動警戒管制", "中央指揮システム", "作戦クラウド",
      "情報収集", "偵察", "SIGINT", "IMINT", "OSINT",
      "ターゲティング", "情報戦", "偽情報対策", "OODA", "認知戦",
      # 追加
      "セキュリティゲートウェイ", "指揮通信", "情報システム", "統合防空指揮",
      "野外通信", "野外系通信", "COTS", "指揮通信システム"],
     5, None, 0.72),

    # ── P6 機動展開能力・国民保護 ────────────────────────────────────────────
    (["機動展開", "PFI船", "空中給油", "揚陸", "南西地域",
      "港湾整備", "国民保護", "住民避難", "機動舟艇", "LSV", "LCU",
      "コンテナトレーラー", "フォークリフト",
      # 輸送（機・艦・車両）
      "輸送", "輸送機", "C-2", "KC-46"],
     6, None, 0.70),

    # ── P71 弾薬・誘導弾（高信頼: 弾薬・火薬・魚雷等） ─────────────────────────
    (["弾薬", "火薬", "火工品", "火薬庫", "弾薬庫",
      "弾薬整備", "弾薬補給", "爆薬", "信管",
      # 口径別弾薬・特殊弾薬
      "155ミリ", "81ミリ", "60ミリ", "BALL",
      "魚雷", "機雷", "炸薬",
      # ミサイル補用（弾薬在庫）
      "ミサイル補用", "誘導弾補用"],
     7, 71, 0.78),

    # ── P71 誘導弾（中信頼: P1/P2未ヒット時のフォールバック） ─────────────────
    # P1(0.82), P1-AAM(0.75), P2(0.82) のいずれかがヒットしていれば
    # KEYWORD_RULES の最高信頼度取得ロジックにより自動的にP1/P2が優先される
    (["誘導弾", "ミサイル"],
     7, 71, 0.70),

    # ── P72 装備品可動率・維持整備（高信頼フレーズ） ──────────────────────────
    (["可動率", "整備補給", "予備部品", "修理部品",
      "補用部品", "整備用資材", "修理費", "可動向上",
      "維持整備", "維持修理", "部品費", "維持費",
      "成果払い", "PBL", "包括契約", "補用品", "修理用部品",
      "保守整備", "性能維持", "機能維持",
      # エンジン補用（修理・交換用）
      "エンジン補用", "補用エンジン",
      # 「補用」単独（スペアパーツ）
      "補用",
      # 定期修理・OH（P43の「修理」低信頼より優先させるため高信頼側に配置）
      "オーバーホール", "定期修理", "改修整備"],
     7, 72, 0.72),

    # ── P72 汎用保守/修理（低信頼） ─────────────────────────────────────────
    (["保守", "修繕", "オーバーホール", "修理", "整備",
      "維持", "点検整備", "定期整備", "整備作業"],
     7, 72, 0.60),

    # ── P73 施設の強靱化（高信頼） ──────────────────────────────────────────
    (["地下化", "えん体", "分散パッド", "格納庫強化",
      "施設強靱", "ライフライン", "EMP対策",
      "施設工事", "建設工事", "建築工事", "改修工事", "舗装工事",
      "庁舎建設", "倉庫建設", "格納庫建設", "施設整備",
      # 追加: 基地賃貸借（施設使用権）
      "賃貸借"],
     7, 73, 0.68),

    # ── P73 汎用工事（低信頼） ───────────────────────────────────────────────
    (["工事", "建設", "建築", "改修", "増築", "新築"],
     7, 73, 0.55),

    # ── P81 防衛生産基盤強化 ─────────────────────────────────────────────────
    (["防衛生産", "サプライチェーン", "装備移転", "防衛産業",
      "産業基盤", "生産能力", "輸出促進"],
     8, 81, 0.75),

    # ── P82 研究開発（高信頼フレーズ） ──────────────────────────────────────
    (["研究開発", "試作品", "基礎研究", "応用研究", "技術研究",
      "研究試作", "防衛イノベーション", "技術実証", "先端技術研究",
      "概念研究", "探索研究",
      # 追加
      "先進技術", "将来型"],
     8, 82, 0.75),

    # ── P82 汎用研究開発（低信頼） ───────────────────────────────────────────
    (["試作", "研究", "開発", "DISTI"],
     8, 82, 0.62),

    # ── P83 基地対策（RDB専用・高優先: 賃貸借・基地周辺用地） ─────────────────
    # rdb系機関の土地賃貸借・移転補償等。全機関適用すると一般賃貸借と混同するためRDB限定。
    (["賃貸借", "土地賃貸", "移転補償", "家屋防音", "飛行場周辺"],
     8, 83, 0.85, {"RDB"}),

    # ── P83 基地対策（全機関）────────────────────────────────────────────────
    (["騒音対策", "防音工事", "基地対策", "基地周辺", "防音",
      "補償", "民生安定", "住宅防音"],
     8, 83, 0.75),

    # ── P84 教育訓練・燃料（高信頼） ────────────────────────────────────────
    (["教育訓練", "訓練弾", "訓練費", "演習用",
      "航空機燃料", "JP-8", "JP8", "Jet-A", "JetA",
      "潤滑油", "作動油", "燃料油"],
     8, 84, 0.72),

    # ── P84 汎用燃料・訓練（低信頼） ────────────────────────────────────────
    (["燃料", "軽油", "灯油", "ガソリン", "重油",
      "チャーター", "借上", "タクシー", "演習", "訓練"],
     8, 84, 0.62),
]

# 起動時に全キーワードを NFKC 正規化（全角英数→半角に統一して照合漏れ防止）
# 5番目要素 org_filter (set[str] | None) を保持する
KEYWORD_RULES: list[tuple] = [
    ([norm(kw) for kw in raw[0]], raw[1], raw[2], raw[3],
     raw[4] if len(raw) > 4 else None)
    for raw in _KEYWORD_RULES_RAW
]

# ─── キーワードマッチ ─────────────────────────────────────────────────────────
# 優先度: 特定キーワードルール > org_maintenance fallback > atla_research fallback
def match_keywords(name: str, agency_id: str | None) -> tuple[int, int | None, float, str] | None:
    """Returns (l1, l2, confidence, matched_kw) or None."""
    n = norm(name)
    org = agency_to_org(agency_id)

    # Step A: KEYWORD_RULES を全部スキャンして最高信頼度のマッチを取得
    best: tuple[int, int | None, float, str] | None = None
    best_conf = 0.0
    for kws, l1, l2, conf, org_filter in KEYWORD_RULES:
        if org_filter is not None and org not in org_filter:
            continue  # org_filter 指定あり & 現機関が対象外 → スキップ
        for kw in kws:
            if kw in n:
                if conf > best_conf:
                    best_conf = conf
                    best = (l1, l2, conf, kw)
                break  # この rule で最初にマッチしたらOK

    # Step B: org_maintenance fallback（KEYWORD_RULES で0.65未満の場合）
    # org in 自衛隊系 かつ 維持/整備/修理系キーワード → P72
    ORG_MAINTENANCE_KWS = ["維持", "整備", "修理", "修繕", "補修", "点検", "保守"]
    ORG_FUEL_KWS        = ["燃料", "灯油", "軽油", "ガソリン", "JP-", "Jet-"]
    if org in ("GSDF", "MSDF", "ASDF", "JS", "ATLA", "RDB"):
        if best_conf < 0.65:
            if any(kw in n for kw in ORG_FUEL_KWS):
                best = (8, 84, 0.60, "org_fuel→P84")
                best_conf = 0.60
            elif any(kw in n for kw in ORG_MAINTENANCE_KWS):
                best = (7, 72, 0.60, "org_maintenance→P72")
                best_conf = 0.60

    # Step C: ATLA 研究開発 fallback（KEYWORD_RULES で0.62未満の場合）
    if org == "ATLA" and best_conf < 0.62:
        if any(kw in n for kw in ["研究", "試作", "開発", "技術評価"]):
            best = (8, 82, 0.58, "atla_research→P82")

    return best


# ─── ファジーマッチ用コーパス構築 ──────────────────────────────────────────────
def build_fuzzy_corpus(pillar_db: str) -> list[tuple[str, int]]:
    """
    [(jigyou_name_norm, pillar_id), ...]
    defense_pillar_jigyou + pillar_mapping_sources から重複除去して構築。
    """
    conn = sqlite3.connect(pillar_db)
    cur = conn.cursor()

    corpus: dict[str, int] = {}  # name_norm → pillar_id

    cur.execute("SELECT jigyou_name_norm, pillar_id FROM defense_pillar_jigyou WHERE jigyou_name_norm IS NOT NULL")
    for row in cur.fetchall():
        jname, pid = row
        if jname and jname not in corpus:
            corpus[jname] = pid

    cur.execute("SELECT jigyou_name_norm, pillar_id FROM pillar_mapping_sources WHERE jigyou_name_norm IS NOT NULL")
    for row in cur.fetchall():
        jname, pid = row
        if jname and jname not in corpus:
            corpus[jname] = pid

    conn.close()
    # (name, pillar_id) のリストに変換
    return list(corpus.items())


# ─── メイン処理 ─────────────────────────────────────────────────────────────
def main(dry_run: bool = False) -> None:
    corpus = build_fuzzy_corpus(str(DB_PILLAR))
    corpus_names = [c[0] for c in corpus]
    name_to_pid  = {c[0]: c[1] for c in corpus}
    print(f"Fuzzy corpus size: {len(corpus_names)} entries")

    conn = sqlite3.connect(str(DB_PROCUREMENT))
    cur  = conn.cursor()

    # contract_pillar テーブル作成
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contract_pillar (
            contract_id INTEGER PRIMARY KEY,
            pillar_l1_code INTEGER,
            pillar_l2_code INTEGER,
            confidence REAL,
            match_method TEXT,
            match_source TEXT,
            fiscal_year INTEGER,
            updated_at TEXT
        )
    """)
    conn.commit()
    print("contract_pillar table: ready")

    # FY対象の既存行を削除（冪等実行のため）
    if not dry_run:
        cur.execute("DELETE FROM contract_pillar WHERE fiscal_year = ?", (TARGET_FY,))
        conn.commit()
        print(f"FY{TARGET_FY} existing rows deleted.")

    # FY2023 契約ロード
    cur.execute("""
        SELECT id, contract_name, agency_id
        FROM contracts
        WHERE fiscal_year = ?
    """, (TARGET_FY,))
    contracts = cur.fetchall()
    print(f"FY{TARGET_FY} contracts loaded: {len(contracts)}")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    results: list[tuple] = []  # (contract_id, l1, l2, conf, method, source)
    fuzzy_top20: list[tuple] = []  # ドライラン確認用

    fuzzy_count   = 0
    keyword_count = 0
    unclassified  = 0
    FUZZY_THRESHOLD = 78

    for cid, cname, agency_id in contracts:
        n = norm(cname or "")

        # Pass 1: fuzzy match
        if n:
            match = process.extractOne(
                n,
                corpus_names,
                scorer=fuzz.token_set_ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
        else:
            match = None

        if match:
            matched_name, score, _ = match
            pid = name_to_pid[matched_name]
            l1, l2 = pillar_l1_l2(pid)
            row = (cid, l1, l2, round(score / 100, 3), "fuzzy_jigyou",
                   f"{matched_name}[{score:.1f}]")
            fuzzy_count += 1
            if len(fuzzy_top20) < 20:
                fuzzy_top20.append((cname, matched_name, score, l1, l2))
            results.append(row)
            continue

        # Pass 2: keyword rules
        kw_result = match_keywords(cname or "", agency_id)
        if kw_result:
            l1, l2, conf, kw = kw_result
            row = (cid, l1, l2, conf, "keyword_rule", kw)
            keyword_count += 1
            results.append(row)
            continue

        # Pass 3: unclassified
        row = (cid, None, None, 0.0, "unclassified", None)
        unclassified += 1
        results.append(row)

    # ─── ドライランモード ────────────────────────────────────────────────
    if dry_run:
        print("\n=== DRY RUN: 上位 fuzzy マッチ20件 ===")
        print(f"{'契約名':40s} {'マッチ事業名':40s} {'スコア':6s} {'L1':3s} {'L2':5s}")
        print("-" * 100)
        for cname, mname, score, l1, l2 in fuzzy_top20:
            cname_s = (cname or "")[:38]
            mname_s = mname[:38]
            print(f"{cname_s:40s} {mname_s:40s} {score:6.1f} {l1!s:3s} {str(l2):5s}")

        print(f"\n=== DRY RUN 分類見込み (FY{TARGET_FY}: {len(contracts)}件) ===")
        print(f"  Pass1 fuzzy_jigyou : {fuzzy_count:6d}件 ({fuzzy_count/len(contracts)*100:.1f}%)")
        print(f"  Pass2 keyword_rule : {keyword_count:6d}件 ({keyword_count/len(contracts)*100:.1f}%)")
        print(f"  未分類             : {unclassified:6d}件 ({unclassified/len(contracts)*100:.1f}%)")
        conn.close()
        return

    # ─── 本番: DB書き込み ────────────────────────────────────────────────
    rows_to_insert = [
        (r[0], r[1], r[2], r[3], r[4], r[5], TARGET_FY, now_iso)
        for r in results
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO contract_pillar
        (contract_id, pillar_l1_code, pillar_l2_code, confidence,
         match_method, match_source, fiscal_year, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    print(f"\n{len(rows_to_insert)} rows inserted/replaced into contract_pillar.")

    # ─── 集計レポート ───────────────────────────────────────────────────────
    print(f"\n=== FY{TARGET_FY} 分類結果 ===")
    print(f"  対象件数           : {len(contracts):6d}件")
    print(f"  Pass1 fuzzy_jigyou : {fuzzy_count:6d}件 ({fuzzy_count/len(contracts)*100:.1f}%)")
    print(f"  Pass2 keyword_rule : {keyword_count:6d}件 ({keyword_count/len(contracts)*100:.1f}%)")
    print(f"  未分類             : {unclassified:6d}件 ({unclassified/len(contracts)*100:.1f}%)")

    print(f"\n=== 柱別件数・金額 ===")
    cur.execute("""
        SELECT
            cp.pillar_l1_code,
            COUNT(*) as cnt,
            ROUND(SUM(c.contract_amount) / 1e8, 1) as amt_hyoku
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
        GROUP BY cp.pillar_l1_code
        ORDER BY cp.pillar_l1_code
    """, (TARGET_FY,))
    rows = cur.fetchall()

    PILLAR_NAMES = {
        1: "P1 スタンド・オフ防衛",
        2: "P2 統合防空ミサイル防衛",
        3: "P3 無人アセット",
        4: "P4 領域横断作戦",
        5: "P5 指揮統制・情報",
        6: "P6 機動展開・国民保護",
        7: "P7 持続性・強靱性",
        8: "P8 防衛生産基盤・研究開発",
        None: "未分類",
    }
    for l1, cnt, amt in rows:
        name = PILLAR_NAMES.get(l1, f"P{l1}")
        amt_s = f"{amt}億円" if amt else "（金額なし）"
        print(f"  {name:30s}: {cnt:6d}件 / {amt_s}")

    # match_method 別集計
    print(f"\n=== match_method 別 ===")
    cur.execute("""
        SELECT match_method, COUNT(*) FROM contract_pillar
        WHERE fiscal_year = ? GROUP BY match_method ORDER BY COUNT(*) DESC
    """, (TARGET_FY,))
    for method, cnt in cur.fetchall():
        print(f"  {method:20s}: {cnt:6d}件")

    conn.close()
    print("\n完了。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="DBに書き込まず上位マッチ20件を確認する")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
