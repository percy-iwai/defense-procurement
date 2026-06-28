# ショート動画 制作 引継ぎメモ（次セッション用）

最終更新: 2026-06-14

## このセッションで決まったこと / できたこと

- 企画は **docs/short_video_plans.md** に5本（#12〜#16）の実行仕様（秒単位構成・検証済みSQL・台本JSONスキーマ・法務ルール）が確定済み。**まずこれを読むこと。**
- そのうち **#16「買った後が本番」F-35A編のデモ動画を1本完成**させた（パイプライン実証）。
- ポップ路線の元アイデアは docs/service_ideas.md の #11〜#16。

## 完成済みデモ（#16 F-35A編）

| ファイル | 内容 |
|----------|------|
| `temp/f35_demo/f35_lifecycle_v2.mp4` | **完成版**（60秒・写真・機数/単価シーン・クロスフェード・ずんだもん音声・効果音） |
| `temp/f35_demo/f35_lifecycle_demo.mp4` | 初版（写真なし・Windows TTS）。参考 |
| `temp/f35_demo/make_demo2.py` | 完成版のフレーム生成（Pillow）。シーン定義はここ |
| `temp/f35_demo/script_f35_lifecycle.json` | 台本JSON（plans.mdのスキーマ準拠）。数値の出所も記載 |
| `temp/f35_demo/assets/f35_img01.jpg ほか` | 航空自衛隊HPのF-35写真（©JASDF、出典明記要） |

## 確立した制作パイプライン（重要・再利用する）

```
1. データ抽出   修復済みDB(data/db/backup/procurement_repaired_YYYYMMDD.db)からSQL
               ※ライブDBはcontract_pillar破損中。JOINするSQLは必ず修復済みコピーで実行
2. フレーム描画  Pillow（make_demo2.py）。1080x1920 / 10fps / 60秒 = 600枚PNG
               日本語フォント: C:/Windows/Fonts/YuGothB.ttc, YuGothM.ttc
3. ナレーション  VOICEVOX（ずんだもん speaker=3）。エンジンは下記手順で起動
4. 効果音       make_demo2.py と同階層で合成（se_track.wav。数式合成、依存なし）
5. 合成        ffmpeg で frames + narration + se を amix してmux
```

### ツールは導入済み（winget）

- **ffmpeg**: `~/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_*/ffmpeg-8.1-full_build/bin/ffmpeg`
- **VOICEVOX**: `~/AppData/Local/Microsoft/WinGet/Packages/HiroshibaKazuyuki.VOICEVOX_*/VOICEVOX/`
  - エンジン起動: `VOICEVOX/vv-engine/run.exe --host 127.0.0.1 --port 50021`
  - 起動後 `http://127.0.0.1:50021/version` が返れば準備OK。`/audio_query`→`/synthesis` で合成
  - ⚠️ ハーネスのツールシェルから直接 run.exe を起動すると不安定だった →
    **schtasks（タスクスケジューラ）経由 or PowerShell Start-Process** で起動するのが確実
- **Node.js**: 導入済みだが **Remotionはnpm install不調（@remotion/playerのキャッシュ衝突）で断念**。
  当面は Pillow+ffmpeg 経路で十分。Remotionをやるなら別途依存解決が必要。

### ffmpeg合成コマンド（実績）

```bash
FF=".../ffmpeg"
"$FF" -y -framerate 10 -i frames2/f%04d.png \
  -i narration_zunda.wav -i se_track.wav \
  -filter_complex "[1:a]volume=1.0[v];[2:a]volume=0.5[s];[v][s]amix=inputs=2:duration=longest:normalize=0[a]" \
  -map 0:v -map "[a]" -c:v libx264 -pix_fmt yuv420p -r 30 -c:a aac -b:a 160k -shortest out.mp4
```

### VOICEVOX合成の注意

- 出力は **24000Hz / 16bit / mono**。ffmpeg amix が異レートを吸収するのでナレーションは24000のまま配置でよい。
- ずんだもんは語尾「〜なのだ」。各セグメントを **シーン枠（秒）に収める**必要あり →
  長い時は `speedScale` を 0.08刻みで上げるか、テキストを短縮（make_demo2の隣で実施した手法）。
- `audioop` は Python 3.13+ で削除済み。リサンプルはffmpeg側に任せ、Pythonでやらないこと。

## 次にやること（残り4本）

plans.md の #12〜#15 を順に制作。立ち上げ順序の推奨は plans.md 末尾参照（#14 bot → #13/#12 → #15）。
ただし**動画として作りやすいのは #16と同じ縦型尺もの**なので、#16のmake_demo2.pyを雛形に：

1. **#12 月次ランキングTOP10** — plans.md のSQLで当月TOP10取得 → カウントダウン構成
2. **#13 クイズ** — 「身近な品目」734件ヒット済み。3択ダミーは正解×0.1/×10
3. **#15 都道府県** — 県別SQLは検証済み（plans.mdに正規化版あり）。47本ストック
4. **#14 Xbot** — これは動画でなく画像+投稿。Pillowで画像1枚生成に切り替え

各回の数値は必ず **修復済みDBコピー**からSQLで取り、創作しない（plans.mdの鉄則）。
F-35編で使った写真取得の手口（空自HP `/asdf/equipment/sentouki/<機体>/` から
`<img>` を辿る、403はフルUA、消失はWaybackフォールバック）は他機体・装備でも流用可。

## 引き継ぎチェックリスト（次セッション冒頭で確認）

- [ ] docs/short_video_plans.md を読む（5本の仕様）
- [ ] temp/f35_demo/make_demo2.py と script_f35_lifecycle.json を雛形として確認
- [ ] 最新の修復済みDBコピー名を確認（`ls data/db/backup/procurement_repaired_*.db`）
- [ ] VOICEVOXエンジンを起動（schtasks/Start-Process経由）→ /version 疎通
- [ ] 作りたい回のSQLを修復済みDBで実走して数値を確定 → 制作
