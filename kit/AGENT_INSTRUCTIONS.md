# AIエージェント向け指示書（Claude Cowork 想定）

このフォルダは「防衛調達DB 引っ越しキット」です。あなた（AIエージェント）の役割は、
**用意済みのスクリプトを順番に起動して完了を待つこと**です。コードを書くことではありません。

## 最初に貼るプロンプト（人間用: これをCoworkセッションの最初に貼り付ける）

```
このフォルダは防衛調達DBの引っ越しキットです。kit/AGENT_INSTRUCTIONS.md の
行動ルールに従って、kit/REBUILD.md の Step 1〜5 を順番に実行し、DBを再構築して
ください。各ステップはスクリプトを起動して SUMMARY 行で成否判定するだけです。
スクリプトの改変・再実装はしないでください。長時間処理はバックグラウンドで
実行し、完了を待ってから次に進んでください。最後に verify の結果を報告して
ください。
```

## 行動ルール（クレジット消費を最小にするための約束）

1. **各ステップは「起動 → 完了待ち → 最後の `SUMMARY` 行で成否判定」だけ。**
   ログ全文を読まない。スクリプトのソースを読まない。
2. **スクリプトの修正・再実装・改善提案をしない。** 設計済み・検証済みです。
   うまく動かない場合も、まず下の早見表 → それでも不明なら**人間に報告して指示を待つ**。
3. **長時間処理（Step 2 のダウンロード、Step 3 の再構築）はバックグラウンド実行**し、
   完了通知まで待つ。進捗を頻繁にポーリングしない
   （目安: 確認は30分に1回まで。`wc -l kit/exports/download_manifest.jsonl` で十分）。
4. **深い調査（ログ精読・DB直接クエリ）をしてよいのは verify が FAIL のときだけ。**
   そのときも読むのは `kit/exports/verify_report.json` と該当ステップのログ末尾50行まで。
5. ネットワークを使うのは `kit/downloader.py` と増分収集だけ。それ以外は全てローカル処理。
6. `data/db/procurement.db` を手で UPDATE/DELETE しない。修正はすべてスクリプト経由。

## 実行手順（= REBUILD.md の要約）

| # | コマンド | 成功判定（SUMMARY行） | 所要 |
|---|---------|----------------------|------|
| 1 | `bash kit/setup_env.sh`（Win: `kit\setup_env.ps1`） | `setup=OK` | 数分 |
| 2 | `python kit/downloader.py` | `fail=0`（gone404は許容） | 3〜5h |
| 3 | `python kit/rebuild_all.py` | `failed_steps=なし` | 1〜3h |
| 4 | `python kit/verify_rebuild.py` | `result=PASS` または `WARN` | 数分 |
| 5 | `python -m streamlit run dashboard/app.py` | 起動してページ表示 | — |

※ Step 3 には verify が含まれるため、Step 4 は実質確認の再実行。

## よくある事象と一次対処（この表の範囲は自分で対処してよい）

| 事象 | 一次対処 | 上限 |
|------|---------|------|
| downloader で `fail=N` | `python kit/downloader.py --retry-failed` | 2回まで |
| downloader が中断した | そのまま再実行（レジュームされる） | — |
| rebuild_all で `[FAIL] step NN` | `python kit/rebuild_all.py --from-step NN` | 2回まで |
| verify で URL欠損 WARN | `python kit/downloader.py --urls kit/exports/verify_missing_urls.txt` → `python kit/replay_load.py` → `python kit/verify_rebuild.py` | 1周まで |
| `database is locked` | streamlit 等を止めて再実行 | — |
| 文字化け | `PYTHONUTF8=1` を設定して再実行 | — |

**上限を超えても直らない / 表にない事象 → 作業を止めて人間に報告。**
報告に含めるもの: ①実行したコマンド ②最後のSUMMARY行 ③該当ログ末尾50行
（`logs/rebuild/NN_*.log`）④ `kit/exports/verify_report.json` の `fails` 配列。

## 人間に判断を仰ぐべきこと（自分で決めない）

- `gone404`（消失URL）由来の欠損をどこまで許容するか
- expected との差が1%を超えたままの状態を「完了」と呼ぶか
- スクリプトの改修・依存パッケージのバージョン変更
- FY2026以降の増分収集をいつ・どの頻度で回すか

## このDBについての前提知識（質問されたとき用）

- 中身: 防衛省・自衛隊の調達公表データ FY2022–2025、約15.5万契約・約26.7兆円
- 主DB: `data/db/procurement.db`（contracts ほか8テーブル）
- 7本柱分類（contract_pillar）と要求元判定（contract_requesting_org)は
  AI・ルール・手動の混成判定で、**再計算せずインポートで復元**している
- 詳しい経緯は `CLAUDE.md`（Phase 1〜17）。ただし通常作業で読む必要はない
