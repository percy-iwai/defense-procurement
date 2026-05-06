# クロール Tips & ノウハウ

自動収集を進める中で得た知見をまとめる。

---

## 1. FY別クロール起点URL の使い分け

| 収集目標FY | 使用カラム | is_warp | 理由 |
|-----------|-----------|---------|------|
| FY2025 | `site_url`（ライブ） | False | 4月〜現在まで全月掲載中 |
| FY2024 | `site_url`（ライブ） | False | 直近年度はまだライブ掲載継続中 |
| FY2023 | `site_url_2024_07`（WARP 2024年7月） | True | FY2023データがライブ削除前に収録 |
| FY2022 | `site_url_2023_07`（WARP 2023年7月） | True | FY2022データがライブ削除前に収録 |

WARP クロール（FY2022/2023）は `is_warp=True` を渡すことで自動的に 2.5秒レート制限が適用される。
`--workers 4` を指定しても `effective_workers = 1` に自動変換される（`crawl_warp_fy.py` L431）。

---

## 1-B. WARPスナップでFY別データが取れない機関（既知の限界）

| 機関 | 対象FY | 原因 | 対策 |
|------|--------|------|------|
| rdb_kyushu, rdb_tohoku | FY2022 | WARP 2023_07 に `contract/announcement/index.html` が収録なし（404） | 対策なし、データ欠損確定 |
| rdb_kyushu, rdb_tohoku | FY2023 | WARP 2024_07 には掲載されているがFY2024契約のみ（FY2023分はrolled off） | 対策なし |
| msdf_m0, msdf_s0, msdf_asd等 | FY2022 | WARP 2023_07（Jul 2023）はFY2023 4-6月分のみ表示（rolling 4ヶ月） | FY2022は回収不能 |
| msdf_m0, msdf_s0, msdf_asd等 | FY2023 7-3月 | WARP 2024_07（Jul 2024）はFY2024 4-6月分のみ表示 | Jan-Mar 2024スナップが必要だが未取得 |

**WARPスナップの対象期間のデータしか取れない**のが根本制約。Jul スナップでは「その時点で公開中の直近約4ヶ月分」しか見えないrolling pageの場合、1スナップあたりのカバー期間が短い。

## 1-C. crawl_warp_fy.py ログ切り詰め注意（修正済み）

L333 に `entry_url[:80]` があり、rdb_kyushu 等では WARP URL プレフィックスがちょうど80文字で
「親ディレクトリを使っているように見える」誤解を招いた。修正済み（URL全体を出力）。

```
# 旧: 見かけ上 rdb/kyushu/ で終わる（実際は正しいURLの先頭80文字）
rdb_kyushu FY2022: https://warp.ndl.go.jp/20230715/20230715000000/https://www.mod.go.jp/rdb/kyushu/
# 新: 全URL表示
rdb_kyushu FY2022: https://warp.ndl.go.jp/20230715/20230715000000/https://www.mod.go.jp/rdb/kyushu/contract/announcement/index.html
```

---

## 2. WARP URL で多発するパターン

### 2-A. `https:/` ダブルスラッシュ欠落バグ（**重大・修正済み**）
**症状**: WARP ページ内の**相対リンク** XLS/PDF が全件サイレントスキップされていた。

**原因**: Python の `urllib.parse.urljoin` は、パス部分に含まれる `https://` を
「パスの `//` → `/` 正規化」ルールで `https:/` に縮める。

```
base  = https://warp.ndl.go.jp/20240715/20240715000000/https://www.mod.go.jp/msdf/bukei/t2/
href  = nyuusatsu/RAKUSATSU_B.xls           # 相対リンク
↓ urljoin
結果  = https://warp.ndl.go.jp/20240715/20240715000000/https:/www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls
#                                                               ↑ スラッシュ1本（欠落）
```

`fetch()` はこの URL を requests に渡すと `400 Bad Request` → None → サイレントスキップ。

**影響**: 相対パスのリンクを使う全 WARP ページで発生。msdf_bukei 系の XLS リンクが全件対象。
修正前は FY2022/2023 msdf 全機関で 0件。修正後に +12,000件超 回収。

**修正箇所** (2026-05-06 適用済み):

1. `collectors/index_scraper.py` `_collect_links_from_html()`:
```python
absurl = urljoin(base_url, href)
absurl = re.sub(r"/https:/([^/])", r"/https://\1", absurl)  # 追加
```
2. `pipeline/crawl_warp_fy.py` `_deep_scrape_files()`:
```python
abs_url = re.sub(r"/https:/([^/])", r"/https://\1", urljoin(url, href))  # 修正
```

**注意**: 絶対パスリンク（`https://` から始まる href）は影響を受けない。
PDF を絶対 URL で列挙する rdb/atla/asdf/gsdf 等の多くは元から正常動作していた。
msdf_bukei 等、相対 URL で XLS をリンクする機関のみが被影響。

### 2-B. WARP スナップが存在しない URL（404）
機関によってはスナップ収録対象外。WARNING `index取得失敗` + 0件で通過する。
実害なし。

### 2-C. WARP スナップの構造変化
例: `asdf_3dep` の FY2023用 WARP URL が `sheet001.htm` という Excel Web Archive 形式で
実ファイルリンクが含まれていないケース → 0件。将来の対処は深度を上げるか別スナップを探す。

---

## 3. agency 別の既知クロール特性

### asdf_2dep（第2補給処）
- FY2024 ライブ: 高成功率（7,371件）
- FY2023 WARP: asdf_2dep の FY2023 WARP URL が存在し、データ収録済み（要確認）

### asdf_3dep（第3補給処）
- WARP URL の実ファイルパス: `koukyou_excell/nyuusatu/kouhyou-n-{RYMM}.xlsx`
- WARP 設定: coll=20250510 / ts=20250509054434（深夜日付またぎに注意）
- FY2023 WARP `site_url_2024_07` では sheet001.htm が取得失敗 → 0件

### asdf_hamamatsu（浜松基地）
- FY2024 に 14分 かかる（大量PDFを逐次処理）。FY2023も同様の見込み。

### asdf_ichigaya（市ヶ谷基地）
- FY2024 に 10分 かかる。

### asdf_hyakuri（百里基地）
- FY2024 に 8分 かかる。FY2023も同様。

### asdf_komaki（小牧基地）
- Excel Web Archive（sheet001.htm〜sheet014.htm）を 14シートひとつずつ試みるが全部 WARNING
- 実際のファイルは別構造。FY2023 WARP でも0件の可能性大。

### asdf_kumagaya（熊谷基地）
- procurement_info.html が WARP で404。FY2023 0件の可能性大。

---

## 4. パーサー既知バグと修正

### 4-A. `_to_amount()` 連結バグ（gsdf_buki 等）
**症状**: `contract_amount` が 8,000兆円超になる（例: `8444545692890001`）  
**原因**: PDFセルに「税抜金額 スペース 税込金額」が同居しているのに
`re.sub(r"[^\d\.\-]", "", s)` がスペースも除去して連結してしまう  
**修正**: `parsers/pdf_table.py` の `_to_amount()` で先にスペース分割し末尾トークン（税込）を取る  
**後処理**: 修正前のコードで insert されたレコードは `contract_amount > 1e10` で検出して修正:
```python
rows = con.execute('SELECT rowid, contract_amount FROM contracts WHERE agency_id=? AND contract_amount > 1e10').fetchall()
for rowid, amt in rows:
    s = str(int(amt)); n = len(s) // 2; tax_incl = int(s[n:])
    con.execute('UPDATE contracts SET contract_amount=? WHERE rowid=?', (tax_incl, rowid))
con.commit()
```
**注意**: 実行中クロールは起動時の旧コードをメモリに保持するので、クロール完了後に後処理が必要。

### 4-B. 日付スペース区切り（asdf_chitose 等）
`'6 . 4 . 1'` 形式の和暦（ドット前後スペース）が未対応だった  
→ `_to_date_str()` の正規表現を `\s*\.\s*` に変更済み

### 4-C. 和暦スラッシュ区切り（asdf_kisarazu 等）
`'R6/8/9'` 形式（スラッシュ区切り）が未対応だった  
→ `[./年]` に変更済み

### 4-D. 2行ヘッダーPDF（gsdf_aasch 等）
「契約\n金額」→ 空白除去後に "契約金額" としてマッチする修正済み

---

## 5. クロール時間の目安（FY2023 WARP、1 worker）

| 機関グループ | 1機関あたりの目安 |
|-------------|------------------|
| ASDF 小規模（ファイルなし/少数） | 10〜30秒 |
| ASDF 中規模（PDF 10〜50件） | 1〜5分 |
| ASDF 大規模（PDF 100件超） | 5〜15分 |
| hamamatsu, ichigaya, hyakuri | 8〜15分 |
| RDB（地方防衛局、少数PDF） | 1〜3分/機関 |
| GSDF（大規模） | 5〜20分/機関 |
| ATLA（大規模） | 10〜30分/機関 |
| MSDF（中〜大規模） | 5〜20分/機関 |

FY2023 全96機関: **推定 4〜8時間**（WARP 2.5秒レート制限起因）

---

## 6. デバッグ Tips

### タスク出力ファイルを直接 tail する
```bash
tail -30 /tmp/claude/C--Users-Percy-Iwai-Documents-defense-procurement-2nd/<session_id>/tasks/<task_id>.output
```
TaskOutput ツールは 20行上限があるため、直接 tail の方が状況把握に適している。

### 現在の DB 件数をクロール中に確認
クロール中でも読み取りのみなら問題なし（SQLite WAL モード前提）:
```python
import sqlite3
con = sqlite3.connect('data/db/procurement.db')
for r in con.execute('SELECT fiscal_year, COUNT(*) FROM contracts GROUP BY fiscal_year ORDER BY fiscal_year').fetchall():
    print(f'FY{r[0]}: {r[1]:,}件')
```

### WARP URL の動作確認
`collectors/http_client.py` の `fetch(url, is_warp=True)` を単体で叩いて確認:
```python
from collectors.http_client import fetch
data = fetch("https://warp.ndl.go.jp/...", is_warp=True)
print(len(data) if data else "None")
```

---

## 7. url_matrix 更新（クロール後）

クロール完了後に `pipeline/reconcile_urlmatrix.py` を実行して
`flag_collected` / `status` を最新の `procurement.db` 内容に合わせる。
WARP URL と live URL の不一致は `_strip_warp()` で正規化して照合。

---

*最終更新: 2026-05-06*
