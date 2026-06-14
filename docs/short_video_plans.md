# ショート動画 企画書 5本（#12〜#16）

対象: docs/service_ideas.md のポップ路線 #12〜#16 の実行仕様。
読者: 制作を担当するAIエージェント（および人間の最終確認者）。
前提DB: `data/db/procurement.db`（contracts 155,063件 / FY2022–2025）+
`data/db/defense_pillar.db`。SQLはすべて読み取り専用で実行可能なものを記載。

> **依存条件**: vendor集計を使う企画（#14, #15）は監査A-5（vendor_name正規化）の
> 完了後に精度が上がる。完了前は `REPLACE(vendor_name,'㈱','株式会社')` 等の
> 簡易正規化をSQL内で行うこと（各SQLに記載済み）。

---

## 共通仕様（全企画に適用）

### 台本JSONスキーマ

制作パイプラインの中間成果物。**1動画=1JSON**。これを動画テンプレに流し込む。

```json
{
  "series": "ranking_monthly",        // 企画ID: ranking_monthly | quiz | bot_daily | prefecture | lifecycle
  "episode_id": "ranking_202605",     // 一意ID（ファイル名にも使用）
  "title": "【2026年5月】防衛省の高額契約TOP10",
  "duration_sec": 60,
  "scenes": [
    {
      "t_start": 0.0, "t_end": 3.0,
      "type": "hook",                  // hook | item | reveal | outro
      "text_main": "今月、防衛省が一番高い買い物をしたのは？",
      "text_sub": null,
      "image": null,                   // 画像パス or null（nullはテンプレ背景）
      "image_credit": null,            // 出典表記（画像があれば必須）
      "tts": "今月、防衛省がいちばん高い買い物をしたのは？"
    }
  ],
  "sources": [                         // 概要欄に列挙する出典
    "防衛省 中央調達に係る契約に関する情報の公表（財計第2017号）",
    "本動画の集計は独自データベースによる（誤りは概要欄のフォームへ）"
  ],
  "description": "概要欄テキスト（導線リンク含む）",
  "tags": ["防衛省", "自衛隊", "防衛費", "雑学"],
  "thumbnail_text": "1位は まさかの○○"
}
```

### 制作パイプライン（共通）

1. **抽出**: 各企画のSQLを実行 → ネタ候補CSV
2. **台本生成**: 候補から台本JSON生成（LLMは言い回しの調整のみ。**数値・社名・品名は
   SQLの結果をそのまま使い、創作・丸め・推測をしない**）
3. **人間チェック**: 台本JSONを1本ずつ目視承認（社名・金額・出典の3点確認）
4. **レンダリング**: テンプレ（Remotion または ffmpeg + drawtext）に流し込み
   1080×1920 / 30fps / H.264。TTSはVOICEVOX等のローカルTTS（クレジット消費なし）
5. **投稿**: タイトル・概要欄・タグはJSONから自動組み立て

### 表記・法務ルール（全本必須）

- 画面内に常時または末尾2秒で出典表記:
  `出典: 防衛省公表データ（財計第2017号）を独自集計`
- 防衛省サイトの画像は政府標準利用規約（出典明記で利用可）。
  Wikipedia画像は CC BY-SA（撮影者名+ライセンス名を image_credit に）。
  出典不明の画像は**使わない**（テンプレ背景＋テキストで成立する設計にする）
- 金額は契約額（税込・公表値）。「約」を付けて億円単位で丸める（丸め方: 小数1位）
- 企業への価値判断ワード（軍需企業、死の商人、ボロ儲け等）は**禁止**。
  事実（品名・金額・件数・シェア）のみ
- 7本柱分類・シェア%を使う場合は「独自集計」と画面内に明示

### 共通KPI

- 1本あたり制作時間（人間の確認込み）: 15分以内
- 初月: 各シリーズ4本ずつ投稿し、維持率50%超のシリーズに集中する
- 収益はショート広告でなく、概要欄→ニュースレター登録数で測る

---

## #12 「今月の防衛調達ランキングTOP10」

### 一言コンセプト
毎月の公表データから高額契約TOP10をカウントダウン。**ネタ切れが構造的にない**定番枠。

### フォーマット（60秒 / 縦型）

| 秒 | シーン | 内容 |
|----|--------|------|
| 0–3 | hook | 「今月、防衛省が一番高い買い物をしたのは？」 |
| 3–48 | item×10 | 10位→2位: 各4.5秒。「第○位 ○○（品名を15字以内に要約） 約○○億円（発注: ○○）」 |
| 48–55 | reveal | 1位: 7秒かけて発表。品名+金額+一言ツッコミ（例: 「燃料だけで○○億」） |
| 55–60 | outro | 「合計○○億円。詳細は概要欄のニュースレターで」+出典表記 |

### データ抽出SQL

```sql
-- 当月のTOP10（:ym = '2026-05' 形式。contract_dateはYYYYMMDD文字列）
SELECT contract_name, vendor_name, contract_amount,
       agency_name, agency_category, bid_method
FROM contracts
WHERE substr(contract_date,1,6) = REPLACE(:ym, '-', '')
  AND contract_amount IS NOT NULL
ORDER BY contract_amount DESC
LIMIT 10;

-- アウトロ用: 当月合計
SELECT COUNT(*), SUM(contract_amount) FROM contracts
WHERE substr(contract_date,1,6) = REPLACE(:ym, '-', '');
```

### 台本化ルール
- 品名はそのままだと長い（例:「○○の購入及びこれに伴う技術支援役務」）→
  **15字以内に要約してよいが、元の品名を text_sub に残す**
- vendor_name は10位〜2位では出さなくてよい（情報過多）。1位のみ表示
- 同一品の分割契約が複数ランクインした場合は備考「※同種契約が他に○件」

### スピンオフ（同テンプレ使い回し）
- 軍種別（陸/海/空/装備庁）月4本、年度末「FY2025年間TOP10」、「随意契約だけTOP10」

### リスク
- 公表は機関により1〜2ヶ月遅れる → タイトルは「最新公表分」と逃げを打つ。
  月次増分収集（kit/REBUILD.md の増分手順）が前提

---

## #13 「自衛隊の買い物、いくらでしょう？」クイズ

### 一言コンセプト
調達品の価格を3択で当てるクイズ。コメント欄が「答え合わせ会場」になる参加型。

### フォーマット（30秒 / 縦型）

| 秒 | シーン | 内容 |
|----|--------|------|
| 0–3 | hook | 「自衛隊が買った『○○』、いくらでしょう？」 |
| 3–8 | item | 品名+説明1行（何に使うものか）。画像があれば表示 |
| 8–15 | quiz | 3択表示（正解1+ダミー2）。カウントダウンSE |
| 15–22 | reveal | 正解発表+「ちなみに○○件買ってます」等の追い情報 |
| 22–30 | outro | 「次のクイズはこちら→」+出典表記 |

### ネタ抽出SQL（3系統をローテーション）

```sql
-- A. 身近な品目（食品・楽器・動物・日用品系キーワード）
SELECT contract_name, vendor_name, contract_amount, agency_name
FROM contracts
WHERE contract_amount BETWEEN 100000 AND 50000000
  AND (contract_name LIKE '%ピアノ%' OR contract_name LIKE '%楽器%'
    OR contract_name LIKE '%カレー%' OR contract_name LIKE '%パン%'
    OR contract_name LIKE '%犬%'     OR contract_name LIKE '%寝具%'
    OR contract_name LIKE '%自転車%' OR contract_name LIKE '%ピザ%')
ORDER BY RANDOM() LIMIT 20;

-- B. 極端な金額（高額の代表格）
SELECT contract_name, contract_amount, agency_name FROM contracts
WHERE contract_amount > 10000000000  -- 100億超
ORDER BY RANDOM() LIMIT 10;

-- C. 極小金額（1円契約等。監査C-1の異常値リストがそのままネタ）
SELECT contract_name, contract_amount, agency_name, vendor_name FROM contracts
WHERE contract_amount BETWEEN 1 AND 1000 ORDER BY contract_amount LIMIT 20;
```

### 3択ダミーの作り方（機械的に）
- ダミー1 = 正解×0.1（桁下げ）、ダミー2 = 正解×10（桁上げ）を基本に、
  キリよく丸める。**正解の位置はランダム**
- 1円契約系は逆フォーマット: 「この中で実在する契約はどれ？」

### 留意
- C系統（1円契約）は「入札制度の仕組み（再リース等で名目価格になる）」を
  リベール後に1行で説明し、「不正」と誤読されない作りにする

---

## #14 「本日の注目契約」X(Twitter) 自動投稿bot

### 一言コンセプト
毎日1件、注目契約のインフォグラフィック画像を完全無人投稿。
動画チャンネルとニュースレターへの**常設導線**。

### 投稿フォーマット
- 画像1枚（1200×675）: 品名（要約）/ 金額 / 発注機関 / 契約方式 /
  「今年度この企業の受注: ○件・約○億円」/ 出典表記
- 本文テンプレ:
  `【本日の注目契約】○○省が「○○」を約○億円で契約（○○社・随意契約）。`
  `詳しくは→（ニュースレターURL） #防衛費 #防衛調達`

### ネタ選定ロジック（曜日ローテーション）

| 曜日 | 選定ルール | SQL条件の骨子 |
|------|-----------|--------------|
| 月 | 直近公表分の最高額 | ORDER BY contract_amount DESC LIMIT 1（未投稿のもの） |
| 火 | 随意契約の大型案件 | bid_method='随意契約' AND amount>1e9 |
| 水 | 意外な品目 | #13のA系統キーワード |
| 木 | 落札率99%超 | award_rate >= 0.99 AND amount > 1e8 |
| 金 | 初登場ベンダー | vendor初出（下記SQL） |
| 土 | 装備品深掘り | contract_equipment 経由で equipment_master 紐付きの契約 |
| 日 | 今週の合計振り返り | 週次集計（画像はグラフ1枚） |

```sql
-- 金曜用: 初登場ベンダー（FY2025で初めて現れた企業の最大契約）
WITH first_fy AS (
  SELECT REPLACE(REPLACE(vendor_name,'㈱','株式会社'),'（株）','株式会社') AS v,
         MIN(fiscal_year) AS fy0
  FROM contracts WHERE vendor_name IS NOT NULL GROUP BY v
)
SELECT c.contract_name, c.vendor_name, c.contract_amount, c.agency_name
FROM contracts c
JOIN first_fy f ON REPLACE(REPLACE(c.vendor_name,'㈱','株式会社'),'（株）','株式会社') = f.v
WHERE f.fy0 = 2025 AND c.fiscal_year = 2025
ORDER BY c.contract_amount DESC LIMIT 5;
```

### 実装メモ
- 投稿済み管理: `posted_log.jsonl`（contract自然キーを記録、重複投稿防止）
- 画像生成: HTMLテンプレ→headlessブラウザでPNG化（またはPillow）。
  ブランドカラー・ロゴ位置は固定テンプレ
- **無人とはいえ週1回は人間がログを見る**（誤集計・炎上芽の早期発見）
- 木曜（落札率99%超）は事実のみ淡々と。「談合」等の示唆ワード禁止（共通ルール）

---

## #15 「うちの県の防衛産業」47都道府県シリーズ

### 一言コンセプト
県別の受注総額と「県内の意外な1社」を紹介するご当地シリーズ。
**47本が最初から確定**している企画。地元視聴者の保存・シェアが強い。

### フォーマット（60秒 / 縦型）

| 秒 | シーン | 内容 |
|----|--------|------|
| 0–4 | hook | 「○○県の会社、防衛省からいくら受注してると思う？」 |
| 4–12 | item | 県内受注総額+件数（FY2022–2025累計）「4年間で約○○億円・○○件」 |
| 12–30 | item×2 | 県内最大の1社（社名+主な品目+金額）/ 県内の基地・機関の発注額 |
| 30–48 | reveal | 「意外な1社」: 民生品で有名な地元企業の防衛契約（品名+金額） |
| 48–60 | outro | 「あなたの県は全国○位。次は隣の○○県」+出典表記 |

### データ抽出SQL

```sql
-- 県別集計（47都道府県の正規前方一致。substrだけだと「東京都千」のように
-- 市区が混入するため、都/道/府/県の区切りで抽出する）
WITH pref AS (
  SELECT id, contract_amount,
    CASE
      WHEN vendor_address LIKE '北海道%' THEN '北海道'
      WHEN vendor_address LIKE '東京都%' THEN '東京都'
      WHEN vendor_address LIKE '京都府%' THEN '京都府'
      WHEN vendor_address LIKE '大阪府%' THEN '大阪府'
      WHEN substr(vendor_address, 4, 1) = '県' THEN substr(vendor_address, 1, 4)  -- 神奈川県等
      WHEN substr(vendor_address, 3, 1) = '県' THEN substr(vendor_address, 1, 3)  -- 愛知県等
      ELSE NULL
    END AS p
  FROM contracts WHERE vendor_address IS NOT NULL
)
SELECT p, COUNT(*) AS cnt, ROUND(SUM(contract_amount)/1e8) AS oku
FROM pref WHERE p IS NOT NULL GROUP BY p ORDER BY oku DESC;
-- ※実走検証済み（東京都 約12.97兆 / 兵庫 約1.89兆 / 神奈川 約1.67兆 …）。
-- ただし外国住所・非標準表記でノイズグループが出る（実測86グループ）ため、
-- 台本生成時に p を47都道府県の正規名リストと突合し、不一致は「その他・海外」に集約する

-- 県内TOP社（:pref = '愛知県' 等）
SELECT REPLACE(REPLACE(vendor_name,'㈱','株式会社'),'（株）','株式会社') AS v,
       COUNT(*) AS cnt, SUM(contract_amount) AS amt,
       MAX(contract_name) AS sample_item
FROM contracts
WHERE vendor_address LIKE :pref || '%'
GROUP BY v ORDER BY amt DESC LIMIT 10;
```

### 「意外な1社」の選定基準（人間チェック必須）
- 県内TOP10のうち、社名から防衛を連想しない企業（食品・印刷・建設・運輸等）
- 確認事項: 同名異社でないこと（corporate_numberがあれば突合）、
  契約内容が役務（清掃・給食等）の場合は「基地を支える仕事」として紹介する
  （「武器を作っている」と誤認させない）

### 公開順の戦略
- 初回は防衛産業の集積county（愛知・神奈川・東京）でなく、
  **「防衛と無縁そうな県」から**始める（意外性がフォーマットの証明になる）
- 都道府県名をタイトル先頭に（検索流入: 「○○県 防衛」）

### 制約の明示
- vendor_address の充足率は**88.1%**（実測・2026-06-13）→ 「本社所在地ベースの集計で、
  工場所在地は反映されない」「住所未記載の契約11.9%は集計対象外」を概要欄に明記
  （例: 三菱重工の受注は東京都計上）

---

## #16 「買った後が本番」装備品ライフサイクル費シリーズ

### 一言コンセプト
「買うのに○億、でも維持に毎年○億」— 取得費と維持整備費を
個別契約の積み上げで見せる。**本DBにしかできない**深掘り企画のショート版。

### フォーマット（60秒 / 縦型）

| 秒 | シーン | 内容 |
|----|--------|------|
| 0–5 | hook | 「F-35って、買った後いくらかかるか知ってる？」 |
| 5–15 | item | 取得契約: 「機体の取得 約○○億円（FY○○）」 |
| 15–40 | item×3 | 維持系契約を年次で積む: 「部品供給 ○億」「定期修理 ○億」「訓練装置 ○億」… 画面下に累積カウンター |
| 40–52 | reveal | 「4年間の関連契約 合計約○○億円」氷山グラフィック（水面下が維持費） |
| 52–60 | outro | 「次回: ○○編」+「分類は独自集計」+出典表記 |

### データ抽出SQL

> ⚠️ このSQLは contract_pillar を JOIN する。ライブDBは btree破損（監査A-1）で
> JOIN結果が不安定なため、**修復完了まで `data/db/backup/procurement_repaired_20260613.db`
> に対して実行する**こと。

```sql
-- 装備品別の関連契約（:eq = equipment_master.equipment_id）
SELECT c.fiscal_year, c.contract_name, c.contract_amount,
       p.pillar_l2_code,                -- 72 = 維持整備（独自分類）
       e.confidence
FROM contract_equipment e
JOIN contracts c        ON c.id = e.contract_id
LEFT JOIN contract_pillar p ON p.contract_id = c.id
WHERE e.equipment_id = :eq AND e.confidence >= 0.7
ORDER BY c.fiscal_year, c.contract_amount DESC;

-- 装備品の候補リスト（紐付き契約数が多い順 = シリーズ化候補）
SELECT m.equipment_id, m.name_ja, m.branch,
       COUNT(*) AS n_contracts, SUM(c.contract_amount) AS amt
FROM equipment_master m
JOIN contract_equipment e ON e.equipment_id = m.equipment_id
JOIN contracts c ON c.id = e.contract_id
GROUP BY m.equipment_id ORDER BY amt DESC LIMIT 30;
```

### シリーズ第1期（候補SQLの実走結果・2026-06-13検証済み）

| 装備品 | 紐付き契約数 | 累計額 | 採用 |
|--------|------------:|-------:|------|
| F-35A (ASDF) | 36件 | 約1兆2,693億円 | ◎ 第1回（知名度最強） |
| 12式地対艦誘導弾能力向上型 (GSDF) | 138件 | 約8,583億円 | ◎ 契約数が多く積み上げ演出向き |
| イージス・システム搭載艦 (MSDF) | 49件 | 約6,742億円 | ◎ |
| 25式高速滑空弾 (GSDF) | 118件 | 約6,218億円 | ○（知名度低→「聞いたことない兵器」枠） |
| 地対艦誘導弾連隊 (GSDF) | 147件 | 約5,279億円 | ○ |

（紐付け12,743件・confidence>=0.7の範囲内。続編は候補SQLの6位以下から）

### 正確性の担保（この企画だけ厳しめ）
- 「合計」は**本DBで装備品に紐付けられた契約の合計**であり全費用ではない。
  画面とナレーション両方で「少なくとも」と言う（過大でなく過小方向に倒す）
- confidence < 0.7 の紐付けは使わない
- 維持/取得の区分は contract_pillar（独自分類）である旨を明示
- 数字に異論が来たら個別契約リストを提示できる（むしろ信頼性の見せ場）

### 展開
- ショートで掴み→同素材でロング動画（8–10分、契約リストを全部見せる）→
  note/ニュースレター記事の3点セット。1装備品から3コンテンツを搾る

---

## 立ち上げ順序の提案

1. **#14 bot** を最初に常設（無人・毎日・低リスク。素材生成パイプラインの試運転を兼ねる）
2. **#13 クイズ** と **#12 ランキング** を各4本制作して反応を比較（制作が最も軽い2本）
3. 勝った方に集中しつつ、**#15 都道府県** を週1で消化（47週分のストック）
4. チャンネルが回り始めたら **#16 ライフサイクル** を看板企画として投入
   （最も独自性が高い=他者が真似できない）
