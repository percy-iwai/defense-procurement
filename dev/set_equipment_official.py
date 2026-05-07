"""equipment_master.ref_url_official に防衛省公式装備品ページを設定。

クロール元（2026-05-07時点）:
- ASDF: https://www.mod.go.jp/asdf/equipment/  → 機種別ディレクトリ（/sentouki/F-35/ 等）
- MSDF: https://www.mod.go.jp/msdf/equipment/  → /ships/, /aircraft/, /rotorcraft/ ディレクトリ
- GSDF: https://www.mod.go.jp/gsdf/equipment/  → カテゴリ単位（/fire/, /air/ 等）
        ※GSDFは単一ページ＋モーダルUIのため、カテゴリページが最も特定的なURL

joint_* やシステム系装備品の多くは個別公式ページが存在しないため None のまま。
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'db' / 'procurement.db'

OFFICIAL_URLS: dict[str, str] = {
    # ── ASDF (個別ページあり) ─────────────────────────────────────
    'asdf_f35a':       'https://www.mod.go.jp/asdf/equipment/sentouki/F-35/',
    'asdf_f15jdj':     'https://www.mod.go.jp/asdf/equipment/sentouki/F-15/',
    'asdf_f2ab':       'https://www.mod.go.jp/asdf/equipment/sentouki/F-2/',
    'asdf_e767':       'https://www.mod.go.jp/asdf/equipment/keikaiki/E-767/',
    'asdf_e2c':        'https://www.mod.go.jp/asdf/equipment/keikaiki/E-2C/',
    'asdf_e2d':        'https://www.mod.go.jp/asdf/equipment/keikaiki/E-2C/',  # E-2D解説はE-2Cページにある（同系列）
    'asdf_c2':         'https://www.mod.go.jp/asdf/equipment/yusouki/C-2/',
    'asdf_c1':         'https://www.mod.go.jp/asdf/equipment/yusouki/C-1/',
    'asdf_c130h':      'https://www.mod.go.jp/asdf/equipment/yusouki/C-130H/',
    'asdf_kc130h':     'https://www.mod.go.jp/asdf/equipment/yusouki/C-130H/',  # KC-130HはC-130系列
    'asdf_kc767':      'https://www.mod.go.jp/asdf/equipment/yusouki/KC-767/',
    'asdf_kc46a':      'https://www.mod.go.jp/asdf/equipment/kc-46a.html',
    'asdf_ch47j':      'https://www.mod.go.jp/asdf/equipment/yusouki/CH-47J/',
    'asdf_uh60j':      'https://www.mod.go.jp/asdf/equipment/kyuunanki/UH-60J/',
    'asdf_rq4b':       'https://www.mod.go.jp/asdf/equipment/globalhawk/RQ-4B_Globalhawk/',
    'asdf_pac3':       'https://www.mod.go.jp/asdf/equipment/other/Patriot/',
    'asdf_basic_sam':  'https://www.mod.go.jp/asdf/equipment/other/yuudoudan/',
    'asdf_aim120':     'https://www.mod.go.jp/asdf/equipment/other/yuudoudan/',
    'asdf_aim9x':      'https://www.mod.go.jp/asdf/equipment/other/yuudoudan/',
    'asdf_jsm':        'https://www.mod.go.jp/asdf/equipment/other/yuudoudan/',
    'asdf_jnaam':      'https://www.mod.go.jp/asdf/equipment/other/yuudoudan/',
    # ASDFの汎用カテゴリ（個別ページなしの装備）
    'asdf_jfps3':      'https://www.mod.go.jp/asdf/equipment/',
    'asdf_jfps5':      'https://www.mod.go.jp/asdf/equipment/',
    'asdf_jtps102a':   'https://www.mod.go.jp/asdf/equipment/',
    'asdf_jupx111':    'https://www.mod.go.jp/asdf/equipment/',
    'asdf_tacan':      'https://www.mod.go.jp/asdf/equipment/',
    'asdf_914e':       'https://www.mod.go.jp/asdf/equipment/yusouki/KC-767/',  # KC-767の給油システム
    'asdf_rc2':        'https://www.mod.go.jp/asdf/equipment/yusouki/C-2/',     # C-2派生
    'asdf_ec2':        'https://www.mod.go.jp/asdf/equipment/yusouki/C-2/',     # C-2派生（電子戦機）
    'asdf_ashk':       'https://www.mod.go.jp/asdf/equipment/',
    'asdf_kijou_dempa':'https://www.mod.go.jp/asdf/equipment/',
    'asdf_uav_attritable': 'https://www.mod.go.jp/asdf/equipment/globalhawk/RQ-4B_Globalhawk/',
    'asdf_cloud_c2':   'https://www.mod.go.jp/asdf/equipment/',
    'asdf_gcap':       'https://www.mod.go.jp/asdf/equipment/sentouki/F-2/',     # F-2後継

    # ── MSDF (個別ページあり) ─────────────────────────────────────
    'msdf_p1':         'https://www.mod.go.jp/msdf/equipment/aircraft/patrol/p-1/',
    'msdf_p3c':        'https://www.mod.go.jp/msdf/equipment/aircraft/patrol/p-3c/',
    'msdf_us2':        'https://www.mod.go.jp/msdf/equipment/aircraft/rescue/us-2/',
    'msdf_sh60j':      'https://www.mod.go.jp/msdf/equipment/rotorcraft/patrol/sh60j/',
    'msdf_sh60k':      'https://www.mod.go.jp/msdf/equipment/rotorcraft/patrol/sh60k/',
    'msdf_sh60l':      'https://www.mod.go.jp/msdf/equipment/rotorcraft/patrol/sh60k/',  # SH-60Lは後継
    'msdf_mch101':     'https://www.mod.go.jp/msdf/equipment/rotorcraft/ms-t/mch-101/',
    # 艦艇カテゴリ
    'msdf_cat_destroyer':    'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_cat_submarine':    'https://www.mod.go.jp/msdf/equipment/ships/index3.html',
    'msdf_cat_auxiliary':    'https://www.mod.go.jp/msdf/equipment/ships/index2.html',
    'msdf_cat_mine_warfare': 'https://www.mod.go.jp/msdf/equipment/ships/index2.html',
    'msdf_cat_patrol':       'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_cat_transport':    'https://www.mod.go.jp/msdf/equipment/ships/index2.html',
    # MSDF艦載・戦闘システム（個別ページなし、ships/ が最特定）
    'msdf_aegis_ship':   'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_aos_ship':     'https://www.mod.go.jp/msdf/equipment/ships/index4.html',  # 音響測定艦は支援船扱い
    'msdf_opy2':         'https://www.mod.go.jp/msdf/equipment/ships/ffm/mogami/',  # もがみ型搭載
    'msdf_oqr5':         'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_ozz5':         'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_ozz100':       'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_nolq3':        'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_slq32':        'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_20mm_ciws':    'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_vls_mk41':     'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_07vla':        'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_12torpedo':    'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_17ssm':        'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_23sam':        'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_97torpedo':    'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_tomahawk':     'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_seasparrow':   'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_sm3':          'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_sm6':          'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_railgun':      'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_taiken_bogo':  'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_lrasm':        'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_usv':          'https://www.mod.go.jp/msdf/equipment/ships/',
    'msdf_logistics':    'https://www.mod.go.jp/msdf/equipment/',
    'msdf_maccs':        'https://www.mod.go.jp/msdf/equipment/',

    # ── GSDF (カテゴリ単位) ───────────────────────────────────────
    # 火器・弾薬
    'gsdf_03sam_kai':         'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_11sam':             'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_12ssm_kai':         'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_91sam':             'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_20rifle':           'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_hgv':               'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_cat_arty':          'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_cat_heavy_mortar':  'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_cat_portable_sam':  'https://www.mod.go.jp/gsdf/equipment/fire/',
    'gsdf_cat_ssm_regiment':  'https://www.mod.go.jp/gsdf/equipment/fire/',
    # 車両
    'gsdf_cat_armored':       'https://www.mod.go.jp/gsdf/equipment/ve/',
    'gsdf_cat_tank':          'https://www.mod.go.jp/gsdf/equipment/ve/',
    # 航空機
    'gsdf_ah1s':              'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_ah64d':             'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_ch47jja':           'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_lr2':               'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_oh1':               'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_uh1j':              'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_uh2':               'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_uh60ja':            'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_v22':               'https://www.mod.go.jp/gsdf/equipment/air/',
    'gsdf_cat_combat_aircraft':'https://www.mod.go.jp/gsdf/equipment/air/',
    # 通信・電子器材
    'gsdf_adccs':             'https://www.mod.go.jp/gsdf/equipment/ce/',
    'gsdf_fccs':              'https://www.mod.go.jp/gsdf/equipment/ce/',
    'gsdf_idou_dempa':        'https://www.mod.go.jp/gsdf/equipment/ce/',
    'gsdf_jasq2':             'https://www.mod.go.jp/gsdf/equipment/ce/',
    'gsdf_wbml_radio':        'https://www.mod.go.jp/gsdf/equipment/ce/',
    'gsdf_yagai_comm':        'https://www.mod.go.jp/gsdf/equipment/ce/',

    # ── joint_* (個別公式ページ少。一部にユーザー指定URL) ───────
    'joint_xband_kirameki':   'https://www.mod.go.jp/asdf/equipment/',
}


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    n = 0
    for eid, url in OFFICIAL_URLS.items():
        cur.execute(
            'UPDATE equipment_master SET ref_url_official = ? WHERE equipment_id = ?',
            (url, eid),
        )
        n += cur.rowcount
    con.commit()
    cur.execute('SELECT COUNT(*) FROM equipment_master WHERE ref_url_official IS NOT NULL')
    print(f'rows updated: {n}, total with ref_url_official: {cur.fetchone()[0]}/{con.execute("SELECT COUNT(*) FROM equipment_master").fetchone()[0]}')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
