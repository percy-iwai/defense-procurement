"""
FY2023 未分類契約へのセマンティック埋め込みによる7本柱コード付与

Usage:
    python dev/assign_pillar_semantic.py --dry-run    # DB書き込みなし・結果確認のみ
    python dev/assign_pillar_semantic.py              # 本番実行
    python dev/assign_pillar_semantic.py --threshold 0.70  # 閾値調整

モデル: intfloat/multilingual-e5-large (GPU: RTX 5060 Ti)
ピラー定義: docs/pillar_narrative.md

手順:
  1. pillar_narrative.md から各ピラーのテキストを抽出し "passage: " プレフィックス付きで埋め込み
  2. 未分類FY2023契約名を "query: " プレフィックス付きで埋め込み (batch=256)
  3. コサイン類似度で最近傍ピラーを特定
  4. similarity >= threshold の場合のみ UPDATE (それ以下は unclassified 維持)
  5. match_method = 'semantic_embedding', confidence = similarity score
"""

import argparse
import re
import shutil
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer

# ─── パス定義 ─────────────────────────────────────────────────────────────────
BASE        = Path(__file__).resolve().parent.parent
DB_REAL     = BASE / "data/db/procurement.db"
DB_TMP      = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "procurement_semantic.db"
NARRATIVE   = BASE / "docs/pillar_narrative.md"
TARGET_FY   = 2023
MODEL_NAME  = "intfloat/multilingual-e5-large"
BATCH_SIZE  = 256
DEFAULT_THR = 0.75

sys.stdout.reconfigure(encoding="utf-8")


# ─── pillar_l2 → (l1, l2) マッピング ─────────────────────────────────────────
# ピラーコード定義（assign_pillar_fy2023.py と同一体系）
PILLAR_META: list[tuple[int, int | None, str]] = [
    (1, None, "P1 スタンド・オフ防衛能力"),
    (2, None, "P2 統合防空ミサイル防衛能力"),
    (3, None, "P3 無人アセット防衛能力"),
    (4, 41,   "P41 宇宙（領域横断）"),
    (4, 42,   "P42 サイバー（領域横断）"),
    (4, 43,   "P43 電磁波・艦船・航空機（領域横断）"),
    (5, None, "P5 指揮統制・情報関連機能"),
    (6, None, "P6 機動展開能力・国民保護"),
    (7, 71,   "P71 弾薬・誘導弾（持続性）"),
    (7, 72,   "P72 装備品維持整備（持続性）"),
    (7, 73,   "P73 施設強靱化（持続性）"),
    (8, 81,   "P81 防衛生産基盤"),
    (8, 82,   "P82 研究開発"),
    (8, 83,   "P83 基地対策"),
    (8, 84,   "P84 教育訓練・燃料"),
]

# ─── ピラー説明文（passage）─────────────────────────────────────────────────────
# pillar_narrative.md から抽出した各ピラーの要約テキスト。
# モデルに渡す前に "passage: " を付与する。
# 内容更新時は NARRATIVE ファイルを正として、このリストも更新すること。
PILLAR_PASSAGES_RAW: dict[tuple[int, int | None], str] = {

    (1, None): (
        "スタンド・オフ防衛能力。敵の射程圏外から攻撃できる長射程誘導弾・ミサイルの調達・開発。"
        "主な装備品：12式地対艦誘導弾（能力向上型）、島嶼防衛用高速滑空弾、極超音速誘導弾、"
        "トマホーク巡航ミサイル、JSM（対艦ミサイル）、JASSM、LRASM、93式空対艦誘導弾、"
        "スタンド・イン・ジャマー電子戦機。"
        "空対空ミサイル：AIM-120（AMRAAM）、AAM-4、AAM-5。"
        "弾頭・推進薬・発射機・射撃統制装置・シミュレータ・試験器材の調達、"
        "米国発射試験支援、ミサイル技術援助契約、反撃能力（敵基地攻撃能力）整備、"
        "VLS搭載潜水艦、スタンドオフミサイル、長射程精密誘導弾、島嶼防衛ミサイル。"
        "ミサイル発射試験、能力向上型技術試験用器材、スタンドオフ電子戦、"
        "GNSSシミュレータ、ダミー弾、模擬弾、長射程対艦ミサイル。"
    ),

    (2, None): (
        "統合防空ミサイル防衛能力。弾道ミサイル・航空機・巡航ミサイルを迎撃する"
        "防空システム・迎撃システムの整備。"
        "主な装備品：イージス・システム搭載艦（BMD対応）、PAC-3ミサイル（ペトリオット）、"
        "SM-3・SM-6迎撃ミサイル、LTAMDS（次世代地対空レーダー）、"
        "戦闘機F-35A/B/C（ステルス戦闘機）、F-15（緊急発進・邀撃）、F-2（対空任務）、"
        "E-2D（早期警戒機）、警戒管制レーダー（FPS-7等）、地対空誘導弾。"
        "FCネットワーク、共同交戦能力（CEC）、BMD指揮統制、"
        "高出力レーザー兵器、高出力マイクロ波（HPM）兵器、防空ミサイル。"
        "射撃統制装置、レーダー部品、整備訓練器材、発射筒、ミサイル発射機、"
        "弾道ミサイル防衛、航空機緊急発進、邀撃、迎撃、早期警戒管制。"
    ),

    (3, None): (
        "無人アセット防衛能力。無人機（UAV）・無人水中航走体（UUV）・無人水上艇（USV）・"
        "無人地上車両（UGV）など自律型・遠隔操作型システムの調達・開発。"
        "大型高高度滞空無人機（RQ-4グローバルホーク、シーガーディアン・MQ-9B）、"
        "小型・携行型の無人偵察機・攻撃用ドローン、"
        "情報収集・偵察・攻撃・機雷掃海・水中捜索任務用の無人プラットフォーム。"
        "無人機対処器材（カウンターUAV）、スウォーム技術、AI自律制御研究、"
        "無人機用センサ・ペイロード・データリンク、"
        "小型無人機、偵察用無人機、攻撃用無人機、滞空型無人機、"
        "無人航走体、無人偵察、自律型無人、遠隔操作無人、ドローン。"
    ),

    (4, 41): (
        "宇宙領域（領域横断作戦能力）。宇宙状況把握（SSA）、衛星コンステレーション、"
        "宇宙作戦部隊用センサ、軍事衛星（偵察衛星・通信衛星・測位補完）。"
        "携行型衛星通信装置、衛星ミッション解析システム、"
        "SDA（宇宙領域把握）システム、宇宙状況把握センサ（光学・レーダー）、"
        "衛星通信の抗たん性強化、Xバンド衛星通信（きらめき）、"
        "航空宇宙自衛隊、宇宙作戦、宇宙航空、SSA、SDA、"
        "衛星搭載機器、衛星コンステレーション、宇宙監視、宇宙状況把握、"
        "人工衛星、宇宙系、衛星システム。"
    ),

    (4, 42): (
        "サイバー領域（領域横断作戦能力）。サイバー防衛能力強化、"
        "ゼロトラストネットワーク構築、能動的サイバー防御（ACD）、"
        "防衛情報通信基盤（DII）のセキュリティ強化、"
        "セキュリティゲートウェイ（SWG）、リスク管理フレームワーク（RMF）、"
        "ネットワーク防衛システム、サイバーセキュリティ、"
        "サイバー関連部隊、サイバー事案対処、"
        "サイバー防衛、サイバー攻撃対処、セキュリティ強化、"
        "情報セキュリティ、ゼロトラスト、暗号化通信。"
    ),

    (4, 43): (
        "電磁波領域・主要装備品（領域横断作戦能力）。"
        "電子戦装備（NEWS等）、スタンドオフ電子戦機、電磁妨害（ECM/ECCM）器材、"
        "次期戦闘機（GCAP/F-3）。"
        "護衛艦・哨戒艦・潜水艦・イージス艦・フリゲート（FFM）、"
        "哨戒機（P-1固定翼哨戒機）、"
        "回転翼機（SH-60哨戒ヘリコプター・UH-60・CH-47・AH-64・OH-1・V-22）、"
        "早期警戒管制機（E-767）、"
        "艦載レーダー・ソナー・水中聴音器・音響探知器、"
        "ガスタービン機関・航空エンジン（搭載用）、"
        "艦艇搭載機器・電波測定装置・機上電波・HPS-・FPS-、"
        "電磁波、電子戦、EW、電磁妨害、信号探知、電磁パルス、EMP、"
        "護衛艦用、艦艇用、潜水艦用。"
    ),

    (5, None): (
        "指揮統制・情報関連機能。作戦指揮・情報収集・情報処理・通信の各能力強化。"
        "統合作戦司令部の指揮システム（JADGE自動警戒管制組織、中央指揮システム）、"
        "作戦クラウド（陸自クローズ系クラウド基盤、中央クラウド）、"
        "偵察・SIGINT・IMINT・OSINT情報収集能力、"
        "情報戦・認知戦・偽情報対策システム、OODAループ支援システム。"
        "野外通信システム（JGSM）・野外系通信器材、"
        "指揮通信システム、情報システム関連機器・ソフトウェア・ライセンス、"
        "セキュリティゲートウェイ、統合防空指揮システム、"
        "C4I、指揮統制、偵察情報、通信システム、情報処理、"
        "電子情報収集、情報本部、戦術データリンク、乗車用安全帽偵察用。"
    ),

    (6, None): (
        "機動展開能力・国民保護。南西諸島・離島防衛のための部隊展開力と"
        "有事・災害時の国民保護体制整備。"
        "輸送機C-2・空中給油機KC-46・輸送艦・揚陸艦（LSV・LCU・LCAC）、"
        "PFI船（民間船舶活用）、機動舟艇、コンテナトレーラー、"
        "フォークリフト・クレーン等荷役器材、"
        "港湾整備・埠頭整備（南西地域）、住民避難計画支援システム、"
        "野外医療・救護器材、国民保護情報システム。"
        "輸送支援装備、揚陸支援、機動展開、南西地域、国民保護、"
        "輸送機、空中給油、フォークリフト、コンテナ輸送、荷役。"
    ),

    (7, 71): (
        "弾薬・誘導弾の確保（持続性・強靱性）。"
        "弾薬・火薬・炸薬・信管・火工品の調達、弾薬庫・火薬庫の整備。"
        "155ミリ砲弾・81ミリ迫撃砲弾・60ミリ迫撃砲弾等の口径別弾薬、"
        "魚雷・機雷の調達、ミサイル補用部品・誘導弾補用部品の在庫確保。"
        "弾薬補給・弾薬整備、爆薬、弾薬整備、火薬庫、弾薬庫建設、"
        "訓練弾・演習弾（弾薬として）、誘導弾補用、ミサイル補用、"
        "BALL弾、炸薬、機雷掃海用火工品。"
    ),

    (7, 72): (
        "装備品の可動率向上・維持整備（持続性・強靱性）。"
        "予備部品・補用部品・修理部品の調達、修理費・整備費。"
        "PBL（成果払い包括整備）契約、オーバーホール・定期整備・点検整備・保守整備作業。"
        "補用エンジン・エンジン補用の調達、"
        "装備品の可動率向上・性能維持・機能維持のための整備用資材・工具・治具。"
        "補用部品、整備補給、補用品、修理用部品、整備作業、"
        "可動率、整備器材、部品費、輸入部品、補給品、"
        "各種補用部品（輸入）、修繕費、維持修理費。"
    ),

    (7, 73): (
        "施設の強靱化（持続性・強靱性）。"
        "格納庫・庁舎・倉庫・弾薬庫等の建設・改修・増築、"
        "地下化・えん体化工事、分散パッド・格納庫強化工事、"
        "施設のEMP対策・ライフライン強化、"
        "基地内施設の賃貸借（用地確保）、舗装工事・土木工事・施設整備工事。"
        "建設工事、建築工事、改修工事、新築工事、増改築工事、"
        "施設整備、庁舎建設、倉庫建設、格納庫建設、"
        "擁壁工事、基礎工事、電気設備工事、空調設備工事、"
        "住宅工事、宿舎建設、訓練施設整備。"
    ),

    (8, 81): (
        "防衛生産・技術基盤の強化。"
        "国内防衛産業のサプライチェーン強化・生産能力増強、"
        "防衛装備移転促進、産業基盤維持のための補助・出資、"
        "防衛産業保護・育成施策、装備移転、サプライチェーン、"
        "防衛産業基盤、生産能力強化、防衛生産基盤強化法。"
    ),

    (8, 82): (
        "研究開発・試作・技術評価（防衛生産基盤強化）。"
        "基礎研究・応用研究・技術研究・先端技術研究、防衛イノベーション推進、"
        "研究試作品・試作機の製造、技術実証・概念研究・探索研究、"
        "技術援助契約、先進技術・将来型装備品の研究開発費、"
        "防衛イノベーション技術研究所（DISTI）、研究開発費、"
        "試作品、技術試験、研究試作、基礎的な研究、応用研究、"
        "探索的研究、先進技術の研究、将来装備品の研究。"
    ),

    (8, 83): (
        "基地対策経費（防衛生産基盤）。"
        "基地周辺の防音工事（住宅防音・学校防音）、騒音対策、補償費、"
        "民生安定施策、基地周辺整備、住宅防音の設計・施工監理。"
        "防音工事、騒音対策、基地対策、基地周辺、"
        "住宅防音、学校防音、補助金、基地周辺住民。"
    ),

    (8, 84): (
        "教育訓練費・燃料費・その他運営経費（防衛生産基盤）。"
        "教育訓練費・演習費・訓練弾、"
        "航空機燃料（JP-8・Jet-A）・艦船用燃料（軽油・重油）、"
        "潤滑油・作動油、タクシー借上・車両チャーター。"
        "燃料、軽油、灯油、ガソリン、重油、航空機燃料、JP-8、"
        "艦船用燃料、訓練、演習、教育訓練、タクシー借上、チャーター。"
    ),
}


# ─── NFKC 正規化 ──────────────────────────────────────────────────────────────
def norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s)


# ─── ナラティブから各ピラーテキストを抽出（補助的検証用） ──────────────────────
def load_narrative_summary(path: Path) -> dict[str, str]:
    """markdown から H2 セクション（## P{n}.）を辞書で返す（デバッグ用）。"""
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    pattern = re.compile(r"^## (P\d.*?)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[header] = text[start:end].strip()[:500]
    return sections


# ─── メイン処理 ───────────────────────────────────────────────────────────────
def main(dry_run: bool = False, threshold: float = DEFAULT_THR) -> None:
    print(f"{'=== DRY RUN ===' if dry_run else '=== 本番実行 ==='}")
    print(f"モデル: {MODEL_NAME}")
    print(f"閾値: {threshold}")
    print(f"対象: FY{TARGET_FY} / match_method='unclassified'")
    print()

    # ── 1. モデルロード ──────────────────────────────────────────────────────
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"デバイス: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    print(f"\nモデルロード中: {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME, device=device)
    print("  -> ロード完了")

    # ── 2. ピラー passage のエンコード ───────────────────────────────────────
    print("\nピラー passage をエンコード中...")
    pillar_keys = [(l1, l2) for l1, l2, _ in PILLAR_META]
    pillar_names = [name for _, _, name in PILLAR_META]
    passages = [
        f"passage: {PILLAR_PASSAGES_RAW[(l1, l2)]}"
        for l1, l2, _ in PILLAR_META
    ]
    pillar_embs = model.encode(
        passages,
        batch_size=len(passages),
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_tensor=True,
        device=device,
    )  # shape: (n_pillars, dim)
    print(f"  -> {len(passages)} ピラーをエンコード完了 (dim={pillar_embs.shape[1]})")

    # ── 3. 未分類契約をDBからロード ──────────────────────────────────────────
    print(f"\nDB: {DB_REAL}")
    conn_r = sqlite3.connect(str(DB_REAL))
    cur_r = conn_r.cursor()
    cur_r.execute("""
        SELECT c.id, c.contract_name
        FROM contracts c
        JOIN contract_pillar cp ON cp.contract_id = c.id
        WHERE cp.match_method = 'unclassified'
          AND c.fiscal_year = ?
    """, (TARGET_FY,))
    rows = cur_r.fetchall()
    conn_r.close()
    total = len(rows)
    print(f"未分類契約: {total:,} 件")

    if total == 0:
        print("未分類契約がありません。終了。")
        return

    # ── 4. 契約名のエンコード（バッチ処理） ─────────────────────────────────
    print(f"\n契約名をエンコード中 (batch_size={BATCH_SIZE})...")
    ids    = [r[0] for r in rows]
    names  = [norm(r[1] or "") for r in rows]
    queries = [f"query: {n}" if n else "query: （名称なし）" for n in names]

    # GPUメモリを効率化するため SentenceTransformer の encode_multi_process は省略し
    # 標準 encode を batch_size 指定で呼び出す
    contract_embs = model.encode(
        queries,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_tensor=True,
        device=device,
    )  # shape: (n_contracts, dim)
    print(f"  -> エンコード完了: {contract_embs.shape}")

    # ── 5. コサイン類似度計算（GPU行列積） ─────────────────────────────────
    print("\nコサイン類似度を計算中...")
    # similarity[i, j] = contract_embs[i] · pillar_embs[j]
    sim = (contract_embs @ pillar_embs.T).cpu().float()  # shape: (n_contracts, n_pillars)

    # 各契約の最大類似度とそのピラーインデックス
    best_sim, best_idx = sim.max(dim=1)
    best_sim  = best_sim.numpy()
    best_idx  = best_idx.numpy()
    print(f"  -> 完了")

    # ── 6. 割り当て結果の集計 ────────────────────────────────────────────────
    updates: list[tuple[int, int, int | None, float]] = []  # (contract_id, l1, l2, sim)
    pillar_cnt: dict[tuple[int, int | None], int] = {}

    for i in range(total):
        s = float(best_sim[i])
        if s < threshold:
            continue
        pi   = int(best_idx[i])
        l1, l2, _ = PILLAR_META[pi]
        updates.append((ids[i], l1, l2, s))
        key = (l1, l2)
        pillar_cnt[key] = pillar_cnt.get(key, 0) + 1

    assigned   = len(updates)
    unassigned = total - assigned
    print(f"\n=== 割り当て結果（閾値={threshold}） ===")
    print(f"  割り当て可能  : {assigned:6,} 件 ({assigned/total*100:.1f}%)")
    print(f"  未分類維持   : {unassigned:6,} 件 ({unassigned/total*100:.1f}%)")

    print("\n柱別件数:")
    for l1, l2, name in PILLAR_META:
        cnt = pillar_cnt.get((l1, l2), 0)
        if cnt:
            print(f"  {name:35s}: {cnt:6,}件")

    # ── 7. サンプル出力（各ピラー上位5件） ───────────────────────────────────
    print("\n=== サンプル（各ピラー上位5件）===")
    # インデックス逆引き用
    pillar_samples: dict[tuple[int, int | None], list[tuple[float, str]]] = {}
    for i in range(total):
        s = float(best_sim[i])
        if s < threshold:
            continue
        pi = int(best_idx[i])
        l1, l2, _ = PILLAR_META[pi]
        key = (l1, l2)
        if key not in pillar_samples:
            pillar_samples[key] = []
        if len(pillar_samples[key]) < 5:
            pillar_samples[key].append((s, names[i]))

    for l1, l2, name in PILLAR_META:
        samples = pillar_samples.get((l1, l2), [])
        if not samples:
            continue
        print(f"\n{name}:")
        for s, cname in sorted(samples, reverse=True):
            print(f"  [{s:.3f}] {cname[:60]}")

    # ── 8. サニティチェック（既存 keyword_rule と比較） ──────────────────────
    print("\n=== サニティチェック: 既存 keyword_rule との一致率 ===")
    conn_s = sqlite3.connect(str(DB_REAL))
    cur_s  = conn_s.cursor()
    cur_s.execute("""
        SELECT c.id, cp.pillar_l1_code, c.contract_name
        FROM contracts c
        JOIN contract_pillar cp ON cp.contract_id = c.id
        WHERE cp.match_method = 'keyword_rule'
          AND c.fiscal_year = ?
        LIMIT 500
    """, (TARGET_FY,))
    kw_rows = cur_s.fetchall()
    conn_s.close()

    if kw_rows:
        kw_ids   = [r[0] for r in kw_rows]
        kw_l1    = {r[0]: r[1] for r in kw_rows}
        kw_names = [f"query: {norm(r[2] or '')}" for r in kw_rows]
        kw_embs  = model.encode(
            kw_names, batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_tensor=True, device=device,
        )
        kw_sim = (kw_embs @ pillar_embs.T).cpu().float()
        kw_best_sim, kw_best_idx = kw_sim.max(dim=1)
        match_cnt = 0
        total_kw  = len(kw_rows)
        for i, row in enumerate(kw_rows):
            pred_l1 = PILLAR_META[int(kw_best_idx[i])][0]
            true_l1 = kw_l1[row[0]]
            if pred_l1 == true_l1:
                match_cnt += 1
        print(f"  keyword_rule サンプル {total_kw}件中: "
              f"{match_cnt}件一致 ({match_cnt/total_kw*100:.1f}%)")

    # ── 9. ドライランならここで終了 ─────────────────────────────────────────
    if dry_run:
        print("\n[DRY RUN] DBへの書き込みはスキップ。")
        return

    # ── 10. DBコピー → UPDATE → コピーバック ────────────────────────────────
    print(f"\nDBコピー中: {DB_REAL.name} -> {DB_TMP.name}")
    shutil.copy2(DB_REAL, DB_TMP)

    conn_w = sqlite3.connect(str(DB_TMP))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"UPDATE 中... ({assigned:,} 件)")
    update_rows = [
        (l1, l2, round(s, 4), "semantic_embedding",
         f"multilingual-e5-large[{s:.3f}]", now_iso, cid)
        for cid, l1, l2, s in updates
    ]
    conn_w.executemany("""
        UPDATE contract_pillar
        SET pillar_l1_code = ?,
            pillar_l2_code = ?,
            confidence     = ?,
            match_method   = ?,
            match_source   = ?,
            updated_at     = ?
        WHERE contract_id = ?
          AND match_method = 'unclassified'
    """, update_rows)
    conn_w.commit()

    # 実際の更新件数を確認
    cur_w = conn_w.cursor()
    cur_w.execute("""
        SELECT match_method, COUNT(*) FROM contract_pillar
        WHERE fiscal_year = ? GROUP BY match_method ORDER BY COUNT(*) DESC
    """, (TARGET_FY,))
    print(f"\n=== 更新後 FY{TARGET_FY} match_method 分布 ===")
    for method, cnt in cur_w.fetchall():
        print(f"  {method:25s}: {cnt:6,}件")

    conn_w.close()
    print(f"\nコピーバック: {DB_TMP.name} -> {DB_REAL.name}")
    shutil.copy2(DB_TMP, DB_REAL)
    DB_TMP.unlink(missing_ok=True)
    print("完了。")


# ─── エントリポイント ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FY2023 未分類契約へのセマンティック埋め込みピラー付与")
    parser.add_argument("--dry-run", action="store_true",
                        help="DBに書き込まず結果確認のみ")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THR,
                        help=f"コサイン類似度閾値 (デフォルト: {DEFAULT_THR})")
    args = parser.parse_args()
    main(dry_run=args.dry_run, threshold=args.threshold)
