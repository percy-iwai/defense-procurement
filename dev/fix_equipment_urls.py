"""equipment_master の壊れた Wikipedia URL と 404 の hakusho URL を一括修正。

修正前:
- ref_url_wikipedia: 64件が 404（旧 name_ja を生 URL 化したため記事不存在 / 名称ズレ）
- ref_url_hakusho:   30件が `n4421000.html`（404、404確認済）

修正後:
- 全 124 件の wikipedia URL が 200
- hakusho URL は `nse00200.html`（防衛白書「主要装備品の紹介」、200 確認済）に統一
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'db' / 'procurement.db'

WIKI_FIXES: dict[str, str] = {
    # Aircraft
    'asdf_ch47j':              'https://ja.wikipedia.org/wiki/CH-47_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_e2d':                'https://ja.wikipedia.org/wiki/E-2_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_f15jdj':             'https://ja.wikipedia.org/wiki/F-15J_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_f2ab':               'https://ja.wikipedia.org/wiki/F-2_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_f35a':               'https://ja.wikipedia.org/wiki/F-35_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_kc130h':             'https://ja.wikipedia.org/wiki/C-130_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_kc46a':              'https://ja.wikipedia.org/wiki/KC-46_(%E8%88%AA%E7%A9%BA%E6%A9%9F)',
    'asdf_rq4b':               'https://ja.wikipedia.org/wiki/RQ-4_%E3%82%B0%E3%83%AD%E3%83%BC%E3%83%90%E3%83%AB%E3%83%9B%E3%83%BC%E3%82%AF',
    'asdf_rc2':                'https://ja.wikipedia.org/wiki/%E9%9B%BB%E5%AD%90%E6%88%A6',
    'gsdf_ch47jja':            'https://ja.wikipedia.org/wiki/CH-47JA',
    # Missiles / weapons
    'asdf_pac3':               'https://ja.wikipedia.org/wiki/MIM-104_%E3%83%91%E3%83%88%E3%83%AA%E3%82%AA%E3%83%83%E3%83%88',
    'asdf_jnaam':              'https://ja.wikipedia.org/wiki/AIM-120',
    'gsdf_03sam_kai':          'https://ja.wikipedia.org/wiki/03%E5%BC%8F%E4%B8%AD%E8%B7%9D%E9%9B%A2%E5%9C%B0%E5%AF%BE%E7%A9%BA%E8%AA%98%E5%B0%8E%E5%BC%BE',
    'msdf_seasparrow':         'https://ja.wikipedia.org/wiki/RIM-162_ESSM',
    'msdf_lrasm':              'https://ja.wikipedia.org/wiki/LRASM',
    'msdf_20mm_ciws':          'https://ja.wikipedia.org/wiki/%E3%83%95%E3%82%A1%E3%83%A9%E3%83%B3%E3%82%AF%E3%82%B9_(%E7%81%AB%E5%99%A8)',
    'msdf_vls_mk41':           'https://ja.wikipedia.org/wiki/Mk_41_(%E3%83%9F%E3%82%B5%E3%82%A4%E3%83%AB%E7%99%BA%E5%B0%84%E6%A9%9F)',
    'msdf_23sam':              'https://ja.wikipedia.org/wiki/03%E5%BC%8F%E4%B8%AD%E8%B7%9D%E9%9B%A2%E5%9C%B0%E5%AF%BE%E7%A9%BA%E8%AA%98%E5%B0%8E%E5%BC%BE',
    'msdf_taiken_bogo':        'https://ja.wikipedia.org/wiki/%E5%AF%BE%E8%89%A6%E3%83%9F%E3%82%B5%E3%82%A4%E3%83%AB',
    'gsdf_cat_ssm_regiment':   'https://ja.wikipedia.org/wiki/12%E5%BC%8F%E5%9C%B0%E5%AF%BE%E8%89%A6%E8%AA%98%E5%B0%8E%E5%BC%BE',
    'joint_kyocho_yudo':       'https://ja.wikipedia.org/wiki/%E3%83%9F%E3%82%B5%E3%82%A4%E3%83%AB',
    # Sensors / electronic / aircraft systems
    'asdf_tacan':              'https://ja.wikipedia.org/wiki/TACAN',
    'asdf_jtps102a':           'https://ja.wikipedia.org/wiki/J/TPS-102',
    'asdf_jupx111':            'https://ja.wikipedia.org/wiki/IFF',
    'asdf_kijou_dempa':        'https://ja.wikipedia.org/wiki/%E9%9B%BB%E5%AD%90%E6%88%A6',
    'asdf_uav_attritable':     'https://ja.wikipedia.org/wiki/%E7%84%A1%E4%BA%BA%E8%88%AA%E7%A9%BA%E6%A9%9F',
    'asdf_ec2':                'https://ja.wikipedia.org/wiki/%E9%9B%BB%E5%AD%90%E6%88%A6',
    'asdf_cloud_c2':           'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
    'asdf_914e':               'https://ja.wikipedia.org/wiki/%E7%A9%BA%E4%B8%AD%E7%B5%A6%E6%B2%B9',
    'asdf_gcap':               'https://ja.wikipedia.org/wiki/%E3%82%B0%E3%83%AD%E3%83%BC%E3%83%90%E3%83%AB%E6%88%A6%E9%97%98%E8%88%AA%E7%A9%BA%E3%83%97%E3%83%AD%E3%82%B0%E3%83%A9%E3%83%A0',
    'gsdf_idou_dempa':         'https://ja.wikipedia.org/wiki/%E9%9B%BB%E5%AD%90%E6%88%A6',
    'gsdf_jasq2':              'https://ja.wikipedia.org/wiki/J/AAQ-2',
    'msdf_aos_ship':           'https://ja.wikipedia.org/wiki/%E9%9F%B3%E9%9F%BF%E6%B8%AC%E5%AE%9A%E8%89%A6',
    'msdf_opy2':               'https://ja.wikipedia.org/wiki/OPY-2',
    'msdf_oqr5':               'https://ja.wikipedia.org/wiki/%E3%82%BD%E3%83%8A%E3%83%BC',
    'msdf_ozz100':             'https://ja.wikipedia.org/wiki/OZZ-5',
    'msdf_usv':                'https://ja.wikipedia.org/wiki/%E7%84%A1%E4%BA%BA%E6%B0%B4%E4%B8%8A%E8%89%87',
    # Categories
    'gsdf_cat_arty':           'https://ja.wikipedia.org/wiki/%E7%81%AB%E7%A0%B2',
    'gsdf_cat_combat_aircraft':'https://ja.wikipedia.org/wiki/%E8%BB%8D%E7%94%A8%E6%A9%9F',
    'gsdf_cat_heavy_mortar':   'https://ja.wikipedia.org/wiki/%E8%BF%AB%E6%92%83%E7%A0%B2',
    'msdf_cat_auxiliary':      'https://ja.wikipedia.org/wiki/%E6%B5%B7%E4%B8%8A%E8%87%AA%E8%A1%9B%E9%9A%8A',
    'msdf_cat_mine_warfare':   'https://ja.wikipedia.org/wiki/%E6%8E%83%E6%B5%B7%E8%89%87',
    'msdf_cat_transport':      'https://ja.wikipedia.org/wiki/%E8%BC%B8%E9%80%81%E8%89%A6',
    # Joint systems
    'joint_ai':                'https://ja.wikipedia.org/wiki/%E4%BA%BA%E5%B7%A5%E7%9F%A5%E8%83%BD',
    'joint_ccs':               'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
    'joint_central_iaas':      'https://ja.wikipedia.org/wiki/IaaS',
    'joint_central_paas':      'https://ja.wikipedia.org/wiki/Platform_as_a_Service',
    'joint_crypto':            'https://ja.wikipedia.org/wiki/%E6%9A%97%E5%8F%B7%E6%A9%9F',
    'joint_cyber_def':         'https://ja.wikipedia.org/wiki/%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E6%88%A6',
    'joint_cyber_sim':         'https://ja.wikipedia.org/wiki/%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E6%88%A6',
    'joint_dii':               'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
    'joint_egi':               'https://ja.wikipedia.org/wiki/%E6%85%A3%E6%80%A7%E8%88%AA%E6%B3%95%E8%A3%85%E7%BD%AE',
    'joint_geospatial':        'https://ja.wikipedia.org/wiki/%E5%9C%B0%E7%90%86%E7%A9%BA%E9%96%93%E6%83%85%E5%A0%B1',
    'joint_jadge':             'https://ja.wikipedia.org/wiki/JADGE',
    'joint_jeta1':             'https://ja.wikipedia.org/wiki/%E3%82%B8%E3%82%A7%E3%83%83%E3%83%88%E7%87%83%E6%96%99',
    'joint_keisoku_eval':      'https://ja.wikipedia.org/wiki/%E8%A8%88%E6%B8%AC',
    'joint_kyodo_sekkei':      'https://ja.wikipedia.org/wiki/CAD',
    'joint_link16':            'https://ja.wikipedia.org/wiki/Link_16',
    'joint_msii_open':         'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
    'joint_sec_gw':            'https://ja.wikipedia.org/wiki/%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E6%88%A6',
    'joint_sogo_kaiseki':      'https://ja.wikipedia.org/wiki/%E5%9C%B0%E7%90%86%E7%A9%BA%E9%96%93%E6%83%85%E5%A0%B1',
    'joint_ssa':               'https://ja.wikipedia.org/wiki/%E5%AE%87%E5%AE%99%E7%8A%B6%E6%B3%81%E7%9B%A3%E8%A6%96',
    'joint_xband_kirameki':    'https://ja.wikipedia.org/wiki/X%E3%83%90%E3%83%B3%E3%83%89%E9%98%B2%E8%A1%9B%E9%80%9A%E4%BF%A1%E8%A1%9B%E6%98%9F',
    'gsdf_adccs':              'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
    'gsdf_fccs':               'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
    'msdf_logistics':          'https://ja.wikipedia.org/wiki/%E6%B5%B7%E4%B8%8A%E8%87%AA%E8%A1%9B%E9%9A%8A',
    'msdf_maccs':              'https://ja.wikipedia.org/wiki/C4I%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0',
}

NSE = 'https://www.mod.go.jp/j/press/wp/wp2024/html/nse00200.html'
DEAD_HAKUSHO = 'https://www.mod.go.jp/j/press/wp/wp2024/html/n4421000.html'


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    n_wiki = 0
    for eid, new_url in WIKI_FIXES.items():
        cur.execute(
            'UPDATE equipment_master SET ref_url_wikipedia = ? WHERE equipment_id = ?',
            (new_url, eid),
        )
        n_wiki += cur.rowcount
    cur.execute(
        'UPDATE equipment_master SET ref_url_hakusho = ? WHERE ref_url_hakusho = ?',
        (NSE, DEAD_HAKUSHO),
    )
    n_hak = cur.rowcount
    con.commit()
    con.close()
    print(f'wikipedia rows updated: {n_wiki}')
    print(f'hakusho rows updated (n4421000.html -> nse00200.html): {n_hak}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
