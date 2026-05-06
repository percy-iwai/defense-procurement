"""contracts テーブルに category_large/mid/small を追加し、url_matrix に site_url を追加する。

実行:
    python -m pipeline.setup_categories
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROC_DB   = PROJECT_ROOT / "data" / "db" / "procurement.db"
URL_DB    = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

# agency_id → (category_large, category_mid, category_small, site_url)
AGENCY_CATEGORIES: dict[str, tuple[str, str, str, str]] = {
    # 内部部局・統合幕僚監部・情報本部
    "naikyoku_kaikei": ("内部部局", "", "", "https://www.mod.go.jp/j/budget/chotatsu/naikyoku/keiyaku/index.html"),
    "js":              ("統合幕僚監部", "", "", "https://www.mod.go.jp/js/"),
    "dih":             ("情報本部", "", "", "https://www.mod.go.jp/dih/"),
    # 陸上自衛隊
    "hokubu_kaikei":    ("陸上自衛隊", "北部方面隊", "", "https://www.mod.go.jp/gsdf/nae/"),
    "gsdf_nadep":       ("陸上自衛隊", "北部方面隊", "", "https://www.mod.go.jp/gsdf/nae/"),
    "gsdf_hokubu":      ("陸上自衛隊", "北部方面隊", "", ""),
    "tohoku_kaikei":    ("陸上自衛隊", "東北方面隊", "", "https://www.mod.go.jp/gsdf/neae/"),
    "gsdf_neadep":      ("陸上自衛隊", "東北方面隊", "", "https://www.mod.go.jp/gsdf/neae/"),
    "gsdf_eafin":       ("陸上自衛隊", "東部方面隊", "", "https://www.mod.go.jp/gsdf/eae/"),
    "gsdf_eadep":       ("陸上自衛隊", "東部方面隊", "関東補給処", "https://www.mod.go.jp/gsdf/eae/"),
    "gsdf_eadep_matudo":("陸上自衛隊", "東部方面隊", "関東補給処松戸支処", "https://www.mod.go.jp/gsdf/eae/"),
    "gsdf_eadep_koga":  ("陸上自衛隊", "東部方面隊", "関東補給処古賀支処", "https://www.mod.go.jp/gsdf/eae/"),
    "gsdf_eadep_yooga": ("陸上自衛隊", "東部方面隊", "関東補給処用賀支処", "https://www.mod.go.jp/gsdf/eae/"),
    "gsdf_chubu":       ("陸上自衛隊", "中部方面隊", "", "https://www.mod.go.jp/gsdf/mae/"),
    "gsdf_madep":       ("陸上自衛隊", "中部方面隊", "関西補給処", "https://www.mod.go.jp/gsdf/mae/mafin/k/"),
    "gsdf_seibu":       ("陸上自衛隊", "西部方面隊", "", "https://www.mod.go.jp/gsdf/wae/"),
    "gsdf_cfin":        ("陸上自衛隊", "中央会計隊", "", "https://www.mod.go.jp/gsdf/dc/cfin/html/img/"),
    "gsdf_ctrans":      ("陸上自衛隊", "中央輸送隊", "", "https://www.mod.go.jp/gsdf/yokohama/hp2015/06bosyu/nyusatu/tekiseika/"),
    "gsdf_tercom":      ("陸上自衛隊", "教育訓練研究本部", "", "https://www.mod.go.jp/gsdf/tercom/proc4.html"),
    "gsdf_ocsh":        ("陸上自衛隊", "幹部候補生学校", "", "https://www.mod.go.jp/gsdf/ocsh/disclosure/"),
    "gsdf_fsh":         ("陸上自衛隊", "富士学校", "", "https://www.mod.go.jp/gsdf/fsh/fin/jouhoukouhyou.html"),
    "gsdf_aasch":       ("陸上自衛隊", "高射学校", "", "https://www.mod.go.jp/gsdf/aasch/"),
    "gsdf_akeno":       ("陸上自衛隊", "航空学校", "", "https://www.mod.go.jp/gsdf/akeno/html/fin/fin-koukai.html"),
    "gsdf_sigsch":      ("陸上自衛隊", "通信学校", "", "https://www.mod.go.jp/gsdf/sigsch/fin/jiyouhou.htm"),
    "gsdf_buki":        ("陸上自衛隊", "武器学校", "", "https://www.mod.go.jp/gsdf/ord_sch/07_fin/pdf/Joho/Buppin/"),
    "gsdf_kodaira":     ("陸上自衛隊", "小平学校", "", "https://www.mod.go.jp/gsdf/kodaira/keiyaku/koukoku.html"),
    "gsdf_eisei":       ("陸上自衛隊", "衛生学校", "", "https://www.mod.go.jp/gsdf/mss/document/fin/"),
    "gsdf_gmcc":        ("陸上自衛隊", "補給統制本部", "", "https://www.mod.go.jp/gsdf/gmcc/raising/hoto/hzyo/"),
    "gsdf_chosp":       ("陸上自衛隊", "自衛隊中央病院", "", "https://www.mod.go.jp/gsdf/chosp/fin/contents2.html"),
    "gsdf_jujyo":       ("陸上自衛隊", "什器（陸上）", "", ""),
    # 海上自衛隊
    "msdf_t2":       ("海上自衛隊", "補給本部", "", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/"),
    "msdf_yd":       ("海上自衛隊", "艦船補給処", "", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/"),
    "msdf_asd":      ("海上自衛隊", "航空補給処", "", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/"),
    "msdf_d0":       ("海上自衛隊", "大湊地区総監部", "", "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/"),
    "msdf_d1":       ("海上自衛隊", "大湊地区総監部", "函館基地隊", "https://www.mod.go.jp/msdf/bukei/d1/"),
    "msdf_dw":       ("海上自衛隊", "大湊地区総監部", "稚内基地分遣隊", "https://www.mod.go.jp/msdf/bukei/dw/"),
    "msdf_dy":       ("海上自衛隊", "大湊地区総監部", "余市防備隊本部", "https://www.mod.go.jp/msdf/bukei/dy/"),
    "msdf_y0":       ("海上自衛隊", "横須賀地方総監部", "", "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/"),
    "msdf_y2":       ("海上自衛隊", "横須賀地方総監部", "館山航空基地隊", "https://www.mod.go.jp/msdf/bukei/y2/"),
    "msdf_y3":       ("海上自衛隊", "横須賀地方総監部", "下総航空基地隊", "https://www.mod.go.jp/msdf/bukei/y3/"),
    "msdf_y6":       ("海上自衛隊", "横須賀地方総監部", "厚木航空基地隊", "https://www.mod.go.jp/msdf/bukei/y6/"),
    "msdf_yokosuka": ("海上自衛隊", "横須賀地方総監部", "", ""),
    "msdf_m0":       ("海上自衛隊", "舞鶴地方総監部", "", "https://www.mod.go.jp/msdf/bukei/m0/"),
    "msdf_maizuru":  ("海上自衛隊", "舞鶴地方総監部", "", ""),
    "msdf_k1":       ("海上自衛隊", "舞鶴地方総監部", "阪神基地隊", "https://www.mod.go.jp/msdf/bukei/k1/"),
    "msdf_k0":       ("海上自衛隊", "呉地方総監部", "", "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/"),
    "msdf_kure":     ("海上自衛隊", "呉地方総監部", "", ""),
    "msdf_k4":       ("海上自衛隊", "呉地方総監部", "岩国航空基地隊", "https://www.mod.go.jp/msdf/bukei/k4/"),
    "msdf_s1":       ("海上自衛隊", "呉地方総監部", "下関基地隊", "https://www.mod.go.jp/msdf/bukei/s1/"),
    "msdf_k2":       ("海上自衛隊", "呉地方総監部", "徳島航空基地隊", "https://www.mod.go.jp/msdf/bukei/k2/"),
    "msdf_k7":       ("海上自衛隊", "呉地方総監部", "第24航空隊", "https://www.mod.go.jp/msdf/bukei/k7/"),
    "msdf_s0":       ("海上自衛隊", "佐世保地方総監部", "", "https://www.mod.go.jp/msdf/bukei/s0/"),
    "msdf_sasebo":   ("海上自衛隊", "佐世保地方総監部", "", ""),
    "msdf_s2":       ("海上自衛隊", "佐世保地方総監部", "鹿屋航空基地隊", "https://www.mod.go.jp/msdf/bukei/s2/"),
    "msdf_s3":       ("海上自衛隊", "佐世保地方総監部", "大村航空基地隊", ""),
    "msdf_s4":       ("海上自衛隊", "佐世保地方総監部", "大村航空基地隊", "https://www.mod.go.jp/msdf/bukei/s4/"),
    "msdf_sa":       ("海上自衛隊", "佐世保地方総監部", "奄美基地分遣隊", "https://www.mod.go.jp/msdf/bukei/sa/"),
    "msdf_sk":       ("海上自衛隊", "佐世保地方総監部", "沖縄基地隊", "https://www.mod.go.jp/msdf/bukei/sk/"),
    "msdf_sn":       ("海上自衛隊", "佐世保地方総監部", "那覇航空基地隊", "https://www.mod.go.jp/msdf/bukei/sn/"),
    "msdf_st":       ("海上自衛隊", "佐世保地方総監部", "対馬防備隊本部", "https://www.mod.go.jp/msdf/bukei/st/"),
    # 航空自衛隊
    "asdf_2dep":       ("航空自衛隊", "岐阜基地（第2補給処）", "", "https://www.mod.go.jp/asdf/2dep/"),
    "asdf_gifu":       ("航空自衛隊", "岐阜基地（第2補給処）", "", "https://www.mod.go.jp/asdf/2dep/"),
    "asdf_3dep":       ("航空自衛隊", "入間基地（第3補給処）", "", "https://www.mod.go.jp/asdf/3dep/"),
    "asdf_4dep":       ("航空自衛隊", "入間基地（第4補給処）", "", "https://www.mod.go.jp/asdf/4dep/"),
    "asdf_iruma":      ("航空自衛隊", "入間基地（第4補給処）", "", "https://www.mod.go.jp/asdf/iruma/"),
    "asdf_kisarazu":   ("航空自衛隊", "木更津分屯基地", "", "https://www.mod.go.jp/asdf/kisarazu/"),
    "asdf_chitose":    ("航空自衛隊", "千歳基地", "", "https://www.mod.go.jp/asdf/chitose/"),
    "asdf_misawa":     ("航空自衛隊", "三沢基地", "", "https://www.mod.go.jp/asdf/misawa/"),
    "asdf_akita":      ("航空自衛隊", "秋田分屯基地", "", "https://www.mod.go.jp/asdf/akita/"),
    "asdf_matsushima": ("航空自衛隊", "松島基地", "", "https://www.mod.go.jp/asdf/matsushima/"),
    "asdf_niigata":    ("航空自衛隊", "新潟分屯基地", "", "https://www.mod.go.jp/asdf/niigata/"),
    "asdf_hyakuri":    ("航空自衛隊", "百里基地", "", "https://www.mod.go.jp/asdf/hyakuri/"),
    "asdf_ichigaya":   ("航空自衛隊", "市ヶ谷基地", "", "https://www.mod.go.jp/asdf/ichigaya/"),
    "asdf_meguro":     ("航空自衛隊", "目黒基地", "", "https://www.mod.go.jp/asdf/meguro/"),
    "asdf_fuchu":      ("航空自衛隊", "府中基地", "", "https://www.mod.go.jp/asdf/fuchu/"),
    "asdf_yokota":     ("航空自衛隊", "横田基地", "", "https://www.mod.go.jp/asdf/yokota/"),
    "asdf_kumagaya":   ("航空自衛隊", "熊谷基地", "", "https://www.mod.go.jp/asdf/kumagaya/"),
    "asdf_shizuhama":  ("航空自衛隊", "静浜基地", "", "https://www.mod.go.jp/asdf/shizuhama/"),
    "asdf_hamamatsu":  ("航空自衛隊", "浜松基地", "", "https://www.mod.go.jp/asdf/hamamatsu/"),
    "asdf_komaki":     ("航空自衛隊", "小牧基地", "", "https://www.mod.go.jp/asdf/komaki/"),
    "asdf_komatsu":    ("航空自衛隊", "小松基地", "", "https://www.mod.go.jp/asdf/komatsu/"),
    "asdf_nara":       ("航空自衛隊", "奈良基地", "", "https://www.mod.go.jp/asdf/nara/"),
    "asdf_miho":       ("航空自衛隊", "美保基地", "", "https://www.mod.go.jp/asdf/miho/"),
    "asdf_hofukita":   ("航空自衛隊", "防府北基地", "", "https://www.mod.go.jp/asdf/hofukita/"),
    "asdf_hofuminami": ("航空自衛隊", "防府南基地", "", "https://www.mod.go.jp/asdf/hofuminami/"),
    "asdf_tsuiki":     ("航空自衛隊", "築城基地", "", "https://www.mod.go.jp/asdf/tsuiki/"),
    "asdf_ashiya":     ("航空自衛隊", "芦屋基地", "", "https://www.mod.go.jp/asdf/ashiya/"),
    "asdf_kasuga":     ("航空自衛隊", "春日基地", "", "https://www.mod.go.jp/asdf/kasuga/"),
    "asdf_nyutabaru":  ("航空自衛隊", "新田原基地", "", "https://www.mod.go.jp/asdf/nyutabaru/"),
    # 地方防衛局
    "rdb_hokkaido": ("地方防衛局", "北海道防衛局", "", "https://www.mod.go.jp/rdb/hokkaido/keiyaku/keiyakujyoho_kouhyou/"),
    "rdb_tohoku":   ("地方防衛局", "東北防衛局", "", "https://www.mod.go.jp/rdb/tohoku/contract/result/keiyaku/index_46.html"),
    "rdb_n_kanto":  ("地方防衛局", "北関東防衛局", "", "https://www.mod.go.jp/rdb/n_kanto/tyoutatu/kekka/"),
    "rdb_s_kanto":  ("地方防衛局", "南関東防衛局", "", "https://www.mod.go.jp/rdb/s_kanto/"),
    "rdb_kinchu":   ("地方防衛局", "近畿中部防衛局", "", "https://www.mod.go.jp/rdb/kinchu/keiyaku/"),
    "rdb_tokai":    ("地方防衛局", "東海防衛支局", "", "https://www.mod.go.jp/rdb/tokai/"),
    "rdb_chushi":   ("地方防衛局", "中国四国防衛局", "", "https://www.mod.go.jp/rdb/chushi/contract/result/keiyakujyoukyou-main.html"),
    "rdb_kyushu":   ("地方防衛局", "九州防衛局", "", "https://www.mod.go.jp/rdb/kyushu/contract/announcement/index.html"),
    "rdb_okinawa":  ("地方防衛局", "沖縄防衛局", "", "https://www.mod.go.jp/rdb/okinawa/"),
    # 独立機関
    "nda":  ("防衛大学校", "", "", "https://www.mod.go.jp/nda/procurement/bidding_result/"),
    "nids": ("防衛研究所", "", "", "https://www.nids.mod.go.jp/"),
    "ndmc": ("防衛医科大学校", "", "", "https://www.ndmc.ac.jp/info/information/"),
    "igo":  ("防衛監察本部", "", "", "https://www.mod.go.jp/igo/"),
    # 防衛装備庁
    "atla":          ("防衛装備庁", "調達事業部（中央調達）", "", "https://www.mod.go.jp/atla/souhon/supply/jisseki/rakusatu/"),
    "atla_kanbo":    ("防衛装備庁", "長官官房会計官", "", "https://www.mod.go.jp/atla/data/info/ny_honbu/pdf_ichiran/"),
    "atla_koukuu":   ("防衛装備庁", "航空装備研究所", "", "https://www.mod.go.jp/atla/data/info/ny_koukuu/pdf_ichiran/"),
    "atla_riku":     ("防衛装備庁", "陸上装備研究所", "", "https://www.mod.go.jp/atla/data/info/ny_riku/pdf_ichiran/"),
    "atla_kantei":   ("防衛装備庁", "艦艇装備研究所", "", "https://www.mod.go.jp/atla/data/info/ny_kantei/pdf_ichiran/"),
    "atla_shinsedai":("防衛装備庁", "新世代装備研究所", "", "https://www.mod.go.jp/atla/data/info/ny_shinsedai/pdf_ichiran/"),
    "atla_disti":    ("防衛装備庁", "防衛イノベーション科学技術研究所", "", "https://www.mod.go.jp/atla/data/info/ny_disti/pdf_ichiran/"),
    "atla_chitose":  ("防衛装備庁", "千歳試験場", "", "https://www.mod.go.jp/atla/data/info/ny_chitose/pdf_ichiran/"),
    "atla_shimokita":("防衛装備庁", "下北試験場", "", "https://www.mod.go.jp/atla/data/info/ny_shimokita/pdf_ichiran/"),
    "atla_gifu":     ("防衛装備庁", "岐阜試験場", "", "https://www.mod.go.jp/atla/data/info/ny_gifu/pdf_ichiran/"),
}


def _add_column_if_missing(cur: sqlite3.Cursor, table: str, col: str, col_type: str = "TEXT") -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if col not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        return True
    return False


def setup_procurement_db() -> int:
    """contracts に category_large/mid/small を追加して一括 UPDATE。更新件数を返す。"""
    with sqlite3.connect(PROC_DB) as conn:
        cur = conn.cursor()
        added = []
        for col in ("category_large", "category_mid", "category_small"):
            if _add_column_if_missing(cur, "contracts", col):
                added.append(col)
        if added:
            logger.info(f"contracts: カラム追加 {added}")

        # インデックス追加（存在確認後）
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_contracts_cat_large'")
        if not cur.fetchone():
            cur.execute("CREATE INDEX idx_contracts_cat_large ON contracts(category_large)")
            logger.info("インデックス idx_contracts_cat_large 追加")

        conn.commit()

        # 一括 UPDATE
        total_updated = 0
        for agency_id, (cat_large, cat_mid, cat_small, _) in AGENCY_CATEGORIES.items():
            cur.execute(
                "UPDATE contracts SET category_large=?, category_mid=?, category_small=?"
                " WHERE agency_id=?",
                (cat_large or None, cat_mid or None, cat_small or None, agency_id),
            )
            total_updated += cur.rowcount
        conn.commit()

    logger.info(f"contracts UPDATE: {total_updated:,} 件")
    return total_updated


def setup_url_matrix_db() -> int:
    """url_matrix に site_url と site_url_YYYY_MM カラムを追加して site_url を UPDATE。"""
    if not URL_DB.exists():
        logger.warning(f"{URL_DB} が存在しません。スキップ。")
        return 0

    with sqlite3.connect(URL_DB) as conn:
        cur = conn.cursor()
        cols_added = []
        for col in ("site_url", "site_url_2025_07", "site_url_2024_07", "site_url_2023_07"):
            if _add_column_if_missing(cur, "url_matrix", col):
                cols_added.append(col)
        if cols_added:
            logger.info(f"url_matrix: カラム追加 {cols_added}")
        conn.commit()

        total_updated = 0
        for agency_id, (_, _, _, site_url) in AGENCY_CATEGORIES.items():
            if not site_url:
                continue
            cur.execute(
                "UPDATE url_matrix SET site_url=? WHERE agency_id=?",
                (site_url, agency_id),
            )
            total_updated += cur.rowcount
        conn.commit()

    logger.info(f"url_matrix site_url UPDATE: {total_updated:,} 行")
    return total_updated


def report() -> None:
    """実行後の状況レポート。"""
    with sqlite3.connect(PROC_DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT category_large, COUNT(*) FROM contracts GROUP BY category_large ORDER BY 2 DESC")
        print("\n=== contracts category_large 分布 ===")
        for r in cur.fetchall():
            print(f"  {(r[0] or '(NULL)'):20s}: {r[1]:,}")

        cur.execute("SELECT COUNT(*) FROM contracts WHERE category_large IS NULL")
        n_null = cur.fetchone()[0]
        print(f"\n  未マッピング (NULL): {n_null:,} 件")

        if n_null > 0:
            cur.execute(
                "SELECT agency_id, COUNT(*) FROM contracts WHERE category_large IS NULL"
                " GROUP BY agency_id ORDER BY 2 DESC LIMIT 20"
            )
            print("  未マッピング agency_id (上位20):")
            for r in cur.fetchall():
                print(f"    {r[0]:30s}: {r[1]:,}")

    if URL_DB.exists():
        with sqlite3.connect(URL_DB) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM url_matrix WHERE site_url IS NOT NULL")
            n = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM url_matrix")
            total = cur.fetchone()[0]
            print(f"\n=== url_matrix site_url 充填 ===")
            print(f"  {n:,} / {total:,} ({n/total*100:.1f}%)")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    proc_updated = setup_procurement_db()
    url_updated  = setup_url_matrix_db()
    report()

    print(f"\n完了: contracts={proc_updated:,}件, url_matrix={url_updated:,}行")
