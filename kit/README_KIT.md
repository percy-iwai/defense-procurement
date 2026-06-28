# 防衛調達DB 引っ越しキット

防衛省・自衛隊 調達公表データベース（contracts 約15.5万件 / FY2022–2025 / 約26.7兆円）を、
**データを持ち歩かずに**別環境で完全再構築するためのキットです。

## 考え方 — なぜデータを持ち歩かないのか

- DB本体は174MB、ダウンロード済み原本キャッシュは10GB超あり、持ち歩くと重い
- 一次データはすべて公開Web（mod.go.jp / 国立国会図書館WARP / Wayback Machine）にあり、
  **「URLリスト＋パーサー＋手順」さえあれば いつでも・どこでも再生成できる**
- ただし再計算にGPUが要るもの（AIによる7本柱分類）・人手の判断が要るもの（手動修正）は
  再計算せず、**判定結果だけを小さなファイル（計約14MB）でエクスポート**して持ち運ぶ

## クイックスタート（3ステップ）

```bash
# 1. 環境構築（Python 3.10+ が必要）
bash kit/setup_env.sh            # Windows は: powershell -ExecutionPolicy Bypass -File kit\setup_env.ps1

# 2. 原本ダウンロード（約3〜5時間・全自動・中断再開可）
python kit/downloader.py

# 3. DB再構築 → 検証（約1〜3時間・全自動）
python kit/rebuild_all.py
```

最後に `SUMMARY result=PASS` が出れば再現完了。ダッシュボードは
`python -m streamlit run dashboard/app.py` で起動できます
（`.streamlit/secrets.toml.example` を `secrets.toml` にコピーしてパスワードを設定）。

## キットの中身

| パス | 内容 |
|------|------|
| `kit/README_KIT.md` | このファイル（人間向け概要） |
| `kit/REBUILD.md` | ステップバイステップ再構築手順書（失敗時の対処つき） |
| `kit/STANDALONE.md` | **ダッシュボード抜き**で収集→DB→CSV/XLSX出力する最小構成手順 |
| `kit/MONTHLY_UPDATE.md` | **月次更新**の運用手順（ネット開放マシンで増分→SharePoint/Teamsへ） |
| `kit/update_monthly.py` | 月次増分更新（既存DBに今月分を追記→7本柱分類→Excel/CSV出力） |
| `kit/make_dashboard_xlsx.py` | Teams/SharePoint配布用ダッシュボードExcel（グラフ＋明細） |
| `kit/export_tables.py` | DB→CSV/XLSX 出力（標準lib+openpyxlのみ。Streamlit不要） |
| `kit/requirements_standalone.txt` | スタンドアロン版の依存8本（Streamlit/Plotly抜き） |
| `kit/AGENT_INSTRUCTIONS.md` | **Claude Cowork 等のAIエージェント向け指示書**（最初に読ませる） |
| `kit/setup_env.ps1` / `.sh` | Python仮想環境ブートストラップ |
| `kit/requirements_cpu.txt` | 依存パッケージ（GPU系なし） |
| `kit/downloader.py` | WARP / mod.go.jp 特化ダウンローダー（レジューム・404フォールバック付き） |
| `kit/rebuild_all.py` | 再構築オーケストレーター（16ステップを順次実行） |
| `kit/replay_load.py` | 取りこぼしURLの直接リプレイ（ギャップフィル） |
| `kit/import_enrichments.py` | AI分類・OCR・手動判定結果のインポート（GPU不要化の要） |
| `kit/verify_rebuild.py` | 期待値との突合レポート（PASS/WARN/FAIL） |
| `kit/repair_contract_pillar.py` | contract_pillar btree破損の診断・修復ツール |
| `kit/export_kit_data.py` | （旧環境用）このキットの exports を生成したスクリプト |
| `kit/make_kit_zip.py` | （旧環境用）このzip自体の生成スクリプト |
| `kit/exports/urls_replay.csv` | **全6,786 source URL** ＋ URL別の期待行数 |
| `kit/exports/enrichments_*.jsonl.gz` | 7本柱分類・要求元判定・装備品紐付の全行（自然キー付き） |
| `kit/exports/contracts_ocr.jsonl.gz` | OCR由来契約415件の行データ（OCR再実行不要） |
| `kit/exports/tables_small.jsonl.gz` | 調達予定品目表・政策評価書・予算テーブル |
| `kit/exports/manual_overrides_natural.json` | 手動判定の監査証跡（根拠文字列つき） |
| `kit/exports/expected_state.json` | 再構築後の検証基準（件数・金額の期待値） |
| `kit/exports/schema_full.sql` | DBの全DDL |
| `collectors/ parsers/ pipeline/` | 収集・解析・投入のソースコード一式 |
| `dashboard/` | Streamlit ダッシュボード |
| `dev/`（11本のみ） | 増分収集・再分類用スクリプト（ホワイトリスト同梱） |
| `data/db/url_matrix.db` ほか | URLマトリクス・7本柱DB・行政事業レビューDB（小さいので同梱） |
| `data/manual/` | 手動メンテナンスファイル（URLマトリクスExcel・修正CSV等） |
| `CLAUDE.md` / `docs/` | 開発ノート（Phase 1–17 の全経緯）・設計ドキュメント |

## 所要時間とリソースの目安

| 工程 | 時間 | 備考 |
|------|------|------|
| ダウンロード（6,786 URL / 3〜6GB） | 3〜5時間 | WARP 2.5秒/件・mod.go.jp 1秒/件の礼儀的レート制限。中断→再実行で続きから |
| 再構築（パース＋DB投入） | 1〜3時間 | 全ローカル処理。ネットワーク不要（キャッシュ再生） |
| 検証 | 数分 | |

**GPUは不要です。** AIによる分類済みデータはインポートで復元されます。

## ダッシュボード（Streamlit）について

- ダッシュボードは移植先で**入れ直しが必要**（`pip install` で入るローカルライブラリ）。
  ただし**収集〜DB化〜CSV/XLSX出力には不要**です。
- 表データだけ欲しい・制約の強い環境では、Streamlitを入れずに
  **`kit/STANDALONE.md` の最小構成**（依存8本、可視化なし）で完結できます。
- 可視化まで欲しいときだけ `requirements_cpu.txt`（Streamlit/Plotli込み）を使い、
  `python -m streamlit run dashboard/app.py` を起動します。

## 実行場所（重要・2026-06-28 訂正）

- **収集（downloader / update_monthly / rebuild の収集ステップ）は、ネットが開放された
  通常マシン（ターミナルのPython、または母艦の Claude Code）で実行する。**
  Cowork のVM内では動かない（mod.go.jp がallowlist遮断＋ディスク約1.4GB）。
- **Cowork（VM）で動かしてよいのは収集を伴わない処理**（export_tables / make_dashboard_xlsx /
  verify / 分析・資料作成）。
- 本番キットは `--with-db` 版（DB同梱）なので、引っ越し直後の再構築・収集は不要。
  解凍 →（必要時のみ）月次更新はネット開放マシンで、という流れ。

## AIクレジット節約方針（重要）

- **データのダウンロードや Python 実行そのものはトークン（クレジット）を消費しない。**
  消費されるのは「AIが推論する」分だけ。だから収集は人がターミナルで起動すればAIコスト0。
- AIエージェントに任せる場合も:
  1. 仕事は「コマンドを起動して完了を待ち、最後の `SUMMARY` 行を読む」だけ
  2. スクリプトの中身を読ませたり、独自に作り直させたりしない
  3. AIが頭を使うのは **異常時だけ**（`kit/AGENT_INSTRUCTIONS.md` 参照）

## リハーサル実測値（2026-06-13、本キット開発時の検証）

開発元環境でキャッシュ完備の条件により2回のフル再構築リハーサルを実施。両回とも
**全ステップの投入行数が完全一致**（パーサーは決定論的）。一次再現率は
**contracts 134,654 / 155,063（86.8%）**で、エンリッチメントのインポート
（pillar/要求元/OCR/小テーブル）は正常完了。残り約13%は「インデックスページから
リンクが消えたファイル」等で、verify が出力する欠損URLリストを
`downloader.py --urls` → `replay_load.py` で追い込む設計（Step 4 参照）。
それでも残る分は gone404（消失URL）として明示される。

## 再現の限界（正直な注意書き）

- ライブの mod.go.jp URL は年度替わりで消えることがある → downloader が
  Wayback Machine へ自動フォールバックするが、**ライブ・アーカイブ双方から消えたファイルは
  復元不能**（`SUMMARY` の `gone404` に計上され、verify の欠損レポートで影響範囲がわかる）
- パーサーの挙動はライブラリのバージョンに依存しうる → `requirements_cpu.txt` の
  下限を守ること。差分は verify が検出する
- FY2026以降の新規データはこのキットの範囲外 → `REBUILD.md` の「増分収集」参照
