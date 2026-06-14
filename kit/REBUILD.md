# 再構築手順書（新環境用・ステップバイステップ）

各ステップは**1コマンド・冪等（何度実行しても安全）・中断再開可**です。
コマンドはすべて**キットを展開したディレクトリの直下**で実行してください。

> Windows で日本語が文字化けする場合は、先に `set PYTHONUTF8=1`（PowerShellは
> `$env:PYTHONUTF8="1"`）を実行してください。機械判定用の `SUMMARY` 行は常にASCIIです。

---

## Step 0. キットの入手と展開

- zip の場合: 展開するだけ
- git の場合: `GIT_LFS_SKIP_SMUDGE=1 git clone <repo>`（LFSの旧DB 174MB を引かない）

## Step 1. Python環境構築

```bash
bash kit/setup_env.sh                                      # macOS / Linux
powershell -ExecutionPolicy Bypass -File kit\setup_env.ps1  # Windows
```

- **期待される出力**: `SUMMARY setup=OK venv=...`
- **失敗時**: Python 3.10+ が無い → インストールして再実行。
  pip エラー → ネットワーク/プロキシを確認して再実行。
- 以後のコマンドは venv を activate してから実行
  （`source .venv/bin/activate` / `.venv\Scripts\Activate.ps1`）。

## Step 2. 原本ダウンロード（3〜5時間・放置可）

```bash
python kit/downloader.py
```

- 全6,786 URLを `data/raw/_cache/` に保存。進捗は100件ごとに表示。
- **期待される出力**: `SUMMARY ok=... cached=... gone404=少数 fail=0`
- **中断・再開**: いつ止めてもよい。再実行すれば `kit/exports/download_manifest.jsonl`
  を見て続きから走る。
- **失敗時**:
  - `fail=N`（N>0）→ `python kit/downloader.py --retry-failed` を1〜2回。
    それでも残るならネットワーク一時障害の可能性。時間を置いて再実行。
  - `gone404` はエラーではない（ライブ・アーカイブ双方から消えたURL）。
    件数をメモしておき、Step 4 の verify で影響を確認する。
- 進捗確認（別ターミナルから）: `wc -l kit/exports/download_manifest.jsonl`

## Step 3. DB再構築（1〜3時間・放置可）

```bash
python kit/rebuild_all.py
```

16ステップ（スキーマ作成 → 機関別ローダー → ギャップフィル → 判定結果インポート →
検証）を順に実行し、各ステップの行数増分を表示します。
ログは `logs/rebuild/NN_<step>.log`、集計は `kit/exports/rebuild_log.json`。

- **期待される出力**: 各行 `[OK ] step NN <name> +X,XXX行`、
  最後に `SUMMARY contracts=155,xxx failed_steps=なし`
- **失敗時**:
  - `[FAIL] step NN ...` → `logs/rebuild/NN_*.log` の末尾を確認。
    一時的なエラーなら `python kit/rebuild_all.py --from-step NN` で再開（冪等）。
  - 特定ステップだけやり直す: `python kit/rebuild_all.py --steps NN`
  - ステップ一覧: `python kit/rebuild_all.py --list`

## Step 4. 検証

```bash
python kit/verify_rebuild.py
```

- **期待される出力**: `SUMMARY result=PASS`（または軽微な欠損つきの `WARN`）
- **WARN/FAILの読み方**: `kit/exports/verify_report.json` に全比較が入っている。
  - URL欠損 → `kit/exports/verify_missing_urls.txt` を
    `python kit/downloader.py --urls kit/exports/verify_missing_urls.txt` で再取得し、
    `python kit/replay_load.py` → `python kit/verify_rebuild.py` をもう一周
  - それでも埋まらない分は Step 2 の `gone404`（消失URL）が原因の可能性が高い。
    `expected` と `actual` の差分行数が全体の1%未満なら実用上問題ない

## Step 5. ダッシュボード起動

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # パスワードを編集
python -m streamlit run dashboard/app.py --server.port 8501
```

ブラウザで http://localhost:8501 を開き、各ページが表示されれば完了。

---

## 増分収集（FY2026以降の新データ）

確定分の再現とは別系統です。四半期〜月次で以下を実行:

```bash
# 1. 各機関の新規公表分を収集（ライブサイトから。ネットワーク必要）
python -m pipeline.load_atla --fy 2026
python -m pipeline.load_asdf
python -m pipeline.load_msdf
python -m pipeline.load_gsdf
python -m pipeline.load_rdb
python -m pipeline.load_misc
python -m pipeline.load_atla_sub

# 2. ATLA中央調達の要求元判定（新規行のみ対象に再計算）
python dev/recompute_atla_requesting_org.py --dry-run   # 確認
python dev/recompute_atla_requesting_org.py

# 3. 7本柱キーワード分類
python dev/assign_pillar_fy2023.py --fy 2026
```

- セマンティック分類（`dev/assign_pillar_semantic.py`）はGPUが必要。GPU環境を
  得るまでは未分類のまま残してよい（keyword_rule が主力で、semanticは補完）。
- 新しいインデックスページからファイルURLだけ先に集めたい場合:
  `python kit/downloader.py --discover index_urls.txt`

## トラブルシューティング早見表

| 症状 | 対処 |
|------|------|
| `ModuleNotFoundError` | venv を activate していない / Step 1 をやり直す |
| ダウンロードが極端に遅い | WARP側の混雑。`--rate 2.0` で間隔を倍にして安定優先 |
| `database is locked` | 別プロセス（ダッシュボード等）がDBを開いている。閉じて再実行 |
| verify で contracts が数百件足りない | 欠損URL再取得の一周（Step 4 参照）で大半解消 |
| `PRAGMA integrity_check` が ok でない | `python kit/repair_contract_pillar.py --check` で診断 |
| 文字化け | `PYTHONUTF8=1` を設定。SUMMARY 行だけ読めば判定は可能 |
