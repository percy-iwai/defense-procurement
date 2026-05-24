# 要求元判定ロジック (contract_requesting_org)

**対象スクリプト**:
- `dev/recompute_atla_requesting_org.py` — メイン再計算スクリプト
- `dev/fill_requesting_org_fy2022_2024.py` — ヘルパー関数・マッピング辞書
- `dev/manual_atla_overrides.py` — 正規表現パターン辞書
- `dev/match_jigyou_review_fallback.py` — 行政事業レビュー突合
- `dev/match_kenkyuu_hyouka_fallback.py` — 政策評価書突合
- `dashboard/pages/5_requesting_org_methodology.py` — ダッシュボード表示

**出力先テーブル**: `procurement.db` の `contract_requesting_org`

---

## 判定対象

`contracts` テーブルの全件を対象に `contract_requesting_org` を付与する。
非ATLAの機関は agency_id だけで確定できるが、防衛装備庁（ATLA）中央調達は
複数軍種に納品するため追加判定が必要。

---

## Step 0: 正規化関数 `normalize_item_name()`

契約名・調達予定品目名のマッチングに使用する前処理。

```python
import re, unicodedata

_PUNCT_RE = re.compile(
    r"[\s　，、,．。・／/＿_\-－‐ー（）()「」『』【】［］\[\]]+"
)

def normalize_item_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))  # 全角→半角、互換形式正規化
    s = _PUNCT_RE.sub("", s)                   # 句読点・スペース・括弧をすべて除去
    return s.strip().lower()                   # 小文字化
```

**効果**: 「Ａ－３５Ａ」→「a-35a」、「護衛艦（改）」→「護衛艦改」 のように
全角・半角・句読点の揺れを吸収する。最小文字数: マッチには 4 文字以上が必要。

---

## 判定ステップ一覧（優先度順）

| 優先度 | match_source | 信頼度 | 判定根拠 |
|--------|-------------|--------|---------|
| 1 | `agency_rule` | 1.0 | agency_id プレフィックス（非ATLA確定） |
| 2 | `agency_subrule` | 0.5 | ATLAサブ機関 |
| 3 | `choutatsuyotei_exact` | 0.9 | 調達予定品目 完全一致 |
| 4a | `choutatsuyotei_fuzzy` | 0.90 | fuzzy（FY差=0） |
| 4b | `choutatsuyotei_fuzzy` | 0.80 | fuzzy（FY差=1） |
| 4c | `choutatsuyotei_fuzzy` | 0.65 | fuzzy（FY差≥2） |
| 5 | `manual_analysis` | 0.85 | 正規表現パターン辞書 |
| 6 | `collision_month` | 0.70 | 衝突→契約月一致で解消 |
| 7 | `collision_majority` | 0.50 | 衝突→多数決 |
| 7.5 | `equipment_master_branch` | 0.70 | 装備品マスター branch |
| 8 | `fms_vendor_heuristic` | 0.50 | FMSベンダー名プレフィックス |
| 8.5a | `name_keyword` | 0.75 | 契約名中の明示的機関名 |
| 8.5b | `ref_url_inference` | 0.50 | システム名→運用組織推定 |
| 8.5c | `ref_url_inference` | 0.50 | JOINT装備IDマッピング |
| 9 | `fallback_atla` | 0.30 | フォールバック |

---

## Step 1: agency_rule（conf=1.0）

`agency_id` の先頭プレフィックスで機関を確定する。

```python
AGENCY_RULES = [
    ("gsdf_",           "GSDF"),   # 陸上自衛隊
    ("msdf_",           "MSDF"),   # 海上自衛隊
    ("asdf_",           "ASDF"),   # 航空自衛隊
    ("rdb_",            "RDB"),    # 地方防衛局
    ("hokubu_kaikei",   "GSDF"),   # 北陸財務局（陸自経費）
    ("tohoku_kaikei",   "GSDF"),   # 東北財務局（陸自経費）
    ("ndmc",            "NDMC"),   # 防衛医科大学校
    ("nda",             "NDA"),    # 防衛大学校
    ("dih",             "DIH"),    # 情報本部
    ("js",              "JS"),     # 統合幕僚監部
    ("naikyoku_kaikei", "NAIKYOKU"), # 大臣官房会計課
    ("nids",            "NIDS"),   # 防衛研究所
    ("igo",             "KANSATSU"), # 防衛監察本部
]
```

**判定方法**: `agency_id.lower().startswith(prefix)` の先頭一致。
この時点で確定した契約は以降のステップをスキップ。

---

## Step 2: agency_subrule（conf=0.5）

ATLAサブ機関（atla_ プレフィックス）の一部は機関が特定できる。

```python
ATLA_SUB_RULES = {
    "atla_riku":       "GSDF",   # 陸上装備研究所
    "atla_koukuu":     "ASDF",   # 航空装備研究所
    "atla_kantei":     "MSDF",   # 艦艇装備研究所
    "atla_chitose":    "ASDF",   # 千歳試験場
    "atla_gifu":       "ASDF",   # 岐阜試験場
    "atla_shimokita":  "ATLA",   # 下北試験場
    "atla_kanbo":      "ATLA",   # 長官官房会計官
    "atla_shinsedai":  "ATLA",   # 新世代戦闘機開発
    "atla_disti":      "ATLA",   # 防衛イノベーション科学技術研究所
}
```

信頼度が低い（0.5）のは、例えば atla_koukuu が実際には複数軍種向け調達をする場合があるため。

---

## Step 3: choutatsuyotei_exact（conf=0.9）

**調達予定品目表**（防衛装備庁が毎年公表）との完全一致。

**インデックス構造（メモリ上）**:
```python
ChyEntry = namedtuple('ChyEntry', ['chy_id', 'org', 'fiscal_year', 'contract_month'])
chy_idx: dict[str, list[ChyEntry]]  # normalized_name → 全FY分のエントリリスト
```

**判定ロジック**:
```python
def _match_chy_exact(norm: str, idx: dict) -> tuple[str, int] | None:
    if not norm or norm not in idx:
        return None
    cands = idx[norm]
    orgs = {c.org for c in cands}
    if len(orgs) == 1:          # 全FY横断で単一orgのみ
        return (next(iter(orgs)), cands[0].chy_id)
    return None                 # 複数orgが存在 → Step 6へ（collision解消）
```

**参照テーブル**: `choutatsuyotei`（FY2015-2026、約49,075件）
**参照URL**: https://www.mod.go.jp/atla/chotatsu/chotatsuyotei/index.html

---

## Step 4: choutatsuyotei_fuzzy（conf=0.90/0.80/0.65）

正規化名の **サブストリング** 一致で緩くマッチする。
全FY横断で単一org判定済みのエントリに対してのみ適用。

**インデックス構造**:
```python
# (normalized_name, org, tuple_of_all_fiscal_years, sample_chy_id)
fuzzy_idx: list[tuple[str, str, tuple[int, ...], int]]
# norm長の降順でソート済み
```

**判定ロジック**:
```python
def _match_chy_fuzzy(norm, fuzzy_index, contract_fy):
    if not norm or len(norm) < 4:
        return None
    for chy_norm, chy_org, chy_fys, chy_id in fuzzy_index:
        if chy_norm in norm or norm in chy_norm:  # 双方向サブストリング
            min_delta = min(abs(fy - contract_fy) for fy in chy_fys)
            if min_delta == 0:   conf = 0.90
            elif min_delta == 1: conf = 0.80
            else:                conf = 0.65
            matched_fy = min(chy_fys, key=lambda f: abs(f - contract_fy))
            return (chy_org, chy_id, conf, matched_fy)
    return None
```

**注意**: インデックスは全FY横断で単一orgが確定している品目のみ含む。
「灯油1号」のように特定FYのみNDA登録されている場合に誤ってNDAに分類されることを防ぐため、
FYごとではなく全FY横断で単一org判定する設計。

---

## Step 5: manual_analysis（conf=0.85）

`dev/manual_atla_overrides.py` に定義された正規表現パターン。
契約名の raw 文字列（正規化前）に対してマッチ。

**パターン一覧**:
| 正規表現 | org | 備考 |
|---------|-----|------|
| `衛星コンステレーション` | DIH | 小型衛星PfWSシリーズ |
| `画像情報収集衛星` | DIH | 情報本部所管 |
| `民間海上輸送\|民海輸\|民間船舶.*輸送` | JS | 統幕海上輸送 |
| `日米連携機能` | JS | 日米調整 |
| `統合.*演習\|統合運用基盤` | JS | 統合演習・運用基盤 |
| `滞空型無人機\|グローバルホーク\|RQ-?4` | ASDF | RQ-4 グローバルホーク（空自） |
| `幕僚業務用端末.*空` | ASDF | 空自端末 |
| `極超音速誘導弾\|島嶼防衛用高速滑空弾` | GSDF | 陸自スタンドオフ |

---

## Step 6: collision_month（conf=0.7）

Step 3の exact 一致で **複数orgが存在**（collision）するケースの解消。

```python
def _contract_month_fy(contract_date: str | None) -> tuple[int, int] | None:
    # YYYYMMDD または YYYY-MM-DD 形式を想定
    m = int(contract_date[4:6])   # カレンダー月
    fiscal_m = m if m >= 4 else m + 12  # FY月（4月始まり → fiscal 4-15）
    return (m, fiscal_m)
```

**判定**: 契約の FY月と一致する `contract_month` を持つ choutatsuyotei エントリを絞り込み、
絞り込み後に単一orgになれば採用。

---

## Step 7: collision_majority（conf=0.5）

Month 解消でも複数org残存の場合、候補orgの多数決。

```python
from collections import Counter
orgs = [c.org for c in collision_cands]
winning_org = Counter(orgs).most_common(1)[0][0]
```

---

## Step 7.5: equipment_master_branch（conf=0.7）

`contract_equipment` + `equipment_master` を JOIN し、装備品の branch を返す。
**JOINT は除外**（複数軍種用装備品は要求元不明のため）。

```sql
SELECT ce.contract_id, em.branch
FROM contract_equipment ce
JOIN equipment_master em ON em.equipment_id = ce.equipment_id
WHERE em.branch IN ('GSDF', 'MSDF', 'ASDF')
```

複数装備品が紐づく場合は多数決（Counter.most_common(1)）。

---

## Step 8: fms_vendor_heuristic（conf=0.5）

FMS（対外有償軍事援助）ベンダーの vendor_name プレフィックスから推定。

```python
FMS_VENDOR_PREFIX = (
    ("米陸軍省", "GSDF"),   # US Army Secretary of the Army
    ("米海軍省", "MSDF"),   # US Navy Secretary of the Navy
    ("米空軍省", "ASDF"),   # US Air Force Secretary of the Air Force
)
```

**注意**: 米海兵隊はここに含まない（V-22等、米海軍省経由でも陸自用の場合があるため）。
NFKC正規化 + trim 後のベンダー名に対して前方一致。

---

## Step 8.5a: name_keyword（conf=0.75）

契約名に **明示的な機関名・部隊名** が含まれる場合。直接証拠。

```python
NAME_EXPLICIT_ORG_RULES = [
    ("MSDF", ["海上自衛隊", "海幕", "海自"]),
    ("GSDF", ["陸上自衛隊", "陸幕", "陸自"]),
    ("ASDF", ["航空自衛隊", "空幕", "空自"]),
    ("JS",   ["統合指揮", "統幕"]),
    ("DIH",  ["情報本部"]),
]
```

NFKC正規化した契約名に対してサブストリング一致。最初にマッチしたorgを返す。

---

## Step 8.5b: ref_url_inference（conf=0.50）

システム名・装備品名から **運用組織** を推定する。間接証拠のため信頼度低め。

```python
NAME_INFERRED_ORG_RULES = [
    ("MSDF", ["MSII", "艦艇搭載", "非貫通式潜望鏡", "潜水艦", "護衛艦"]),
    ("GSDF", ["地対艦誘導弾", "地対地誘導弾", "10式戦車", "16式機動戦闘車"]),
    ("ASDF", ["自動警戒管制", "JADGE", "宇宙状況監視", "宇宙状況把握",
              "空対艦", "空対地"]),
    ("JS",   ["サイバー防衛", "サイバー演習", "サイバー防護分析",
              "防衛セキュリティゲートウェイ", "中央クラウド",
              "防衛情報通信基盤", "中央指揮システム", "Xバンド防衛通信衛星"]),
    ("DIH",  ["地理空間情報支援", "総合解析システム", "総合解析装置",
              "次期電子情報収集機", "GRQ"]),
]
```

---

## Step 8.5c: ref_url_inference（JOINT装備IDマッピング）（conf=0.50）

JOINT装備品IDのうち、運用主体が明確なものを個別マッピング。

```python
JOINT_EQUIPMENT_INFERRED_ORG = {
    "joint_jadge":          "ASDF",  # JADGE 航空自衛隊防空システム
    "joint_ssa":            "ASDF",  # 宇宙状況把握 空自宇宙作戦群
    "joint_geospatial":     "DIH",   # 地理空間情報支援 情報本部
    "joint_sogo_kaiseki":   "DIH",   # 総合解析システム 情報本部
    "joint_dics":           "DIH",   # 情報本部共通基盤
    "joint_sec_gw":         "JS",    # セキュリティGW 統幕サイバー
    "joint_cyber_def":      "JS",    # サイバー防衛 統幕
    "joint_cyber_sim":      "JS",    # サイバー演習 統幕
    "joint_ccs":            "JS",    # 中央指揮システム 統幕
    "joint_xband_kirameki": "JS",    # Xバンドきらめき 統幕
}
```

**判定**: `contract_equipment` で対象contract_idに紐づくJOINT装備品IDを取得し、
全IDが同一orgにマッピングされる場合のみ採用（複数orgが混在するなら除外）。

---

## Step 9: fallback_atla（conf=0.3）

上記すべてにマッチしない ATLA 契約のデフォルト。

```python
return ("ATLA", "fallback_atla", 0.3, None)
```

残存する典型的なケース:
- ATLA固有の研究開発（要求元が軍種でなくATLA自体）
- 宇宙領域の純粋研究（アッパーステージ能力向上等）
- 名称が汎用的で特定軍種に紐づけできない燃料・消耗品

---

## fallback 後処理スクリプト

fallback_atla の解消を目的とした追加スクリプト（単独実行）:

### 行政事業レビュー突合（jigyou_review）

```bash
python dev/match_jigyou_review_fallback.py --dry-run
python dev/match_jigyou_review_fallback.py
```

- 参照URL: https://www.mod.go.jp/j/approach/agenda/meeting/jigyou_review/index.html
- 手法: サブストリング一致 + キーワード抽出
- 信頼度: 0.70

### 政策評価書突合（kenkyuu_hyouka）

```bash
python -m pipeline.load_kenkyuu_hyouka   # 収集
python dev/match_kenkyuu_hyouka_fallback.py
```

- 参照URL: https://www.soumu.go.jp/main_sosiki/hyouka/gyousei_n/
- 収集対象: `kenkyuu_hyouka` テーブル
- 信頼度: 0.70

### 50億円以上大型案件の手動解決

```bash
python dev/null/fuzzy_low_threshold_50oku.py   # 候補抽出
python dev/apply_fallback_50oku.py --dry-run   # シミュレーション
python dev/apply_fallback_50oku.py             # 本番適用
```

---

## 判定フローまとめ（擬似コード）

```
for each contract in contracts:

    # Step 1: 非ATLA機関
    for prefix, org in AGENCY_RULES:
        if agency_id.startswith(prefix):
            → assign(org, "agency_rule", 1.0)
            continue

    # Step 2: ATLAサブ機関
    if agency_id in ATLA_SUB_RULES:
        → assign(ATLA_SUB_RULES[agency_id], "agency_subrule", 0.5)
        continue

    # 正規化
    norm = normalize_item_name(contract_name)

    # Step 3: choutatsuyotei exact
    result = _match_chy_exact(norm, chy_idx)
    if result:
        → assign(result.org, "choutatsuyotei_exact", 0.9)
        continue

    # Step 4: choutatsuyotei fuzzy
    result = _match_chy_fuzzy(norm, fuzzy_idx, fiscal_year)
    if result:
        → assign(result.org, "choutatsuyotei_fuzzy", result.conf)
        continue

    # Step 5: manual analysis (regex on raw contract_name)
    for pattern, org in MANUAL_PATTERN_OVERRIDES:
        if re.search(pattern, contract_name):
            → assign(org, "manual_analysis", 0.85)
            break
    if matched: continue

    # Step 6-7: collision resolution
    collision_cands = chy_idx.get(norm, [])
    if collision_cands:
        result = _resolve_by_month(collision_cands, contract_date)
        if result:
            → assign(result.org, "collision_month", 0.7)
            continue
        result = _resolve_by_majority(collision_cands)
        → assign(result.org, "collision_majority", 0.5)
        continue

    # Step 7.5: equipment master branch
    branch = equipment_branch_map.get(contract_id)
    if branch:
        → assign(branch, "equipment_master_branch", 0.7)
        continue

    # Step 8: FMS vendor
    vendor_norm = normalize_item_name(vendor_name)
    for prefix, org in FMS_VENDOR_PREFIX:
        if vendor_norm.startswith(prefix):
            → assign(org, "fms_vendor_heuristic", 0.5)
            break
    if matched: continue

    # Step 8.5a: name keyword (explicit)
    name_norm = normalize_item_name(contract_name)
    for org, keywords in NAME_EXPLICIT_ORG_RULES:
        if any(kw in name_norm for kw in keywords):
            → assign(org, "name_keyword", 0.75)
            break
    if matched: continue

    # Step 8.5b: name keyword (inferred)
    for org, keywords in NAME_INFERRED_ORG_RULES:
        if any(kw in name_norm for kw in keywords):
            → assign(org, "ref_url_inference", 0.50)
            break
    if matched: continue

    # Step 8.5c: JOINT equipment
    joint_orgs = {JOINT_EQUIPMENT_INFERRED_ORG[eq_id]
                  for eq_id in contract_equipment_ids
                  if eq_id in JOINT_EQUIPMENT_INFERRED_ORG}
    if len(joint_orgs) == 1:
        → assign(next(iter(joint_orgs)), "ref_url_inference", 0.50)
        continue

    # Step 9: fallback
    → assign("ATLA", "fallback_atla", 0.3)
```

---

## 使用テーブル一覧

| テーブル | DB | 主要カラム | 用途 |
|---------|-----|----------|------|
| `contracts` | procurement.db | id, agency_id, contract_name, vendor_name, contract_date, fiscal_year | 判定対象 |
| `choutatsuyotei` | procurement.db | id, item_name_norm, requesting_org, fiscal_year, contract_month | 調達予定品目 |
| `contract_equipment` | procurement.db | contract_id, equipment_id | 装備品紐づけ |
| `equipment_master` | procurement.db | equipment_id, branch | 装備品→軍種 |
| `contract_requesting_org` | procurement.db | contract_id, requesting_org, match_source, confidence, choutatsuyotei_id | 出力 |
| `kenkyuu_hyouka` | procurement.db | id, project_name, tantou_org | 政策評価書 |

---

## 実行コマンド

```bash
# dry-run（DBに書き込まない、--workers で並列数指定）
python dev/recompute_atla_requesting_org.py --dry-run --workers 14

# 本番（事前バックアップ + atomic UPDATE）
python dev/recompute_atla_requesting_org.py --workers 14

# ログ: logs/recompute_atla_<timestamp>.json
# バックアップ: data/db/backup/procurement_pre_recompute_<timestamp>.db
```

---

## 外部データソース URL

| ソース | URL |
|-------|-----|
| 調達予定品目表（choutatsuyotei） | https://www.mod.go.jp/atla/chotatsu/chotatsuyotei/index.html |
| 行政事業レビュー | https://www.mod.go.jp/j/approach/agenda/meeting/jigyou_review/index.html |
| 政策評価ポータル（kenkyuu_hyouka） | https://www.soumu.go.jp/main_sosiki/hyouka/gyousei_n/ |
| FMS調達実績 | https://www.mod.go.jp/atla/souhon/supply/jisseki/ |
