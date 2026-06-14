# スタンドアロン版（収集 → DB化 → CSV/XLSX 出力）

ダッシュボード（Streamlit）を使わず、**データを集めて表形式で吐き出すだけ**の最小構成。
制約の多い環境（オフラインに近い、GUIなし、権限が弱い等）での実行を想定しています。

## これは何をするか

```
kit/downloader.py     公開Webから原本(Excel/PDF)を data/raw/_cache/ に集める
        ↓
kit/rebuild_all.py    既存パーサーで解析して procurement.db を組み立てる（全15万件）
        ↓
kit/export_tables.py  DB を CSV と XLSX に書き出す  ← ここがゴール
```

ダッシュボードは不要です。最終成果物は `kit/out/` の CSV / XLSX です。

## 依存とインストール（Streamlitは入れない）

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows（mac/Linuxは source .venv/bin/activate）
pip install -r kit/requirements_standalone.txt
```

入るのは **8パッケージのみ**（requests / pandas / openpyxl / xlrd /
beautifulsoup4 / pdfplumber / rapidfuzz / loguru）。Streamlit・Plotly は入りません。

### 「どんな環境でも入るか」の正直な答え

| 工程 | 必要なもの | 制約耐性 |
|------|-----------|---------|
| **出力だけ**（export_tables.py） | Python標準ライブラリ + **openpyxl** だけ | ◎ ほぼどこでも。CSVは標準libのみ、XLSXもopenpyxl1個 |
| **収集・DB化**（downloader/rebuild_all） | 上記8パッケージ。**pandasが必須**（Excel解析の中核） | ○ pandasが入る環境なら動く。pandasはCコンパイル不要のwheelが主要OS/Pythonに揃っており、pipが通れば大抵入る |
| ダッシュボード（任意） | + streamlit / plotly | △ 重い。**スタンドアロン用途では不要** |

- **完全に外部依存ゼロにはできません**。Excel解析(pandas/openpyxl)とPDF解析(pdfplumber)は
  標準ライブラリでは代替が現実的でないためです。ただし**pip が1回通れば以降はオフライン完走**できます
  （downloaderが原本をローカルに溜め、rebuild_allはネット不要で再生）。
- すでにDBがある状態を持ち込めるなら、**出力(export_tables.py)はopenpyxl 1個で動く**ので、
  最も制約の強い環境ではこの工程だけを切り出せます。

## 手順

```bash
# 1) 環境（上記）

# 2) 原本ダウンロード（3〜5時間・中断再開可）
python kit/downloader.py

# 3) DB再構築（1〜3時間・ネット不要）
python kit/rebuild_all.py

# 4) CSV + XLSX 出力
python kit/export_tables.py
#   → kit/out/contracts.csv            全契約（要求元・7本柱コードJOIN済み）
#   → kit/out/by_agency/<機関>.csv     機関カテゴリ別
#   → kit/out/contracts.xlsx           サマリー + 契約一覧（金額カンマ書式・ヘッダー固定）
```

### よく使うオプション

```bash
python kit/export_tables.py --fy 2024 2025               # 年度で絞る
python kit/export_tables.py --agency-category 海上自衛隊  # 機関で絞る
python kit/export_tables.py --format csv                 # CSVだけ（最も軽い）
python kit/export_tables.py --db 別のDB.db --out 別dir
```

## 出力仕様

- **CSV**: UTF-8 BOM付き（Excelで文字化けしない）。18列（契約ID/機関/要求元/年度/契約名/
  業者名/契約額/予定価格/落札率/入札方式/7本柱コード/出所URL 等）
- **XLSX**:
  - 「サマリー」= 機関×年度の件数・金額、7本柱(L1)別の件数・金額
  - 「契約一覧」= 明細（最大10万行。超過分はCSVへ誘導）。金額カンマ書式・ヘッダー行固定
- 行数の目安: 全件約15.5万行 → CSV約45MB / XLSX約17MB

## 注意

- `contract_pillar`（7本柱）は破損履歴があるため、DBは
  `kit/repair_contract_pillar.py --check` で健全性を確認してから出力するのが安全
  （詳細は docs/db_quality_audit_20260613.md A-1）。
- 出力は「再構築DBの現在値」。手動修正や増分収集の後は再度 export_tables.py を回すこと。
