"""Reclassify P4/P7 parent records into sub-pillar mid-level categories.

P4 → P41(宇宙) / P42(サイバー) / P43(車両艦船航空機等)
P7 → P71(弾薬・誘導弾) / P72(装備品等の維持整備費) / P73(施設の強靱化)

Unmappable records remain at parent pillar_id.
"""
import sqlite3
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
DB_REAL = ROOT / "data" / "db" / "defense_pillar.db"
DB_TMP  = Path(r"C:\Users\Percy Iwai\AppData\Local\Temp") / "defense_pillar_reclassify.db"

# ── pillar_id → pillar_name mapping (from defense_pillar_master) ──────────
PILLAR_NAME = {
    41: "宇宙",
    42: "サイバー",
    43: "車両、艦船、航空機等",
    71: "弾薬・誘導弾",
    72: "装備品等の維持、整備費",
    73: "施設の強靱化",
}

# ── row id → new pillar_id mappings ──────────────────────────────────────
# P4 → P41 (Space domain: SSA, HGV detection/tracking, space imagery)
P4_TO_P41 = [
    3,    # ＳＳＡシステム等の整備
    4,    # ＨＧＶ（※）探知・追尾の実証に係る調査研究
    5,    # 高感度広帯域な赤外線検知素子の研究 (HGV/BMD sensing component)
    185,  # 画像解析用データの取得 (FY2023)
    404,  # 画像解析用データの取得 (FY2024)
    619,  # ＨＧＶ対処に関する技術の向上を企図した技術検討
    621,  # 画像解析用データの取得 (FY2025)
]

# P4 → P42 (Cyber/EM domain: cyber defense, cloud, EW, directed energy, C2 systems)
P4_TO_P42 = [
    17,   # システムネットワーク管理機能の整備
    24,   # 高出力マイクロ波（ＨＰＭ）照射技術の実証
    25,   # 高出力レーザーシステムの研究
    30,   # 戦術データリンクの整備
    33,   # 中央指揮システムの換装
    35,   # 自動警戒管制システム（ＪＡＤＧＥ）の能力向上
    193,  # システムネットワーク管理機能（SNMS）の整備
    406,  # 「ゼロトラスト」概念の導入
    407,  # クラウドの整備
    409,  # スレットハンティング器材の整備
    418,  # 低電力通信妨害技術の研究
    424,  # 電子作戦機の開発 (FY2024)
    425,  # 高出力レーザーに関する研究
    426,  # 高出力マイクロ波(ＨＰＭ)に関する研究 (FY2024)
    623,  # 防衛省クラウド(仮称)基盤の整備
    625,  # スレットハンティング器材の整備 (FY2025)
    636,  # 電子作戦機の開発 (FY2025)
    637,  # 艦載用レーザーシステムの研究
    639,  # 高出力マイクロ波(ＨＰＭ)に関する研究 (FY2025)
]

# P4 → P43 (Vehicles, ships, aircraft: platforms and their equipment)
P4_TO_P43 = [
    27,   # 多用機用センサーシステムの搭載に関する調査研究
    36,   # 滞空型ＵＡＶ（※）の試験的運用
    37,   # 艦載型ＵＡＶ（小型）に関する研究
    39,   # 掃海艦の建造 (FY2022)
    40,   # 海洋観測艦の建造
    41,   # 音響測定艦の建造
    45,   # ０３式中距離地対空誘導弾（改善型）の取得
    48,   # 戦闘支援無人機コンセプトの検討
    118,  # 雑音低減型水中発射管の研究
    209,  # ２０式５．５６ｍｍ小銃 (FY2023)
    210,  # 除染セット
    211,  # 戦闘装着セット (FY2023)
    215,  # 哨戒艦の建造
    217,  # 支援船の建造・取得
    218,  # ＵＰ－３Ｄの能力向上
    220,  # 艦齢延伸措置
    221,  # 機齢延伸措置
    222,  # 垂直発射装置ＶＬＳ ＭＫ４１の整備
    223,  # 可変深度ソーナーシステムの整備
    224,  # ソノブイの整備
    428,  # 共通戦術装輪車(歩兵戦闘車)の取得
    429,  # 共通戦術装輪車(機動迫撃砲)の取得
    432,  # １９式装輪自走１５５ｍｍりゅう弾砲の取得
    434,  # 水際障害処理装置
    435,  # ２０式５．５６ｍｍ小銃 (FY2024)
    436,  # 戦闘装着セット (FY2024)
    439,  # 新型補給艦の建造
    440,  # 掃海艦の建造 (FY2024)
    641,  # ２４式装輪装甲戦闘車
    642,  # ２４式機動１２０mm迫撃砲
    643,  # 共通戦術装輪車 (FY2025)
    645,  # １９式装輪自走１５５ｍｍりゅう弾砲 (FY2025)
    652,  # 救難飛行艇(ＵＳ－２)の取得
    654,  # 次期初等練習機(Ｔ－６)及び地上教育器材の取得
    655,  # ２０式５．５６ｍｍ小銃 (FY2025)
]

# P7 → P71 (Ammunition and guided missiles)
P7_TO_P71 = [
    241,  # 155mm榴弾砲弾
    245,  # １５式機雷
]

# P7 → P72 (Equipment maintenance and sustainment management)
P7_TO_P72 = [
    125,  # プロジェクト管理の質的向上
    126,  # ＦＭＳ調達の履行管理
    129,  # 防衛調達における情報セキュリティの強化
]

# P7 → P73 (Facility resilience: natural disaster, base security, runway recovery)
P7_TO_P73 = [
    79,   # 基地警備における監視機能強化に関する実証
    247,  # 滑走路等被害復旧の能力向上に必要な器材の取得
    253,  # 津波・浸水等の自然災害対策
    465,  # 自然災害対策 (FY2024)
    694,  # 自然災害対策 (FY2025)
    701,  # 新たなドローン対処器材の導入 (base protection = facility resilience)
]

# Remain at parent:
#   P4: [9]諸外国との国際協力, [34]日米指揮所訓練, [411]陸自高等工科学校,
#       [416][629]防衛装備品等の生産基盤強化のための体制整備事業,
#       [647]地対艦誘導弾射撃訓練基盤の整備
#   P7: [130]防衛産業のＤＸ調査研究


def build_updates():
    updates = []
    for row_id in P4_TO_P41:
        updates.append((41, PILLAR_NAME[41], row_id))
    for row_id in P4_TO_P42:
        updates.append((42, PILLAR_NAME[42], row_id))
    for row_id in P4_TO_P43:
        updates.append((43, PILLAR_NAME[43], row_id))
    for row_id in P7_TO_P71:
        updates.append((71, PILLAR_NAME[71], row_id))
    for row_id in P7_TO_P72:
        updates.append((72, PILLAR_NAME[72], row_id))
    for row_id in P7_TO_P73:
        updates.append((73, PILLAR_NAME[73], row_id))
    return updates


def run(dry_run: bool = False):
    if not dry_run:
        shutil.copy2(DB_REAL, DB_TMP)
        print(f"Copied {DB_REAL.name} → {DB_TMP.name}")

    conn = sqlite3.connect(DB_TMP if not dry_run else DB_REAL)
    if dry_run:
        conn.execute("BEGIN")  # read-only preview — will rollback

    updates = build_updates()
    print(f"\nTotal updates to apply: {len(updates)}")

    changed = 0
    for new_pid, new_pname, row_id in updates:
        if dry_run:
            row = conn.execute(
                "SELECT pillar_id, jigyou_name, fiscal_year FROM defense_pillar_jigyou WHERE id=?",
                (row_id,)
            ).fetchone()
            if row:
                print(f"  [{row_id:>4}] P{row[0]} → P{new_pid}  FY{row[2]} {row[1]!r}")
        else:
            conn.execute(
                "UPDATE defense_pillar_jigyou SET pillar_id=?, pillar_name=? WHERE id=?",
                (new_pid, new_pname, row_id)
            )
            changed += 1

    if dry_run:
        conn.rollback()
        conn.close()
        return

    conn.commit()

    print(f"\nUpdated {changed} rows")
    print("\n=== Updated pillar distribution ===")
    dist = conn.execute("""
        SELECT pillar_id, pillar_name, COUNT(*) as n
        FROM defense_pillar_jigyou
        GROUP BY pillar_id ORDER BY pillar_id
    """).fetchall()
    for r in dist:
        print(f"  P{r[0]:>3}: {r[1][:35]:35s} n={r[2]}")

    print("\n=== Remaining P4 ===")
    for r in conn.execute(
        "SELECT id, jigyou_name, fiscal_year FROM defense_pillar_jigyou WHERE pillar_id=4"
    ):
        print(f"  [{r[0]}] FY{r[2]} {r[1]!r}")

    print("\n=== Remaining P7 ===")
    for r in conn.execute(
        "SELECT id, jigyou_name, fiscal_year FROM defense_pillar_jigyou WHERE pillar_id=7"
    ):
        print(f"  [{r[0]}] FY{r[2]} {r[1]!r}")

    conn.close()

    # copy back to real DB
    shutil.copy2(DB_TMP, DB_REAL)
    print(f"\nCopied back: {DB_TMP.name} → {DB_REAL.name}")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN ===")
    run(dry_run=dry)
