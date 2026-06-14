# procurement.db 品質監査レポート（2026-06-13）

- 対象: `data/db/procurement.db`（contracts 155,063行 / 約26.7兆円）
- 監査方法: 読み取り専用クエリ（本レポートでは**修正を行っていない**）
- 用途: 修正作業（別セッション・Sonnet担当）への引き継ぎ。各項目に検出SQLを付す
- 補足: A-1の破損があるため、数値の採取は修復済みコピー
  `data/db/backup/procurement_repaired_20260613.db` に対して行った

## サマリー（優先度順）

| # | 区分 | 問題 | 規模 |
|---|------|------|------|
| A-1 | **緊急** | contract_pillar の btree ページ破損（JOIN結果が不定） | 重複682件 |
| A-2 | 高 | Phase 9 手動判定12件（mod_search等）が後続recomputeで消失 | 12件/1,782億円 |
| A-3 | 高 | bid_method の表記ゆれ・理由文混入・NULL | NULL 25,782 + ゆれ約4,500 |
| A-4 | 高 | 7本柱分類の未カバー（FY2022全件未付与 + unclassified） | 実質未分類 69,982件(45%) |
| A-5 | 高 | vendor_name の表記ゆれ（株式会社/㈱/（株）） | 約11.6万件に影響 |
| B-1 | 中 | corporate_number の欠損・形式不正 | NULL 16,395 + 不正 3,034 |
| B-2 | 中 | award_rate 欠損（再計算可能分は少ない） | NULL 86,678 |
| B-3 | 中 | category_small が実質未実装 | 97.1% NULL |
| B-4 | 中 | enrichment テーブルの孤児行 | 878 + 99件 |
| C-1 | 低 | 金額異常値（負値・極小値） | -13円1件 + 1〜100円77件 |
| C-2 | 低 | contract_date NULL | 1,361件 |
| C-3 | 低 | contract_requesting_org 未カバー | 3,871件 |
| D-1 | 構造 | 手動修正が rowid ベースで記録され再構築非互換 | — |

---

## A-1.【緊急】contract_pillar の btree ページ破損

**現象**: `PRAGMA integrity_check` が `Tree 41182 page 42086: Rowid out of order` を報告。
contract_pillar（rootpage 41182）の1ページにセマンティック更新前（2026-05-10
13:23頃）の古いセルが残留しており、**PRIMARY KEY であるはずの contract_id が682件重複**、
JOIN や索引検索の結果が実行ごとに変わる（実測: 同じ JOIN COUNT が 77,130 / 91,284 /
92,010 と揺れた）。フルスキャン（全表走査）だけは安定して113,800行を返す。

2026-05-10 以降の全バックアップ（5/15, 5/22, 5/23）が同一破損を持つ。
クリーンなのはセマンティック実行前（contract_pillar 42,512行時代）のみ。

**検出SQL**:
```sql
PRAGMA integrity_check;
SELECT COUNT(*), COUNT(DISTINCT contract_id) FROM contract_pillar; -- 113800 vs 113118
```

**推奨修正**: 修復ツールを作成済み。
```bash
python kit/repair_contract_pillar.py --check     # 診断
python kit/repair_contract_pillar.py --in-place  # バックアップ取得→修復→VACUUM
```
重複解消ルールは「updated_at 最新を採用（同時刻なら unclassified 以外を優先）」。
修復後は 113,118行・integrity ok になる（修復済みコピーで検証済み）。
**残存リスク**: 破損ページ由来で「新しい行が失われ古い行だけ残った」ケースは原理的に
検出不能。content相違の重複は143件だったため、影響は最大でも同オーダーと推定。
修復後に `dev/assign_pillar_fy2023.py --fy 2023/2024/2025` を再実行すれば
keyword_rule / org_fallback 分は完全に再導出され、この不確実性も解消される
（semantic_embedding / manual_correction は上書きされない設計）。

**修復後の正しい分布**（修復済みコピーで確認）:
keyword_rule 43,962 / unclassified 38,734 / org_fallback 20,012 /
semantic_embedding 10,007 / fuzzy_jigyou 333 / manual_correction 70 = **113,118**

## A-2.【高】Phase 9 手動判定12件が消失（後続 recompute による上書き）

**現象**: CLAUDE.md Phase 9（2026-05-09）で適用した大型案件の手動判定
（`mod_search` 4件 + `fuzzy_lowthreshold` 7件 + 関連1件、計1,782億円分）が、
現DBの contract_requesting_org に**存在しない**。match_source 別集計に
mod_search / fuzzy_lowthreshold が無く、fallback_atla が1,752件残っている。
後続の `recompute_atla_requesting_org.py` 実行が fallback_atla として
上書きしたと推定される（同スクリプトは手動 match_source を保護しない）。

**検出SQL**:
```sql
SELECT match_source, COUNT(*) FROM contract_requesting_org
GROUP BY 1 ORDER BY 2 DESC;  -- mod_search / fuzzy_lowthreshold が0件
```

**推奨修正**:
1. `kit/exports/manual_overrides_natural.json` の `fallback_50oku_apply`（12件、
   自然キー+根拠文字列つき）から再適用する（`dev/apply_fallback_50oku.py` は
   rowid 直書きのため、現DBの id とズレている可能性がある。必ず自然キーで突合すること）
2. 再発防止: `recompute_atla_requesting_org.py` に「手動系 match_source
   （manual_analysis / mod_search / mod_research / fuzzy_lowthreshold / kenkyuu_hyouka /
   jigyou_review）は上書きしない」ガードを追加する

## A-3.【高】bid_method の表記ゆれ・理由文混入・NULL

**現象**（件数は修復済みコピー実測）:

| 値 | 件数 | 問題 |
|---|---:|---|
| 一般競争入札 | 75,359 | 正 |
| 随意契約 | 49,588 | 正 |
| NULL | 25,782 | 16.6% |
| 指名競争入札 | 3,278 | 正（少数） |
| 一般 | 454 | 「一般競争入札」に正規化すべき |
| 〃（同上記号） | 193 | 上行の値を引き継げていないパース漏れ |
| 総合評価落札方式 | 172 | 入札方式とは別軸（一般競争のサブ型） |
| 一般契約 / 一般 競争 入札 / 一般入札 等 | 約110 | スペース・改行混入 |
| 会計法第29条の3第1項 / 技術的適合性…等 | 約60 | **随契理由文が混入**（zuii_reason に移すべき） |
| 市場価格方式 / オープンカウンタ / − 等 | 約30 | 個別判断 |

**検出SQL**:
```sql
SELECT bid_method, COUNT(*) FROM contracts GROUP BY 1 ORDER BY 2 DESC LIMIT 40;
SELECT COUNT(*) FROM contracts WHERE bid_method LIKE '%会計法%';
```

**推奨修正**: 正規化マッピング（例: `replace(replace(bid_method,' ',''),char(10),'')` で
空白除去 → {一般→一般競争入札, 〃→直前行継承は不可能なのでNULL, 会計法%→随意契約
（原文はzuii_reasonへ）}）を UPDATE で適用。元値を保持したい場合は
`bid_method_raw` 列を追加してから正規化する。〃(193件)はソースExcel上の前行継承なので、
同一source_url内で直前の非〃値を引き継ぐ再パースが正攻法。

## A-4.【高】7本柱分類の未カバー45%

**現象**:

| FY | contracts | pillar行あり | うちunclassified | 実質分類済み |
|---|---:|---:|---:|---:|
| 2022 | 31,248 | **0** | — | 0% |
| 2023 | 43,558 | 40,440 | 13,551 | 61.7% |
| 2024 | 45,271 | 41,599 | 14,485 | 59.9% |
| 2025 | 34,986 | 31,079 | 10,698 | 58.2% |

FY2022 は分類パイプライン自体が未適用（Phase 13–17 は FY2023–2025 のみ対象）。
また FY2023–2025 にも pillar 行が無い契約が計7,697件ある（分類実行後に追加収集された行）。

**検出SQL**:
```sql
SELECT c.fiscal_year, COUNT(*),
       SUM(CASE WHEN p.contract_id IS NULL THEN 1 ELSE 0 END) AS no_pillar,
       SUM(CASE WHEN p.match_method='unclassified' THEN 1 ELSE 0 END) AS unclassified
FROM contracts c LEFT JOIN contract_pillar p ON p.contract_id = c.id
GROUP BY 1;
```

**推奨修正**: ①A-1修復後に `python dev/assign_pillar_fy2023.py --fy 2022` を実行
（7本柱は2023年度開始の整備計画概念だが、キーワードルール自体はFY2022契約にも適用可能。
「FY2022は計画期間外」として比較対象から外す設計判断もあり — その場合はダッシュボード側で
明示）。②FY2023–2025 の pillar 行なし7,697件は同スクリプトの再実行で取り込まれる。
③unclassified 38,734件の削減は GPU 環境でのセマンティック再実行
（`dev/assign_pillar_semantic.py`）か、KEYWORD_RULES の追加で対応。

## A-5.【高】vendor_name の表記ゆれ

**現象**: 法人格表記が3系統混在 — 株式会社 77,444 / ㈱ 28,282 / （株） 10,125。
同一企業が別名で集計され、ベンダー別ランキング・依存度分析を歪める。
ほかに「落札者未記載：海自地方総監部の艦艇等維持整備」5,670件（既知・回収不能、
CLAUDE.md 2026-05-06 記録）、NULL 6,712件（msdf_asd が4,670件と突出）。

**検出SQL**:
```sql
SELECT SUM(vendor_name LIKE '%株式会社%'), SUM(vendor_name LIKE '%㈱%'),
       SUM(vendor_name LIKE '%（株）%') FROM contracts;
```

**推奨修正**: 元値は変更せず **`vendor_name_norm` 列を追加**して正規化値を持つ
（NFKC正規化 → ㈱/（株）→株式会社 → 前後空白除去 → 全半角統一）。
ダッシュボードのベンダー集計を norm 列に切り替える。
NULL の補完は不可能（原本Excelに値が無いことを2026-05-06に実証済み）なので対象外。

## B-1.【中】corporate_number の欠損・形式不正

- NULL 16,395件（10.6%）、13桁でない値 3,034件
- 検出SQL: `SELECT COUNT(*) FROM contracts WHERE corporate_number IS NOT NULL AND corporate_number NOT GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'`
- 推奨: 形式不正はNULL化。欠損補完は gBizINFO / 国税庁法人番号API と
  vendor_name_norm（A-5）の突合で可能（外部API利用なので別途判断）

## B-2.【中】award_rate 欠損 55.9%

- NULL 86,678件。ただし再計算可能（contract_amount と estimated_price が両方あるのに
  award_rate が無い）のは**わずか362件** — estimated_price 自体が86,880件NULLのため
- 検出SQL: `SELECT COUNT(*) FROM contracts WHERE award_rate IS NULL AND contract_amount > 0 AND estimated_price > 0`
- 推奨: 362件は `UPDATE ... SET award_rate = ROUND(1.0*contract_amount/estimated_price, 4)` で補完。
  残りは原本に予定価格非公表（単価契約・随契等）であり補完不能 — 「欠損が正」と
  ドキュメント化する方が誠実

## B-3.【中】category_small 実質未実装

- 97.1%（150,506件）NULL。category_large 22.2% / category_mid 25.7% NULL
- 推奨: 利用予定が無ければ列ごと廃止（schema変更）か、7本柱分類（contract_pillar）に
  役割を一本化したと明記。中途半端な状態が一番誤解を生む

## B-4.【中】enrichment テーブルの孤児行

- contract_requesting_org に878件、contract_equipment に99件、親の contracts 行が
  存在しない孤児行がある（過去の重複削除で親だけ消えた残骸）
- 検出SQL: `SELECT COUNT(*) FROM contract_requesting_org t LEFT JOIN contracts c ON c.id=t.contract_id WHERE c.id IS NULL`
- 推奨: DELETE で除去し、今後は `PRAGMA foreign_keys=ON` + FOREIGN KEY 制約付きで
  テーブルを再作成（schema_full.sql 更新）

## C-1.【低】金額異常値

- 負値1件: id=139663（nids「防雑誌U/S品(その1)」-13円、2024-04-01）→ 原本PDF確認のうえ修正/NULL化
- 1〜100円: 77件（うち1円31件）→ 単価契約の単価が紛れた可能性。個別確認リスト化を推奨
- 検出SQL: `SELECT id, agency_id, contract_name, contract_amount FROM contracts WHERE contract_amount <= 100 ORDER BY contract_amount`

## C-2.【低】contract_date NULL 1,361件

- FY別では2022年度1.2% → 2025年度0.5%と改善傾向。fiscal_year はURL等から補完済みのため
  集計への実害は小さい。原本に日付が無いものが大半で、能動的修正は不要

## C-3.【低】contract_requesting_org 未カバー 3,871件

- contracts の2.5%に要求元判定が無い（判定パイプライン実行後に追加収集された行）
- 推奨: A-2のガード追加後に `dev/recompute_atla_requesting_org.py` を再実行

## D-1.【構造】手動修正の rowid 依存

**現象**: `data/manual/manual_corrections_snapshot.json`（83件）と
`dev/apply_fallback_50oku.py` の APPLY リスト（12件）が contracts の rowid をキーに
している。rowid は再構築・重複削除のたびにズレるため、**再現不能な記録形式**
（A-2 の消失もこの構造が遠因）。

**推奨修正**: 手動判定は今後、拡張自然キー
（agency_id, fiscal_year, contract_name, vendor_name, contract_amount,
contract_date, bid_method, source_url）で記録する。
既存分は `kit/exports/manual_overrides_natural.json` に自然キー変換済み
（export_kit_data.py が生成・全件解決済み）なので、これを正本として運用に乗せる。

---

## 修正作業の推奨順序（Sonnet向け）

1. **A-1 修復**（`kit/repair_contract_pillar.py --in-place`）— 他の全作業の前提
2. B-4 孤児行 DELETE（軽い・独立）
3. A-2 手動判定12件の再適用 + recompute ガード追加
4. A-3 bid_method 正規化（マッピング表を作って一括UPDATE）
5. A-5 vendor_name_norm 列追加 + ダッシュボード切替
6. A-4 FY2022 分類実行 + FY2023–2025 再実行
7. B-1/B-2/C-1 の小粒修正
8. 完了後に `python kit/export_kit_data.py` を再実行してキットの exports を更新すること
   （エクスポートは修正前のDB状態を反映しているため）
