# 防衛省調達DB 収集パターン集

> AIエージェントが各調達機関のデータを収集・DB投入する際の手順書。

対象年度: FY2022〜FY2024 | パターン数: 7

---

## 📊 P1: ATLA月次Excel（防衛装備庁本庁）

| 項目 | 内容 |
|------|------|
| 対象機関 | atla |
| ファイル形式 | Excel (.xlsx / .xls) |
| WARP必要 | あり ✅ |
| 収録規模目安 | 13兆円超（FY2022-2024合計） |

**対象機関**: 防衛装備庁（atla）

**URLパターン**:
```
https://www.mod.go.jp/atla/souhon/supply/jisseki/rakusatu/kohyo_r{YY}/
  ファイル名: {YY}_{区分}_{kyousou|zuikei|kihi|sonota}-{NN}.xlsx
  区分: 物品, 役務, 特別, 指定
```
FY2022/2023は上記URLが404のためWARP経由（NDL WARP）で取得。

**手順（AIエージェント向け）**:
1. `pipeline/rebuild.py` の `ATLA_MONTHS` で年度・月リストを構築（r04=FY2022, r05=FY2023, r06=FY2024）
2. ファイル名4パターン×12ヶ月のURLをすべてHTTP GETで試行（404はスキップ）
3. FY2022/2023が404の場合 → `https://warp.ndl.go.jp/` でWARP検索し最新スナップショットのURLを取得
4. 取得したExcelを `parsers/atla_parser.py`（AtlaParser）で解析
5. 列マッピング: 件名→contract_name, 落札業者→vendor_name, 落札金額→contract_amount, 法人番号→corporate_number
6. `INSERT OR IGNORE INTO contracts` で投入（重複防止）

**注意点**:
- FY2024は直接取得可能（r06フォルダ）
- FY2022/2023はWARPの5分レートリミットに注意（2.5秒待機を挟む）
- ファイル種別: kyousou（一般競争）/ zuikei（随意契約）/ kihi（企画競争）/ sonota

---

## 📊 P2: MSDF直接Excel（海自各基地）

| 項目 | 内容 |
|------|------|
| 対象機関 | msdf_y0, msdf_k0, msdf_s0, msdf_m0, msdf_d0 ほか海自20機関 |
| ファイル形式 | Excel (.xlsx / .xls) — ライブURL直接取得 |
| WARP必要 | あり ✅ |
| 収録規模目安 | ~1,000億円（FY2022-2024合計） |

**対象機関**: 海自整備補給隊（y0/k0/s0/m0/d0）、小規模基地（dy/dk/s1等）

**URLパターン**:
```
https://www.mod.go.jp/msdf/bukei/{機関コード}/nyuusatsu/ZUIKEI_B.xlsx
https://www.mod.go.jp/msdf/bukei/{機関コード}/nyuusatsu/RAKUSATSU_B.xlsx
# .xls形式の機関もあり（拡張子要確認）
```
root直下（`/bukei/{code}/ZUIKEI_B.xls`）は当年度データのみ。
前年度データは `nyuusatsu/` サブディレクトリに格納されることが多い。

**手順（AIエージェント向け）**:
1. `pipeline/load_msdf_sub6.py` の `AGENCY_FILES` リストにURLを定義
2. HTTP GET（User-Agent: Mozilla/5.0 を付与 → 403回避）
3. Excelをpandas `read_excel()` で読み込み → 先頭数行をスキャンしてヘッダー行を特定
4. 列名マッピング（MsdfParser）: 品名→contract_name, 落札者→vendor_name, 落札金額→contract_amount
5. 年度判定: セル内の「令和N年度」テキストから `fiscal_year = N + 2018` で算出
6. WARPが必要な場合: WARP検索ページで機関URLの保存日一覧を取得 → FY別最適タイムスタンプ選択

**注意点**:
- `ローリングウィンドウ` 方式: root直下ファイル = 当年度、nyuusatsu/ = 前年度データ
- ファイルが空（0バイト・ヘッダー行のみ）の機関あり → `len(df) == 0` でスキップ
- `.xls`（旧形式）と `.xlsx`（新形式）が混在 → `openpyxl` / `xlrd` 両対応必須
- 余市防衛隊(msdf_dy)はroot直下がFY2025データのみ → `nyuusatsu/RAKUSATSU_B.xls` を使用

---

## 📄 P3: ATLA試験場・月次PDF

| 項目 | 内容 |
|------|------|
| 対象機関 | atla_kanbo, atla_shimokita, atla_chitose, atla_gifu, atla_riku, atla_koukuu, atla_kantei, atla_shinsedai, atla_disti |
| ファイル形式 | PDF（テキスト埋め込み） |
| WARP必要 | なし |
| 収録規模目安 | ~330億円（FY2023-2024） |

**対象機関**: 防衛装備庁 各試験場・研究本部

**URLパターン**:
```
https://www.mod.go.jp/atla/data/info/ny_{機関}/pdf_ichiran/r{YY}/
  ファイル名: {YY}-{kyousou|zuikei|kouji}-{機関略称}-{NN}.pdf
```

**手順（AIエージェント向け）**:
1. インデックスHTMLページ（`pdf_ichiran/r06/` 等）をHTTP GETして全PDFリンクを列挙
2. 各PDFをダウンロード → pdfplumber で `page.extract_text()` を実行
3. テキストが取得できない場合（words=0）→ 画像PDF → OCR必要（スキップまたはtesseract使用）
4. テキストからGenericParserで行単位解析: 行頭に番号・件名・金額のパターンマッチ
5. 金額正規化: 「¥1,234,567」「1,234,567円」「1.2億円」を int(円) に統一
6. `INSERT OR IGNORE INTO contracts` で投入

**注意点**:
- 令和6年度（FY2024）は `r06/` フォルダ、令和7年度は `r07/`
- PDFの表形式は機関ごとに微妙に異なる（列数・ヘッダー名の揺れ）
- 「工事」と「役務」で別ファイルに分かれている機関あり
- インデックスページが403の場合はURLを直接推測（連番NN=01〜12）

---

## 📄 P4: 地方防衛局・PDF/Excel混在

| 項目 | 内容 |
|------|------|
| 対象機関 | rdb_n_kanto, rdb_s_kanto, rdb_tohoku, rdb_hokkaido, rdb_chushi, rdb_kinchu, rdb_kyushu, rdb_okinawa |
| ファイル形式 | PDF + Excel (.xlsx) 混在 |
| WARP必要 | なし |
| 収録規模目安 | ~1.5兆円（FY2022-2024合計） |

**対象機関**: 地方防衛局（北海道・東北・北関東・南関東・中四国・近畿中部・九州・沖縄）

**URLパターン（例: 北関東防衛局）**:
```
PDF:   https://www.mod.go.jp/rdb/n-kanto/nyusatsu-keiyaku/tyoutatu/kekka/z-k-{YYMM}.pdf
Excel: https://www.mod.go.jp/rdb/hokkaido/keiyaku/keiyakujyoho_kouhyou/pdf/r06/{MM}_03kz.xlsx
```
局によってURL構造・ファイル形式・命名規則がすべて異なる。

**手順（AIエージェント向け）**:
1. 各局のページ構造を事前調査（HTML取得 → PDF/XLSリンク抽出）
2. ExcelはGenericParser（列名マッピングが局ごとに異なる）
3. PDFはpdfplumber + テーブル抽出（`page.extract_table()`）を優先
   → テーブル抽出失敗時は `extract_text()` でフォールバック
4. 局ごとの設定を `agencies_v2.py` に `source_urls` として静的リストで管理
5. 工事契約とサービス契約でファイルが分離している局あり → 両方収録

**注意点**:
- 沖縄防衛局(rdb_okinawa)は金額が大きい（基地工事多数）
- 北海道防衛局(rdb_hokkaido)はExcel形式が近年から → FY2022はPDFのみの可能性
- ファイル名の月付き番号（YYMM形式）は局ごとに桁数・区切り文字が異なる

---

## 📄 P5: 航空自衛隊基地・月次PDF

| 項目 | 内容 |
|------|------|
| 対象機関 | asdf_iruma, asdf_chitose, asdf_2dep, asdf_3dep, asdf_4dep ほか航空自衛隊25機関 |
| ファイル形式 | PDF（公表様式） |
| WARP必要 | なし |
| 収録規模目安 | ~8,000億円（FY2022-2024合計） |

**対象機関**: 航空自衛隊各基地・補給処

**URLパターン（例: 百里基地）**:
```
https://www.mod.go.jp/asdf/hyakuri/acs/2-7_procurement/kouhyou/{YY}-{MM}koukyou.pdf
```
各基地でURL構造・ファイル命名が独自。インデックスHTMLがない機関も多い。

**手順（AIエージェント向け）**:
1. 各基地の調達ページ（通常 `/acs/` や `/choutatsu/` 配下）をHTTP GETで取得
2. ページ内のPDFリンクを正規表現で抽出（`koukyou|tekisei|kouhyou|zuikei`を含むパス）
3. PDFをpdfplumber解析 → 標準公表様式（9列: 件名/数量/契約方式/落札業者/金額等）を想定
4. 列位置が安定していれば `extract_table()` でDataFrame化、不安定なら行テキスト解析
5. FY判定: ファイル名の `R{N}` や `r{YY}` から算出（r6=令和6=FY2024）

**注意点**:
- 第2補給処(asdf_2dep)・第4補給処(asdf_4dep)はExcel形式 → GenericParser適用
- 三沢基地(asdf_misawa)のFY2024はOCR必要な画像PDF → スキップ
- 春日基地(asdf_kasuga)・那覇基地(asdf_naha)は標準公表様式なし → 未収録
- 「公共調達の適正化に基づく情報の公表」ページを起点に辿ると効率的

---

## 📄 P6: 陸上自衛隊・PDF/HTML混在

| 項目 | 内容 |
|------|------|
| 対象機関 | gsdf_gmcc, gsdf_cfin, gsdf_seibu, gsdf_chubu, gsdf_eafin ほか陸上自衛隊25機関 |
| ファイル形式 | PDF + HTML + Excel混在 |
| WARP必要 | なし |
| 収録規模目安 | ~1.3兆円（FY2022-2024合計） |

**対象機関**: 陸上自衛隊 各補給処・会計隊・学校等

**URLパターン（例: 陸幕補給本部）**:
```
PDF:  https://www.mod.go.jp/gsdf/gmcc/raising/hoto/hzyo/hzyo{YYMM}{連番}.pdf
HTML: https://www.mod.go.jp/gsdf/eae/kaikei/eafin/zuikei_ekimu.html（テーブル直接掲載）
```

**手順（AIエージェント向け）**:
1. 機関のトップページを取得 → 契約情報へのリンクを抽出
2. HTML直接掲載型: BeautifulSoupで `<table>` タグ解析 → pandas `read_html()` で行列化
3. PDF型: pdfplumber → テキストor テーブル抽出
4. 年度・機関IDを付与して `INSERT OR IGNORE`

**注意点**:
- 陸幕補給本部(gsdf_gmcc)は件数最多（FY2022-2024で15,000件超）
- 一部機関（gsdf_fsh・gsdf_eisei等）はPDF内に複数月分がまとめて収録
- gsdf_eafin はHTMLにDataTableが直接掲載 → スクレイピングでページネーション処理が必要
- 北部・東北・中部・西部の方面会計隊ごとにURL構造が完全に異なる

---

## 📚 P7: WARPアーカイブ経由（過去年度取得）

| 項目 | 内容 |
|------|------|
| 対象機関 | msdf_y0, msdf_k0, msdf_s0, msdf_m0, msdf_d0, atla（FY2022/2023）など |
| ファイル形式 | Excel / PDF（WARP経由） |
| WARP必要 | あり ✅ |
| 収録規模目安 | ライブURLで取得不可能な過去年度データ |

**利用場面**: 現在のライブURLにアクセスすると最新年度のデータしかなく、過去年度が上書きされている場合

**URLパターン（WARP）**:
```
https://warp.ndl.go.jp/{timestamp}id_/{元のURL}
例: https://warp.ndl.go.jp/20230901120000id_/www.mod.go.jp/msdf/bukei/y0/nyuusatsu/ZUIKEI_B.xlsx
```

**手順（AIエージェント向け）**:
1. NDL WARPの検索ページにアクセス:
   `https://warp.ndl.go.jp/search?url={収集対象URL}`
2. ページ内の「保存日一覧」テーブルをスクレイピング（Playwright推奨）
   → 全保存日のタイムスタンプリストを取得
3. FY別の最適タイムスタンプ選択:
   - FY2022（令和4年度）: 2023年4〜6月頃のスナップショット
   - FY2023（令和5年度）: 2024年4〜6月頃のスナップショット
   - FY2024（令和6年度）: 2025年4〜6月頃のスナップショット
4. `https://warp.ndl.go.jp/{timestamp}id_/{url}` でファイルをダウンロード
5. 通常のパーサーで処理（WARP経由でも中身は同じExcel/PDF）

**注意点**:
- レートリミット: 連続リクエストに2.5秒待機を挿入（429エラー対策）
- WARPのタイムスタンプ形式: `YYYYMMDDHHMMSS`（14桁）
- 同一URLに複数スナップショットがある場合は「年度末直後（4月以降）」を優先
- 一部URLはWARPに収録されていない → その場合はInternet Archiveも確認

---

