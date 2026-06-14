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
| asdf_ashiya（芦屋基地） | 115件 | FY2024 76件 + FY2025 39件（4月OCR10件+5〜8月テキストPDF29件）。月9〜3はライブ404・WARP20250715未収録 |
| asdf_kasuga（春日基地） | 248件 | WARP OCR（tekiseika_parser で全12ファイル収集済み、重複28件削除・誤抽出37件contract_name NULL化済み） |

**ASDF合計: ≥23,053件 / ≥12,130億円（Phase 5込み、misawa OCR込み、kasuga 248件）**

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
- `gsdf_hokyuu_honbu` 10,374件: **解決済み（2026-05-22）** → 実体は `gsdf_gmcc`（補給統制本部）と同一。FY2022-2025は収録済み。FY2021(832件)のみ対象外。
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
| 8.5a | `name_keyword` | 契約名キーワード（MSDF/GSDF/ASDF/JS/DIH固有語） | 0.70-0.75 |
| 8.5b | `joint_equipment_explicit` | JOINT装備品IDの明示的org割当（JADGE=ASDF等） | 0.65-0.70 |
| 9 | `fallback_atla` | 残存 | 0.3 |

**廃止:** `vendor_majority`（重工等は複数機関に供給するため信頼性なし）

### 実行結果（2026-05-08、step 8.5追加後）

| match_source | 件数 |
|---|---:|
| choutatsuyotei_exact | 10,687 |
| choutatsuyotei_fuzzy | 5,719 |
| agency_subrule | 5,123 |
| fallback_atla | **4,692** |
| collision_majority | 2,152 |
| equipment_master_branch | 1,129 |
| fms_vendor_heuristic | 411 |
| collision_month | 405 |
| **name_keyword** | **322** |
| manual_analysis | 13 |
| **joint_equipment_explicit** | **6** |
| **合計** | **30,659** |

要求元別: ATLA **9,893** / GSDF **8,282** / MSDF **6,895** / ASDF **4,306** /
NDA 550 / NDMC 388 / JS **171** / DIH **137** / NAIKYOKU 35 / KANSATSU 2

（旧: ATLA 10,221 / JS 85 / DIH 83 / GSDF 8,196 / MSDF 6,823 / ASDF 4,276）

### 実行結果（2026-05-08、choutatsuyotei FY2015-2026拡充後）

choutatsuyotei を FY2015-2026 の12年分（49,075件）に拡充後に再実行。

| match_source | 件数 |
|---|---:|
| choutatsuyotei_exact | **14,278** |
| agency_subrule | 5,123 |
| choutatsuyotei_fuzzy | **4,888** |
| collision_majority | 2,830 |
| **fallback_atla** | **1,792** |
| equipment_master_branch | 677 |
| collision_month | 589 |
| fms_vendor_heuristic | 378 |
| ref_url_inference | 53 |
| name_keyword | 39 |
| manual_analysis | 12 |
| **合計** | **30,659** |

要求元別: GSDF **8,177** / ATLA **8,118** / MSDF **7,893** / ASDF **4,660** /
NDMC 716 / NDA 576 / JS **258** / NAIKYOKU **129** / DIH **119** / RDB 7 / KANSATSU 4 / NIDS 2

（旧: ATLA 9,893 / GSDF 8,282 / MSDF 6,895 / ASDF 4,306 / NDMC 388 / NDA 550 / JS 171 / DIH 137）

**改善**: fallback_atla **4,692 → 1,792**（▲2,900件、62%削減）
- choutatsuyotei_exact が 10,687 → 14,278 に増加（FY2015-2019の18,130件のマッチが寄与）
- `ref_url_inference` が新規登場（53件）
- `joint_equipment_explicit` は 0件に（役割がref_url_inferenceに吸収？）
- バックアップ: `data/db/backup/procurement_pre_recompute_20260508_193751.db`
- ログ: `logs/recompute_atla_20260508_193752.json`

### Step 8.5 設計

**name_keyword キーワードリスト:**
| org | キーワード（代表） | conf |
|---|---|---|
| MSDF | 海上自衛隊, 海幕, 海自, MSII, 艦艇搭載, 潜水艦, 護衛艦 | 0.75 |
| GSDF | 陸上自衛隊, 陸幕, 陸自, 地対艦誘導弾, 10式戦車 | 0.72 |
| ASDF | 航空自衛隊, 空幕, 空自, 自動警戒管制, JADGE, 宇宙状況監視 | 0.72 |
| JS | 統合指揮, 統幕, サイバー防衛, 防衛情報通信基盤, 中央クラウド | 0.70 |
| DIH | 情報本部, 地理空間情報支援, 総合解析システム, GRQ | 0.70 |

**joint_equipment_explicit マッピング:**
joint_jadge→ASDF / joint_ssa→ASDF / joint_geospatial→DIH / joint_dics→DIH /
joint_sogo_kaiseki→DIH / joint_sec_gw→JS / joint_cyber_def→JS / joint_cyber_sim→JS /
joint_ccs→JS / joint_xband_kirameki→JS

### 設計上の判断

- **fuzzy index は全FY横断で単一org判定** — FYごと判定だと「灯油1号」が
  特定FYのみNDA登録 → ATLAの大量燃料調達が誤ってNDAに分類される事故を防ぐ
- **JOINT 装備品はスキップ（8.5b以外）** — equipment_master.branch=JOINT は要求元不明
  ただし明確に要求元が特定できる JOINT 装備品 ID は step 8.5b で明示割当
- **海兵隊はFMSヒューリスティック対象外** — V-22(PMA-275)等、米海軍省経由でも
  実態がGSDFの装備があるため「米海軍省」のみ MSDF とする
- **fallback残存4,692件は honest result** — 研究開発・ATLA固有調達・判定不能が残存
  step 8.5 で 328件 (name_keyword 322 + joint_equipment_explicit 6) を解決

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

## Phase 8: 政策評価書 fallback 解決（2026-05-09）

総務省「政策評価ポータル」掲載の防衛省 政策評価書（事前・事後評価, H27以降）を収集し、
`kenkyuu_hyouka` テーブルに格納。ATLA 中央調達 fallback_atla 契約への追加適用を試みた。

### 収集結果（Phase 1: pipeline/load_kenkyuu_hyouka.py）

- **ポータルエントリ数**: 480件（FY2015–FY2025）
- **kenkyuu_hyouka テーブル挿入**: 432件（48件重複スキップ）→ **現在450件**（2026-05-22 再収集完了、83件回復済み）
- **PDF取得失敗**: 0件
- **担当部局抽出失敗**: 0件
- **org_key マッピング**: ATLA 394件 / MSDF 17件 / GSDF 10件 / ASDF 8件 / NAIKYOKU 3件

FY別: FY2015:6 / FY2016:8 / FY2017:13 / FY2018:9 / FY2019:9 / FY2020:8 / FY2021:8 /
FY2022:14 / FY2023:17 / FY2024:17 / FY2025:371

#### BUREAU_TO_ORG 拡充（事業監理官サブユニット）

括弧内サブユニット「(艦船担当)」等を優先マッチする括弧内先行検査ロジックを追加。
サブユニットは本文の「プロジェクト管理部」（ATLA、9文字）よりキーワードが短いため
longest-first だけでは解決できず、括弧内を先にチェックする実装に変更。

| サブユニット | org | 件数 | 根拠 |
|---|---|---|---|
| 艦船担当 | MSDF | 17 | 潜水艦/UUV/機雷/魚雷/ソーナー 全件MSDF |
| 航空機担当 | ASDF | 8 | 次期戦闘機/スタンドオフ電子戦機 全件ASDF |
| 情報・武器・車両担当 | GSDF | 10 | 92式信管/NBC偵察車/水陸両用 |
| 経理装備局 | ATLA | (前身組織) | |
| 防衛局 | NAIKYOKU | | |
| 管理局 | ATLA | (旧防衛庁) | |

除外（混在のため ATLA のまま）: 艦船武器課・航空機課・誘導武器・統合装備担当

### 突合結果（Phase 2: dev/match_kenkyuu_hyouka_fallback.py）

- **対象 fallback_atla 件数**: 1,771件
- **解決件数**: **15件** (MSDF 8 / ASDF 7)
- **残存 fallback_atla**: 1,756件
- **解決金額**: 約40億円
- **手法**: kw_match のみ（ネットワーク→MSDF、スタンド→ASDF）
- **信頼度**: 0.70

### 設計上の教訓

- tantou_org を DB から直接使用するよう変更（`_infer_org_from_project` は事業名推定のため ATLA R&D事業に対し non-ATLA を返せない）
- 括弧内サブユニット優先ロジックが `map_bureau_to_org()` に必要（longest-first だと「プロジェクト管理部」が「艦船担当」に勝つ）
- 解決数 15件は計画目標（250件+）を大きく下回る。理由: fallback_atla の大半は燃料・消耗品・汎用機器で、政策評価書の R&D 事業名との共通キーワードが極めて少ない

### 実行コマンド

```bash
python -m pipeline.load_kenkyuu_hyouka --dry-run --limit 5  # 動作確認
python -m pipeline.load_kenkyuu_hyouka                       # 全件収集
python dev/match_kenkyuu_hyouka_fallback.py --dry-run        # 突合確認
python dev/match_kenkyuu_hyouka_fallback.py                  # 本番実行
```

ログ: `logs/load_kenkyuu_hyouka_<ts>.json` / `logs/match_kenkyuu_hyouka_<ts>.json`

---

## Phase 9: fallback_atla 50億円以上 大型案件の解決（2026-05-09）

Phase 8 後の `fallback_atla` 1,756件のうち、**金額50億円以上の大型案件 17件
（合計 2,037億円）** に対し、追加調査で解決を試みた。

小額（燃料・消耗品等）は対象外。「金額が大きく単価あたりの分類影響度が
高いもの」のみ手当する方針。

### 手法

1. **bigram Jaccard fuzzy（閾値 J≥0.20）**
   `dev/null/fuzzy_low_threshold_50oku.py` で choutatsuyotei 49,075件と
   character-bigram Jaccard 類似度を計算。既存 `_match_chy_fuzzy`（substring）
   よりさらに緩い閾値で候補抽出。
2. **mod.go.jp / Web 検索による確証取得**
   検索＋選別 PDF 確認で、装備品の運用部隊（要求元）を確定。

### 適用結果（17件中 12件解決、5件 fallback 維持）

`dev/apply_fallback_50oku.py` で適用。新 match_source: `fuzzy_lowthreshold` /
`mod_search`。

| match_source | 件数 | 内訳 |
|---|---:|---|
| fuzzy_lowthreshold | 7 | ATLA→ATLA×5 / ATLA→JS×1 / ATLA→ASDF×1 |
| mod_search | 5 | ATLA→ASDF×5（PW4062×3, ACI, J/ASN-12 EGI） |
| **合計** | **12** | |

| 区分 | 解決件数 | 金額（億） |
|---|---:|---:|
| ATLA → ASDF | 6 | 511 |
| ATLA → JS | 1 | 304 |
| ATLA → ATLA（match_source強化のみ）| 5 | 967 |
| **合計** | **12** | **1,782** |

### 解決の根拠（mod_search 5件）

| #ID | 契約名 | 旧 | 新 | 根拠 |
|---|---|---|---|---|
| 23133/17889/17885 | PW4062推進システム | ATLA | ASDF | mod.go.jp/asdf/equipment/kc-46a.html — KC-46A空中給油機 = 航空自衛隊 |
| 10063 | ACIマルチレベルセキュリティ | ATLA | ASDF | NJSS入札要件「空自クラウドの機能・構成等」 |
| 17120 | GPS/INS統合航法装置 J/ASN-12 | ATLA | ASDF | choutatsuyotei chy#38912 FY2024 ASDF「F-15能力向上用EGI」と同シリーズ |

### Fallback 維持（5件、合計 361億円）— 正当な ATLA 内研究開発

| #ID | 契約名 | 業者 | 理由 |
|---|---|---|---|
| 8736 | アッパーステージ能力向上に関する研究 | スペースワン | ATLAスタートアップR&D、軍種要求元なし |
| 5438 | 即応型マルチミッション実証衛星の製造・試験 | 川崎重工 | 防衛省全体R&D、SDA技術実証 |
| 16182 | 機動対応宇宙システム実証機の試作 | アストロスケール | SDA研究、単一軍種要求元なし |
| 8620 | 宇宙領域...共通キー技術の先行実証に向けた衛星の試作 | QPS研究所 | NAIKYOKU候補は J=0.33 で弱、適用見送り |
| 17605 | 製造工程効率化に係る特定取組 | 三菱重工 | ATLA「特定取組」費用低減プログラム |

### バックアップ・ログ

- バックアップ: `data/db/backup/procurement_pre_fallback50_20260509_080352.db`
- 適用ログ: `logs/apply_fallback50_20260509_080352.json`
- 候補ダンプ: `dev/null/fuzzy_low_threshold_50oku.json`

### 全体集計（Phase 9 完了後）

| match_source | 件数 |
|---|---:|
| choutatsuyotei_exact | 14,278 |
| agency_subrule | 5,123 |
| choutatsuyotei_fuzzy | 4,888 |
| collision_majority | 2,830 |
| **fallback_atla** | **1,752** |
| equipment_master_branch | 677 |
| collision_month | 589 |
| fms_vendor_heuristic | 378 |
| ref_url_inference | 53 |
| name_keyword | 39 |
| jigyou_review | 21 |
| kenkyuu_hyouka | 15 |
| manual_analysis | 12 |
| **fuzzy_lowthreshold** | **7** |
| **mod_research** | **4** |
| **mod_search** | **4** |

要求元別: GSDF 8,170 / ATLA 8,075 / MSDF 7,893 / ASDF 4,666 / NDMC 716 /
NDA 576 / JS 259 / NAIKYOKU 129 / DIH 119 / RDB 7 / KANSATSU 4 / NIDS 2

> **注**: Phase 9 完了後の実際の fallback_atla DB件数は 1,752件（Phase 9 集計表の 1,744 は中間推計）。

### 実行コマンド

```bash
python dev/null/fuzzy_low_threshold_50oku.py             # 候補抽出
python dev/apply_fallback_50oku.py --dry-run             # 適用シミュレーション
python dev/apply_fallback_50oku.py                       # 本番適用（/tmp 経由）
```

---

## Phase 10: 7本柱DB構築・defense_pillar.db分離（2026-05-09）

防衛力整備計画の7本柱マスター・事業マッピング・マッピング根拠を専用DBに分離。

### defense_pillar.db（新規作成）

| テーブル | 件数 | 内容 |
|---------|-----:|------|
| defense_pillar_master | 18件 | 防衛力整備7本柱マスター |
| defense_pillar_jigyou | 830件 | 7本柱×事業マッピング（Phase 11でP4/P7サブ分類済み） |
| pillar_mapping_sources | 2,548件 | マッピング根拠ソース（Phase 11でbukai+5、hakusho+6） |

- `procurement.db` から `defense_pillar_jigyou` / `pillar_mapping_sources` テーブルを削除済み
- `kenkyuu_hyouka` テーブル: btreeページ損失で一時349件に減少 → **450件**（2026-05-22 再収集完了）

### DB接続

- `dashboard/_db.py` 新設：`connect_with_pillar()` ヘルパー（`ATTACH DATABASE 'data/db/defense_pillar.db' AS pillar` で接続）
- ダッシュボード `pages/6_pillar_breakdown.py` 追加（7本柱別調達内訳）

### fallback_atla 推移まとめ（全Phase）

| Phase | 処理 | fallback_atla |
|-------|------|-------------:|
| Phase 7前 | — | 4,692 |
| Phase 7（choutatsuyotei FY2015-2026拡充） | choutatsuyotei_exact +3,591 | **1,792** |
| Phase 7→8間（jigyou_review 21件） | jigyou_review | 1,771 |
| Phase 8（kenkyuu_hyouka 突合） | kenkyuu_hyouka 15件 | 1,756 |
| Phase 9（50億超大型案件手動解決） | mod_search 4件 + mod_research 4件 + fuzzy_lowthreshold 7件 | **1,752** |

---

## Phase 11: P4/P7 中項目分類 & pillar_mapping_sources 追加収集（2026-05-09）

### P4/P7 サブピラー分類（dev/reclassify_p4_p7.py）

`defense_pillar_jigyou` に残存していた pillar_id=4（67件）および pillar_id=7（12件）を
中項目サブピラーに再分類。合計72件を `dev/reclassify_p4_p7.py` で処理。

**pillar_id=4（領域横断作戦能力）→ 3サブピラー:**

| sub-pillar | id | 件数（分類後） |
|---|---|---:|
| 宇宙領域把握 | P41 | 33 |
| サイバー | P42 | 46 |
| 電磁波 | P43 | 98 |
| 親（未分類残存） | P4 | 6 |

**pillar_id=7（持続性・強靱性）→ 3サブピラー:**

| sub-pillar | id | 件数（分類後） |
|---|---|---:|
| 弾薬・誘導弾の確保 | P71 | 21 |
| 装備品等の可動率向上 | P72 | 19 |
| 施設強靱化・後方 | P73 | 16 |
| 親（未分類残存） | P7 | 1 |

分類ロジック: contract_name/jigyou_name の正規表現マッチング（宇宙→P41, サイバー→P42,
電磁波/EW→P43 / 弾薬→P71, 可動率/整備→P72, 強靱化/後方→P73）

### pillar_mapping_sources 追加収集

**A: 分科会PDF（bukai）**

- 37ローカルPDF（siryo07_02.pdf, siryo07_03.pdf 新規DL含む）を再スキャン
- 新規5件追加（合計 107 → **112件**）

**B: 防衛白書HTML（hakusho）**

- URL: `https://www.clearing.mod.go.jp/hakusho_data/{year}/html/n240103000.html`
  - FY2023のみ 200 OK（「3 自衛隊の能力などに関する主要事業」ページ）
  - FY2022/2024/2025 → 404（年ごとにURL体系が異なる）
- FY2024白書: 9桁ページ番号体系（`n100000000.html` 形式、年プレフィックスなし）で全100ページ
  - 主要事業の構造化リストは図表GIF画像のため本文テキスト抽出不可
- 収集方法: Pass 1（○●箇条書き） + **Pass 2（ナレーティブ本文の正規表現キーワード抽出）**
  - `_NARRATIVE_KEYWORDS` / `_SECTION_HEADS` 定数を追加
  - confidence=0.75, notes="hakusho_narrative" で保存
- 新規6件追加（FY2023）: 目標観測弾, 新型レーダー（LTAMDS）, 指向性エネルギー兵器（小型UAV対処）,
  揚陸支援システム（研究）, 輸送車両（コンテナトレーラー）, 荷役器材（大型クレーン・フォークリフト等）
- 合計 267 → **273件**

**pillar_mapping_sources 最終集計（Phase 11後）:**

| source_type | 件数 |
|---|---:|
| bukai | 112 |
| hakusho | 273 |
| hyouka | 28 |
| jigyou_review | 1,305 |
| yosan | 830 |
| **合計** | **2,548** |

### 新規スクリプト

| ファイル | 内容 |
|---|---|
| `dev/reclassify_p4_p7.py` | P4/P7 サブピラー再分類（一回限り実行済み） |
| `dev/load_pillar_sources.py` | bukai PDF + hakusho HTML収集（Pass2追加） |

---

## アーキテクチャ

```
collectors/
  http_client.py      # fetch()（WARP Cookie対応）
  index_scraper.py    # scrape_file_links(), scrape_html_tables()

parsers/
  excel_parser.py     # parse_excel_bytes(), iter_records()
  pdf_table.py        # parse_pdf_records(), _to_date_str(), _to_amount()（text_nospace修正済）
  ocr_parser.py       # parse_ocr_records()（easyocr、三沢等画像PDF用）

pipeline/
  asdf_config.py      # ASDF 29機関 + gifu WARP設定
  load_asdf.py        # ASDF収集
  load_misawa_ocr.py  # 三沢基地FY2024 OCR収集
  gsdf_config.py      # GSDF 25機関（aasch, akeno, nadep等追加済）
  load_gsdf.py        # GSDF収集
  load_atla_sub.py    # 防衛装備庁サブ機関（長官官房・研究所等）
  load_misc.py        # 内局・統幕・防衛医科大・防衛研究所・防衛大学校
  load_kenkyuu_hyouka.py  # 政策評価書収集（Phase 8）★NEW
  msdf_config.py      # MSDF（一部機関にWARP URL追加）
  load_msdf.py        # MSDF収集（PDF処理機能追加）
  [atla|rdb]_config.py, load_*.py  # 防衛装備庁・地方防衛局

dev/
  recompute_atla_requesting_org.py   # ATLA要求元再計算（Phase 7）
  match_kenkyuu_hyouka_fallback.py   # 政策評価書×fallback突合（Phase 8）★NEW
  apply_fallback_50oku.py            # 50億超大型案件手動適用（Phase 9）★NEW
  reclassify_p4_p7.py               # P4/P7サブピラー再分類（Phase 11、実行済）★NEW
  load_pillar_sources.py            # bukai PDF + hakusho HTML収集（Phase 11更新）★NEW
  null/
    fuzzy_low_threshold_50oku.py     # bigram Jaccard候補抽出（Phase 9補助）

db/
  init_db.py          # SQLiteスキーマ初期化

dashboard/
  app.py              # Streamlit可視化（多タブ版）
  _db.py              # DB接続ヘルパー（connect_with_pillar()）★NEW
  pages/
    coverage.py       # カバレッジ分析
    jigyou_review.py  # 行政事業レビュー
    source_urls.py    # ソースURL一覧
    url_matrix.py     # URLマトリクス
    5_requesting_org_methodology.py  # 要求元判定ロジック（Phase 7）
    6_pillar_breakdown.py  # 7本柱別調達内訳（Phase 10）★NEW

data/
  db/
    procurement.db    # 主DB（≥120,631件）
    defense_pillar.db # 7本柱DB（master 18件、jigyou 830件、sources 2,548件）★NEW
    url_matrix.db     # URLマトリクス（4,272行）
    jigyou_review.db  # 行政事業レビューDB
  manual/
    url_matrix_FY2024_UPDATED5.xlsx  # URLマトリクス Excel
    coverage_budget_breakdown.md     # カバレッジ分析
    defense_procurement_patterns.md  # 収集パターン辞書
```

## Phase 12: defense_pillar.db 整備計画概要取込（2026-05-09）

### 防衛力整備計画の概要 (plan_outline.pdf) 取込

| 項目 | 内容 |
|------|------|
| ソース | `https://www.mod.go.jp/j/policy/agenda/guideline/plan/pdf/plan_outline.pdf` |
| source_type | `seibi_keikaku_gaiyou` |
| 抽出件数 | 101件 |
| 挿入件数 | 101件 |
| キャッシュ | `data/raw/seibi_keikaku/plan_outline.pdf` |
| スクリプト | `dev/load_seibi_keikaku_gaiyou.py` |
| DBカラム追加 | `pillar_mapping_sources.amount_hyoku_yen REAL` |
| 金額単位 | 兆円 → 億円 変換（×10000）、5年間計（FY2023-2027）totals |
| fiscal_year | NULL（5カ年計画総額のため年度未分離） |

### 柱別内訳

| pillar_id | L2 | 件数 | 金額合計（億円） |
|-----------|-----|-----:|----------------:|
| P1 スタンド・オフ | — | 12 | 39,200 |
| P2 統合防空 | — | 8 | 19,200 |
| P3 無人アセット | — | 5 | 3,900 |
| P4 領域横断 | — (電磁波) | 7 | 11,200 |
| P4 領域横断 | 宇宙 (41) | 8 | 8,000 |
| P4 領域横断 | サイバー (42) | 4 | 7,300 |
| P4 領域横断 | 車両・艦船・航空機等 (43) | 11 | 32,800 |
| P5 指揮統制 | — | 8 | 6,500 |
| P6 機動展開 | — | 8 | 15,700 |
| P7 持続性 | 弾薬・誘導弾 (71) | 9 | 12,100 |
| P7 持続性 | 装備品維持整備費 (72) | 1 | — |
| P8 防衛生産 | 防衛生産基盤 (81) | 5 | 2,100 |
| P8 防衛生産 | 研究開発 (82) | 14 | 20,300 |
| P8 防衛生産 | 教育訓練費等 (84) | 1 | — |
| **合計** | | **101** | |

**実行コマンド（再収集用）:**
```bash
python dev/load_seibi_keikaku_gaiyou.py --dry-run  # 確認
python dev/load_seibi_keikaku_gaiyou.py             # 本番
```

---

## Phase 15: FY2024/2025 7本柱分類展開 + KEYWORD_RULES追加（2026-05-10）

### 追加KEYWORD_RULES（FY2024/2025解析から発見）

FY2024未分類上位をbyletter収集額で分析し、以下5グループを `_KEYWORD_RULES_RAW` に追加。
FY2023も含めた3年分を再実行済み。

| ルール | ピラー | conf | 追加理由 |
|--------|--------|-----:|---------|
| 補給艦, 補給艦艇, 民間船舶 | P6 | 0.78 | 補給艦14,500t型720億、民間旅客船304億 |
| 掃海艦, 掃海艇, 電子作戦機, US-2, ＵＳ－２, 救難飛行艇, ガスタービン主機 | P43 | 0.78 | 電子作戦機552億、掃海艦149億、US-2 146億 |
| 統合指揮, 作戦指揮 | P5 | 0.78 | 統合指揮通信システム97億 |
| SDB, ＳＤＢ, ＭＫ２５, MK25 | P71 | 0.78 | SDB-Ⅰ等109億、MK25キャニスタ194億 |
| リスク管理枠組み | P42 | 0.82 | RMF認証・監査159億（サイバー施策） |

### 3FY分類結果

| FY | 総件数 | 分類済 | 分類率 | keyword_rule | fuzzy | org_fallback |
|----|-------:|------:|------:|-------------:|------:|-------------:|
| FY2023 | 42,512 | 17,722 | 41.7% | 16,911 | 118 | 575 (+62手動) |
| FY2024 | 43,975 | 16,288 | 37.0% | 15,710 | 156 | 422 |
| FY2025 | 33,385 | 14,081 | 42.2% | 13,599 | 87 | 395 |

> **注意（解決済み）**: Phase 15再実行でFY2023のセマンティック結果（6,709件）がリセットされたが、
> Phase 16（2026-05-10）で `--fy` 引数追加後に3FY一括再実行済み。
> FY2023: 6,471件 / FY2024: 6,321件 / FY2025: 5,336件（合計18,128件）を semantic_embedding 分類。

### FY2024/2025 予算額（令和6/7年度予算概要 P.7 OCR抽出）

| ピラー | FY2024（億円） | FY2025（億円） |
|--------|-------------:|-------------:|
| P1 スタンド・オフ | 7,127 | 9,390 |
| P2 統合防空 | 12,284 | 5,331 |
| P3 無人アセット | 1,146 | 1,110 |
| P4 領域横断 | 16,401 | 16,119 |
| P5 指揮統制 | 4,248 | 3,852 |
| P6 機動展開 | 5,653 | 4,545 |
| P7 持続性・強靱性 | 29,422 | 27,525 |
| P8 防衛生産基盤 | 17,336 | 16,459 |
| **合計** | **93,617** | **84,331** |

PDF形式: 表が画像PDF埋め込み（テキスト抽出不可）→ PyMuPDF でページをPNG化 → EasyOCR で数値抽出。
OCRは大きい数値の先頭桁を落とす傾向があるため、x位置によるカラム推定と合計値検証で補正。

### ダッシュボード更新内容

- `6_pillar_db_viewer.py`: `_BUDGET_FY2024`/`_BUDGET_FY2025` 追加、FYセレクタ default→FY2025、
  全FYカバレッジ表示対応、**年度比較タブ**（P1-P8 横棒グラフ + 3カ年サマリーテーブル）追加
- `98_pillar_logic.py`: DB実績に金額ベースカバレッジ（FY2023/24/25）追加、スクリプト説明更新

### 実行コマンド

```bash
# 3FY一括再実行（KEYWORD_RULES変更後）
python dev/assign_pillar_fy2023.py --fy 2023  # FY2023（manual_correction 62件も再適用）
python dev/assign_pillar_fy2023.py --fy 2024
python dev/assign_pillar_fy2023.py --fy 2025
# 任意: セマンティック後処理（FY2023 unclassified 24,790件→削減）
python dev/assign_pillar_semantic.py --threshold 0.80
```

---

## Phase 16: セマンティック埋め込み 3FY展開（2026-05-10）

`assign_pillar_semantic.py` に `--fy` 引数を追加し、FY2023/2024/2025 の3年分に適用。

| FY | 未分類入力 | semantic割当 | 割当率 | 未分類残存 | サニティ |
|----|----------:|------------:|------:|----------:|------:|
| FY2023 | 24,846 | **6,471** | 26.0% | 18,375 | 97.2% |
| FY2024 | 27,687 | **6,321** | 22.8% | 21,366 | 98.4% |
| FY2025 | 19,304 | **5,336** | 27.6% | 13,968 | 100.0% |
| **合計** | **71,837** | **18,128** | **25.2%** | **53,709** | — |

**金額**: FY2023=5,975億 / FY2024=8,693億 / FY2025=6,209億（3FY計20,877億円）

**柱別割当（3FY合計上位）:**
P72（維持整備）4,643件 / P84（燃料）2,769件 / P43（電磁波・艦船）2,580件 /
P71（弾薬）1,880件 / P73（施設）1,769件 / P83（基地対策）1,313件 /
P82（研究開発）809件 / P5（指揮統制）642件 / P6（機動展開）593件 /
P1（スタンドオフ）439件 / P84以下省略

**manual_correction保護**: セマンティックは `match_method='unclassified'` 行のみ更新するため
FY2023の manual_correction 62件は上書きされない（確認済み）。

---

## 積み残し（2026-05-10現在）

**完了（2026-05-10）**: 事前/事後評価突合（Phase 8）、fallback 50億超突合（Phase 9）、7本柱DB構築・defense_pillar.db分離（Phase 10）、P4/P7サブ分類・bukai/hakusho追加収集（Phase 11）、整備計画概要取込 (Phase 12)、**FY2023への7本柱コード付与パイロット（Phase 13）**、**FY2023 未分類へのセマンティック埋め込みマッチング（Phase 14）**、**FY2024/2025 7本柱分類展開 + KEYWORD_RULES5グループ追加（Phase 15）**、**セマンティック埋め込み3FY展開（FY2023復元+FY2024/2025新規）計18,128件（Phase 16）**、**pillar_corrections 92件処理 + KEYWORD_RULES7グループ追加（地上車両P43/火砲P43/デコイP43/音響測定P43/UC通信P5/GBU→P71）+ org_fallback補給処ルール（大半がFMSスペアパーツ→P72、乗り物系のみP43）+ DIHルール強化（requesting_org='DIH'追加）+ 3FY再実行（Phase 17）**、**中央調達実績PDF（H19〜R05、15ファイル）＋中央調達の概況PDF（R02〜R04、3ファイル）を `data/raw/chuou_chotatsu_jisseki/` / `data/raw/chuou_chotatsu_gaikyo/` に格納（重複2件除去）**

### Phase 14: セマンティック埋め込みマッチング（2026-05-09）

`dev/assign_pillar_semantic.py` を新規作成。`intfloat/multilingual-e5-large`（RTX 5060 Ti / CUDA 12.9）で
FY2023 未分類25,364件に対してコサイン類似度マッチングを実施。

| 閾値 | 割り当て件数 | 未分類残存 |
|------|------------|----------|
| 0.75（dry-run）| 23,765件(93.7%) | 1,599件 | ← 誤分類多数
| **0.80（本番）** | **6,709件(26.5%)** | **18,655件** | ← 採用

**閾値0.80での柱別割り当て:**
P43（電磁波・艦船）1,115件 / P72（維持整備）1,409件 / P84（燃料）1,065件 /
P73（施設）525件 / P83（基地対策）575件 / P82（研究開発）337件 /
P71（弾薬）764件 / P5（指揮統制）241件 / P6（機動展開）203件 /
P1（スタンドオフ）170件 / P3（無人アセット）121件 / P81（防衛生産）84件 /
P41（宇宙）45件 / P2（統合防空）50件 / P42（サイバー）5件

**既知の残存ノイズ（0.80閾値でも）:**
- P43にNDMC医療器材（超音波診断装置・電気手術装置等）が混入
- P82にNDMC研究分析装置が混入
- サニティチェック: keyword_rule 500件中485件一致（97.0%）

**実行コマンド（--fy 引数追加済み、Phase 16で3FY展開完了）:**
```bash
python dev/assign_pillar_semantic.py --fy 2023 --threshold 0.80   # FY2023（6,471件）
python dev/assign_pillar_semantic.py --fy 2024 --threshold 0.80   # FY2024（6,321件）
python dev/assign_pillar_semantic.py --fy 2025 --threshold 0.80   # FY2025（5,336件）
python dev/assign_pillar_semantic.py --threshold 0.75     # 緩め（誤分類注意）
```

| 優先度 | タスク | 理由 |
|--------|--------|------|
| 高 | FY2025 3月（202603）定期収集 | 各機関が4-5月に順次公表中 |
| ✅完了 | `kenkyuu_hyouka` 再収集（2026-05-22） | 450件に回復済み |
| 中 | P4/P7 親残存（P4=6件、P7=1件）の手動分類 | 正規表現でマッチしない7件が未分類で残存 |
| ✅完了 | `gsdf_hokyuu_honbu` 調査・補完（2026-05-22） | 実体は `gsdf_gmcc`（同一機関）。FY2022-2025収録済み。hzyo071201.pdf 27件も url_fy_fallback 修正で収録 |
| 中 | `msdf_d2` 92件 | ローリングXLSがFY2021に後退、回収不可 |
| 中 | url_matrix filled_new 85件 | 特定月PDFが未収集（atla_gifu等）|
| 低 | asdf_ashiya FY2024 4月分 | 画像PDF、OCR実施済み（品質粗め3件）|
| 低 | asdf_misawa OCR追加 | R606-R610 追加処理で件数増見込み |

## 実行方法

```bash
# Phase 13-15: 7本柱コード付与 + KEYWORD_RULES適用
python dev/assign_pillar_fy2023.py --dry-run   # ドライラン確認
python dev/assign_pillar_fy2023.py              # FY2023本番実行（manual_correction 83件含む）
python dev/assign_pillar_fy2023.py --fy 2024   # FY2024
python dev/assign_pillar_fy2023.py --fy 2025   # FY2025

# Phase 16: セマンティック埋め込みマッチング（未分類→7本柱）3FY対応
# 依存: torch>=2.11.0+cu128, sentence-transformers>=5.4.1, intfloat/multilingual-e5-large
python dev/assign_pillar_semantic.py --fy 2023 --threshold 0.80  # FY2023（6,471件）
python dev/assign_pillar_semantic.py --fy 2024 --threshold 0.80  # FY2024（6,321件）
python dev/assign_pillar_semantic.py --fy 2025 --threshold 0.80  # FY2025（5,336件）
# ドライラン確認
python dev/assign_pillar_semantic.py --fy 2024 --dry-run

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

### 物件費（契約ベース）の正しい理解【重要・毎回確認すること】

#### 結論
予算概要に記載された柱別金額（P1: ○○億、P2: ○○億…）は**契約額ベース**。
DBの契約集計額も**契約額ベース**。
→ **両者は直接比較できる。歳出予算（支払ベース）と混同しないこと。**

#### よくある誤解（やってはいけない説明）
❌「多年度契約だからカバレッジが100%を超えても仕方ない」
❌「歳出化経費が含まれるから比較できない」
❌「予算と契約は軸が違うので比較困難」

これらはすべて誤り。予算概要の数字も契約締結ベースで計上されている。

#### 正しい解釈
- カバレッジ > 100% → 計画より多く契約した（補正予算、前倒し調達、または分類誤り）
- カバレッジ < 100% → 計画より少ない契約しかDBに入っていない（未収集、秘密契約、分類漏れ）
- 歳出化経費（過去契約の今年度支払分）はDBに出てこない。比較対象でもない。

この概念はPercyに何度も確認・修正されている。新しいタスクを起動した際も必ずこの前提を確認すること。

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

---

## 最後の作業ポイント（2026-05-10 時点）

### 継続タスク

- **pillar_corrections_pending.csv**: ピラービューワーから随時修正指示が追加される。
  `status='pending'` 行を処理 → DB UPDATE → `status='processed'` に更新してコミット。
  `pending_review` (contract_id=6906: 協調制御ロバストネットワーク実験装置) は要確認残し。

- **rapidfuzz必要**: `pip install rapidfuzz` がローカル環境に必要。
  `python dev/assign_pillar_fy2023.py` を実行してFY2023の7本柱マッピング再分類を完成させること。
  再実行すると `contract_pillar` の FY2023 全行を削除してから再挿入するため、
  キーワードルールで正しく分類されることを確認してから実行すること。

### 次の大きな作業

- **FY2024・FY2025への7本柱マッピング展開**:
  `dev/assign_pillar_fy2023.py` の `TARGET_FY` を 2024 / 2025 に変更して順次実行。
  セマンティック埋め込みも `dev/assign_pillar_semantic.py --threshold 0.80` で同様に展開。

- **公開版ダッシュボードpush**:
  `dashboard/app.py` + `pages/*.py` が整備されたタイミングで
  Streamlit Cloud または社内サーバーへのデプロイを検討。

### キーワードルール注意事項（assign_pillar_fy2023.py）

- `次期戦闘機（その*）` は P82（開発費）に分類 → `次期戦闘機（その` キーワードで捕捉（conf=0.91）
- `次期戦闘機用エンジンシステム` も P82（同上）
- 純粋な機体取得（F-35A/B量産等）は P43 のまま（`F-35A`, `F-35B` キーワード、conf=0.85）
- `ペトリオット定期修理` / `試行定期修理` / `システム維持` は P72（conf=0.89）
- `防衛セキュリティゲートウェイ` は P42（conf=0.82、P5「セキュリティゲートウェイ」より優先）
- `自動警戒管制システム` / `移動式警戒監視システム` は P2（conf=0.84）
- `戦術データリンク` は P5（conf=0.82）

## Phase 18: 引っ越しキット構築（2026-06-13）

- `kit/` 一式作成（export/downloader/rebuild/import/verify/repair/zip + README_KIT/REBUILD/AGENT_INSTRUCTIONS）。データ非携行でCowork環境に再構築可能。⚠️ **contract_pillar btree破損を発見**（重複765件、5/10以降全バックアップ汚染）→ 修復済みコピー `backup/procurement_repaired_20260613.db` からエクスポート済み。ライブDBの修復は `kit/repair_contract_pillar.py --in-place`（docs/db_quality_audit_20260613.md A-1参照、未実施）。監査: `docs/db_quality_audit_20260613.md` / サービス案: `docs/service_ideas.md`
- **DB品質修正完了（2026-06-14）**: `docs/db_quality_audit_20260613.md` 全11項目実施済み。A-1修復（765件→0重複）・A-2手動判定12件再適用＋recomputeガード追加・A-3 bid_method正規化・A-4 FY2022分類（FY全4年100%カバー達成）・A-5 vendor_name_norm追加・B-1/B-2/B-4/C-1処理済み。新スクリプト: `dev/fix_db_quality.py` / `dev/apply_manual_overrides.py` / `dev/normalize_bid_method.py` / `dev/add_vendor_norm.py`
