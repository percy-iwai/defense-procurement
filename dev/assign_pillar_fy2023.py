"""
FY2023〜2025 契約への7本柱コード付与（--fyオプションで対象年度を指定）
Usage:
    python dev/assign_pillar_fy2023.py --dry-run        # ドライラン（上位マッチ20件表示）
    python dev/assign_pillar_fy2023.py                  # 本番実行（FY2023）
    python dev/assign_pillar_fy2023.py --fy 2024        # FY2024に適用
    python dev/assign_pillar_fy2023.py --fy 2025        # FY2025に適用
"""

import argparse
import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz, process

# ─── パス定義 ───────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
DB_PROCUREMENT    = BASE / "data/db/procurement.db"
DB_PILLAR         = BASE / "data/db/defense_pillar.db"
CORRECTIONS_JSON  = BASE / "data/manual/manual_corrections_snapshot.json"
TARGET_FY         = 2023

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

    # ── P85 シュワブ単独（最高優先: conf=0.92）──────────────────────────────────
    # 「シュワブ」= キャンプ・シュワブ（辺野古沖埋立工事等の基地）
    # 火薬庫工事（P71誤分類）・警備業務（semantic誤分類）を防ぐため単独・高信頼で配置
    (["シュワブ"],
     8, 85, 0.92),

    # ── P85 米軍再編関係経費等（conf=0.90）─────────────────────────────────────
    # 馬毛島/普天間/辺野古は確認済み（既存ルール）
    # org_filterなし（rdb系以外でもatla/gsdf等で馬毛島・普天間工事が出るため全機関適用）
    (["普天間", "辺野古", "嘉手納以南", "代替施設", "V字形滑走路",
      "馬毛島", "空母艦載機", "FCLP",
      "SACO", "沖合展開", "楚辺通信所",
      "グアム移転", "再編関連措置", "再編連絡"],
     8, 85, 0.90),

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

    # ── P2 艦対空ミサイル（高信頼: conf=0.88）──────────────────────────────────
    # SeaRAM/RIM-116: 艦艇近接防空、シースパロー/RIM-7: 中距離艦対空
    # SM-2: スタンダードミサイルMk2（イージス艦対空）、SM-3/SM-6は下のルールにも存在
    (["SeaRAM", "RIM-116", "シースパロー", "RIM-7",
      "SM-2", "スタンダードミサイル"],
     2, None, 0.88),

    # ── P2 統合防空ミサイル防衛能力 ─────────────────────────────────────────────
    # 迎撃システム・防空レーダ・早期警戒機
    # F-35/F15/F-2/戦闘機 は削除 → 上の P43 高優先ルールで処理
    # E-2D/早期警戒機は防空コアアセット（seibi_keikaku_gaiyou P2）なので維持
    (["イージス", "統合防空", "PAC-3", "SM-3", "SM-6", "ペトリオット",
      "LTAMDS", "FCネットワーク", "共同交戦能力", "CEC",
      "警戒管制レーダ", "地対空誘導弾",
      "防空ミサイル",
      "E-2D", "E2D", "早期警戒機"],
     2, None, 0.82),
    # ※ HPM・高出力マイクロ波・高出力レーザ は P43（電磁波）ルールへ移管

    # ── P2 自動警戒管制・移動式警戒監視（高優先: P5「自動警戒管制」0.72 に勝つ conf=0.84）
    # 自動警戒管制システム（JADGE）・J/TPS系移動式レーダは統合防空の中核システム
    (["自動警戒管制システム", "移動式警戒監視システム",
      "J/TPS-", "固定式警戒管制"],
     2, None, 0.84),

    # ── P3 無人アセット防衛能力 ──────────────────────────────────────────────────
    (["無人機", "UAV", "UUV", "USV", "UGV", "ドローン", "無人水中",
      "無人水上", "無人地上", "滞空型無人", "無人アセット", "無人航走",
      "偵察用無人", "攻撃用無人",
      # 追加
      "RQ-4", "シーガーディアン"],
     3, None, 0.78),

    # ── P3 スウォーム・UxV群制御（P82「研究試作」0.75 に勝つ conf=0.82）────────────
    # 根拠: UxVスウォーム技術の研究→P3確定（無人アセット防衛能力の中核技術）
    (["スウォーム", "UxVを活用した", "群制御技術", "複数UAV"],
     3, None, 0.82),

    # ── P41 宇宙 ─────────────────────────────────────────────────────────────
    (["宇宙", "衛星", "SSA", "宇宙作戦", "SDA", "宇宙状況把握",
      "宇宙領域把握", "コンステレーション", "宇宙航空"],
     4, 41, 0.82),

    # ── P42 サイバー ─────────────────────────────────────────────────────────
    (["サイバー", "ゼロトラスト", "RMF", "能動的サイバー",
      "防衛情報通信基盤", "DII", "セキュリティ強化", "ネットワーク防衛",
      "サイバー防衛",
      # クラウド・IT防衛インフラ（P84借上ルールの誤分類を回避）
      # 根拠: yosan FY2023 p21「中央クラウド整備（434億）・空自クラウド整備（756億）等」P42
      "クラウド", "IaaS", "PaaS", "SaaS",
      "スレットハンティング", "SNMS"],
     4, 42, 0.78),

    # ── P42 防衛セキュリティゲートウェイ（P5「セキュリティゲートウェイ」0.72 に勝つ conf=0.82）
    # 根拠: 防衛SGWはサイバー防衛インフラ（P42）、P5「指揮通信」とは別管理
    (["防衛セキュリティゲートウェイ", "防衛SGW", "マルチレベルセキュリティ共同設計"],
     4, 42, 0.82),

    # ── P82 次期戦闘機の開発（P43「次期戦闘機」0.88 に勝つ conf=0.91）───────────
    # 根拠: yosan FY2023 p40「次期戦闘機の開発（1,023億）」P82・再掲なし=P82本計上
    # 純粋な機体取得（F-35A/B等）はP43が本計上（p23 再掲なし）なのでこちらは開発費のみ
    # 「次期戦闘機（その*）」は開発フェーズの個別契約 → P82（手動修正2件で確認済み）
    (["次期戦闘機開発", "次期戦闘機の開発", "GCAPの開発",
      "次期戦闘機（その", "次期戦闘機用エンジンシステム"],
     8, 82, 0.91),

    # ── P43 次期戦闘機/GCAP（高優先: P2「戦闘機」0.82 に勝つ conf=0.88）───────────
    # 根拠: jigyou_review P43×3FY, hakusho P43×4FY, yosan P43 FY2022
    # 「戦闘機」P2:0.82 より高い conf を設定して P43 に正しく落とす
    (["次期戦闘機", "GCAP"],
     4, 43, 0.88),

    # ── P43 F-35A/B 取得（高優先: conf=0.85 > P2:0.82）─────────────────────────
    # 根拠: jigyou_review「戦闘機（F-35A/B）の取得」P43、seibi_keikaku_gaiyou P4
    # NFKC: 全角「Ｆ－３５Ａ」→「F-35A」に正規化されるため半角キーワードで照合可
    (["F-35A", "F-35B", "F35A", "F35B"],
     4, 43, 0.85),

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

    # ── P43 ソーナー/水中センサー（OQQ等 明示ルール） ─────────────────────────
    # 「ソーナー」「水中聴音」は上のP43ブロックにも含まれるが、
    # OQQ等の装備品コードをカバーするため独立エントリとして追加
    (["ソーナー", "OQQ", "水中聴音", "パッシブソーナー", "アクティブソーナー"],
     4, 43, 0.75),

    # ── P43 電磁波兵器（HPM・高出力マイクロ波・高出力レーザ: P2から移管 conf=0.83）──
    # 根拠: HPM装置(検証用)→P43確定。高出力マイクロ波・レーザ兵器・固体レーザは電磁波ドメイン
    # 「高出力レーザ」をP2から本ルールへ移管（conf=0.83 > P2の0.82 で確実にP43が勝つ）
    (["HPM", "高出力マイクロ波", "電磁波兵器", "電磁波装置",
      "高出力レーザ", "固体レーザ", "レーザ兵器", "高エネルギーレーザ"],
     4, 43, 0.83),

    # ── P43 ECM・電子対抗手段（conf=0.82）──────────────────────────────────────
    # 根拠: F-35用ECM装置→P43確定。電子対抗手段は電磁波ドメインのコア能力
    (["ECM装置", "電子対抗手段", "電子攻撃装置"],
     4, 43, 0.82),

    # ── P43 F-15能力向上（高優先: P73「改修」0.55/P72「改修整備」0.72 に勝つ conf=0.85）
    # 根拠: F-15能力向上量産改修→P43確定（改修キット取得は施設強靭化ではない）
    (["F-15能力向上", "F-15の能力向上", "F15能力向上",
      "F-2ミッション・トレーニング", "F-2用ターゲティング",
      "F-2緊急射出", "F-35用ECM"],
     4, 43, 0.85),

    # ── P43 ソノブイ/潜望鏡/艦砲（水中センサー・艦艇装備）──────────────────────
    # 根拠: ソノブイ=ソーナーと同じP43カテゴリ、非貫通式潜望鏡/センサマスト=艦艇センサ
    (["ソノブイ", "HQS-", "非貫通式潜望鏡", "センサマスト",
      "5インチ砲", "機関砲性能向上", "VLS MK", "垂直発射装置MK"],
     4, 43, 0.78),

    # ── P5 指揮統制・情報関連機能 ────────────────────────────────────────────
    # 「自動警戒管制」はP2高優先ルール(0.84)へ移管
    # 「セキュリティゲートウェイ」はP42専用ルール(0.82)へ移管
    (["指揮統制", "C4I", "統合作戦", "統合司令", "JADGE",
      "中央指揮システム", "作戦クラウド",
      "情報収集", "偵察", "SIGINT", "IMINT", "OSINT",
      "ターゲティング", "情報戦", "偽情報対策", "OODA", "認知戦",
      # 追加
      "指揮通信", "情報システム", "統合防空指揮",
      "野外通信", "野外系通信", "COTS", "指揮通信システム"],
     5, None, 0.72),

    # ── P5 戦術データリンク（P42「クラウド/サイバー」0.78 に勝つ conf=0.82）──────
    # 根拠: 戦術データリンク=Link-16等のC2ネットワーク → 指揮統制(P5)、サイバー(P42)ではない
    (["戦術データリンク", "J/MSQ-", "Link-16", "Link16", "TADIL"],
     5, None, 0.82),

    # ── P5 情報収集・画像情報・認知領域（conf=0.78）──────────────────────────────
    # 根拠: 「画像データの取得」「電波状況取得」=情報本部の情報収集業務 → P5
    # 「認知領域」は認知戦・情報戦の分析 → P5（P82「研究」0.62 に勝つ）
    (["画像データの取得", "画像データ取得", "電波状況取得",
      "認知領域", "情報優越", "電磁情報収集"],
     5, None, 0.78),

    # ── P5 海上・海中情報処理システム（conf=0.78）────────────────────────────────
    # 根拠: 海上作戦情報処理システム・MSII・OYX・GRQ系装置=C2/情報系 → P5
    (["海上作戦情報処理", "MSII", "OYX-", "GRQ-",
      "電波監視解析", "情報処理サブシステム", "収集システムGRQ",
      "地理空間情報支援"],
     5, None, 0.78),

    # ── P6 機動展開能力・国民保護 ────────────────────────────────────────────
    (["機動展開", "PFI船", "空中給油", "揚陸", "南西地域",
      "港湾整備", "国民保護", "住民避難", "機動舟艇", "LSV", "LCU",
      "コンテナトレーラー", "フォークリフト",
      # 輸送（機・艦・車両）
      "輸送", "輸送機", "C-2", "KC-46",
      # ロジスティクス基盤（P82「開発」より優先: 実用システム整備）
      "ロジスティクス基盤システム", "海自ロジスティクス"],
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

    # ── P71 対空ミサイル（短距離AAM: P1/P2未ヒット時のフォールバック）──────────
    # 根拠: AIM-9X サイドワインダー→P71確定（短距離AAM=弾薬カテゴリ）
    (["AIM-9", "AIM9", "サイドワインダー"],
     7, 71, 0.78),

    # ── P71 対戦車弾薬（りゅう弾・成形炸薬弾）──────────────────────────────────
    # 根拠: 120mmTKG JM12A1対戦車りゅう弾→P71確定（弾薬・誘導弾）
    (["対戦車りゅう弾", "対戦車弾", "120mmTKG", "JM12A1"],
     7, 71, 0.80),

    # ── P71 誘導弾（中信頼: P1/P2未ヒット時のフォールバック） ─────────────────
    # P1(0.82), P1-AAM(0.75), P2(0.82) のいずれかがヒットしていれば
    # KEYWORD_RULES の最高信頼度取得ロジックにより自動的にP1/P2が優先される
    (["誘導弾", "ミサイル"],
     7, 71, 0.70),

    # ── P72 F-35 ALGS（自律型後方支援: conf=0.88 > F-35A→P43:0.85）────────────
    # ALGS = Autonomic Logistics Global Sustainment（F-35の維持整備インフラ）
    # 根拠: bukai FY2025「F-35A」P7 と整合; 本体取得（P43）と維持整備（P72）を分離
    (["ALGS"],
     7, 72, 0.88),

    # ── P72 誘導弾/レーダー系の定期修理・システム維持（最高優先） ─────────────────
    # 根拠: ペトリオット定期修理3件・J/FPS定期修理4件・SeaRAM定期整備 全件P72確定
    # conf=0.89: P2「SeaRAM」0.88・P2「ペトリオット/警戒管制レーダ」0.82 に勝つ
    (["ペトリオット定期修理", "ペトリオット・システム維持",
      "試行定期修理", "現地定期修理",
      "の定期整備"],
     7, 72, 0.89),

    # ── P72 部品枯渇対策・改修キット（P73「改修」0.55 に勝つ conf=0.84）────────────
    # 根拠: MCH-101部品枯渇対策（改修キット）→P72確定（施設強靭化ではなく装備品維持）
    (["部品枯渇対策", "PAR部品", "枯渇対策改修", "改修キット",
      "補給支援の取得"],
     7, 72, 0.84),

    # ── P72 定期検査・定検（艦艇・武器: conf=0.82）────────────────────────────────
    # 根拠: 定期検査（艦船/武器）・艦艇等定検 全件P72確定（維持整備）
    (["定期検査", "艦艇等定検", "艦艇定検"],
     7, 72, 0.82),

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

    # ── P72 誘導弾/ミサイル整備修理（購入・取得・製造含む場合はP71が上位優先） ──
    # P71「誘導弾」(0.70)・「弾薬補用」(0.78) より整備系複合語を優先するための明示ルール
    # 「誘導弾購入」「誘導弾取得」等の場合は本ルールがマッチしないのでP71が適用される
    (["誘導弾整備", "ミサイル整備", "誘導弾定期整備", "誘導弾修理",
      "誘導弾オーバーホール", "誘導弾部品", "誘導弾検査"],
     7, 72, 0.80),

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
      "賃貸借",
      # 追加: 地質・土木調査（施設整備のための調査=P73）
      "土質調査", "地質調査", "地盤調査", "係留施設"],
     7, 73, 0.68),

    # ── P73 汎用工事（低信頼） ───────────────────────────────────────────────
    (["工事", "建設", "建築", "改修", "増築", "新築"],
     7, 73, 0.55),

    # ── P81 防衛生産基盤強化 ─────────────────────────────────────────────────
    (["防衛生産", "サプライチェーン", "装備移転", "防衛産業",
      "産業基盤", "生産能力", "輸出促進"],
     8, 81, 0.75),

    # ── P81 製造工程効率化・特定取組（P82「研究」0.62 に勝つ conf=0.85）─────────────
    # 根拠: 「製造工程効率化に係る特定取組」→P81確定（費用低減プログラム=防衛生産基盤）
    (["製造工程効率化", "特定取組"],
     8, 81, 0.85),

    # ── P82 実証装置・実証機（P2の0.82に勝つ conf=0.83）─────────────────────────
    # 根拠: 高出力レーザ実証装置(29億)→P82確定。「実証装置」は量産前R&Dフェーズを示す
    (["実証装置", "実証機"],
     8, 82, 0.83),

    # ── P82 FTB化改修・飛行試験機（P73「改修」0.55 に勝つ conf=0.84）──────────────
    # 根拠: FTB化試改修（Flying Test Bed化）=試験目的の機体改修=研究開発
    (["FTB化", "飛行試験機化", "FTB試改修"],
     8, 82, 0.84),

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
    # 「借上」はクラウドシステム借上（P42）と競合するため除外
    (["燃料", "軽油", "灯油", "ガソリン", "重油",
      "チャーター", "タクシー", "演習", "訓練"],
     8, 84, 0.62),

    # ── P6 補給艦・民間船舶（FY2024/2025追加） ───────────────────────────────
    (["補給艦", "補給艦艇", "民間船舶"],
     6, None, 0.78),

    # ── P43 掃海艦・電子作戦機・US-2・ガスタービン主機（FY2024/2025追加） ─────
    (["掃海艦", "掃海艇", "電子作戦機", "US-2", "ＵＳ－２", "救難飛行艇",
      "ガスタービン主機"],
     4, 43, 0.78),

    # ── P5 統合指揮・作戦指揮（FY2024追加） ─────────────────────────────────
    (["統合指揮", "作戦指揮"],
     5, None, 0.78),

    # ── P71 SDB・MK25キャニスタ（FY2024/2025追加） ──────────────────────────
    (["SDB", "ＳＤＢ", "ＭＫ２５", "MK25"],
     7, 71, 0.78),

    # ── P42 リスク管理枠組み=RMF（FY2024追加） ───────────────────────────────
    (["リスク管理枠組み"],
     4, 42, 0.82),

    # ── P43 地上車両（全体取得）（conf=0.73 > P72「維持整備」0.72）────────────────
    # 根拠: Percy確認済み（トラック/高機動車/装軌車/ドーザ等は全車両調達→P43確定）
    # conf=0.73: P72の最高値(0.72)より高く設定し、維持整備キーワードと同時ヒット時もP43優先
    (["トラック", "高機動車", "装軌車", "ドーザ", "装甲車",
      "10式戦車", "16式機動戦闘車", "11式装軌車"],
     4, 43, 0.73),

    # ── P43 火砲・小火器（取得）──────────────────────────────────────────────
    # 根拠: 機関砲/無反動砲/砲座は装備品取得→P43（弾薬・砲弾はP71ルールが上位）
    (["機関砲", "無反動砲", "火砲", "砲座", "施線砲"],
     4, 43, 0.72),

    # ── P43 デコイ・おとり装備 ────────────────────────────────────────────────
    (["デコイ"],
     4, 43, 0.75),

    # ── P43 音響測定装置・水中音響センサー（ソーナー系）──────────────────────────
    # 根拠: 音響測定装置信号処理部=ソーナー関連→P43確定
    (["音響測定装置", "音響特性分析", "水中音響"],
     4, 43, 0.75),

    # ── P5 UC統合通信・システムネットワーク管理 ────────────────────────────────
    # 根拠: UCサービス基盤=統合通信インフラ→P5、システムネットワーク管理=C2インフラ→P5
    (["UCサービス", "システムネットワーク管理", "システム・ネットワーク管理",
      "統合通信基盤"],
     5, None, 0.75),

    # ── P71 航空爆弾（GBU/JDAM系）───────────────────────────────────────────
    # 根拠: GBU-39(SDB)等は弾薬→P71確定
    (["GBU-", "JDAM"],
     7, 71, 0.78),
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


# ─── org_fallback ─────────────────────────────────────────────────────────────
_FMS_AMMO_KWS = [
    "AMMO", "AMMUNITION", "MISSILE", "CARTRIDGE",
    "ROCKET", "WARHEAD", "BOMB", "GRENADE",
]

_HOKYUSHO_VEHICLE_KWS: list[str] = [
    norm(kw) for kw in [
        "航空機", "艦船", "護衛艦", "潜水艦", "ヘリコプター", "ヘリ",
        "輸送機", "戦闘機", "掃海艦", "掃海艇", "哨戒機", "哨戒艦",
        "戦車", "装甲車", "高機動車", "装軌車",
    ]
]

def apply_org_fallback(
    conn: sqlite3.Connection, fy: int, dry_run: bool = False
) -> dict[str, int]:
    """
    keyword_rule / fuzzy_jigyou で未分類の行に対して機関情報ベースの追加分類を適用。

    Rule 1: 装備庁研究所 → P82（研究開発）
      agency_id LIKE 'atla%' AND agency_name に「研究所」「技術研究本部」「研究本部」のいずれか
    Rule 2: 情報本部 → P5（指揮統制・情報）
      agency_name LIKE '%情報本部%' OR requesting_org = 'DIH'
    Rule 3: FMS弾薬 → P12 (l1=1, l2=12)
      contract_name が英大文字主体 かつ AMMO/MISSILE 等の弾薬キーワードを含む
    Rule 4: 補給処 → P43（乗り物系）or P72（部品・消耗品系）
      agency_name LIKE '%補給処%'
    """
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts: dict[str, int] = {
        "atla_research": 0, "dih": 0, "fms_ammo": 0,
        "hokyusho_vehicle": 0, "hokyusho_parts": 0,
    }

    # Rule 1: 装備庁研究所 → P82
    rule1_rows = cur.execute("""
        SELECT cp.contract_id
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.match_method = 'unclassified'
          AND c.agency_id LIKE 'atla%'
          AND (  c.agency_name LIKE '%研究所%'
              OR c.agency_name LIKE '%技術研究本部%'
              OR c.agency_name LIKE '%研究本部%')
    """, (fy,)).fetchall()
    rule1_ids = [r[0] for r in rule1_rows]
    counts["atla_research"] = len(rule1_ids)
    if not dry_run and rule1_ids:
        cur.executemany("""
            UPDATE contract_pillar
            SET pillar_l1_code = 8, pillar_l2_code = 82, confidence = 0.62,
                match_method = 'org_fallback', match_source = 'atla_research→P82',
                updated_at = ?
            WHERE contract_id = ?
        """, [(now_iso, cid) for cid in rule1_ids])

    # Rule 2: 情報本部 → P5（l2=None）
    # agency_name に「情報本部」を含む場合、または contract_requesting_org.requesting_org = 'DIH'
    rule2_rows = cur.execute("""
        SELECT DISTINCT cp.contract_id
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        LEFT JOIN contract_requesting_org cro ON cro.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.match_method = 'unclassified'
          AND (c.agency_name LIKE '%情報本部%' OR cro.requesting_org = 'DIH')
    """, (fy,)).fetchall()
    rule2_ids = [r[0] for r in rule2_rows]
    counts["dih"] = len(rule2_ids)
    if not dry_run and rule2_ids:
        cur.executemany("""
            UPDATE contract_pillar
            SET pillar_l1_code = 5, pillar_l2_code = NULL, confidence = 0.60,
                match_method = 'org_fallback', match_source = 'dih→P5',
                updated_at = ?
            WHERE contract_id = ?
        """, [(now_iso, cid) for cid in rule2_ids])

    # Rule 3: FMS弾薬 → P12（l1=1, l2=12）
    # 英大文字3文字以上連続 かつ 弾薬キーワードを含む
    kw_cond = " OR ".join("c.contract_name LIKE ?" for _ in _FMS_AMMO_KWS)
    rule3_rows = cur.execute(f"""
        SELECT cp.contract_id
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.match_method = 'unclassified'
          AND c.contract_name GLOB '*[A-Z][A-Z][A-Z]*'
          AND ({kw_cond})
    """, [fy] + [f"%{kw}%" for kw in _FMS_AMMO_KWS]).fetchall()
    rule3_ids = [r[0] for r in rule3_rows]
    counts["fms_ammo"] = len(rule3_ids)
    if not dry_run and rule3_ids:
        cur.executemany("""
            UPDATE contract_pillar
            SET pillar_l1_code = 1, pillar_l2_code = 12, confidence = 0.62,
                match_method = 'org_fallback', match_source = 'fms_ammo→P12',
                updated_at = ?
            WHERE contract_id = ?
        """, [(now_iso, cid) for cid in rule3_ids])

    # Rule 4: 補給処 → P43（乗り物系）or P72（部品・消耗品系）
    # 乗り物系: 航空機/護衛艦/戦闘機/ヘリ/戦車等のキーワードを含む → P43 conf=0.60
    # 部品・消耗品系: 上記以外（FMSスペアパーツ・整備品等） → P72 conf=0.55
    rule4_rows = cur.execute("""
        SELECT cp.contract_id, c.contract_name
        FROM contract_pillar cp
        JOIN contracts c ON cp.contract_id = c.id
        WHERE cp.fiscal_year = ?
          AND cp.match_method = 'unclassified'
          AND c.agency_name LIKE '%補給処%'
    """, (fy,)).fetchall()

    rule4a_ids: list[int] = []  # 乗り物系 → P43
    rule4b_ids: list[int] = []  # 部品・消耗品系 → P72
    for cid, cname in rule4_rows:
        n = norm(cname or "")
        if any(kw in n for kw in _HOKYUSHO_VEHICLE_KWS):
            rule4a_ids.append(cid)
        else:
            rule4b_ids.append(cid)

    counts["hokyusho_vehicle"] = len(rule4a_ids)
    counts["hokyusho_parts"]   = len(rule4b_ids)

    if not dry_run and rule4a_ids:
        cur.executemany("""
            UPDATE contract_pillar
            SET pillar_l1_code = 4, pillar_l2_code = 43, confidence = 0.60,
                match_method = 'org_fallback', match_source = 'hokyusho→P43',
                updated_at = ?
            WHERE contract_id = ?
        """, [(now_iso, cid) for cid in rule4a_ids])

    if not dry_run and rule4b_ids:
        cur.executemany("""
            UPDATE contract_pillar
            SET pillar_l1_code = 7, pillar_l2_code = 72, confidence = 0.55,
                match_method = 'org_fallback', match_source = 'hokyusho→P72',
                updated_at = ?
            WHERE contract_id = ?
        """, [(now_iso, cid) for cid in rule4b_ids])

    if not dry_run:
        conn.commit()
    return counts


# ─── manual_corrections 再適用 ────────────────────────────────────────────────
def apply_manual_corrections(
    conn: sqlite3.Connection, fy: int, snapshot_path: Path, dry_run: bool = False
) -> int:
    """
    manual_corrections_snapshot.json に記録された手動修正を contract_pillar に上書き適用。
    DELETE 後の再実行で自動分類に埋もれないよう conf=0.99 で保護する。

    JSON 形式: {"contract_id": [l1, l2_or_null], ...}
    """
    if not snapshot_path.exists():
        print(f"  [manual_corrections] スナップショットなし: {snapshot_path}")
        return 0

    with open(snapshot_path, encoding="utf-8") as f:
        snapshot: dict[str, list] = json.load(f)

    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # fy 内の contract_id のみ対象（他FY修正を誤って上書きしない）
    fy_ids = {
        r[0]
        for r in cur.execute(
            "SELECT contract_id FROM contract_pillar WHERE fiscal_year = ?", (fy,)
        ).fetchall()
    }

    rows: list[tuple] = []
    for cid_str, (l1, l2) in snapshot.items():
        cid = int(cid_str)
        if cid not in fy_ids:
            continue
        rows.append((l1, l2, 0.99, "manual_correction", cid_str, now_iso, cid))

    if not dry_run and rows:
        cur.executemany("""
            UPDATE contract_pillar
            SET pillar_l1_code = ?, pillar_l2_code = ?, confidence = ?,
                match_method = ?, match_source = ?, updated_at = ?
            WHERE contract_id = ?
        """, rows)
        conn.commit()

    return len(rows)


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
def main(dry_run: bool = False, fy: int = TARGET_FY, gap_fill: bool = False) -> None:
    corpus = build_fuzzy_corpus(str(DB_PILLAR))
    corpus_names = [c[0] for c in corpus]
    name_to_pid  = {c[0]: c[1] for c in corpus}
    print(f"Fuzzy corpus size: {len(corpus_names)} entries")
    print(f"Target FY: {fy}")

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

    # FY対象の既存行を削除（冪等実行のため）— gap_fill時はスキップ
    if not dry_run and not gap_fill:
        cur.execute("DELETE FROM contract_pillar WHERE fiscal_year = ?", (fy,))
        conn.commit()
        print(f"FY{fy} existing rows deleted.")
    elif gap_fill:
        print(f"FY{fy} gap-fill mode: 既存行を保持して未分類契約のみ対象")

    # FY 契約ロード（gap_fill時は contract_pillar に行がない契約のみ）
    if gap_fill:
        cur.execute("""
            SELECT id, contract_name, agency_id
            FROM contracts
            WHERE fiscal_year = ?
              AND id NOT IN (SELECT contract_id FROM contract_pillar)
        """, (fy,))
    else:
        cur.execute("""
            SELECT id, contract_name, agency_id
            FROM contracts
            WHERE fiscal_year = ?
        """, (fy,))
    contracts = cur.fetchall()
    print(f"FY{fy} contracts loaded: {len(contracts)}")

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

        print(f"\n=== DRY RUN 分類見込み (FY{fy}: {len(contracts)}件) ===")
        print(f"  Pass1 fuzzy_jigyou : {fuzzy_count:6d}件 ({fuzzy_count/len(contracts)*100:.1f}%)")
        print(f"  Pass2 keyword_rule : {keyword_count:6d}件 ({keyword_count/len(contracts)*100:.1f}%)")
        print(f"  未分類             : {unclassified:6d}件 ({unclassified/len(contracts)*100:.1f}%)")
        print()
        print("=== DRY RUN: org_fallback 見込み ===")
        fb_counts = apply_org_fallback(conn, fy, dry_run=True)
        print(f"  Rule1 atla_research→P82  : {fb_counts['atla_research']:4d}件")
        print(f"  Rule2 dih→P5             : {fb_counts['dih']:4d}件")
        print(f"  Rule3 fms_ammo→P12       : {fb_counts['fms_ammo']:4d}件")
        print(f"  Rule4a hokyusho→P43      : {fb_counts['hokyusho_vehicle']:4d}件")
        print(f"  Rule4b hokyusho→P72      : {fb_counts['hokyusho_parts']:4d}件")
        mc_count = apply_manual_corrections(conn, fy, CORRECTIONS_JSON, dry_run=True)
        print(f"  manual_correction再適用   : {mc_count:4d}件")
        conn.close()
        return

    # ─── 本番: DB書き込み ────────────────────────────────────────────────
    rows_to_insert = [
        (r[0], r[1], r[2], r[3], r[4], r[5], fy, now_iso)
        for r in results
    ]
    insert_sql = """
        INSERT OR {} INTO contract_pillar
        (contract_id, pillar_l1_code, pillar_l2_code, confidence,
         match_method, match_source, fiscal_year, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """.format("IGNORE" if gap_fill else "REPLACE")
    cur.executemany(insert_sql, rows_to_insert)
    conn.commit()
    print(f"\n{len(rows_to_insert)} rows inserted into contract_pillar ({'IGNORE' if gap_fill else 'REPLACE'}).")

    # ─── org_fallback ステージ ──────────────────────────────────────────────
    print("\n=== org_fallback 適用 ===")
    fb_counts = apply_org_fallback(conn, fy, dry_run=False)
    print(f"  Rule1 atla_research→P82  : {fb_counts['atla_research']:4d}件")
    print(f"  Rule2 dih→P5             : {fb_counts['dih']:4d}件")
    print(f"  Rule3 fms_ammo→P12       : {fb_counts['fms_ammo']:4d}件")
    print(f"  Rule4a hokyusho→P43      : {fb_counts['hokyusho_vehicle']:4d}件")
    print(f"  Rule4b hokyusho→P72      : {fb_counts['hokyusho_parts']:4d}件")
    org_fallback_total = sum(fb_counts.values())
    print(f"  合計                    : {org_fallback_total:4d}件")

    # ─── manual_corrections 再適用 ─────────────────────────────────────────
    print("\n=== manual_corrections 再適用 ===")
    mc_count = apply_manual_corrections(conn, fy, CORRECTIONS_JSON, dry_run=False)
    print(f"  適用件数: {mc_count}件")

    # ─── 集計レポート ───────────────────────────────────────────────────────
    print(f"\n=== FY{fy} 分類結果 ===")
    print(f"  対象件数           : {len(contracts):6d}件")
    print(f"  Pass1 fuzzy_jigyou : {fuzzy_count:6d}件 ({fuzzy_count/len(contracts)*100:.1f}%)")
    print(f"  Pass2 keyword_rule : {keyword_count:6d}件 ({keyword_count/len(contracts)*100:.1f}%)")
    print(f"  Pass3 org_fallback : {org_fallback_total:6d}件 ({org_fallback_total/len(contracts)*100:.1f}%)")
    print(f"  manual_correction  : {mc_count:6d}件")
    remaining = unclassified - org_fallback_total - mc_count
    print(f"  未分類（残）       : {remaining:6d}件 ({remaining/len(contracts)*100:.1f}%)")

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
    """, (fy,))
    pillar_rows = cur.fetchall()

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
    for l1, cnt, amt in pillar_rows:
        name = PILLAR_NAMES.get(l1, f"P{l1}")
        amt_s = f"{amt}億円" if amt else "（金額なし）"
        print(f"  {name:30s}: {cnt:6d}件 / {amt_s}")

    # match_method 別集計
    print(f"\n=== match_method 別 ===")
    cur.execute("""
        SELECT match_method, COUNT(*) FROM contract_pillar
        WHERE fiscal_year = ? GROUP BY match_method ORDER BY COUNT(*) DESC
    """, (fy,))
    for method, cnt in cur.fetchall():
        print(f"  {method:20s}: {cnt:6d}件")

    conn.close()
    print("\n完了。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="DBに書き込まず上位マッチ20件を確認する")
    parser.add_argument("--fy", type=int, default=TARGET_FY,
                        help=f"対象年度（デフォルト: {TARGET_FY}）")
    parser.add_argument("--gap-fill", action="store_true",
                        help="既存行を保持し、contract_pillarに行がない契約のみ分類（セマンティック結果を保護）")
    args = parser.parse_args()
    main(dry_run=args.dry_run, fy=args.fy, gap_fill=args.gap_fill)
