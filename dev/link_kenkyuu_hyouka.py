"""
equipment_master の各装備品に kenkyuu_hyouka テーブルの政策評価書 PDF URL を
ref_url_hakusho として紐付けるスクリプト。

Usage:
  python dev/link_kenkyuu_hyouka.py --dry-run   # マッチ候補を表示のみ（デフォルト）
  python dev/link_kenkyuu_hyouka.py --apply     # DBに書き込み
"""
import sqlite3
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROC_DB = ROOT / "data/db/procurement.db"

# equipment_id → kenkyuu_hyouka.jigyou_name の部分一致キーワード
# 最新FY優先で1件を選択し pdf_url を ref_url_hakusho に設定する
MANUAL_MAP = {
    "gsdf_12ssm_kai": "12式地対艦誘導弾",
    "gsdf_hgv":       "高速滑空弾の要素技術",
    "asdf_jnaam":     "次期中距離空対空誘導弾",
    "msdf_railgun":   "将来レールガンの研究",
    "joint_hcm":      "極超音速誘導弾要素技術",
    "joint_gpi":      "GPIの共同開発",
    "asdf_gcap":      "次期戦闘機と連携する無人機",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = args.apply

    conn = sqlite3.connect(PROC_DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT equipment_id, name_ja, ref_url_hakusho FROM equipment_master ORDER BY branch, equipment_id"
    )
    equipment = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    matched = []
    for eq_id, kw in MANUAL_MAP.items():
        cur.execute(
            "SELECT jigyou_name, tantou_org, fiscal_year, pdf_url "
            "FROM kenkyuu_hyouka WHERE jigyou_name LIKE ? ORDER BY fiscal_year DESC LIMIT 1",
            (f"%{kw}%",),
        )
        r = cur.fetchone()
        if not r:
            print(f"  [MISS] {eq_id}: '{kw}' が kenkyuu_hyouka に見つからない")
            continue
        jigyou_name, org, fy, pdf_url = r
        name_ja, existing_url = equipment.get(eq_id, ("?", None))
        matched.append((eq_id, name_ja, jigyou_name, org, fy, pdf_url, existing_url))

    print(f"マッチ: {len(matched)} 件\n")
    print("=== マッチ一覧 ===")
    for eq_id, name_ja, jigyou_name, org, fy, pdf_url, existing_url in matched:
        skip = existing_url is not None
        flag = " [SKIP: 既存あり]" if skip else ""
        url_type = (
            "soumu" if "soumu.go.jp" in pdf_url
            else "mod/hyouka" if "mod.go.jp/j/approach" in pdf_url
            else "WARP"
        )
        print(f"  {eq_id:<30} [{url_type} FY{fy}]{flag}")
        print(f"    {jigyou_name}")
        print(f"    {pdf_url[:90]}")

    if apply:
        print("\n=== DB更新 ===")
        updated = 0
        for eq_id, name_ja, jigyou_name, org, fy, pdf_url, existing_url in matched:
            if existing_url is not None:
                print(f"  SKIP {eq_id}: ref_url_hakusho 既存あり")
                continue
            cur.execute(
                "UPDATE equipment_master SET ref_url_hakusho = ? WHERE equipment_id = ?",
                (pdf_url, eq_id),
            )
            if cur.rowcount > 0:
                print(f"  SET  {eq_id}: {pdf_url[:70]}")
                updated += 1
        conn.commit()
        print(f"\n更新完了: {updated} 件")
    else:
        print("\n（--apply を指定するとDBに書き込まれます）")

    conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
