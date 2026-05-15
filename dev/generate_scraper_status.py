"""
Generate scraper_status.json from procurement.db.
Lists all scrapers, their coverage, and agencies missing FY2025 March data.
Run from the main project directory: python dev/generate_scraper_status.py
"""
import sqlite3
import json
from datetime import date

DB = r"data/db/procurement.db"
OUT = "scraper_status.json"

LOADERS = {
    "pipeline/load_atla.py": {
        "agencies": ["atla"],
        "source_type": "Excel",
        "description": "防衛装備庁本庁（月次Excel）",
    },
    "pipeline/load_atla_sub.py": {
        "agencies": [
            "atla_kanbo", "atla_koukuu", "atla_riku", "atla_kantei",
            "atla_shinsedai", "atla_chitose", "atla_shimokita",
            "atla_gifu", "atla_disti",
        ],
        "source_type": "PDF",
        "description": "防衛装備庁サブ機関（研究所・試験場）",
    },
    "pipeline/load_asdf.py": {
        "agencies": [
            "asdf_2dep", "asdf_3dep", "asdf_4dep", "asdf_ichigaya",
            "asdf_chitose", "asdf_misawa", "asdf_iruma", "asdf_matsushima",
            "asdf_hyakuri", "asdf_komatsu", "asdf_gifu", "asdf_hamamatsu",
            "asdf_yokota", "asdf_komaki", "asdf_kisarazu", "asdf_niigata",
            "asdf_fuchu", "asdf_nara", "asdf_tsuiki", "asdf_hofukita",
            "asdf_hofuminami", "asdf_miho", "asdf_kumagaya", "asdf_shizuhama",
            "asdf_akita", "asdf_meguro", "asdf_ashiya", "asdf_kasuga",
            "asdf_nyutabaru",
        ],
        "source_type": "Excel/PDF/HTML",
        "description": "航空自衛隊 29機関",
    },
    "pipeline/load_gsdf.py": {
        "agencies": [
            "gsdf_gmcc", "gsdf_cfin", "gsdf_chubu", "hokubu_kaikei",
            "gsdf_seibu", "gsdf_ctrans", "gsdf_tercom", "gsdf_eadep",
            "gsdf_nadep", "gsdf_neadep", "gsdf_madep", "tohoku_kaikei",
            "gsdf_eafin", "gsdf_ocsh", "gsdf_fsh", "gsdf_aasch",
            "gsdf_akeno", "gsdf_sigsch", "gsdf_kodaira", "gsdf_eisei",
            "gsdf_chosp", "gsdf_kitautsu", "gsdf_essch", "gsdf_buki",
            "gsdf_eadep_koga", "gsdf_eadep_yooga", "gsdf_eadep_matudo",
        ],
        "source_type": "PDF/HTML",
        "description": "陸上自衛隊 25+機関",
    },
    "pipeline/load_msdf.py": {
        "agencies": [
            "msdf_y0", "msdf_k0", "msdf_s0", "msdf_m0", "msdf_d0",
            "msdf_t2", "msdf_asd", "msdf_yd", "msdf_k4", "msdf_sk",
            "msdf_d1", "msdf_k1", "msdf_dw", "msdf_dy", "msdf_y6",
            "msdf_y2", "msdf_k2", "msdf_k7", "msdf_s3", "msdf_st",
            "msdf_s2", "msdf_sn", "msdf_sa", "msdf_s1",
        ],
        "source_type": "Excel",
        "description": "海上自衛隊 24機関",
    },
    "pipeline/load_rdb.py": {
        "agencies": [
            "rdb_hokkaido", "rdb_tohoku", "rdb_n_kanto", "rdb_s_kanto",
            "rdb_kinchu", "rdb_chushi", "rdb_kyushu", "rdb_okinawa",
            "rdb_tokai",
        ],
        "source_type": "Excel/PDF/HTML",
        "description": "地方防衛局 9機関",
    },
    "pipeline/load_misc.py": {
        "agencies": ["naikyoku_kaikei", "dih", "js", "ndmc", "nids", "nda"],
        "source_type": "Excel/PDF",
        "description": "内局・統幕・防衛医科大・防衛研究所・防衛大学校",
    },
    "pipeline/load_igo.py": {
        "agencies": ["igo"],
        "source_type": "PDF",
        "description": "防衛監察本部",
    },
    "pipeline/load_misawa_ocr.py": {
        "agencies": ["asdf_misawa"],
        "source_type": "OCR",
        "description": "三沢基地FY2024画像PDF専用（easyocr）",
        "note": "load_asdf.pyとは別の専用ローダー",
    },
    "pipeline/load_kenkyuu_hyouka.py": {
        "agencies": ["kenkyuu_hyouka"],
        "source_type": "PDF",
        "description": "政策評価書（総務省ポータル）— 要求元判定補助用",
    },
    "pipeline/load_from_urlmatrix.py": {
        "agencies": [],
        "source_type": "mixed",
        "description": "url_matrix.db 未収録URL補完（after主要ローダー完了後）",
        "note": "reconcile_urlmatrix.py → load_from_urlmatrix.py の順で実行",
    },
    "pipeline/load_eadep_nadep_warp.py": {
        "agencies": ["gsdf_eadep", "gsdf_nadep"],
        "source_type": "PDF (WARP)",
        "description": "関東・北海道補給処FY2024 WARP専用",
        "note": "一回限りスクリプト（FY2024分のみ）",
    },
}

# agency_id -> loader mapping
agency_to_loader = {}
agency_to_meta = {}
for loader, meta in LOADERS.items():
    for a in meta["agencies"]:
        agency_to_loader[a] = loader
        agency_to_meta[a] = {
            "source_type": meta["source_type"],
            "description": meta.get("description", ""),
        }


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            agency_id,
            MAX(contract_date)   AS max_date,
            COUNT(*)             AS total_cnt,
            SUM(CASE WHEN fiscal_year = 2025 THEN 1 ELSE 0 END) AS fy2025_cnt,
            MAX(CASE WHEN fiscal_year = 2025 THEN contract_date END) AS fy2025_max_date
        FROM contracts
        GROUP BY agency_id
        ORDER BY agency_id
    """)
    rows = cur.fetchall()
    conn.close()

    records = []
    for row in rows:
        agency_id, max_date, total_cnt, fy2025_cnt, fy2025_max_date = row
        missing_march = max_date is None or max_date < "20260301"
        meta = agency_to_meta.get(agency_id, {})
        records.append({
            "agency_id":          agency_id,
            "loader_script":      agency_to_loader.get(agency_id, "unknown"),
            "source_type":        meta.get("source_type", "unknown"),
            "max_date":           max_date,
            "total_cnt":          total_cnt,
            "fy2025_cnt":         fy2025_cnt or 0,
            "fy2025_max_date":    fy2025_max_date,
            "missing_march_2026": missing_march,
        })

    missing = sorted(
        [r for r in records if r["missing_march_2026"]],
        key=lambda r: (r["fy2025_cnt"] or 0),
        reverse=True,
    )

    loaders_summary = []
    for loader, meta in LOADERS.items():
        loaders_summary.append({
            "loader_script":   loader,
            "description":     meta.get("description", ""),
            "source_type":     meta["source_type"],
            "agency_count":    len(meta["agencies"]),
            "agency_ids":      meta["agencies"],
            "note":            meta.get("note", ""),
        })

    output = {
        "generated_at":            str(date.today()),
        "total_agencies_in_db":    len(records),
        "missing_march_2026_count": len(missing),
        "loaders": loaders_summary,
        "parsers": [
            {"file": "parsers/pdf_table.py",   "description": "PDF表パーサー（50+ヘッダーキーワード対応）"},
            {"file": "parsers/excel_parser.py", "description": "Excelパーサー（.xlsx/.xls両対応）"},
            {"file": "parsers/ocr_parser.py",   "description": "easyocr画像PDFパーサー"},
        ],
        "collectors": [
            {"file": "collectors/http_client.py",   "description": "HTTPクライアント（WARP Cookie・キャッシュ・リトライ対応）"},
            {"file": "collectors/index_scraper.py", "description": "HTMLインデックスページ解析（PDF/Excelリンク抽出）"},
        ],
        "parallel_groups": {
            "note": "group1-7 は互いに独立・並列実行可。完了後に group8 を順次実行。",
            "group1_atla":  ["python -m pipeline.load_atla", "python -m pipeline.load_atla_sub"],
            "group2_asdf":  ["python -m pipeline.load_asdf"],
            "group3_msdf":  ["python -m pipeline.load_msdf"],
            "group4_gsdf":  ["python -m pipeline.load_gsdf"],
            "group5_rdb":   ["python -m pipeline.load_rdb"],
            "group6_misc":  ["python -m pipeline.load_misc"],
            "group7_igo":   ["python -m pipeline.load_igo"],
            "group8_post":  [
                "python pipeline/reconcile_urlmatrix.py",
                "python -m pipeline.load_from_urlmatrix",
            ],
        },
        "agencies": records,
        "missing_march_2026": missing,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Written {OUT}")
    print(f"  Total agencies in DB : {len(records)}")
    print(f"  Missing March 2026   : {len(missing)}")
    print()
    print("--- Missing March 2026 (FY2025データあり順) ---")
    for r in missing:
        marker = "" if r["fy2025_cnt"] > 0 else " [FY2025なし]"
        print(f"  {r['agency_id']:<30} fy2025={r['fy2025_cnt']:>4}  max={r['max_date']}{marker}")


if __name__ == "__main__":
    main()
