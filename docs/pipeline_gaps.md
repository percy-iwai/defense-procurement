# パイプライン抜け漏れ確認

調査日: 2026-05-21  
対象: `pipeline/*.py`, `collectors/*.py`, `parsers/*.py`

---

## 1. 4分類の収録状況

財務省通知の4分類（公共工事/物品役務 × 競争/随契）に対する各機関の実装レベル。

| 実装レベル | 機関 | 詳細 |
|---|---|---|
| ✅ 4分類完全実装 | **naikyoku_kaikei**（大臣官房会計課） | `_NAIKYOKU_KINDS` 辞書で `buppin_k/z`（物品役務競争/随契）・`kouji_k/z`（工事競争/随契）の4ファイルを明示処理 |
| ⚠️ ファイル名ヒューリスティック | **MSDF**（海上自衛隊 24機関） | `_classify_kind()` が `_K.XLSX` → 工事、`ZUIKEI` → 随契と判定。工事/物品役務 × 競争/随契の4分類を近似カバー |
| ⚠️ URLパターンのみ | **GSDF**（陸上自衛隊 27機関） | URLに `zuikei`/`kyousou` が含まれれば随契/競争と分類。工事/物品役務の区別なし |
| ⚠️ URLパターンのみ | **ASDF**（航空自衛隊 29機関） | 同上。未分類はデフォルト「物品役務」扱い |
| ⚠️ 閾値ベース区別 | **ATLA**（防衛装備庁 10機関） | 競争/随意 × 基準以上/未満の4分類（MoF 4分類とは異なる軸） |
| ⚠️ 区別なし | **RDB**（地方防衛局 9局） | Excel内の構造から競争/随契は判別可能だが、工事/物品役務の明示的分類なし |
| ⚠️ 区別なし | **js/dih/ndmc/nids/nda** | ファイル種別でカテゴリを推定。工事/物品役務の区別なし |

**汎用パーサー** (`excel_parser.py`, `pdf_table.py`, `index_scraper.py`) は4分類を意識せずヘッダーキーワードで列マッピングするため、カテゴリ情報はファイル名・URLから付与する必要がある。

---

## 2. HTMLテーブル形式の対応状況

`collectors/index_scraper.py` の `scrape_html_tables()` 関数がHTMLテーブル形式に対応している。

### 実際にHTMLテーブルを使用している機関

| 機関 | agency_id | 方式 |
|------|-----------|------|
| 小牧基地（航空自衛隊） | asdf_komaki | Excel Web Archive（sheet001.htm/sheet003.htm） |
| 美保基地（航空自衛隊） | asdf_miho | HTMLテーブル直接掲載（工期始を契約日代用） |
| 防府北基地（航空自衛隊） | asdf_hofukita | HTMLテーブル直接掲載（同上） |
| 木更津分屯基地（航空自衛隊） | asdf_kisarazu | HTMLテーブル直接掲載 |
| 東部方面会計隊（陸上自衛隊） | gsdf_eafin | HTMLテーブル直接掲載 |
| 東海防衛支局（地方防衛局） | rdb_tokai | HTMLテーブル掲載 |

### scrape_html_tables() の実装メモ
- Excel Web Archive（Frameset + sheet003.htm ネスト構造）に fallback ロジックあり
- セル内テキストの `(PDF:...)` 参照は除去処理済み
- 有効なヘッダー行が見つからない場合、全 TR を1テーブルとして処理する fallback あり

---

## 3. 防衛省調達機関リンク集（ichiran.html）との照合

`https://www.mod.go.jp/j/budget/chotatsu/ichiran.html` に掲載されている20機関カテゴリとパイプラインの対応:

| ichiran.html の機関 | 対応 agency_id | カバー状況 |
|---|---|---|
| 内部部局 | naikyoku_kaikei | ✅ |
| 統合幕僚監部 | js | ✅ |
| 陸上自衛隊 | gsdf_* (27機関) | ✅ |
| 海上自衛隊 | msdf_* (24機関) | ✅ |
| 航空自衛隊 | asdf_* (29機関) | ✅ ※下記例外あり |
| 北海道防衛局 | rdb_hokkaido | ✅ |
| 東北防衛局 | rdb_tohoku | ✅ |
| 北関東防衛局 | rdb_n_kanto | ✅ |
| 南関東防衛局 | rdb_s_kanto | ✅ |
| 近畿中部防衛局 | rdb_kinchu | ✅ |
| 東海防衛支局 | rdb_tokai | ✅ |
| 中国四国防衛局 | rdb_chushi | ✅ |
| 九州防衛局 | rdb_kyushu | ✅ |
| 沖縄防衛局 | rdb_okinawa | ✅ |
| 防衛大学校 | nda | ✅ |
| 防衛医科大学校 | ndmc | ✅ |
| 防衛研究所 | nids | ✅ |
| 情報本部 | dih | ✅ |
| 防衛監察本部 | igo | ✅ |
| 防衛装備庁 | atla + atla_sub (10機関) | ✅ |

**結論: ichiran.html レベルでのギャップはなし。**

ただし ichiran.html は各組織のトップページへのリンクのみで、実際には各組織内の個別基地・部隊・補給処を深掘りして初めてファイルを取得できる。その深掘り先（各基地等）については別途カバレッジ確認が必要。

### 既知の収集困難機関（例外）
| 機関 | agency_id | 理由 |
|---|---|---|
| 春日基地（航空自衛隊） | asdf_kasuga | WARP（20250510/20250509054434）経由でFY2024データのインデックス取得可能。ただし全PDFがCCITTFaxDecodeスキャン画像PDF（テキスト抽出不可）・OCR必要。FY2023以前はWARPでも404。asdf_ashiyaと同等の状況。 |
| 芦屋基地（航空自衛隊） | asdf_ashiya | 全件画像PDF。OCR実施済みだが品質粗め（4月分3件） |
| 北部補給処（陸上自衛隊） | gsdf_hokyuu_honbu | **解決済み（2026-05-22）**: 1st DBの誤 agency_id。実体は `gsdf_gmcc`（補給統制本部）と同一。FY2022-2025 の全 URL は 2nd DB の `gsdf_gmcc` として収録済み。FY2021（6 URL, 832件）のみ TARGET_FYS 対象外で意図的除外。`hzyo071201.pdf`（契約日非公表 `#####`）は `url_fy_fallback` 修正で FY2025 として 27件収録完了。 |
| 第2整備補給隊（海上自衛隊） | msdf_d2 | ローリングXLSがFY2021データに後退、FY2022+なし |

---

## 4. WARP経由でしか取得できない機関

| 機関 | agency_id | WARP 依存の理由 |
|---|---|---|
| 第3補給処（航空自衛隊） | asdf_3dep | ライブURLが削除済み。WARPスナップショット（coll=20250510, ts=20250509054434）のみ有効 |
| 関東補給処（陸上自衛隊） | gsdf_eadep | FY2023以前はWARPのみ（FY2025はlive取得可） |
| 北海道補給処（陸上自衛隊） | gsdf_nadep | FY2023以前はWARPのみ（FY2025はlive取得可） |
| MSDF各機関のFY2022/2023 | msdf_* | `crawl_warp_fy.py` によるWARP補完。各機関ライブサイトは直近2〜3年のみ掲載 |

WARP URL形式:
```
https://warp.ndl.go.jp/{coll}/{ts}/{original_url}
```
- `coll`: スナップショット収集日（YYYYMMDD）
- `ts`: タイムスタンプ（YYYYMMDDHHmmss）。深夜クロールの場合 coll ≠ ts[:8] になることがある

---

## 5. 残存ギャップまとめ

| カテゴリ | 内容 | 対応状況 |
|---|---|---|
| 4分類実装 | GSDF/ASDF/RDBで工事/物品役務の区別が不完全 | 許容（URLパターンで近似） |
| 4分類実装 | ATLAは閾値ベース区別（MoF 4分類とは軸が異なる） | 許容（ATLA固有の公表形式に従う） |
| 画像PDF（OCR未実装） | msdf_d2（データなし） | asdf_kasugaはtekiseika_parser実装済み・276件収録済み ✅ |
| 画像PDF | asdf_ashiya FY2024 4月分（OCR実施済み、品質粗め） | 一部収録済み |
| source_url なし | gsdf_hokyuu_honbu → **解決済み** | 実体は gsdf_gmcc（同一機関）、FY2022-2025 収録済み。FY2021のみ対象外 |
| WARP Cookie | 一部WARP URLへのアクセスにCookie認証が必要 | http_client.py で対応済み |
