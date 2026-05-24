# 7本柱分類判定ロジック (contract_pillar)

**対象スクリプト**:
- `dev/assign_pillar_fy2023.py` — キーワード分類メインスクリプト（--fy 引数でFY指定）
- `dev/assign_pillar_semantic.py` — セマンティック埋め込み分類
- `dashboard/pages/6_pillar_db_viewer.py` — ダッシュボード表示
- `dashboard/pages/98_pillar_logic.py` — ロジック説明ページ

**出力先テーブル**: `procurement.db` の `contract_pillar`

---

## ピラー定義

防衛力整備計画（2022年12月）の「7本柱」＋「防衛生産・技術基盤（共通基盤）」。
ダッシュボードでは P8 を含む 8 分類 + L2 サブ分類で管理。

### L1（大分類）

| pillar_id | 日本語名 | 略称 |
|-----------|---------|------|
| 1 | スタンド・オフ防衛能力 | P1 |
| 2 | 統合防空ミサイル防衛能力 | P2 |
| 3 | 無人アセット防衛能力 | P3 |
| 4 | 領域横断作戦能力 | P4 |
| 5 | 指揮統制・情報関連機能 | P5 |
| 6 | 機動展開能力・国民保護 | P6 |
| 7 | 持続性・強靱性 | P7 |
| 8 | 防衛生産・技術基盤（共通基盤） | P8 |

### L2（サブ分類）

| pillar_id | 親 | 日本語名 |
|-----------|-----|---------|
| 41 | P4 | 宇宙領域把握 |
| 42 | P4 | サイバー防衛 |
| 43 | P4 | 電磁波・主要装備（艦艇・航空機・地上装備等） |
| 71 | P7 | 弾薬・誘導弾の確保 |
| 72 | P7 | 装備品等の可動率向上 |
| 73 | P7 | 施設強靱化・後方 |
| 81 | P8 | 防衛生産基盤強化 |
| 82 | P8 | 研究開発 |
| 83 | P8 | 基地対策 |
| 84 | P8 | 教育訓練・燃料等 |
| 85 | P8 | 米軍再編関係経費 |

**L1/L2 の変換規則**:
```python
if pillar_id <= 8:
    l1 = pillar_id
    l2 = None
else:
    l1 = pillar_id // 10   # 41 → 4, 72 → 7, 84 → 8
    l2 = pillar_id
```

---

## 分類ステップ（優先度順）

```
Pass 1: fuzzy_jigyou     ← defense_pillar_jigyou + pillar_mapping_sources との rapidfuzz 一致
Pass 2: keyword_rule     ← KEYWORD_RULES の全件スキャン（最高conf採用）
  └── org_maintenance fallback  ← conf不足時の維持整備・燃料系フォールバック
  └── ATLA research fallback    ← ATLA研究機関の研究開発フォールバック
Pass 3: semantic_embedding ← multilingual-e5-large でコサイン類似度
Pass 4: manual_correction  ← JSON辞書から直接書き込み（protected）
└── Unclassified           ← いずれにも合致しない場合
```

---

## Pass 1: fuzzy_jigyou（match_method='fuzzy_jigyou'）

**コーパス**: `defense_pillar_jigyou` + `pillar_mapping_sources` テーブルから `jigyou_name_norm` を読み込む。

```sql
SELECT jigyou_name_norm, pillar_id FROM defense_pillar_jigyou
  WHERE jigyou_name_norm IS NOT NULL
UNION ALL
SELECT jigyou_name_norm, pillar_id FROM pillar_mapping_sources
  WHERE jigyou_name_norm IS NOT NULL
```

**マッチング**:
- ライブラリ: `rapidfuzz.process.extractOne()`
- スコアリング: `token_set_ratio`（語順・部分一致に強い）
- 閾値: **score ≥ 78**
- confidence = score / 100

このパスが通れば以降のパスはスキップ。

---

## Pass 2: keyword_rule（match_method='keyword_rule'）

### 基本動作

```python
# 全 KEYWORD_RULES を contract_name に対してスキャン
best_conf = 0.0
best_result = None
for rule in KEYWORD_RULES:
    if rule.matches(contract_name, org):
        if rule.conf > best_conf:
            best_conf = rule.conf
            best_result = rule
# 最高confのルールを採用（先頭一致ではない）
```

**正規化**: `unicodedata.normalize("NFKC", s)` のみ（句読点除去なし）。
`org_filter` が指定されているルールは、`agency_to_org(agency_id)` が一致する場合のみ適用。

### 機関→org変換

```python
def agency_to_org(agency_id: str | None) -> str:
    a = agency_id.lower()
    if a.startswith("gsdf"):     return "GSDF"
    if a.startswith("msdf"):     return "MSDF"
    if a.startswith("asdf"):     return "ASDF"
    if a.startswith("atla"):     return "ATLA"
    if a.startswith("rdb"):      return "RDB"
    if a.startswith("js"):       return "JS"
    if a.startswith("dih"):      return "DIH"
    if a.startswith("nids"):     return "NIDS"
    if a.startswith("ndmc"):     return "NDMC"
    if a.startswith("nda"):      return "NDA"
    if a.startswith("naikyoku"): return "NAIKYOKU"
    return "OTHER"
```

---

## KEYWORD_RULES 完全テーブル

`_KEYWORD_RULES_RAW` の全エントリ。conf が同じルールが並んでいる場合、
高い方が採用される（全スキャン後に最高conf選択）。

### P1 — スタンド・オフ防衛能力

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| スタンドオフ, スタンド・オフ, 高速滑空弾, トマホーク, 極超音速, 12式地対艦, 島嶼防衛用, 反撃能力, 長射程, スタンドインジャマー, スタンド・イン・ジャマー, VLS搭載潜水艦, JSM, JASSM, LRASM, 93式空対艦 | 1 | — | 0.82 | — |
| AIM-120, AIM120, AAM-4, AAM-5, AAM4, AAM5 | 1 | — | 0.75 | — |

### P2 — 統合防空ミサイル防衛能力

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| SeaRAM, RIM-116, シースパロー, RIM-7, SM-2, スタンダードミサイル | 2 | — | 0.88 | — |
| イージス, 統合防空, PAC-3, SM-3, SM-6, ペトリオット, LTAMDS, FCネットワーク, 共同交戦能力, CEC, 警戒管制レーダ, 地対空誘導弾, 防空ミサイル, E-2D, E2D, 早期警戒機 | 2 | — | 0.82 | — |
| 自動警戒管制システム, 移動式警戒監視システム, J/TPS-, 固定式警戒管制 | 2 | — | 0.84 | — |

### P3 — 無人アセット防衛能力

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 無人機, UAV, UUV, USV, UGV, ドローン, 無人水中, 無人水上, 無人地上, 滞空型無人, 無人アセット, 無人航走, 偵察用無人, 攻撃用無人, RQ-4, シーガーディアン | 3 | — | 0.78 | — |
| スウォーム, UxVを活用した, 群制御技術, 複数UAV | 3 | — | 0.82 | — |

### P4 — 領域横断作戦能力

#### P41 — 宇宙領域把握

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 宇宙, 衛星, SSA, 宇宙作戦, SDA, 宇宙状況把握, 宇宙領域把握, コンステレーション, 宇宙航空 | 4 | 41 | 0.82 | — |

#### P42 — サイバー防衛

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 防衛セキュリティゲートウェイ, 防衛SGW, マルチレベルセキュリティ共同設計 | 4 | 42 | 0.82 | — |
| サイバー, ゼロトラスト, RMF, 能動的サイバー, 防衛情報通信基盤, DII, セキュリティ強化, ネットワーク防衛, サイバー防衛, クラウド, IaaS, PaaS, SaaS, スレットハンティング, SNMS | 4 | 42 | 0.78 | — |

#### P43 — 電磁波・主要装備

**重要**: 次期戦闘機「開発」は P82 が優先（conf=0.91 > 0.88）。取得・量産は P43。

| キーワード | L1 | L2 | conf | org_filter | 備考 |
|-----------|----|----|------|-----------|------|
| 次期戦闘機開発, 次期戦闘機の開発, GCAPの開発, 次期戦闘機（その, 次期戦闘機用エンジンシステム | 8 | 82 | 0.91 | — | **P82優先** |
| 次期戦闘機, GCAP | 4 | 43 | 0.88 | — | 取得 |
| F-35A, F-35B, F35A, F35B | 4 | 43 | 0.85 | — | P2より優先 |
| F-15能力向上, F-15の能力向上, F15能力向上, F-2ミッション・トレーニング, F-2用ターゲティング, F-2緊急射出, F-35用ECM | 4 | 43 | 0.85 | — | アップグレードキット（P73より優先） |
| HPM, 高出力マイクロ波, 電磁波兵器, 電磁波装置, 高出力レーザ, 固体レーザ, レーザ兵器, 高エネルギーレーザ | 4 | 43 | 0.83 | — | 指向性エネルギー兵器 |
| ECM装置, 電子対抗手段, 電子攻撃装置 | 4 | 43 | 0.82 | — | 電子妨害 |
| 電磁波, 電子戦, EW, 電磁妨害, NEWS, スタンドオフ電子戦機, 信号探知, 電磁パルス, EMP | 4 | 43 | 0.75 | — | 電磁波全般 |
| 護衛艦, 哨戒艦, 潜水艦, イージス艦, FFM | 4 | 43 | 0.75 | — | 艦艇取得 |
| 哨戒機, 固定翼哨戒, P-1, SH-60, SH60, UH-60, UH60, CH-47, CH47, AH-64, AH64, OH-1, OH1, V-22, V22, E-767, E767 | 4 | 43 | 0.75 | — | 航空機取得 |
| レーダ, ソナー, ソーナー, 水中聴音, 音響探知, HPS-, FPS-, 機上電波, 電波測定 | 4 | 43 | 0.75 | — | センサ類 |
| ガスタービン機関, エンジン搭載用 | 4 | 43 | 0.75 | — | エンジン |
| OQQ, パッシブソーナー, アクティブソーナー | 4 | 43 | 0.75 | — | ソーナー型番 |
| ソノブイ, HQS-, 非貫通式潜望鏡, センサマスト, 5インチ砲, 機関砲性能向上, VLS MK, 垂直発射装置MK | 4 | 43 | 0.78 | — | 艦載兵器 |
| 掃海艦, 掃海艇, 電子作戦機, US-2, ＵＳ－２, 救難飛行艇, ガスタービン主機 | 4 | 43 | 0.78 | — | FY2024追加 |
| トラック, 高機動車, 装軌車, ドーザ, 装甲車, 10式戦車, 16式機動戦闘車, 11式装軌車 | 4 | 43 | 0.73 | — | 地上車両 |
| 機関砲, 無反動砲, 火砲, 砲座, 施線砲 | 4 | 43 | 0.72 | — | 火砲 |
| デコイ | 4 | 43 | 0.75 | — | デコイ |
| 音響測定装置, 音響特性分析, 水中音響 | 4 | 43 | 0.75 | — | 音響センサ |

### P5 — 指揮統制・情報関連機能

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 戦術データリンク, J/MSQ-, Link-16, Link16, TADIL | 5 | — | 0.82 | — |
| 画像データの取得, 画像データ取得, 電波状況取得, 認知領域, 情報優越, 電磁情報収集 | 5 | — | 0.78 | — |
| 海上作戦情報処理, MSII, OYX-, GRQ-, 電波監視解析, 情報処理サブシステム, 収集システムGRQ, 地理空間情報支援 | 5 | — | 0.78 | — |
| UCサービス, システムネットワーク管理, システム・ネットワーク管理, 統合通信基盤 | 5 | — | 0.75 | — |
| 統合指揮, 作戦指揮 | 5 | — | 0.78 | — |
| 指揮統制, C4I, 統合作戦, 統合司令, JADGE, 中央指揮システム, 作戦クラウド, 情報収集, 偵察, SIGINT, IMINT, OSINT, ターゲティング, 情報戦, 偽情報対策, OODA, 認知戦, 指揮通信, 情報システム, 統合防空指揮, 野外通信, 野外系通信, COTS, 指揮通信システム | 5 | — | 0.72 | — |

### P6 — 機動展開能力・国民保護

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 補給艦, 補給艦艇, 民間船舶 | 6 | — | 0.78 | — |
| 機動展開, PFI船, 空中給油, 揚陸, 南西地域, 港湾整備, 国民保護, 住民避難, 機動舟艇, LSV, LCU, コンテナトレーラー, フォークリフト, 輸送, 輸送機, C-2, KC-46, ロジスティクス基盤システム, 海自ロジスティクス | 6 | — | 0.70 | — |

### P7 — 持続性・強靱性

#### P71 — 弾薬・誘導弾の確保

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 弾薬, 火薬, 火工品, 火薬庫, 弾薬庫, 弾薬整備, 弾薬補給, 爆薬, 信管, 155ミリ, 81ミリ, 60ミリ, BALL, 魚雷, 機雷, 炸薬, ミサイル補用, 誘導弾補用 | 7 | 71 | 0.78 | — |
| AIM-9, AIM9, サイドワインダー | 7 | 71 | 0.78 | — |
| 対戦車りゅう弾, 対戦車弾, 120mmTKG, JM12A1 | 7 | 71 | 0.80 | — |
| SDB, ＳＤＢ, ＭＫ２５, MK25 | 7 | 71 | 0.78 | — |
| GBU-, JDAM | 7 | 71 | 0.78 | — |
| 誘導弾, ミサイル | 7 | 71 | 0.70 | — | 汎用（最低優先） |

#### P72 — 装備品等の可動率向上

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| ALGS | 7 | 72 | 0.88 | — | F-35整備インフラ |
| ペトリオット定期修理, ペトリオット・システム維持, 試行定期修理, 現地定期修理, の定期整備 | 7 | 72 | 0.89 | — | 最高優先 |
| 部品枯渇対策, PAR部品, 枯渇対策改修, 改修キット, 補給支援の取得 | 7 | 72 | 0.84 | — |
| 定期検査, 艦艇等定検, 艦艇定検 | 7 | 72 | 0.82 | — |
| 誘導弾整備, ミサイル整備, 誘導弾定期整備, 誘導弾修理, 誘導弾オーバーホール, 誘導弾部品, 誘導弾検査 | 7 | 72 | 0.80 | — |
| 可動率, 整備補給, 予備部品, 修理部品, 補用部品, 整備用資材, 修理費, 可動向上, 維持整備, 維持修理, 部品費, 維持費, 成果払い, PBL, 包括契約, 補用品, 修理用部品, 保守整備, 性能維持, 機能維持, エンジン補用, 補用エンジン, 補用, オーバーホール, 定期修理, 改修整備 | 7 | 72 | 0.72 | — |
| 保守, 修繕, オーバーホール, 修理, 整備, 維持, 点検整備, 定期整備, 整備作業 | 7 | 72 | 0.60 | — | 汎用（最低優先） |

#### P73 — 施設強靱化・後方

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 地下化, えん体, 分散パッド, 格納庫強化, 施設強靱, ライフライン, EMP対策, 施設工事, 建設工事, 建築工事, 改修工事, 舗装工事, 庁舎建設, 倉庫建設, 格納庫建設, 施設整備, 賃貸借, 土質調査, 地質調査, 地盤調査, 係留施設 | 7 | 73 | 0.68 | — |
| 工事, 建設, 建築, 改修, 増築, 新築 | 7 | 73 | 0.55 | — | 汎用（最低優先） |

### P8 — 防衛生産・技術基盤（共通基盤）

#### P81 — 防衛生産基盤強化

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 製造工程効率化, 特定取組 | 8 | 81 | 0.85 | — | P82より優先 |
| 防衛生産, サプライチェーン, 装備移転, 防衛産業, 産業基盤, 生産能力, 輸出促進 | 8 | 81 | 0.75 | — |

#### P82 — 研究開発

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 次期戦闘機開発, 次期戦闘機の開発, GCAPの開発, 次期戦闘機（その, 次期戦闘機用エンジンシステム | 8 | 82 | 0.91 | — | **最高優先（P43より強い）** |
| FTB化, 飛行試験機化, FTB試改修 | 8 | 82 | 0.84 | — | 飛行試験機化（P73より優先） |
| 実証装置, 実証機 | 8 | 82 | 0.83 | — | 概念実証（P2より優先） |
| 研究開発, 試作品, 基礎研究, 応用研究, 技術研究, 研究試作, 防衛イノベーション, 技術実証, 先端技術研究, 概念研究, 探索研究, 先進技術, 将来型 | 8 | 82 | 0.75 | — |
| 試作, 研究, 開発, DISTI | 8 | 82 | 0.62 | — | 汎用（最低優先） |

#### P83 — 基地対策

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 賃貸借, 土地賃貸, 移転補償, 家屋防音, 飛行場周辺 | 8 | 83 | 0.85 | RDB限定 |
| 騒音対策, 防音工事, 基地対策, 基地周辺, 防音, 補償, 民生安定, 住宅防音 | 8 | 83 | 0.75 | — |

#### P84 — 教育訓練・燃料等

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| 教育訓練, 訓練弾, 訓練費, 演習用, 航空機燃料, JP-8, JP8, Jet-A, JetA, 潤滑油, 作動油, 燃料油 | 8 | 84 | 0.72 | — |
| 燃料, 軽油, 灯油, ガソリン, 重油, チャーター, タクシー, 演習, 訓練 | 8 | 84 | 0.62 | — | 汎用（最低優先） |

#### P85 — 米軍再編関係経費

| キーワード | L1 | L2 | conf | org_filter |
|-----------|----|----|------|-----------|
| シュワブ | 8 | 85 | 0.92 | — | **全ルール最高優先** |
| 普天間, 辺野古, 嘉手納以南, 代替施設, V字形滑走路, 馬毛島, 空母艦載機, FCLP, SACO, 沖合展開, 楚辺通信所, グアム移転, 再編関連措置, 再編連絡 | 8 | 85 | 0.90 | — |

---

## org_maintenance fallback（Pass 2 内部）

Pass 2 終了後、**最高 conf < 0.65** の契約に対して追加判定。

```python
# 維持整備フォールバック
if best_conf < 0.65 and org in {"GSDF", "MSDF", "ASDF", "JS", "ATLA", "RDB"}:
    maint_kws = ["維持", "整備", "修理", "修繕", "補修", "点検", "保守"]
    if any(kw in contract_name_nfkc for kw in maint_kws):
        → assign P72, "org_fallback", conf=0.60

# 燃料フォールバック
fuel_kws = ["燃料", "灯油", "軽油", "ガソリン", "JP-", "Jet-"]
if any(kw in contract_name_nfkc for kw in fuel_kws):
    → assign P84, "org_fallback", conf=0.60
```

## ATLA research fallback（Pass 2 内部）

```python
# ATLA機関 + conf不足 + 研究所名
if org == "ATLA" and best_conf < 0.62:
    if any(kw in agency_name for kw in ["研究所", "技術研究本部", "研究本部"]):
        res_kws = ["研究", "試作", "開発", "技術評価"]
        if any(kw in contract_name_nfkc for kw in res_kws):
            → assign P82, "org_fallback", conf=0.58
```

---

## Pass 3: semantic_embedding（match_method='semantic_embedding'）

**対象**: `match_method = 'unclassified'` の契約のみ（keyword_rule未分類）。

**モデル**: `intfloat/multilingual-e5-large`

| パラメータ | 値 |
|-----------|-----|
| デバイス | GPU (CUDA) / CPU fallback |
| バッチサイズ | 256 |
| 類似度指標 | コサイン類似度（L2正規化後の内積） |
| 入力形式（ピラー説明） | `"passage: {pillar_description}"` |
| 入力形式（契約名） | `"query: {contract_name}"` |
| デフォルト閾値 | 0.75 |
| 本番適用閾値 (FY2023-2025) | 0.80 |

**ピラー説明文 (PILLAR_PASSAGES_RAW)**: 各 L2 ピラーに日本語の説明文を定義。
例: `P1 = "スタンド・オフ防衛能力。敵の射程圏外から攻撃できる長射程誘導弾..."`
全15ピラー（L1 P1-P3, P5-P6 + L2 P41-43, P71-73, P81-85）をエンコード済み。

---

## Pass 4: manual_correction（match_method='manual_correction'）

**ソース**: `data/manual/manual_corrections_snapshot.json`
```json
{
    "12345": [4, 43],
    "67890": [7, 71],
    ...
}
```

**適用**: JSON dict の {contract_id: [l1, l2_or_null]} を直接 DB に UPDATE。
- confidence = 0.99（自動分類による上書きから保護）
- `match_method='unclassified'` 行のみを上書き対象とするため、
  semantic/keyword が既に付与されている行には作用しない

---

## 分類フローまとめ（擬似コード）

```
for each contract in contracts WHERE fiscal_year = TARGET_FY:
    name_nfkc = nfkc_normalize(contract_name)
    org = agency_to_org(agency_id)

    # Pass 1: fuzzy_jigyou
    result = rapidfuzz.extractOne(
        name_nfkc,
        corpus_norms,
        scorer=token_set_ratio,
        score_cutoff=78
    )
    if result:
        → assign(pillar_id=corpus_pillar[result.index],
                 match_method="fuzzy_jigyou",
                 confidence=result.score/100)
        continue

    # Pass 2: keyword_rule (全ルールスキャン → 最高conf)
    best = None
    for rule in KEYWORD_RULES:
        if rule.org_filter and org not in rule.org_filter:
            continue
        if any(kw in name_nfkc for kw in rule.keywords):
            if rule.conf > (best.conf if best else 0):
                best = rule
    if best:
        → assign(pillar_id=best.pillar_id,
                 match_method="keyword_rule",
                 confidence=best.conf)
        # org_maintenance / ATLA research fallbackはここで上書き可
        continue

    # org_maintenance fallback
    if best_conf < 0.65 and org in {...}:
        if maint_kw_match or fuel_kw_match:
            → assign(P72 or P84, "org_fallback", 0.60)
            continue

    # ATLA research fallback
    if org == "ATLA" and conf < 0.62 and is_research_agency:
        if research_kw_match:
            → assign(P82, "org_fallback", 0.58)
            continue

    # Pass 2終了時点で未分類
    → assign(None, "unclassified", 0.0)

# Pass 3: semantic_embedding (別スクリプト: assign_pillar_semantic.py)
for each contract WHERE match_method = 'unclassified' AND fiscal_year = TARGET_FY:
    sim = cosine_similarity(encode("query: " + contract_name), pillar_embeddings)
    best_pillar = argmax(sim)
    if sim[best_pillar] >= THRESHOLD:
        → assign(pillar_id=best_pillar,
                 match_method="semantic_embedding",
                 confidence=sim[best_pillar])

# Pass 4: manual_correction (別途適用)
for contract_id, (l1, l2) in manual_corrections.items():
    → update contract_pillar SET l1=l1, l2=l2, conf=0.99, method="manual_correction"
```

---

## テーブルスキーマ

### `contract_pillar`（procurement.db）

```sql
CREATE TABLE contract_pillar (
    contract_id  INTEGER PRIMARY KEY,
    pillar_l1_code INTEGER,
    pillar_l2_code INTEGER,
    confidence   REAL,
    match_method TEXT,  -- fuzzy_jigyou | keyword_rule | semantic_embedding
                        -- manual_correction | org_fallback | unclassified
    match_source TEXT,  -- マッチしたキーワード or ピラー名
    fiscal_year  INTEGER,
    updated_at   TEXT
)
```

### `defense_pillar_jigyou`（defense_pillar.db）

```sql
CREATE TABLE defense_pillar_jigyou (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pillar_id     INTEGER NOT NULL,
    pillar_name   TEXT NOT NULL,
    jigyou_name   TEXT NOT NULL,
    jigyou_name_norm TEXT NOT NULL,
    fiscal_year   INTEGER NOT NULL,
    source_file   TEXT NOT NULL,
    UNIQUE(pillar_id, jigyou_name, fiscal_year)
)
```

### `pillar_mapping_sources`（defense_pillar.db）

```sql
CREATE TABLE pillar_mapping_sources (
    id              INTEGER PRIMARY KEY,
    source_type     TEXT,   -- jigyou_review | yosan | hakusho | bukai | seibi_keikaku_gaiyou | hyouka
    fiscal_year     INTEGER,
    pillar_id       INTEGER,
    jigyou_name     TEXT,
    jigyou_name_norm TEXT,
    amount_hyoku_yen REAL,
    confidence      REAL,
    notes           TEXT,
    source_url      TEXT,
    raw_context     TEXT
)
```

### `defense_pillar_master`（defense_pillar.db）

```sql
CREATE TABLE defense_pillar_master (
    pillar_id INTEGER PRIMARY KEY,
    level     INTEGER,   -- 1 or 2
    name      TEXT NOT NULL,
    parent_id INTEGER,   -- L2のみ：親L1のpillar_id
    notes     TEXT
)
```

---

## 実行コマンド

```bash
# キーワード分類（FY指定、manual_correction再適用含む）
python dev/assign_pillar_fy2023.py --fy 2023   # FY2023
python dev/assign_pillar_fy2023.py --fy 2024   # FY2024
python dev/assign_pillar_fy2023.py --fy 2025   # FY2025
python dev/assign_pillar_fy2023.py --dry-run    # 書き込みなし確認

# セマンティック分類（未分類のみ）
# 依存: torch>=2.11.0+cu128, sentence-transformers>=5.4.1
python dev/assign_pillar_semantic.py --fy 2023 --threshold 0.80
python dev/assign_pillar_semantic.py --fy 2024 --threshold 0.80
python dev/assign_pillar_semantic.py --fy 2025 --threshold 0.80
python dev/assign_pillar_semantic.py --dry-run

# 注意: --fy でFYを指定すると該当FYのcontract_pillar行を全削除して再挿入
# → 冪等な再実行が可能だが、manual_correctionは再適用されるので確認してから実行
```

---

## 外部データソース URL

| ソース | URL | 用途 |
|-------|-----|------|
| 防衛力整備計画の概要 | https://www.mod.go.jp/j/policy/agenda/guideline/plan/pdf/plan_outline.pdf | ピラー定義・金額 |
| 令和7年度予算概要 | https://www.mod.go.jp/j/approach/others/expense/r07/pdf/gaiyou.pdf | FY2025予算 |
| 令和6年度予算概要 | https://www.mod.go.jp/j/approach/others/expense/r06/pdf/gaiyou.pdf | FY2024予算 |
| 令和5年度予算概要 | https://www.mod.go.jp/j/approach/others/expense/r05/pdf/gaiyou.pdf | FY2023予算 |
| 行政事業レビュー | https://www.mod.go.jp/j/approach/agenda/meeting/jigyou_review/index.html | pillar_mapping_sources |
| 防衛省白書 | https://www.clearing.mod.go.jp/hakusho_data/{year}/html/ | pillar_mapping_sources |

## 予算額（参照値、defense_pillar.db に格納済み）

| ピラー | FY2023（億円） | FY2024（億円） | FY2025（億円） |
|--------|-------------:|-------------:|-------------:|
| P1 スタンド・オフ | 14,207 | 7,127 | 9,390 |
| P2 統合防空 | 9,867 | 12,284 | 5,331 |
| P3 無人アセット | 1,827 | 1,146 | 1,110 |
| P4 領域横断 | 16,250 | 16,401 | 16,119 |
| P5 指揮統制 | 4,588 | 4,248 | 3,852 |
| P6 機動展開 | 2,696 | 5,653 | 4,545 |
| P7 持続性 | 33,687 | 29,422 | 27,525 |
| P8 共通基盤 | 21,795 | 17,336 | 16,459 |
| **合計** | **104,917** | **93,617** | **84,331** |

---

## 既知の分類上の注意点

- **NDMC医療器材**: semantic_embedding (閾値0.80) でも P43 に混入することがある（超音波診断装置等）
- **「誘導弾」単体**: conf=0.70 で P71 に分類されるが、整備・修理文脈なら P72 の方が正しい場合がある → 実際には「誘導弾整備」等の複合語でP72に分類される
- **P83 の org_filter**: `org_filter={"RDB"}` のルール（賃貸借等）は地方防衛局のみ。他機関の賃貸借は P73 または unclassified
- **FY別再実行**: `--fy` で指定した FY の全行を削除→再挿入するため、`manual_correction` も再適用される。KEYWORD_RULES 変更後は必ず3FY一括再実行すること
