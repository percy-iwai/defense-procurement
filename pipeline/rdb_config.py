"""地方防衛局 (RDB) 9局の収集設定。

各局でフォーマットが異なるため、機関ごとに「収集戦略」を持つ。
- "scrape_index": index URLからリンク列挙してファイル取得（汎用・最も堅牢）
- "iter_pattern": URL パターンを iter で全列挙して 200のみ取得（Excel/PDF生成型サイト向け）

各局は複数の戦略を持てる（年度別 index URL + パターン補完）。
"""
from __future__ import annotations

# 共通: User-Agent fetch は collectors.http_client で対応済

# r{RR}_{cYY} → fiscal_year (RR=令和N年, cYY=西暦下2桁)
# r05 (令和5) は 04月〜=2023年, r06=2024年, r07=2025年
def reiwa_to_fy(rr: int) -> int:
    return 2018 + rr  # r05=FY2023, r06=FY2024, r07=FY2025

def fy_to_reiwa(fy: int) -> int:
    return fy - 2018


# ── 9局の設定 ─────────────────────────────────────────────
RDB_AGENCIES: list[dict] = [
    # ── 1. 北海道防衛局 ──────────────────────
    {
        "agency_id": "rdb_hokkaido",
        "agency_name": "北海道防衛局",
        # Excel: pdf/r{RR}/{cyy}_{MM}{type}.xlsx (type: kk/kz/bek/bez 等)
        "index_urls": [
            "https://www.mod.go.jp/rdb/hokkaido/keiyaku/keiyakujyoho_kouhyou/pdf/r06/",
            "https://www.mod.go.jp/rdb/hokkaido/keiyaku/keiyakujyoho_kouhyou/pdf/r07/",
            "https://www.mod.go.jp/rdb/hokkaido/keiyaku/keiyakujyoho_kouhyou/",
        ],
        "extensions": (".xlsx", ".xls"),
    },
    # ── 2. 東北防衛局 ──────────────────────
    {
        "agency_id": "rdb_tohoku",
        "agency_name": "東北防衛局",
        # PDF: result/keiyaku/{CYY}-{M}-{N}.pdf (N=1..4, CYY=西暦2桁)
        # index_46.html = FY2024/2025のみ（24-x〜26-x）
        # FY2023 (23-4 〜 24-3) はliveで全件存在するがindexなし → url_patternsで補完
        "index_urls": [
            "https://www.mod.go.jp/rdb/tohoku/contract/result/keiyaku/index_46.html",
            "https://www.mod.go.jp/rdb/tohoku/contract/result/keiyaku/",
        ],
        "extensions": (".pdf",),
        "url_patterns": [
            f"https://www.mod.go.jp/rdb/tohoku/contract/result/keiyaku/{cy}-{m}-{n}.pdf"
            for cy, months in [(23, range(4, 13)), (24, range(1, 4))]
            for m in months
            for n in range(1, 5)
        ],
    },
    # ── 3. 北関東防衛局 ──────────────────────
    {
        "agency_id": "rdb_n_kanto",
        "agency_name": "北関東防衛局",
        # PDF: tyoutatu/kekka/{n|z}-{b|k}-{YYMM}.pdf
        "index_urls": [
            "https://www.mod.go.jp/rdb/n-kanto/nyusatsu-keiyaku/nyusatukekkasonota/nyusatukekkasonota.html",
            "https://www.mod.go.jp/rdb/n-kanto/nyusatsu-keiyaku/tyoutatu/kekka/",
        ],
        "extensions": (".pdf",),
        # iterパターン補完: prefixes × YYMM (FY2022-2025)
        "url_patterns": [
            f"https://www.mod.go.jp/rdb/n-kanto/nyusatsu-keiyaku/tyoutatu/kekka/{p}-{yy:02d}{m:02d}.pdf"
            for p in ("n-b", "n-k", "z-b", "z-k")
            for yy in (4, 5, 6, 7)  # 令和4〜7
            for m in list(range(4, 13)) + list(range(1, 4))
        ],
    },
    # ── 4. 南関東防衛局 ──────────────────────
    {
        "agency_id": "rdb_s_kanto",
        "agency_name": "南関東防衛局",
        # PDF パスは年度別: contract/information/images/reiwa{N}nendo/R{Y}.{M}/...
        "index_urls": [
            "https://www.mod.go.jp/rdb/s-kanto/contract/information/index.html",
            "https://www.mod.go.jp/rdb/s-kanto/contract/information/",
        ],
        "extensions": (".pdf",),
    },
    # ── 5. 近畿中部防衛局 ──────────────────────
    {
        "agency_id": "rdb_kinchu",
        "agency_name": "近畿中部防衛局",
        # Excel: contract/information/files/{type}_{competitive|zuikei}_{CYYMM}.xlsx
        "index_urls": [
            "https://www.mod.go.jp/rdb/kinchu/contract/information/",
            "https://www.mod.go.jp/rdb/kinchu/contract/information/index.html",
        ],
        "extensions": (".xlsx", ".xls"),
    },
    # ── 6. 中国四国防衛局 (WARP必須 for FY2022/2023) ───
    {
        "agency_id": "rdb_chushi",
        "agency_name": "中国四国防衛局",
        "index_urls": [
            "https://www.mod.go.jp/rdb/chushi/contract/result/keiyakujyoukyou-main.html",
            "https://www.mod.go.jp/rdb/chushi/contract/result/",
            # WARP: FY2022/2023用（id_なし：リンク書換えあり → PDF発見率向上）
            "https://warp.ndl.go.jp/20240715/20240715000000/https://www.mod.go.jp/rdb/chushi/contract/result/keiyakujyoukyou-main.html",
            "https://warp.ndl.go.jp/20230715/20230715000000/https://www.mod.go.jp/rdb/chushi/contract/result/keiyakujyoukyou-main.html",
        ],
        "extensions": (".pdf",),
        "is_warp": True,
        # WARP url_patterns: FY2022(2204-2303) + FY2023(2304-2403) の全PDF直接指定
        "url_patterns": [
            f"https://warp.ndl.go.jp/{warp_ts}/https://www.mod.go.jp/rdb/chushi/contract/result/pdf/keiyaku-{typ}{yy:02d}{mm:02d}.pdf"
            for warp_ts, fy_months in [
                # FY2022: 20230715 snapshot (2022/04 〜 2023/03)
                ("20230715/20230715000000", [(22, range(4, 13)), (23, range(1, 4))]),
                # FY2023: 20240715 snapshot (2023/04 〜 2024/03)
                ("20240715/20240715000000", [(23, range(4, 13)), (24, range(1, 4))]),
            ]
            for typ in ("bk", "bz", "kk", "kz")
            for yy, months in fy_months
            for mm in months
        ],
    },
    # ── 7. 九州防衛局 ──────────────────────
    {
        "agency_id": "rdb_kyushu",
        "agency_name": "九州防衛局",
        "index_urls": [
            "https://www.mod.go.jp/rdb/kyushu/contract/announcement/index.html",
            "https://www.mod.go.jp/rdb/kyushu/contract/announcement/",
            # WARP: FY2022/2023用（id_なし：リンク書換えあり → PDF発見率向上）
            "https://warp.ndl.go.jp/20240715/20240715000000/https://www.mod.go.jp/rdb/kyushu/contract/announcement/index.html",
            "https://warp.ndl.go.jp/20230715/20230715000000/https://www.mod.go.jp/rdb/kyushu/contract/announcement/index.html",
        ],
        "extensions": (".pdf",),
        "is_warp": True,
        # WARP url_patterns: FY2023 PDF直接指定（20240715 snapshot）
        # 命名規則: {RRMM}{type}.pdf (RR=令和年2桁, MM=月2桁)
        # + k{RRMM}{type}.pdf（工事系の k-prefix バリアント）
        "url_patterns": [
            f"https://warp.ndl.go.jp/20240715/20240715000000/https://www.mod.go.jp/rdb/kyushu/contract/announcement/pdf/{prefix}{rr:02d}{mm:02d}{typ}.pdf"
            for prefix in ("", "k")
            for rr, months in [(5, range(4, 13)), (6, range(1, 4))]  # FY2023 = R5/04〜R6/03
            for mm in months
            for typ in ("buppinnyuusatu", "buppinnyuusatsu", "buppinnzuikei", "buppinzuikei",
                         "kouzinyuusatsu", "kouzinyuusatu", "kouzizuikei")
        ],
    },
    # ── 8. 沖縄防衛局 ──────────────────────
    {
        "agency_id": "rdb_okinawa",
        "agency_name": "沖縄防衛局",
        # PDF: contract/information/pdf/{cal_year}/{N}{type}/{N}{type}{M}.pdf
        "index_urls": [
            "https://www.mod.go.jp/rdb/okinawa/contract/information/index.html",
            "https://www.mod.go.jp/rdb/okinawa/contract/information/",
            "https://www.mod.go.jp/rdb/okinawa/",
        ],
        "extensions": (".pdf",),
    },
    # ── 9. 東海防衛支局 (HTML テーブル + PDF/Excel 索引) ───
    # html_table_pages: result/ ページ（現行: 16件）
    # index_urls: information/ ページからPDF/Excelリンクを収集
    {
        "agency_id": "rdb_tokai",
        "agency_name": "東海防衛支局",
        "html_table_pages": [
            # (url, fiscal_year, contract_type)
            (f"https://www.mod.go.jp/rdb/tokai/contract/constraction/result/{cy}_koji/", fy, "工事")
            for cy, fy in [("2022", 2022), ("2023", 2023), ("2024", 2024), ("2025", 2025)]
        ] + [
            (f"https://www.mod.go.jp/rdb/tokai/contract/constraction/result/{cy}_gyomu/", fy, "業務")
            for cy, fy in [("2022", 2022), ("2023", 2023), ("2024", 2024), ("2025", 2025)]
        ],
        "index_urls": [
            "https://www.mod.go.jp/rdb/tokai/contract/constraction/information/",
            "https://www.mod.go.jp/rdb/tokai/contract/constraction/",
        ],
        "extensions": (".pdf", ".xlsx", ".xls"),
    },
]
