# ショート動画 #11「この企業、実は国防支えてる？」企業候補 調査結果（引き継ぎ）

作成: 2026-06-14 / 調査者: Claude（DB調査担当）
用途: 別エージェントへの引き継ぎ。第1弾の台本作成・追加深掘りに使う。

## コンセプト（再掲）
- 「えっ、あの会社が？」と思わせる中堅・大手の意外な防衛供給
- 装備品写真 × 契約額 3〜4連発 → 防衛省調達シェア/独占性 → 社名リベール（45秒）

## 使用DB
- **メイン**: `data/db/backup/procurement_repaired_20260613.db`（contract_pillar修復済み）
  - `contracts`（155,063件）— ※注意: このDBの contracts には `vendor_name_norm` / `contract_pillar` カラムは**無い**。集計は `vendor_name` を LIKE で寄せて行った。
  - `equipment_master`（126件）— ここにある。`defense_pillar.db` には無い。
  - `contract_equipment`（contract_id, equipment_id, confidence）— 契約↔装備品リンク
  - `contract_pillar`（113,118件・別テーブル, contract_id でJOIN）
- 作業クエリ: `dev/null/query_*.py`（SELECTのみ・DB更新なし）

## equipment_master 突合のやり方（重要・再利用可）
`contracts` に pillar/装備カラムが無いので JOIN で取る:
```sql
SELECT em.equipment_id, em.name_ja, em.branch, COUNT(*) n
FROM contracts c
JOIN contract_equipment ce ON c.id = ce.contract_id
JOIN equipment_master em ON ce.equipment_id = em.equipment_id
WHERE c.vendor_name LIKE '%旭化成%'
GROUP BY em.equipment_id ORDER BY n DESC;
```
`equipment_master` の `ref_url_official` / `ref_url_wikipedia` が動画の装備品写真・出典に使える。

---

## 第1弾 推奨: 旭化成（「えっ」度最大 × 金額最大 × 独占）

---

## 候補 TOP（「えっ」度 × データの強さ）

| 順 | 社名 | 普段のイメージ | 防衛調達(合算) | 突合できた装備 | 契約形態 |
|---|------|------|------|------|------|
| **A** | **旭化成** | サランラップ・ヘーベルハウス | **189.5億** | 各種火砲(155mm) [GSDF] 8件 / DII | 大半 随意=独占 |
| **B** | **横浜ゴム** | タイヤ | **107億** | 潜水艦 [MSDF] 6件 | 随意=独占 |
| **C** | **カシオ** | G-SHOCK・電卓 | **32.5億**(1件) | 研究委託 | 一般競争 |
| **D** | **ミネベアミツミ** | ベアリング | **138億** | P-1/SH-60K/L/J [MSDF] | 随意=独占 |
| **E** | **ニコン** | カメラ・顕微鏡 | **118億** | 護衛艦光学センサ | — |
| ＋ | **ブリヂストン** | タイヤ | **62.8億** | F-15/F-2/P-3C/US-2/KC-767等 70件超 | — |

> 数字は表記ゆれ（株式会社/全角/事業部名）を LIKE で合算した概算。台本に出す前に表記別の内訳を再確認推奨。

### 「えっ」ポイント詳細
- **A 旭化成（189.5億）**: サランラップ／ヘーベルハウスの旭化成が **99式155mmりゅう弾砲の発射装薬（火薬）** を国内唯一供給（全件随意契約）。FY2024 48.2億・FY2025 39億。加えて統合衛生情報システム 51.5億。
  - 装備: `gsdf_cat_arty 各種火砲` https://ja.wikipedia.org/wiki/火砲
- **B 横浜ゴム（107億）**: タイヤのヨコハマが **潜水艦ソナードーム用ゴム（ラバーウィンドウ ZQQ-6）** と **潜水艦用防振管継手** を独占供給。
  - 装備: `msdf_cat_submarine 潜水艦` https://ja.wikipedia.org/wiki/潜水艦
- **C カシオ（32.5億・1件）**: G-SHOCKのカシオが「**腕時計型ウェアラブル端末による航空機操縦者の状態推定・警告に関する研究**」を一般競争で受注。1件で32.5億の桁違い。→「調達」でなく「研究受注」と表現する方が正確。
- **D ミネベアミツミ（138億）**: ベアリングのミネベアが **イジェクタ・ラック BRU-47/A（爆弾投下装置）** と **P-1哨戒機/SH-60ヘリ向けソノブイランチコンテナ** を供給。
  - 装備: `msdf_p1 P-1` 公式 https://www.mod.go.jp/msdf/equipment/aircraft/patrol/p-1/
- **E ニコン（118億）**: カメラのニコンが **護衛艦搭載の光学センサ（センサマスト部）** を供給。初度費だけでFY2024に39億。※equipment_master直接リンクは無いが案件名「光学センサ」で明確。
- **＋ブリヂストン（62.8億）**: 乗用車タイヤのブリヂストンが **F-15/F-2/P-3C航空機用タイヤ** を供給。equipment_master 突合が最も豊富（F-15J/DJ, F-2A/B, P-3C, US-2, KC-767等 計70件超）→ 機体写真を多用するなら素材が一番揃う。

### 装備品 参照URL（動画の写真・出典用）
| 装備 | id | 公式 | Wikipedia |
|---|---|---|---|
| F-15J/DJ | asdf_f15jdj | mod.go.jp/asdf/equipment/sentouki/F-15/ | ja.wikipedia.org/wiki/F-15J_(航空機) |
| F-2A/B | asdf_f2ab | mod.go.jp/asdf/equipment/sentouki/F-2/ | ja.wikipedia.org/wiki/F-2_(航空機) |
| P-3C | msdf_p3c | mod.go.jp/msdf/equipment/aircraft/patrol/p-3c/ | ja.wikipedia.org/wiki/P-3C |
| P-1 | msdf_p1 | mod.go.jp/msdf/equipment/aircraft/patrol/p-1/ | ja.wikipedia.org/wiki/P-1 |
| 護衛艦 | msdf_cat_destroyer | — | ja.wikipedia.org/wiki/護衛艦 |
| 潜水艦 | msdf_cat_submarine | — | ja.wikipedia.org/wiki/潜水艦 |
| 各種火砲(155mm) | gsdf_cat_arty | — | ja.wikipedia.org/wiki/火砲 |

---

## 引き継ぎ先への注意・残タスク
1. **表記ゆれの確定**: ミネベアミツミ・横浜ゴム・ニコン・旭化成は複数表記で分散。台本の数字確定前に `vendor_name` 別内訳を再集計すること。
2. **カシオ**は研究委託（一般競争）→「独占供給」フレームは使わない。
3. 旭化成・横浜ゴム・ミネベアの大型案件は**全て随意契約＝事実上の国内独占供給**。「実はこの会社しか作れない」ストーリーに使える。
4. 動画作りは `short-video-factory` スキル（企画書→骨子→ドラフト→完成、Percyレビュー2回＋AIレビュワー並列）に従う。
5. 既存の制作作法は `docs/short_video_handoff.md` と memory `project_short_video` を参照。
