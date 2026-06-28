# 月次更新の手順（ロックダウン環境向け）

毎月、最新の防衛調達データに更新して全員がブラウザで見られるようにする運用。
**収集はネット開放された編集者マシン、見るのはロックダウンPCのブラウザ**、という切り分け。

> ⚠️ **重要（2026-06-28 訂正）**: 収集処理は **Claude Cowork のVM内では動きません**。
> CoworkのVMはネットが厳格なallowlist（`api.anthropic.com / pypi.org / registry.npmjs.org` のみ）で
> **mod.go.jp / WARP に到達できず**、さらに**空きディスクが約1.4GBしかなく11GBのPDFが入らない**ためです。
> 収集は「ネットが開放された編集者の通常マシン（ターミナルでPython、または Claude Code）」で実行してください。
> Cowork（VM）が担えるのは収集を伴わない処理（既存DBからのExcel生成・分析）だけです。

## 全体像

```
 DB編集者の通常マシン（ネット開放・Python or Claude Code）
   [procurement.db]  ←─ 状態はここに置きっぱなし。SharePoint往復なし
     │ ①増分収集→追記  ②Excel/CSV出力 ──┐
     │（mod.go.jpへ収集＝ここでしかできない）│ ③xlsxだけアップロード（上書き）
     ▼                                    ▼
            SharePoint/Teams  [防衛調達ダッシュボード.xlsx]
                                  │
                                  ▼
       全員：ブラウザ（Excel for the web）で最新を閲覧 ← インストール不要
```

- **状態(procurement.db)はDB編集者の通常マシンに保持**。SharePointへ毎月戻す必要なし。
  次月もそのローカルDBから増分する。
- SharePointに出すのは**閲覧用xlsxだけ**（一方向・上書き）。
- ①②は**ネットが開放された編集者の通常マシン**で行う（mod.go.jpへ収集するため）。
  - ロックダウンPCの上ではPython自体が動かせない（インストール不可・ポータブルもブロック）。
  - **Cowork VM内でも収集は不可**（mod.go.jpがallowlist遮断＋ディスク不足）。Coworkは②のExcel生成など
    ネット不要処理だけ手伝える。
- 留意: ローカル1台に状態が集中するので、**たまにDBをSharePoint等へ安全コピー**しておくと
  PC故障時も安心（毎月の往復は不要、あくまでバックアップ）。失っても kit からURL再構築は可能
  （※再構築もネット開放マシンで。Cowork不可）。

## 毎月の手順（手動トリガー）

前提: 編集者の通常マシン（ネット開放）に `data/db/procurement.db` が居る。
初回だけ無いので、その回は `python kit/rebuild_all.py` でフル構築する
（ただし `--with-db` 版キットなら解凍時点でDBが入っているので構築は不要）。

1. **更新コマンドを1つ実行**（編集者の環境で）:
   ```bash
   python kit/update_monthly.py            # 当年度を増分収集→7本柱分類→Excel/CSV出力
   # 任意: python kit/update_monthly.py --deep   # 要求元の再計算も（重い・精度↑）
   ```
   - 追記前に自動バックアップ（`data/db/backup/procurement_pre_monthly_*.db`）
   - 増分なので数分〜十数分。`INSERT OR IGNORE` で二重登録なし
   - 最後に `SUMMARY before=… after=… added=…`

2. **成果物を確認** … `kit/out/防衛調達ダッシュボード.xlsx` と `contracts.csv` が更新される

3. **xlsxだけSharePointに上げる**（手動ドラッグ＆ドロップ）:
   - `防衛調達ダッシュボード.xlsx` → Teams/SharePointの閲覧用フォルダに**上書き**
     （ファイル名を変えない＝タブのリンク不変、全員が次に開くと最新）
   - **procurement.db はローカルに置いたままでOK**（SharePointへ戻さない）

4. **全員はそのまま** … Teamsタブ／SharePointのExcelをブラウザで開けば最新

> たまに（四半期に1回など）`procurement.db` をSharePointや外付けに**安全コピー**しておくと、
> 編集者PCの故障時も安心。毎月の往復ではなく、あくまで保険。

## 注意点

- 状態DBは編集者ローカル保持。SharePointへ戻す運用ではない（保険コピーのみ任意）。
- **7本柱のセマンティック分類はGPUが要る**ため月次では回さない（keyword分類が主力で十分）。
  GPU環境を得たときだけ `dev/assign_pillar_semantic.py` を別途。
- 月次で `kit/repair_contract_pillar.py --check` が破損を警告したら、
  `--in-place` で修復してから出力（docs/db_quality_audit A-1）。update_monthly が自動でチェックする。
- 自動化（Coworkルーチン＋Graphで自動アップロード）に進みたくなったら、
  手動運用が固まってから。認証（アプリ登録・API権限）はIT許可が要る。

## トラブル時

- `update_monthly.py` が `FAIL` を出したステップ → `logs/monthly/<step>.log` の末尾を確認。
  一時的なネットワーク不調なら同じコマンドを再実行（冪等）。
- 収集件数が増えない月 → 各機関の公表が遅れている可能性（4〜6月に前年度分が出揃う傾向）。
- DBが大きくなってExcel for the webで重い → ダッシュボードは集計＋主要列なので軽い。
  生全件が要る人にだけ `contracts.csv`（zipして配布）を渡す。
