"""FY2023 7本柱別集計 + FY2023予算比較"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

MAIN_DB = "data/db/procurement.db"
PILLAR_DB = "data/db/defense_pillar.db"

# FY2023 令和5年度単年予算額（契約ベース）
# 出典: 防衛省「令和5年度予算の概要」(2023-03-28) 各柱見出し「約X兆X,XXX億円（含む他分野）」
# ※ 「含む他分野」= 他の柱との重複事業を含む見出し金額（公称予算）
# ※ P83 のみ p62 物件費費目別「基地対策経費等」参考値
# ※ P84 は費目別「維持費等30,375億」の一部で算出困難 → 0（別途集計の対象外）
# ※ P85 は p49「米軍再編6,090億 + SACO152億 = 6,242億」
BUDGET_L2 = {
    1:  14207,  # P1 スタンドオフ防衛能力         約1兆4,207億円  (p12)
    2:   9867,  # P2 統合防空ミサイル防衛能力      約9,867億円     (p14)
    3:   1827,  # P3 無人アセット防衛能力          約1,827億円     (p17)
    41:  1844,  # P41 宇宙                        約1,844億円     (p20)
    42:  2643,  # P42 サイバー                    約2,643億円     (p21)
    43: 11763,  # P43 車両・艦船・航空機等          約1兆1,763億円  (p24)
    5:   4588,  # P5 指揮統制・情報関連機能         約4,588億円     (p29)
    6:   2696,  # P6 機動展開能力・国民保護         約2,696億円     (p30)
    71:  8283,  # P71 弾薬・誘導弾                約8,283億円     (p31, スタンドオフ・統合防空弾薬を含む)
    72: 20355,  # P72 装備品等の維持整備費          約2兆355億円    (p32)
    73:  5049,  # P73 施設の強靱化                約5,049億円     (p33)
    81:  1463,  # P81 防衛生産基盤の強化           約1,463億円     (p36)
    82:  8968,  # P82 研究開発                    約8,968億円     (p38)
    83:  5122,  # P83 基地対策                    5,122億円       (p62 費目別参考)
    84:     0,  # P84 教育訓練費・燃料費等          費目別算出困難（維持費等30,375億に内包）
    85:  6242,  # P85 米軍再編関係経費等            6,242億円       (p49 米軍再編6,090+SACO152)
}
BUDGET_L1 = {
    1: BUDGET_L2[1],
    2: BUDGET_L2[2],
    3: BUDGET_L2[3],
    4: BUDGET_L2[41] + BUDGET_L2[42] + BUDGET_L2[43],   # 16,250億
    5: BUDGET_L2[5],
    6: BUDGET_L2[6],
    7: BUDGET_L2[71] + BUDGET_L2[72] + BUDGET_L2[73],   # 33,687億
    8: BUDGET_L2[81] + BUDGET_L2[82] + BUDGET_L2[83] + BUDGET_L2[85],  # P84除く
}

conn = sqlite3.connect(MAIN_DB)
conn.execute(f"ATTACH DATABASE '{PILLAR_DB}' AS pillar")
cur = conn.cursor()

# ======================================================
# 1. L1別集計
# ======================================================
sql_l1 = """
SELECT
    cp.pillar_l1_code,
    pm.name AS l1_name,
    COUNT(*) AS cnt,
    ROUND(SUM(c.contract_amount) / 1e8, 1) AS amount_oku,
    ROUND(SUM(c.estimated_price) / 1e8, 1) AS est_oku
FROM contract_pillar cp
JOIN contracts c ON c.id = cp.contract_id
LEFT JOIN pillar.defense_pillar_master pm
    ON pm.pillar_id = cp.pillar_l1_code AND pm.level = 1
WHERE cp.fiscal_year = 2023
  AND cp.pillar_l1_code IS NOT NULL
GROUP BY cp.pillar_l1_code
ORDER BY cp.pillar_l1_code
"""
cur.execute(sql_l1)
l1_rows = cur.fetchall()

# ======================================================
# 2. L2別集計
# ======================================================
sql_l2 = """
SELECT
    cp.pillar_l1_code,
    l1.name AS l1_name,
    cp.pillar_l2_code,
    l2.name AS l2_name,
    COUNT(*) AS cnt,
    ROUND(SUM(c.contract_amount) / 1e8, 1) AS amount_oku,
    ROUND(SUM(c.estimated_price) / 1e8, 1) AS est_oku
FROM contract_pillar cp
JOIN contracts c ON c.id = cp.contract_id
LEFT JOIN pillar.defense_pillar_master l1
    ON l1.pillar_id = cp.pillar_l1_code AND l1.level = 1
LEFT JOIN pillar.defense_pillar_master l2
    ON l2.pillar_id = cp.pillar_l2_code AND l2.level = 2
WHERE cp.fiscal_year = 2023
  AND cp.pillar_l1_code IS NOT NULL
GROUP BY cp.pillar_l1_code, cp.pillar_l2_code
ORDER BY cp.pillar_l1_code, cp.pillar_l2_code
"""
cur.execute(sql_l2)
l2_rows = cur.fetchall()

# unclassified
cur.execute("""
SELECT COUNT(*),
       ROUND(SUM(c.contract_amount)/1e8,1),
       ROUND(SUM(c.estimated_price)/1e8,1)
FROM contract_pillar cp
JOIN contracts c ON c.id=cp.contract_id
WHERE cp.fiscal_year=2023 AND cp.pillar_l1_code IS NULL
""")
uc = cur.fetchone()
uc_cnt, uc_amt, uc_est = uc[0], uc[1] or 0, uc[2] or 0

# FY2023 全contracts
cur.execute("SELECT COUNT(*), ROUND(SUM(contract_amount)/1e8,1) FROM contracts WHERE fiscal_year=2023")
all_c = cur.fetchone()

conn.close()

SEP = "=" * 74
SEP2 = "-" * 74

# ======================================================
# 出力: L1別サマリ（件数・金額のみ）
# ======================================================
print(SEP)
print("  FY2023（令和5年度）7本柱 大項目(L1)別 調達実績集計")
print("  ※ contract_pillar テーブル fiscal_year=2023 の全レコードを対象")
print(SEP)
print(f"  {'コード':<6} {'名称':<24} {'件数':>7} {'契約額(億円)':>12} {'予定価格(億円)':>14}")
print(SEP2)

tot_cnt = tot_amt = tot_est = 0
l1_dict = {}
for row in l1_rows:
    code, name, cnt, amt, est = row
    amt = amt or 0; est = est or 0
    label = name or "—"
    print(f"  P{code:<5} {label:<24} {cnt:>7,}  {amt:>12,.1f}  {est:>14,.1f}")
    tot_cnt += cnt; tot_amt += amt; tot_est += est
    l1_dict[code] = (name, cnt, amt, est)

print(SEP2)
print(f"  {'分類済み計':<30} {tot_cnt:>7,}  {tot_amt:>12,.1f}  {tot_est:>14,.1f}")
print(f"  {'未分類（unclassified）':<30} {uc_cnt:>7,}  {uc_amt:>12,.1f}  {uc_est:>14,.1f}")
grand_cnt = tot_cnt + uc_cnt
grand_amt = tot_amt + uc_amt
grand_est = tot_est + uc_est
print(SEP)
print(f"  {'contract_pillar 合計':<30} {grand_cnt:>7,}  {grand_amt:>12,.1f}  {grand_est:>14,.1f}")
print(f"  {'（FY2023全contracts件数）':<30} {all_c[0]:>7,}  {(all_c[1] or 0):>12,.1f}")
print()

# ======================================================
# 出力: L1別 予算比較表
# ======================================================
print(SEP)
print("  FY2023 大項目(L1)別 予算vs集計 比較表")
print("  出典: 防衛省「令和5年度予算の概要」2023-03-28 各柱見出し金額（含む他分野）")
print("  ※ 予算額は「約X兆X,XXX億円（他分野を除くとX,XXX億円）」表記の含む他分野値")
print("  ※ P8は P84(教育訓練費等)を除く。P4・P7は重複計上込みのため合計が大きい")
print("  ※ カバレッジ = DB契約額 ÷ 予算額（含む他分野）")
print(SEP)
print(f"  {'柱':<6} {'名称':<24} {'DB集計(億)':>11} {'予算額(億)':>11} {'カバレッジ':>10}  備考")
print(SEP2)

for code in sorted(l1_dict.keys()):
    name, cnt, amt, est = l1_dict[code]
    name = name or "—"
    bgt = BUDGET_L1.get(code, 0)
    bgt_str = f"{bgt:>11,}" if bgt else f"{'—':>11}"
    if bgt > 0:
        ratio = amt / bgt * 100
        ratio_str = f"{ratio:>9.1f}%"
        flag = "  ⚠ 予算超過" if ratio > 120 else ("  ↓ 低カバレッジ" if ratio < 50 else "")
    else:
        ratio_str = f"{'—':>10}"; flag = ""
    print(f"  P{code:<5} {name:<24} {amt:>11,.1f} {bgt_str} {ratio_str}{flag}")

print(SEP2)
bgt_total = sum(BUDGET_L1.values())
print(f"  {'分類済み計（P1-P8）':<30} {tot_amt:>11,.1f} {bgt_total:>11,} {tot_amt/bgt_total*100:>9.1f}%")
print(f"  {'未分類':<30} {uc_amt:>11,.1f}")
print(f"  {'DB合計（分類済＋未分類）':<30} {grand_amt:>11,.1f}")
print()
print(f"  DB合計（FY2023 contracts）: {all_c[0]:,}件 / {all_c[1] or 0:,.1f}億円")
print(f"  物件費（契約ベース）: 89,525億（R5予算 p62、SACO・米軍再編除く）")
print(f"  全体カバレッジ（DB合計/89,525億）: {(all_c[1] or 0)/89525*100:.1f}%")
print(f"  ※ 各柱予算は「含む他分野」のため合計 > 89,525億（重複計上あり）")
print()

# ======================================================
# 出力: L2別 予算比較表
# ======================================================
print(SEP)
print("  FY2023 中項目(L2)別 予算vs集計 比較表")
print("  ※ P71は「スタンドオフ・統合防空弾薬を除く弾薬」が他分野除く値。DB分類とズレあり")
print("  ※ P84予算は費目別から算出困難のため予算列「—」")
print(SEP)
print(f"  {'コード':<8} {'名称':<28} {'DB集計(億)':>11} {'予算額(億)':>11} {'カバレッジ':>10}")
print(SEP2)

prev_l1 = None
for row in l2_rows:
    l1c, l1n, l2c, l2n, cnt, amt, est = row
    amt = amt or 0
    if l1c != prev_l1:
        if prev_l1 is not None:
            print()
        print(f"  ▌P{l1c} {l1n or ''}:")
        prev_l1 = l1c
    if l2c is None:
        code_str = f"P{l1c}（親）"
        label = "（サブ分類なし）"
        bgt = 0
    else:
        code_str = f"P{l2c}"
        label = l2n or ""
        bgt = BUDGET_L2.get(l2c, 0)
    bgt_str = f"{bgt:>11,}" if bgt else f"{'—':>11}"
    if bgt > 0:
        ratio = amt / bgt * 100
        ratio_str = f"{ratio:>9.1f}%"
        flag = " ⚠" if ratio > 120 else ("  ↓" if ratio < 40 else "")
    else:
        ratio_str = f"{'—':>10}"; flag = ""
    print(f"     {code_str:<8} {label:<28} {amt:>11,.1f} {bgt_str} {ratio_str}{flag}")
print()

# ======================================================
# 出力: match_method別内訳
# ======================================================
conn2 = sqlite3.connect(MAIN_DB)
cur2 = conn2.cursor()
cur2.execute("""
SELECT match_method, COUNT(*), ROUND(SUM(c.contract_amount)/1e8,1)
FROM contract_pillar cp JOIN contracts c ON c.id=cp.contract_id
WHERE cp.fiscal_year=2023 AND cp.pillar_l1_code IS NOT NULL
GROUP BY match_method ORDER BY COUNT(*) DESC
""")
mm_rows = cur2.fetchall()
conn2.close()

print(SEP)
print("  FY2023 分類根拠（match_method）別内訳")
print(SEP)
print(f"  {'match_method':<30} {'件数':>7} {'契約額(億円)':>12}")
print(SEP2)
for r in mm_rows:
    mm, cnt, amt = r
    print(f"  {(mm or 'NULL'):<30} {cnt:>7,}  {(amt or 0):>12,.1f}")
print()
