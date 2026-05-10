# プロジェクト全体サマリー（2026-03-26〜05-08）

## プロジェクト概要
防衛省・自衛隊の調達公表データ（FY2022-2025）を自動収集・構造化し、SQLite DBに格納するパイプライン＋Streamlitダッシュボードプロジェクト。

---

## Phase 1-3: 基盤構築（3/26〜4月中旬）

### DB設計・初期収集
- SQLite DB設計（contracts テーブル、UNIQUE制約）
- FY計算ルール: month >= 4 → year; else → year - 1
- 防衛装備庁（ATLA）中央調達の収集パイプライン構築
- 地方防衛局（RDB）8局の収集
- WARP/Wayback経由の過去データ回収

### 主要バグ修正
- Excel float精度: `525800000.00000006` → `_to_int_amount`で`int(round(float(val)))`
- fiscal_year NULL: 契約日からFY算出に簡素化（ユーザー指示「契約日からもってこればいいよ」）
- ATLA 3月スナップ問題: 20230301→20230715に変更でQ4データ回収（+2,019件、65.8%→96.2%）
- URL正規化バグ: `https:/`（スラッシュ1つ）→ `https://`修正で+12,264件回収

### カバレッジ分析
- 物件費（契約ベース）= 一般物件費 + 新規後年度負担
- 非契約系除外（HNS、基地用地、補助金、光熱水料）
- 不用額の年度別把握
- 予算概要からの正確な数値設定（Percyによる手動修正多数）

### URLマトリクス
- 96機関 × 4カテゴリ × 12ヶ月 × 4FYの追跡DB
- site_url / WARP snapshot URL管理
- FY2024から4FYに拡張（expand_url_matrix_fy.py）

---

## Phase 4: ASDF収集（4月下旬〜4/30完了）

- 航空自衛隊29基地・機関からデータ収集
- Excel月次、PDF、HTML（Excel Web Archive含む）、WARP経由
- 合計22,805件 / 12,130億円
- バグ5件修正（日付パース、WARP URLパターン、HTML nested table等）
- 三沢基地FY2024: 画像PDF→easyocr OCR対応

---

## Phase 5: 追加機関収集（5/1〜5/5）

- 防衛装備庁サブ機関（長官官房、イノベーション研究所等）
- 防衛医科大学校、統合幕僚監部、情報本部、防衛研究所、防衛大学校
- 大臣官房会計課（内局）
- GSDF追加（北海道補給処、高射学校、航空学校）
- MSDF追加（第203整備補給隊等）
- 1st/3rd DB差分移行（migrate_from_v1/v3）

---

## Phase 6: 積み残し補完（5/5）

- Rolling Excel対応（msdf_y3等）
- NDA HTML収集
- OCR追加（芦屋基地）
- バグ3件修正（ダミー行フィルタ、予定価格誤マッピング、WARP URL不一致）

**Phase 6完了時点: 120,631件 / 223,802億円**

---

## Phase 7: 要求元判定ロジック（5/5〜5/8、CLAUDE.md記載の初版）

- 調達予定品目表（choutatsuyotei）との全FY横断fuzzy突合
- 装備品マスターbranch推定
- FMSベンダー軍種推定
- 手動オーバーライド辞書
- vendor_majority廃止（重工は複数機関に供給するため信頼性なし）

---

## Phase 8-13: 本セッション（5/7〜5/8）

### Phase 8: DB充実化企画（ディスカッション）
- 3軸分類企画: ①要求元 ②7本柱 ③装備品・システム
- 共通基盤: ファジーマッチエンジン（確信度スコア、Percy確認フロー）
- 優先順位: ③→①→②
- 情報源の優先順位:
  - 装備品: 防衛白書→公式ページ→Wikipedia→RSシステム/仕様書
  - 要求元: 調達予定品目表→行政事業レビュー→予算概要→事前/事後評価

### Phase 9: データ修正
- rdb_kyushu/chushi WARP再収集（+695件、FY2023ゼロ問題解消）
- vendor_name「値なし」→説明的ラベル（5,670件）
- 海自落札者補填タイミング発見（FY終了後6ヶ月で一括補填）
- ATLA本庁→調達事業部ラベル修正（2,022件）
- ローリングPDF reconcile（+314セル）
- URLマトリクスFY2023/2024の歯抜け解消

### Phase 10: ダッシュボードUI改修
- TOP30拡張、大型契約Top30新設
- 検索ページ新規作成（NFKC全角半角正規化）
- ページ構成整理（URLマトリクス一本化、カバレッジ集約）
- グラフズーム無効化
- 行政事業レビューに概要・目的列追加

### Phase 11: GitHub + Streamlit Cloud
- git init + Git LFS（*.db）
- percy-iwai/defense-procurement（PRIVATE）
- Streamlit Cloud デプロイ + PW認証（3111）

### Phase 12: 装備品辞書
- 44品目→126品目（白書CSV + C4ISR系 + 誘導弾 + TOP10ベンダー網羅）
- ファジーマッチエンジン（contract_equipment 12,743行、マッチ率7.42%）
- 解説URL: 公式102品目、Wikipedia全品目
- ダッシュボード連携（📖リンク列）

### Phase 13: 要求元判定
- 調達予定品目表 FY2015-2026（12年分、49,075件）収集完了
  - R04-R06: PDF 39本テキスト抽出（パーサーバグ修正: item_name 88%空→修正）
  - H27-R03: WARP経由PDF 66本新規収集
  - R07-R08: Excel
- 全151,192件に要求元割当（100%カバー）
- 判定ロジック14ステップ（recompute_atla_requesting_org.py）
- fallback: 5,020→1,771件（65%削減）
- 行政事業レビューDB突合（+21件）
- ダッシュボード: 要求元グラフ（全FY対応、ドリルダウン付き）

---

## 現在のDB状態（2026-05-08時点）

| 指標 | 値 |
|---|---|
| 総契約件数 | 151,192件 |
| 総金額 | 約254,000億円 |
| 収録機関数 | 109機関 |
| FY2024カバレッジ | 96.3% |
| equipment_master | 126品目 |
| contract_equipment | 12,743行（マッチ率7.42%） |
| choutatsuyotei | 49,075件（FY2015-2026） |
| contract_requesting_org | 151,192行（100%カバー、fallback 1,771件） |

---

## 積み残し

### 高優先
- ②防衛力強化の7本柱分類
- 要求元fallback 1,771件の追加解決（予算概要突合、事前/事後評価）
- FY2025 3月分データ収集
- 海自vendor_name補填（WARP再クロール FY2022/2023）
- CLAUDE.md全面更新（DB現況が古い）

### 中優先
- gsdf_hokyuu_honbu 10,374件（source_urlなし）
- FY2022 ASDF一部機関ギャップ
- url_matrix filled_new残85件

### 低優先
- asdf_ashiya/misawa OCR追加
- 装備品辞書のさらなる拡充

---

## 技術的教訓
- マウントFS経由のSQLite書き込み→DB破損。/tmp経由で回避
- git init後にworktree分離が有効化→ファイル不整合。CLAUDE.mdにルール明記
- コードタスク細切れ立て→DB破損・ファイル切断。1目的1タスクに集約
- PDFパース後の品質チェック（item_name充填率）を必ず実施
- push前にpy_compile構文チェック必須
- 「存在しない」と安易に断言しない（R01以前の品目表の件）

---

## 参照ファイル
- 全文チャットログ: `docs/dispatch_session_20260508_full.jsonl`
- DB充実化企画: `docs/enrichment_plan.md`
- 要求元判定ロジック: `dev/recompute_atla_requesting_org.py`
- CLAUDE.md: プロジェクト開発ノート（Phase 1-7の詳細バグログ含む）
