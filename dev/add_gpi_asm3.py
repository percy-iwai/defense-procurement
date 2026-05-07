"""GPI と ASM-3(改) の equipment_master エントリを追加。

ユーザー提供URL:
- GPI（滑空段階迎撃用誘導弾）: https://www.mod.go.jp/j/approach/anpo/2024/1101_usa-j.html
  → 日米共同開発のため joint_gpi として追加
- ASM-3(改): https://warp.ndl.go.jp/web/.../jizen_03_honbun.pdf
  → F-2搭載ASMだが現存エントリと重複しないため asdf_asm3 として追加
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'db' / 'procurement.db'

NEW_ROWS = [
    {
        'equipment_id': 'joint_gpi',
        'name_ja': '滑空段階迎撃用誘導弾GPI',
        'name_en': 'Glide Phase Interceptor (GPI)',
        'branch': 'JOINT',
        'category': 'ミサイル防衛',
        'ref_url_hakusho': None,
        'ref_url_official': 'https://www.mod.go.jp/j/approach/anpo/2024/1101_usa-j.html',
        'ref_url_wikipedia': 'https://ja.wikipedia.org/wiki/SM-3',
        'keywords': 'GPI,滑空段階迎撃,Glide Phase Interceptor,日米共同開発,極超音速対処',
    },
    {
        'equipment_id': 'asdf_asm3',
        'name_ja': 'ASM-3（改）空対艦誘導弾',
        'name_en': 'ASM-3 (Kai)',
        'branch': 'ASDF',
        'category': '誘導弾',
        'ref_url_hakusho': 'https://warp.ndl.go.jp/web/20201210084638/www.mod.go.jp/j/approach/hyouka/seisaku/31/pdf/jizen_03_honbun.pdf',
        'ref_url_official': 'https://www.mod.go.jp/asdf/equipment/sentouki/F-2/',
        'ref_url_wikipedia': 'https://ja.wikipedia.org/wiki/ASM-3',
        'keywords': 'ASM-3,空対艦誘導弾,F-2,改',
    },
]


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    n = 0
    for row in NEW_ROWS:
        cur.execute(
            """INSERT OR REPLACE INTO equipment_master
               (equipment_id, name_ja, name_en, branch, category,
                ref_url_hakusho, ref_url_official, ref_url_wikipedia, keywords)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (row['equipment_id'], row['name_ja'], row['name_en'],
             row['branch'], row['category'],
             row['ref_url_hakusho'], row['ref_url_official'], row['ref_url_wikipedia'],
             row['keywords']),
        )
        n += cur.rowcount
    con.commit()
    cur.execute('SELECT COUNT(*) FROM equipment_master')
    print(f'rows inserted: {n}, total equipment_master: {cur.fetchone()[0]}')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
