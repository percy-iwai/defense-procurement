"""equipment_master 一括追加スクリプト（メインDB直接書き込み）。

使用法: python dev/insert_equipment_master.py
"""
from __future__ import annotations

import sqlite3
import urllib.parse
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "procurement.db"
HAKUSHO_URL = "https://www.mod.go.jp/j/press/wp/wp2024/html/nse00200.html"


def wiki_url(name_ja: str) -> str:
    return "https://ja.wikipedia.org/wiki/" + urllib.parse.quote(name_ja)


# (equipment_id, name_ja, branch, category, keywords)
ITEMS: list[tuple[str, str, str, str, str]] = [
    # === 誘導弾系 ===
    ("gsdf_12ssm_kai", "12式地対艦誘導弾能力向上型", "GSDF", "誘導弾",
     "12式地対艦,能力向上型,12SSM改"),
    ("gsdf_hgv", "島嶼防衛用高速滑空弾", "GSDF", "誘導弾",
     "高速滑空弾,島嶼防衛,HGV"),
    ("joint_hcm", "極超音速誘導弾", "JOINT", "誘導弾",
     "極超音速,HCM"),
    ("gsdf_03sam_kai", "03式中距離地対空誘導弾改善型", "GSDF", "誘導弾",
     "03式,中SAM,中距離地対空"),
    ("asdf_pac3", "PAC-3", "ASDF", "誘導弾",
     "PAC-3,ペトリオット,Patriot"),
    ("msdf_sm3", "SM-3", "MSDF", "誘導弾",
     "SM-3,SM3,スタンダードミサイル,ブロックIIA"),
    ("msdf_sm6", "SM-6", "MSDF", "誘導弾",
     "SM-6,SM6"),
    ("asdf_aim120", "AIM-120", "ASDF", "誘導弾",
     "AIM-120,AMRAAM"),
    ("asdf_aim9x", "AIM-9X", "ASDF", "誘導弾",
     "AIM-9X"),
    ("asdf_jsm", "JSM", "ASDF", "誘導弾",
     "JSM"),
    ("msdf_tomahawk", "トマホーク", "MSDF", "誘導弾",
     "トマホーク,Tomahawk"),
    ("msdf_17ssm", "17式艦対艦誘導弾", "MSDF", "誘導弾",
     "17式艦対艦,SSM-2"),
    ("gsdf_11sam", "11式短距離地対空誘導弾", "GSDF", "誘導弾",
     "11式短距離地対空,短SAM"),
    ("asdf_basic_sam", "基地防空用地対空誘導弾", "ASDF", "誘導弾",
     "基地防空用地対空"),
    ("gsdf_91sam", "91式携帯地対空誘導弾", "GSDF", "誘導弾",
     "91式携帯,携SAM"),

    # === 艦艇・航空機系 ===
    ("msdf_aegis_ship", "イージス・システム搭載艦", "MSDF", "艦艇",
     "イージス・システム搭載艦,イージスシステム搭載艦"),
    ("asdf_gcap", "次期戦闘機/GCAP", "ASDF", "航空機",
     "次期戦闘機,GCAP"),
    ("asdf_ec2", "スタンド・オフ電子戦機", "ASDF", "航空機",
     "スタンド・オフ電子戦機,EC-2"),

    # === その他装備 ===
    ("joint_jeta1", "航空タービン燃料Jet A-1", "JOINT", "燃料",
     "Jet A-1,航空タービン燃料,JetA-1"),
    ("gsdf_20rifle", "20式5.56mm小銃", "GSDF", "小火器",
     "20式5.56mm,20式小銃"),
    ("msdf_railgun", "レールガン", "MSDF", "兵装",
     "レールガン,将来レールガン"),
    ("msdf_12torpedo", "12式魚雷", "MSDF", "兵装",
     "12式魚雷,長魚雷"),
    ("msdf_97torpedo", "97式魚雷", "MSDF", "兵装",
     "97式魚雷,短魚雷"),
    ("msdf_07vla", "07式垂直発射魚雷投射ロケット", "MSDF", "兵装",
     "07式,VLA,魚雷投射ロケット"),
    ("msdf_ozz5", "OZZ-5", "MSDF", "無人機",
     "OZZ-5,水中無人機"),
    ("msdf_ozz100", "OZZ-100", "MSDF", "無人機",
     "OZZ-100"),
    ("msdf_20mm_ciws", "高性能20mm機関砲", "MSDF", "兵装",
     "高性能20mm機関砲,CIWS,ファランクス"),
    ("msdf_usv", "USV水上無人機", "MSDF", "無人機",
     "戦闘支援型多目的USV,水上無人機,USV"),

    # === 宇宙系 ===
    ("joint_constellation", "衛星コンステレーション", "JOINT", "宇宙",
     "衛星コンステレーション,コンステレーション"),
    ("joint_xband_kirameki", "Xバンド防衛通信衛星きらめき", "JOINT", "宇宙",
     "きらめき,Xバンド,防衛衛星通信,Superbird"),
    ("joint_ssa", "SSA衛星システム", "JOINT", "宇宙",
     "SSA衛星,宇宙状況監視,宇宙領域把握"),

    # === サイバー系 ===
    ("joint_cyber_sim", "サイバー総合模擬環境", "JOINT", "サイバー",
     "サイバー総合模擬環境,模擬環境"),
    ("joint_cyber_def", "サイバー防護分析装置", "JOINT", "サイバー",
     "サイバー防護分析,CYDEF,侵入検知"),

    # === 電子戦系 ===
    ("msdf_slq32", "AN/SLQ-32", "MSDF", "電子戦",
     "AN/SLQ-32,SLQ-32,電子戦装置"),
    ("msdf_nolq3", "NOLQ-3", "MSDF", "電子戦",
     "NOLQ-3,電波探知妨害"),
    ("gsdf_jasq2", "J/ASQ-2", "GSDF", "電子戦",
     "J/ASQ-2,統合電子戦装置"),

    # === 指揮統制・情報系 ===
    ("joint_dii", "防衛情報通信基盤DII", "JOINT", "C4ISR",
     "DII,防衛情報通信基盤,クローズ系"),
    ("gsdf_wbml_radio", "広帯域多目的無線機", "GSDF", "通信",
     "広帯域多目的無線機,SNMS,野外通信システム"),
    ("gsdf_yagai_comm", "野外通信システム", "GSDF", "通信",
     "野外通信システム"),
    ("joint_ccs", "中央指揮システムCCS", "JOINT", "C4ISR",
     "中央指揮システム,CCS"),
    ("asdf_cloud_c2", "空自クラウド指揮統制", "ASDF", "C4ISR",
     "クラウド指揮統制,クラウドシステム,宇宙作戦指揮統制"),
    ("msdf_maccs", "海上航空作戦指揮統制MACCS", "MSDF", "C4ISR",
     "MACCS,海上航空作戦指揮"),
    ("joint_dics", "DICS", "JOINT", "C4ISR",
     "DICS,情報本部共通基盤"),
    ("joint_link16", "戦術データリンクLink-16", "JOINT", "C4ISR",
     "Link-16,MIDS,JTIDS,戦術データリンク,MOS MOD"),
    ("joint_crypto", "暗号装置", "JOINT", "C4ISR",
     "IP暗号,秘匿装置,YSC-27,GPS-C21"),
    ("joint_geospatial", "地理空間情報支援システム", "JOINT", "C4ISR",
     "地理空間情報,映像情報統合"),

    # === 統合防空ミサイル防衛系 ===
    ("msdf_vls_mk41", "VLS MK41", "MSDF", "IAMD",
     "VLS,MK41,垂直発射装置"),
    ("msdf_opy2", "多機能レーダOPY-2", "MSDF", "IAMD",
     "OPY-2,OYX-1,OYQ-32,多機能レーダ"),
    ("gsdf_adccs", "ADCCS", "GSDF", "IAMD",
     "ADCCS,対空戦闘指揮統制"),
    ("gsdf_fccs", "FCCS", "GSDF", "IAMD",
     "FCCS,火力戦闘指揮統制"),
    ("asdf_jtps102a", "J/TPS-102A", "ASDF", "IAMD",
     "J/TPS-102,移動式警戒監視"),
    ("asdf_jfps5", "J/FPS-5", "ASDF", "IAMD",
     "J/FPS-5,ガメラレーダ"),
    ("asdf_jfps3", "J/FPS-3", "ASDF", "IAMD",
     "J/FPS-3"),
    ("asdf_jupx111", "J/UPX-111", "ASDF", "IAMD",
     "J/UPX-111,味方識別"),

    # === センサー系 ===
    ("msdf_oqr5", "OQR-5えい航式ソーナー", "MSDF", "センサー",
     "OQR-5,OQR-4,OQR-2,えい航式,TASS"),
    ("msdf_aos_ship", "音響測定艦システム", "MSDF", "センサー",
     "音響測定艦"),

    # === 無人機系 ===
    ("asdf_uav_attritable", "UAVアトリタブル", "ASDF", "無人機",
     "アトリタブル,JDXS-H1,無人航空機"),

    # === 航法系 ===
    ("joint_ins", "慣性航法装置", "JOINT", "航法",
     "慣性航法,MEMS-HR,CN-1655,J/ASN-7"),
    ("joint_egi", "EGI統合航法装置", "JOINT", "航法",
     "EGI,J/ASN-12,GPS/INS"),
    ("asdf_tacan", "TACAN航法援助装置", "ASDF", "航法",
     "TACAN,ILS,VOR,DME,航法援助"),

    # === AI系 ===
    ("joint_ai", "AI技術（人工知能）", "JOINT", "AI",
     "人工知能,AI技術,機械学習,画像類識別"),
]


def main() -> int:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    before = cur.execute("SELECT COUNT(*) FROM equipment_master").fetchone()[0]
    print(f"[before] equipment_master rows: {before}")

    rows = [
        (
            eid,
            name_ja,
            None,                          # name_en
            branch,
            category,
            HAKUSHO_URL,                   # ref_url_hakusho
            None,                          # ref_url_official
            wiki_url(name_ja),             # ref_url_wikipedia
            keywords,
        )
        for (eid, name_ja, branch, category, keywords) in ITEMS
    ]

    cur.executemany(
        """
        INSERT OR REPLACE INTO equipment_master
            (equipment_id, name_ja, name_en, branch, category,
             ref_url_hakusho, ref_url_official, ref_url_wikipedia, keywords)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    con.commit()

    after = cur.execute("SELECT COUNT(*) FROM equipment_master").fetchone()[0]
    print(f"[after]  equipment_master rows: {after}")
    print(f"[diff]   inserted/replaced: {len(rows)}; net new: {after - before}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
