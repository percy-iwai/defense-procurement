# defense_procurement_2nd — 開発ノート

## ⚠️ 重要: ファイル編集ルール

**すべてのファイル編集はメインディレクトリに直接行うこと。worktreeに書かないこと。**

- メインディレクトリ: `C:\Users\Percy Iwai\Documents\defense_procurement_2nd`
- SQLite DB: `data/db/procurement.db`（メインディレクトリの実体ファイル）
- ダッシュボード: `dashboard/app.py`, `dashboard/pages/*.py`

Claude Codeのworktree分離機能がデフォルトで有効だが、worktreeに書き込むとローカルのStreamlitに反映されず、
git pushしてもworktreeの変更がmainに反映されないことがある。
必ずメインディレクトリのファイルを直接編集し、DBもメインディレクトリのprocurement.dbに書き込むこと。

## プロジェクト概要
防衛省・自衛隊の調達公表データ（FY2022–2025）を自動収集・構造化し、
SQLite DB（`data/db/procurement.db`）に格納するパイプライン。
Dashboardは `dashboard/app.py`（Dash/Plotly）で可視化。

## DB現況（2026-05-05 時点）

| カテゴリ | 件数 | 総額 |
|---------|------|------|
| 防衛装備庁 (ATLA) | 25,719件 | 158,873億円 |
| 海上自衛隊 (MSDF) | 28,261件 | 14,359億円 |
| 航空自衛隊 (ASDF) | 22,732件 | 12,130億円 |
| 陸上自衛隊 (GSDF) | 31,011件 | 8,753億円 |
| 地方防衛局 (RDB) | 8,059件 | 26,435億円 |
| 情報本部 (DIH) | 597件 | 1,274億円 |
| 防衛省内局 | 753件 | 842億円 |
| 統合幕僚監部 (JS) | 446件 | 642億円 |
| 防衛医科大学校 (NDMC) | 2,646件 | 454億円 |
| 防衛研究所 (NIDS) | 234件 | 17億円 |
| 防衛大学校 (NDA) | 48件 | — |
| **合計** | **≥120,631件** | **≥223,802億円** |

| FY | 件数 | 金額 |
|----|-----:|-----:|
| FY2022 | 17,784件 | 15,727億円 |
| FY2023 | 30,336件 | 71,156億円 |
| FY2024 | 43,801件 | 81,723億円（カバレッジ97.4%） |
| FY2025 | 28,537件 | 55,171億円 |

> **注**: Phase 5 完了（2026-05-05）。migrate_from_v1/v3 実行済み。
> 3rd DB（97,162件）との差分は大部分を収録済み。

---

## Phase 4: ASDF（航空自衛隊）収集ログ

### 対象機関と結果（2026-04-30 完了）

| agency_id | 件数 | 備考 |
|-----------|------|------|
| asdf_2dep（第2補給処） | 7,371件 | Excel月次 RR04-07 |
| asdf_4dep（第4補給処） | 5,149件 | PDF インデックス |
| asdf_3dep（第3補給処） | 3,636件 | Excel + WARP（要 Cookie） |
| asdf_iruma（入間基地） | 1,107件 | PDF |
| asdf_chitose（千歳基地） | 832件 | PDF |
| asdf_komatsu（小松基地） | 520件 | PDF |
| asdf_hyakuri（百里基地） | 491件 | PDF |
| asdf_ichigaya（市ヶ谷基地） | 396件 | PDF |
| asdf_tsuiki（築城基地） | 362件 | PDF |
| asdf_kumagaya（熊谷基地） | 351件 | PDF |
| asdf_misawa（三沢基地） | 332件 | PDF（FY2024は画像PDF） |
| asdf_fuchu（府中基地） | 310件 | PDF |
| asdf_nyutabaru（新田原基地） | 248件 | PDF |
| asdf_nara（奈良基地） | 187件 | PDF |
| asdf_niigata（新潟分屯基地） | 162件 | PDF |
| asdf_hamamatsu（浜松基地） | 136件 | PDF（掲載日ベース） |
| asdf_gifu（岐阜基地） | 121件 | PDF |
| asdf_shizuhama（静浜基地） | 115件 | PDF |
| asdf_hofuminami（防府南基地） | 115件 | PDF |
| asdf_akita（秋田分屯基地） | 96件 | PDF |
| asdf_meguro（目黒基地） | 81件 | PDF |
| asdf_matsushima（松島基地） | 80件 | PDF |
| asdf_yokota（横田基地） | 57件 | PDF |
| asdf_komaki（小牧基地） | 45件 | HTML（Excel Web Archive） |
| asdf_miho（美保基地） | 21件 | HTML（工期始を契約日代用） |
| asdf_hofukita（防府北基地） | 16件 | HTML（工期始を契約日代用） |
| asdf_kisarazu（木更津分屯基地） | 9件 | HTML（R6/8/9形式日付） |
| asdf_ashiya（芦屋基地） | 73件 | FY2024 PDF（5〜翌2月分はテキストPDF）、4月分は画像PDF→OCR要 |
| asdf_kasuga（春日基地） | 0件 | スキップ：second/kaikei/ 403 |

**ASDF合計: ≥22,805件 / ≥12,130億円（Phase 5込み、misawa OCR込み）**

---

## Phase 4 バグ修正ログ

### Bug 1: asdf_3dep WARP URLパターン誤り
- **原因**: `_3dep_warp_patterns()` が `kyousou{RR}{MM}.xlsx` / `zuikei{RR}{MM}.xlsx` を生成していたが
  実際のWARPファイルパスは `koukyou_excell/nyuusatu/kouhyou-n-{RYMM}.xlsx` /
  `koukyou_excell/zuikei/kouhyou-z-{RYMM}.xlsx`
- **修正**: `pipeline/asdf_config.py` の `_3dep_warp_patterns()` を正確なパスに更新
- **WARP設定**: coll=20250510 / ts=20250509054434（深夜日付またぎ）
- **影響**: 0件 → 3,636件

### Bug 2: asdf_chitose 日付パース失敗
- **原因**: 千歳基地PDFの日付フォーマットが `'6 . 4 . 1'`（ドット前後にスペース）で、
  正規表現 `^(\d{1,2})\.(\d{1,2})\.(\d{1,2})$` にマッチしなかった
- **修正**: `parsers/pdf_table.py` の正規表現を
  `^(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})$` に変更（スペース任意）
- **影響**: 0件 → 832件

### Bug 3: asdf_hofukita / asdf_miho FY決定不能
- **原因**: 工事系HTMLの日付列が「工期始」（工事開始日）で、標準の「契約日」ヘッダーが存在せず
  FYが決定できなかった
- **修正**:
  1. `pipeline/load_asdf.py` の `_process_html_tables()` に「工期始」「着手日」を
     `contract_date` 代替列として追加
  2. `_fy_from_html_url()` 関数追加：`kekka_06.html` → FY2024 などURLからFY推定
- **影響**: hofukita 0→16件、miho 0→21件

### Bug 4: asdf_kisarazu 日付フォーマット未対応
- **原因**: 木更津の落札日が `R6/8/9`（スラッシュ区切り）で
  `_to_date_str()` がマッチしなかった
- **修正**: `parsers/pdf_table.py` の和暦パターンを `[.年]` → `[./年]` に変更（スラッシュ追加）
- **影響**: 0件 → 9件

### Bug 5: asdf_komaki HTML抽出失敗（Excel Web Archive nested table）
- **原因**: Excel Web Archive（sheet003.htm）はネストされたテーブル構造を持ち、
  外部テーブルをイテレートしても有効なヘッダー行が見つからなかった。
  また、セル内テキストに `get_text(separator=" ")` によるスペースが含まれており
  `"落札金額" in text` のチェックが `"落札 金額"` にマッチしなかった
- **修正**:
  1. `collectors/index_scraper.py` の `scrape_html_tables()` に fallback追加：
     per-tableアプローチで有効なヘッダーが見つからない場合、
     `soup.find_all("tr")` を全体スキャンして1仮想テーブルとして扱う
  2. `pipeline/load_asdf.py` の `_process_html_tables()` ヘッダー検索時に
     セル内スペースを除去してから結合（`str(c).replace(" ", "")` 適用）
- **影響**: 0件 → 45件

---

## Phase 5: 追加収集機関（2026-05-05 実行完了）

**defense_procurement_3rd から統合・実行済み:**

| agency_id | 担当スクリプト | 実績 | 備考 |
|-----------|--------------|-----:|------|
| atla_kanbo（防衛装備庁長官官房会計官） | `load_atla_sub.py` | 805件 | PDF P3パターン |
| atla_disti（防衛イノベーション科学技術研究所） | `load_atla_sub.py` | 145件 | PDF P3パターン |
| atla_koukuu/riku/kantei/shinsedai等 | `load_atla_sub.py` | 各100-300件 | PDF P3パターン |
| ndmc（防衛医科大学校） | `load_misc.py` | 2,646件 | ndmc.ac.jp WP直接URL |
| js（統合幕僚監部） | `load_misc.py` | 446件 | PDF YYMM命名規則 |
| dih（情報本部） | `load_misc.py` | 597件 | supply/public-r{ry}.html |
| nids（防衛研究所） | `load_misc.py` | 234件 | keiyaku/pdf/{k\|z}{YYYYMM}.pdf |
| nda（防衛大学校） | HTML直接収集 | 48件 | procurement/bidding_result/ |
| naikyoku_kaikei（大臣官房会計課） | `load_misc.py` | 753件 | Excel月次（要:ダミー行フィルタ修正） |
| gsdf_nadep（北海道補給処） | `load_gsdf.py` | 875件 | FY2025のみ安定取得可 |
| gsdf_aasch（高射学校） | `load_gsdf.py` | 45件 | PDF（2行ヘッダー対応）|
| gsdf_akeno（航空学校） | `load_gsdf.py` | 138件 | PDF |
| gsdf_ocsh（幹部候補生学校） | `load_gsdf.py` | 0件 | 契約日なし全件スキップ |
| asdf_misawa OCR分（FY2024） | `load_misawa_ocr.py` | 109件(+OCR中) | easyocr, R606-R610が画像PDF |
| msdf_y3（第203整備補給隊） | インライン収集 | 81件 | Excel rolling file |
| msdf_s4（第22整備補給隊） | インライン収集 | 44件 | Excel rolling file |
| msdf_d2（第2整備補給隊） | インライン収集 | 0件 | ローリングExcelがFY2021データに後退 |
| migrate_from_v1 | `migrate_from_v1.py` | 多数 | 1st DB差分URL再収集 |
| migrate_from_v3 | `migrate_from_v3.py` | 多数 | 3rd DB差分URL再収集 |

**既知の未収録（回収困難）:**
- `gsdf_hokyuu_honbu` 10,374件: source_type=None（URL無し）、直接DBコピー不可
- `msdf_d2` 92件: ローリングXLSがFY2021期に後退、FY2022+データなし
- `msdf_y3` 81件 → 収録済み ✓
- `nda` 48件 → HTML収集完了 ✓

**実行コマンド（定期再収集用）:**
```bash
python -m pipeline.load_misc
python -m pipeline.load_atla_sub
python -m pipeline.load_gsdf
python -m pipeline.load_misawa_ocr  # OCR（easyocr + fitz 要）
python -m pipeline.reconcile_urlmatrix
```

---

## Phase 6: 積み残し補完（2026-05-05）

### 追加収集

| 機関 | 件数 | 方法 |
|------|-----:|------|
| msdf_y3（第203整備補給隊） | +81件 | Rolling Excel直接収集 |
| msdf_s4（第22整備補給隊） | +44件 | Rolling Excel直接収集 |
| nda（防衛大学校） | +48件 | HTML table収集（工事7テーブル）|
| asdf_ashiya（芦屋基地） 4月分 | +3件 | OCR（品質粗め、画像PDF） |
| migrate_from_v1 | 多数 | 1st DB差分URL再収集 |
| migrate_from_v3 | 多数 | 3rd DB差分URL再収集 |

### Bug 6: naikyoku_kaikei ダミー行の再挿入
- **原因**: load_misc.py の collect_naikyoku() が contract_name='0一式'/vendor_name='0' のプレースホルダー行をフィルタしていなかった。毎回の再収集で復活。
- **修正**: `pipeline/load_misc.py` の collect_naikyoku() に iter_records 後のダミー行フィルタを追加
- **DB**: 既存35件削除（FY2024 50件残存は正当なNULL = タクシー借上等の単価契約）

### Bug 7: excel_parser._map_columns の「予定価格の計算方式」誤マッピング
- **原因**: ヘッダー「予定価格の計算方式」に「予定価格」キーワードが含まれ、estimated_price がテキスト列に誤マッピング → 単価契約でcontract_amount/estimated_price両方NULL
- **修正**: `parsers/excel_parser.py` の `_map_columns()` に `if keyword == "予定価格" and "計算方式" in cell: continue` を追加
- **影響**: msdf_t2/k1/sk/y0 等の単価契約 284件が正常取得に

### Bug 8: reconcile_urlmatrix WARP URL不一致
- **原因**: procurement.db に WARP URL で収録されたレコードの source_url が url_matrix の live URL と一致しなかった。また HTML index ページ（sheet001.htm）はfilename一致でも検出不可。
- **修正**: `pipeline/reconcile_urlmatrix.py` に `_strip_warp()` 関数追加・WARP正規化後のマッチング・HTML indexページはagency_id収録確認でフラグ更新
- **影響**: flag_collected=0 の filled_new: 103 → 85件（18件のgsdf_seibu HTML index ページを解決）

### 既知の残存 NULL（正当なもの）
- `naikyoku_kaikei` FY2024: 50件 → タクシー借上・期間のみ記載の単価契約
- `rdb_kinchu`: 10件 → 情報公開法第5条（国家安全保障）非公開
- `rdb_hokkaido`: 2件 → 同上
- `msdf_sk` 12件 → 単価契約（estimated_priceも未設定）

### Phase 5 バグ修正ログ（defense_procurement_3rd から反映済み）

#### Bug 1: gsdf_aasch 2行ヘッダーPDF解析失敗
- **修正**: `parsers/pdf_table.py` の `_find_header_idx()` に `text_nospace`（空白除去版）追加
  → "契約\n金額" → "契約金額" マッチ可能に
- HEADER_KEYWORDS に `("競争等の区分", "bid_method")` 追加

#### Bug 2: gsdf_nadep 全インデックスURL 403
- **修正**: `pipeline/gsdf_config.py` の gsdf_nadep index_urls を
  `nyuusatujouhou/070kouhyou07/kouhyou07.htm` に変更（FY2025のみ取得可能）

---

## Phase 7: 要求元判定ロジック改訂（2026-05-08）

ATLA中央調達契約 30,659件 / 169,924億 の `contract_requesting_org`
判定ロジックを刷新。`vendor_majority`（重工は要求元べったりではない）を廃止し、
choutatsuyotei（調達予定品目表）との全FY横断 fuzzy 突合・装備品マスター branch
推定・FMSベンダー軍種推定・手動オーバーライド辞書を導入。

### 優先順位（recompute_atla_requesting_org.py）

| 順 | match_source | 内容 | conf |
|---|---|---|---|
| 1 | `agency_rule` | 非ATLA agency_id 確定 | 1.0 |
| 2 | `agency_subrule` | ATLAサブ機関 → 全部 ATLA 仮処置 | 0.5 |
| 3 | `choutatsuyotei_exact` | 全FYの NFKC正規化完全一致 + 単一org | 0.9 |
| 4a | `choutatsuyotei_fuzzy` (Δ0) | 同一FY substring fuzzy（全FY横断単一org判定） | 0.90 |
| 4b | `choutatsuyotei_fuzzy` (Δ1) | Δ1 FY fuzzy | 0.80 |
| 4c | `choutatsuyotei_fuzzy` (Δ2+) | Δ2以上 FY fuzzy | 0.65 |
| 4d | `manual_analysis` | 手動オーバーライド辞書（行政事業レビュー参照） | 0.85 |
| 6 | `collision_month` | exact複数org → 契約月一致で解消 | 0.7 |
| 7 | `collision_majority` | exact複数org → 多数決 | 0.5 |
| 7.5 | `equipment_master_branch` | 装備品 branch が GSDF/MSDF/ASDF（JOINT除外） | 0.7 |
| 8 | `fms_vendor_heuristic` | 米陸→GSDF, 米海→MSDF, 米空→ASDF | 0.5 |
| 9 | `fallback_atla` | 残存 | 0.3 |

**廃止:** `vendor_majority`（重工等は複数機関に供給するため信頼性なし）

### 実行結果（2026-05-08）

| match_source | 件数 |
|---|---:|
| choutatsuyotei_exact | 10,687 |
| choutatsuyotei_fuzzy | 5,719 |
| agency_subrule | 5,123 |
| fallback_atla | 5,020 |
| collision_majority | 2,152 |
| equipment_master_branch | 1,129 |
| fms_vendor_heuristic | 411 |
| collision_month | 405 |
| manual_analysis | 13 |
| **合計** | **30,659** |

要求元別: ATLA 10,221 / GSDF 8,196 / MSDF 6,823 / ASDF 4,276 /
NDA 550 / NDMC 388 / JS 85 / DIH 83 / NAIKYOKU 35 / KANSATSU 2

### 設計上の判断

- **fuzzy index は全FY横断で単一org判定** — FYごと判定だと「灯油1号」が
  特定FYのみNDA登録 → ATLAの大量燃料調達が誤ってNDAに分類される事故を防ぐ
- **JOINT 装備品はスキップ** — equipment_master.branch=JOINT は要求元不明
  （DII=GSDF多数, JADGE=ASDF多数 等、装備品ごとに要求元が異なる）
- **海兵隊はFMSヒューリスティック対象外** — V-22(PMA-275)等、米海軍省経由でも
  実態がGSDFの装備があるため「米海軍省」のみ MSDF とする
- **fallback残存5,020件は honest result** — 旧 vendor_majority 18,305件の多くを
  「判定不能」に正しく戻した結果。manual_overrides 拡充で順次解決

### 実行コマンド

```bash
# dry-run（DBに書き込まない）
python dev/recompute_atla_requesting_org.py --dry-run --workers 14

# 本番（事前バックアップ + atomic 更新）
python dev/recompute_atla_requesting_org.py --workers 14
```

実行ログ: `logs/recompute_atla_<timestamp>.json`
バックアップ: `data/db/backup/procurement_pre_recompute_<timestamp>.db`

ダッシュボード: 「🎯 要求元判定ロジック」ページ（`pages/5_requesting_org_methodology.py`）

---

## アーキテクチャ

```
collectors/
  http_client.py      # fetch()（WARP Cookie対応）
  index_scraper.py    # scrape_file_links(), scrape_html_tables()

parsers/
  excel_parser.py     # parse_excel_bytes(), iter_records()
  pdf_table.py        # parse_pdf_records(), _to_date_str(), _to_amount()（text_nospace修正済）
  ocr_parser.py       # parse_ocr_records()（easyocr、三沢等画像PDF用）★NEW

pipeline/
  asdf_config.py      # ASDF 29機関 + gifu WARP設定
  load_asdf.py        # ASDF収集
  load_misawa_ocr.py  # 三沢基地FY2024 OCR収集 ★NEW
  gsdf_config.py      # GSDF 25機関（aasch, akeno, nadep等追加済）
  load_gsdf.py        # GSDF収集
  load_atla_sub.py    # 防衛装備庁サブ機関（長官官房・研究所等）★NEW
  load_misc.py        # 内局・統幕・防衛医科大・防衛研究所・防衛大学校 ★NEW
  msdf_config.py      # MSDF（一部機関にWARP URL追加）
  load_msdf.py        # MSDF収集（PDF処理機能追加）
  [atla|rdb]_config.py, load_*.py  # 防衛装備庁・地方防衛局

db/
  init_db.py          # SQLiteスキーマ初期化

dashboard/
  app.py              # Streamlit可視化（多タブ版）★更新
  pages/
    coverage.py       # カバレッジ分析 ★NEW
    jigyou_review.py  # 行政事業レビュー ★NEW
    source_urls.py    # ソースURL一覧 ★NEW
    url_matrix.py     # URLマトリクス ★NEW

data/
  db/
    procurement.db    # 主DB（≥120,631件、Phase 6まで）
    url_matrix.db     # URLマトリクス（4,272行）★NEW
    jigyou_review.db  # 行政事業レビューDB ★NEW
  manual/
    url_matrix_FY2024_UPDATED5.xlsx  # URLマトリクス Excel ★NEW
    coverage_budget_breakdown.md     # カバレッジ分析 ★NEW
    defense_procurement_patterns.md  # 収集パターン辞書 ★NEW
```

## 積み残し（2026-05-05現在）

| 優先度 | タスク | 理由 |
|--------|--------|------|
| 高 | FY2025 3月（202603）定期収集 | 各機関が4-5月に順次公表中 |
| 中 | `gsdf_hokyuu_honbu` 10,374件 | source_urlなしのため直接移行不可 |
| 中 | `msdf_d2` 92件 | ローリングXLSがFY2021に後退、回収不可 |
| 中 | url_matrix filled_new 85件 | 特定月PDFが未収集（atla_gifu等）|
| 低 | asdf_ashiya FY2024 4月分 | 画像PDF、OCR実施済み（品質粗め3件）|
| 低 | asdf_misawa OCR追加 | R606-R610 追加処理で件数増見込み |

## 実行方法

```bash
# 全ASDF機関を収集してDB投入
python -m pipeline.load_asdf

# 特定機関のみ（デバッグ用）
python -m pipeline.load_asdf --agency asdf_3dep asdf_chitose

# ドライラン（DB書き込みなし）
python -m pipeline.load_asdf --dry-run

# Phase 5: 内局・統幕・防衛医科大・研究所・大学校
python -m pipeline.load_misc
python -m pipeline.load_misc --agency ndmc js dih  # 特定機関のみ

# Phase 5: 防衛装備庁サブ機関
python -m pipeline.load_atla_sub
python -m pipeline.load_atla_sub --agency atla_kanbo atla_disti  # 特定機関のみ

# Phase 5: GSDF追加機関（gsdf_config.py に定義済み）
python -m pipeline.load_gsdf

# OCR（三沢基地FY2024、要: easyocr, fitz, Pillow）
python -m pipeline.load_misawa_ocr --dry-run  # まずドライランで確認
python -m pipeline.load_misawa_ocr

# ダッシュボード起動
python -m streamlit run dashboard/app.py --server.port 8501
```

## 重要設定

- **TARGET_FYS** = {2022, 2023, 2024, 2025}（`pipeline/load_asdf.py`）
- **FY計算**: month >= 4 → FY = year; month < 4 → FY = year - 1
- **WARP (asdf_3dep)**: coll=20250510, ts=20250509054434
  - 深夜クロール（日付またぎ）: coll ≠ ts[:8]
  - WARP_BASE_3DEP = `https://warp.ndl.go.jp/20250510/20250509054434/https://www.mod.go.jp/asdf/3dep/prd/kakusyukouhyou/koukyou/`

## 既知の限界

- **asdf_ashiya（芦屋基地）**: 全ファイル画像スキャンPDF → OCR必要
- **asdf_kasuga（春日基地）**: second/kaikei/ が HTTP 403
- **FY2022 ASDF**: 一部機関はFY2022データが存在しない（2,417件 / 621億で他FYより少ない）
- **asdf_misawa（三沢基地）**: FY2024はほぼ画像PDF（R606〜R610が画像PDF）

---

## MSDF総監部 placeholder vendor_name レコードの整理（2026-05-06）

### 現象
`vendor_name = '値なし（元データが空白）'` が 5,670件 (FY2022:1,750・FY2023:2,356・FY2024:2・
FY2025:1,562) 存在。全件が海自5地方総監部 (msdf_y0/k0/s0/m0/d0) の ZUIKEI_B (随契) +
RAKUSATSU_B (落札) に集中、内容は艦艇等の維持整備契約（契約名の85%に「艦」を含む）。

### 当初の誤仮説と否定
「FY末公表時に空白→6ヶ月後に補填」と推測したが**実証で否定**。WARP snapshot 別の空欄率が
変動して見えたのは INSERT OR IGNORE のためで、各 snapshot を直接パースすると初期も後期も
補填率はほぼ同じ。後期 WARP/LIVE にも該当行の補填データは存在しない。

### 実際の正体
過去の旧ローダーが nan vendor を `'値なし（元データが空白）'` に置換して入れた**孤立データ**。
現コードベース（excel_parser.py / load_msdf.py / crawl_warp_fy.py）はこの placeholder を
**生成しない**（grep 確認済）。1st/3rd DB にも該当無し。

### 対応（実施済 2026-05-06）
- vendor_name を `'（落札者未記載：海自地方総監部の艦艇等維持整備）'` にリネーム (5,670件)
- 通常クロールではこのラベルが再増加しない（現コードが placeholder を生成しないため）
- 再収集による補填は不可（生Excelに該当行のvendor補填データが存在しない）

---

## 予算構造・カバレッジ分析

### 物件費（契約ベース）の構造
**出典: 防衛省「令和6年度予算の概要」2024-03-28 P.54–61**

```
歳出予算 77,249億円（歳出ベース）
├ 人件・糧食費   22,290億
├ 歳出化経費     37,928億  ← 過去の多年度契約の当年度支払分（過去分）
│   └ 維持費等16,732 / 装備品7,783 / 航空機5,276 / 施設2,496 / 艦船1,985 / 研開1,959 / 基対869 / 他827
└ 一般物件費     17,032億  ← 当年度締結かつ当年度支払の物件費

物件費（契約ベース）= 93,625億円（当該年度に結ぶ契約額の合計）
├ 一般物件費     17,032億  ← 当年度締結・当年度支払（歳出予算と共通）
└ 新規後年度負担 76,594億  ← 当年度締結・翌年度以降支払（複数年度契約）
```

**後年度負担の仕組み**: 護衛艦4–5年、航空機3–5年、誘導弾4年、維持整備1–2年などの複数年度契約。
契約締結年度に計上（契約ベース）されるが、支払は翌年度以降に分散する。

### 物件費（契約ベース）93,625億円の内訳（FY2024予算、P58）

| 費目 | 金額（億） | 構成比 | 前年差 |
|------|----------:|--------|--------|
| 維持費等（修理費等含む） | 32,321 | 34.5% | +1,947 |
| 装備品等購入費 | 21,307 | 22.8% | △180 |
| 航空機購入費 | 9,467 | 10.1% | △85 |
| 研究開発費 | 8,225 | 8.8% | △743 |
| 艦船建造費等 | 7,618 | 8.1% | +3,853 |
| 施設整備費等 | 6,691 | 7.1% | +787 |
| 基地対策経費等 | 5,108 | 5.5% | △14 |
| その他 | 2,889 | 3.1% | △1,466 |
| **合計** | **93,625** | **100%** | **+4,100** |

### 機関別物件費（契約ベース）（P60）

| 機関 | FY2024予算（億） |
|------|---------------:|
| 海上自衛隊 | 29,397 |
| 航空自衛隊 | 23,914 |
| 陸上自衛隊 | 20,960 |
| 内部部局 | 6,386 |
| 防衛装備庁 | 9,596 |
| 統合幕僚監部 | 1,352 |
| 情報本部 | 1,564 |
| 地方防衛局 | 61 |
| **合計** | **93,625** |

### FY2024 中央調達実績（防衛装備庁）
**出典: mod.go.jp/atla/souhon/supply/jisseki/pdf/r06_chotatsu_jisseki.pdf**

| 要求機関 | 件数 | 金額（億） |
|---------|-----:|----------:|
| 海幕 | 2,387 | 20,380 |
| 空幕 | 2,003 | 14,003 |
| 陸幕 | 2,860 | 13,861 |
| 装備庁 | 257 | 7,678 |
| その他 | 487 | 2,021 |
| **合計** | **7,994** | **57,943** |

契約方式別: 一般競争3,072件/2,354億、**随意契約4,710件/46,755億（80.7%）**、FMS 212件/8,834億
→ 随意契約・FMSが金額ベースで大半。大型装備品は随意契約（相手方限定）が通常。

上位ベンダー: 三菱重工14,567億 / 川崎重工6,383億 / 三菱電機4,956億 / 日本電気3,117億

> **注意**: 中央調達（57,943億）は防衛装備庁経由の大型調達のみ。
> 公表DB（財計第2017号）には各省庁の単年度契約も含まれ、FY2024計 81,267億と大きい。
> FMS（8,834億）は財計第2017号の公表対象外のため公表DBには含まれない。

### カバレッジ分析（FY2024）
**出典: `temp/coverage_budget_breakdown.md`**

| 項目 | 金額 | 算出根拠 |
|------|-----:|---------|
| 物件費（契約ベース）| 93,625億 | 予算書P.58 |
| △ 非契約系（光熱水・補助金・借料等）| ▲約8,500億 | 費目別分析 |
| △ 不用額（FY2024決算）| ▲約1,200億 | 朝日/日刊ゲンダイ 2025-11 |
| **実質契約対象母数** | **≈84,000億** | 計算値 |
| 公表DB収録額（FY2024）| 81,267億（40,771件）| `procurement.db` |
| **カバレッジ率** | **≈96.7%** | 81,267÷84,000 |

残ギャップ約2,700億の主因: ①秘密契約 ②画像PDF未OCR ③gsdf_seibu 403 ④収集漏れ不明分

---

## 会計検査院 調査メモ

### 令和5年度決算検査報告（r05/2023-r05-0712）
**出典: https://report.jbaudit.go.jp/org/r05/2023-r05-0712-0.htm**

**予算規模（R5）**:
- 補正後予算額: 7兆0951億
- 物件費（契約ベース）: 8兆9525億（R6は93,625億に増加）
- 中央調達 計画額: 5兆8498億 / 実績額: 5兆5737億（**達成率95.2%**）
- 歳出化経費: 2兆8821億（元年度1兆8819億から52%増）
- 後年度負担残高（R5末）: **9兆4558億**（R元年末比約2倍）
- 15分野別物件費（R5）: 8兆9525億
  - 装備品等の維持整備⑩: 1兆7929億（最大）
  - スタンド・オフ防衛①: 1兆4129億
  - 車両・艦船・航空機等⑥: 1兆1763億

**FMS調達（R5）**:
- 支払対象: 約57.87億ドル / 支出決定: 7,928億円
- **為替差損: 1,239億円**（契約時レートvs支払時レート）

**主要指摘事項**:
1. **月例報告未提出**: 12式地対艦誘導弾等（計2,927億円）が契約後一定期間報告なし
2. **納期遅延**: 変更122件（平均136日、最長433日）、猶予185件（平均162日）
3. **後年度負担の急増**: R5末9.4兆（R1末比2倍）→ 会計検査院が管理・情報開示改善を勧告

### 令和8年1月 FMS検査報告（平成30年度調査の更新版）
- FMS調達の推移: H25年1,040億（全体の5.0%）→ H29年3,791億（15.9%）→ R5年57.87億ドル
- 未精算・未納入が継続課題（過去報告で85件/349億）
- 勧告: 出荷促進、精算書照合、未精算額削減、契約管理費減免協定の検討

### DBへの活用可能性
- 会計検査院データは**統計・集計値が中心**で個別契約データは非公表
- 財計第2017号の公表DB（本プロジェクトの収集対象）が個別契約の一次データ
- 会計検査院数値は**カバレッジ検証・母数確認**に有用（93,625億円の出所確認済み）
