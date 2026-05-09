"""
equipment_master の各装備品と jigyou_review.db の事業を紐付け、
jigyou_review_id カラムに設定するスクリプト。

Usage:
  python dev/link_jigyou_review.py --dry-run   # マッチ候補を表示のみ
  python dev/link_jigyou_review.py --apply     # DBに書き込み
"""
import sqlite3
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROC_DB = ROOT / "data/db/procurement.db"
JR_DB   = ROOT / "data/db/jigyou_review.db"

# ──────────────────────────────────────────────
# 手動マッピング: equipment_id → jigyou_review.projects.name (最新FYを使用)
# ──────────────────────────────────────────────
MANUAL_MAP = {
    # ASDF 航空機
    "asdf_f35a":     "戦闘機（Ｆ-３５Ａ/Ｂ）の取得",
    "asdf_f15jdj":   "戦闘機（F-15）近代化改修/能力向上",
    "asdf_e2d":      "早期警戒機（Ｅ－２Ｄ）の取得",
    "asdf_ch47j":    "ＣＨ－４７Ｊの取得",
    "asdf_uh60j":    "救難ヘリコプター（UH-60J）の取得",
    "asdf_c2":       "次期輸送機(C-2)の取得",
    "asdf_kc46a":    "空中給油・輸送機（ＫＣ－４６Ａ）の取得",
    "asdf_rq4b":     "滞空型無人機等の取得（省統一）",
    # ASDF 誘導弾・システム
    "asdf_pac3":     "地対空誘導弾ﾍﾟﾄﾘｵｯﾄ",
    "asdf_basic_sam":"基地防空用地対空誘導弾（改）及び新近距離地対空誘導弾",
    "asdf_jnaam":    "次期中距離空対空誘導弾の開発",
    "asdf_jfps5":    "固定式警戒管制レーダー装置（ＦＰＳ－５）への機能付加",
    "asdf_gcap":     "次期戦闘機",
    "asdf_ec2":      "スタンド・オフ電子戦機",
    "asdf_rc2":      "電波情報収集機（RC-2）の取得",
    # GSDF
    "gsdf_v22":      "ティルト・ローター機（Ｖ－２２）の取得",
    "gsdf_ch47jja":  "輸送ヘリコプター（ＣＨ－４７ＪＡ）の取得",
    "gsdf_lr2":      "連絡偵察機（ＬＲ－２）の取得",
    "gsdf_12ssm_kai":"１２式地対艦誘導弾能力向上型（地発型・艦発型・空発型）の開発",
    "gsdf_03sam_kai":"０３式中距離地対空誘導弾（改善型）能力向上型の開発",
    "gsdf_hgv":      "島嶼防衛用高速滑空弾の取得",
    "gsdf_20rifle":  "２０式５．５６ｍｍ小銃",
    # MSDF
    "msdf_aegis_ship":"イージス・システム搭載艦の整備",
    "msdf_cat_destroyer":"護衛艦（ＦＦＭ）",
    "msdf_cat_mine_warfare":"掃海艦艇（ＭＳＯ、ＭＳＣ）",
    "msdf_cat_submarine":"潜水艦（ＳＳ）",
    "msdf_sh60k":    "哨戒ヘリコプター（ＳＨ－６０Ｋ）の取得",
    "msdf_sh60l":    "哨戒ヘリコプター（ＳＨ－６０Ｌ）の取得",
    "msdf_mch101":   "輸送ヘリコプター（ＭＣＨ－１０１の生産購入）",
    "msdf_p1":       "固定翼哨戒機（Ｐ－１）の取得",
    "msdf_us2":      "救難飛行艇（ＵＳ－２）の取得",
    "msdf_tomahawk": "トマホークの取得",
    "msdf_sm3":      "ＳＭ－３ブロックⅡＡ",
    "msdf_sm6":      "ＳＭ－６",
    "msdf_17ssm":    "島嶼防衛用新対艦誘導弾の研究",
    "msdf_ozz5":     "機雷捜索用ＵＵＶ（ＯＺＺ－５）の整備",
    "msdf_23sam":    "新艦対空誘導弾（能力向上型）",
    "msdf_railgun":  "将来レールガンの研究",
    "msdf_aos_ship": "音響測定艦（ＡＯＳ）",
    "msdf_cat_patrol":"哨戒艦",
    # JOINT
    "joint_gpi":     "ＧＰＩの日米共同開発",
    "joint_jadge":   "自動警戒管制組織の弾道ﾐｻｲﾙ対処機能(BMD)\n自動警戒管制組織の航空警戒管制機能の近代化",
    "joint_ssa":     "宇宙領域把握（ＳＤＡ）の強化",
    "joint_hcm":     "極超音速誘導弾の研究",
    "joint_dii":     "防衛情報通信基盤（DII)の整備",
    "joint_sec_gw":  "防衛セキュリティゲートウェイの整備",
    "joint_cyber_def":"サイバー防護分析装置の整備",
    "joint_constellation": "衛星コンステレーションによるＨＧＶ探知・追尾システムの概念検討",
    "joint_xband_kirameki": "Ｋｕバンド衛星通信用経費",  # 近似
    # 追加
    "asdf_f2ab":    "Ｆ－２能力向上改修",
    "gsdf_uh2":     "多用途ヘリコプターの取得",
}

# JADGE は2行に結合されているので別処理
JADGE_NAME = "自動警戒管制組織の弾道ﾐｻｲﾙ対処機能(BMD)\n自動警戒管制組織の航空警戒管制機能の近代化"


def get_projects(jr_conn):
    """jigyou_review.db から全プロジェクト (id, name, fiscal_year) を取得。
    同名事業は最新FYのものを優先。"""
    cur = jr_conn.cursor()
    cur.execute("""
        SELECT id, name, fiscal_year
        FROM projects
        ORDER BY fiscal_year DESC
    """)
    rows = cur.fetchall()
    # name → (id, fy) の最新FY優先マップ
    name_to_id = {}
    for pid, name, fy in rows:
        if name not in name_to_id:
            name_to_id[name] = (pid, fy)
    return name_to_id  # {name: (id, fy)}


def find_by_name(name_to_id, target_name):
    """完全一致で検索。見つからなければ None。"""
    # 完全一致
    if target_name in name_to_id:
        return name_to_id[target_name]
    # 前後スペース除去・全角空白正規化
    target_norm = target_name.strip().replace("　", " ")
    for name, val in name_to_id.items():
        if name.strip().replace("　", " ") == target_norm:
            return val
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="マッチ候補を表示のみ（デフォルト）")
    parser.add_argument("--apply", action="store_true",
                        help="DBに書き込む")
    args = parser.parse_args()
    apply = args.apply

    jr_conn = sqlite3.connect(JR_DB)
    proc_conn = sqlite3.connect(PROC_DB)

    name_to_id = get_projects(jr_conn)
    print(f"jigyou_review プロジェクト: {len(name_to_id)} 件")

    cur = proc_conn.cursor()
    cur.execute("SELECT equipment_id, name_ja, jigyou_review_id FROM equipment_master ORDER BY branch, equipment_id")
    equipment = cur.fetchall()
    print(f"equipment_master: {len(equipment)} 件\n")

    matched = []
    not_matched = []

    for eq_id, name_ja, existing_id in equipment:
        target = MANUAL_MAP.get(eq_id)
        if target:
            result = find_by_name(name_to_id, target)
            if result:
                pid, fy = result
                matched.append((eq_id, name_ja, pid, fy, target))
            else:
                print(f"  [MAP MISS] {eq_id}: '{target}' が jigyou_review に見つからない")
                not_matched.append(eq_id)
        else:
            not_matched.append(eq_id)

    print(f"マッチ: {len(matched)} 件 / 未マッチ: {len(not_matched)} 件\n")
    print("=== マッチ一覧 ===")
    for eq_id, name_ja, pid, fy, proj_name in matched:
        print(f"  {eq_id:<30} FY{fy}  {proj_name[:40]}")
        print(f"    -> id={pid}")

    if not_matched:
        print(f"\n=== 未マッチ ({len(not_matched)} 件) ===")
        for eq_id in not_matched:
            print(f"  {eq_id}")

    if apply:
        print("\n=== DB更新 ===")
        updated = 0
        for eq_id, name_ja, pid, fy, proj_name in matched:
            cur.execute(
                "UPDATE equipment_master SET jigyou_review_id = ? WHERE equipment_id = ?",
                (pid, eq_id)
            )
            if cur.rowcount > 0:
                updated += 1
        proc_conn.commit()
        print(f"更新完了: {updated} 件")
    else:
        print("\n（--apply を指定するとDBに書き込まれます）")

    jr_conn.close()
    proc_conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
