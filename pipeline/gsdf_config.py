"""陸上自衛隊 (GSDF) 25機関の収集設定。

ほとんどがPDFソース。各機関のURL構造は公表標準様式に従うが、ファイル命名は様々。

戦略:
- index_urls: 機関のトップ/契約情報ページからPDFリンク自動抽出
- url_patterns: 命名規則が明確な機関は iter で全列挙（404はスキップ）
"""
from __future__ import annotations


def _months_4y_all() -> list[tuple[int, int]]:
    """(reiwa, month) のリスト（令和4-7年・全月）。"""
    out: list[tuple[int, int]] = []
    for rr in (4, 5, 6, 7):
        for mm in range(1, 13):
            out.append((rr, mm))
    return out


GSDF_AGENCIES: list[dict] = [
    # ── 1. 補給統制本部（最大規模）──────────
    {
        "agency_id": "gsdf_gmcc",
        "agency_name": "補給統制本部",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/gmcc/raising/",
            "https://www.mod.go.jp/gsdf/gmcc/raising/hoto/hzyo/",
        ],
        # hzyo{RR}{MM}{NN}.pdf — 件数多いので nn=1..15 で十分
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/gmcc/raising/hoto/hzyo/hzyo{rr:02d}{mm:02d}{nn:02d}.pdf"
            for rr, mm in _months_4y_all()
            for nn in range(1, 16)
        ],
    },
    # ── 2. 陸自中央会計隊（連番）─────────
    # file{N}.pdf 番号制（N=1..960程度まで存在）。custom.html に最新ファイルリンクあり。
    {
        "agency_id": "gsdf_cfin",
        "agency_name": "陸自中央会計隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/dc/cfin/html/",
            "https://www.mod.go.jp/gsdf/dc/cfin/",
            "https://www.mod.go.jp/gsdf/dc/cfin/html/custom.html",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/dc/cfin/html/img/file{n}.pdf"
            for n in range(1, 961)
        ],
    },
    # ── 3. 中部方面会計隊 ─────────
    {
        "agency_id": "gsdf_chubu",
        "agency_name": "中部方面会計隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/mae/mafin/",
            "https://www.mod.go.jp/gsdf/mae/mafin/k/",
            "https://www.mod.go.jp/gsdf/mae/mafin/info/",
        ],
        # jo{RR}{MM}.pdf, K{RR}{MM}.pdf, kouhyou{RR}.pdf
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/mae/mafin/k/jo{rr:02d}{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ] + [
            f"https://www.mod.go.jp/gsdf/mae/mafin/info/K{rr:02d}{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ] + [
            f"https://www.mod.go.jp/gsdf/mae/mafin/k/kouhyou{rr:02d}.pdf"
            for rr in (4, 5, 6, 7)
        ],
    },
    # ── 4. 北部方面会計隊 ─────────
    {
        "agency_id": "hokubu_kaikei",
        "agency_name": "北部方面会計隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/",
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/r6kensetukouzihattyuuzisseki.htm",
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/r5kensetukouzihattyuuzisseki.htm",
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/r4kensetukouzihattyuuzisseki.htm",
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/r7kensetukouzihattyuuzisseki.htm",
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/ppR6.htm",
            "https://www.mod.go.jp/gsdf/nae/fin/nafin/ppR7.htm",
        ],
    },
    # ── 5. 西部方面会計隊（複雑な命名）──────
    # wa-fin/ はフレームセット（239B、中身なし）。wa-fin/04/〜07/ は403。
    # 正しいインデックス: jh/tekisei.htm (Excel Web Archive フレームセット、4シート)
    # PDFは wa-fin/04/ 以下に格納。命名規則: {unit}_{RY}.{MM}_{sheet}.pdf (現行)
    #                                   R{YYMM}_{unit}_b{sheet}.pdf (旧)
    # FY2024 はライブから消えているため WARP（20250607031330）を併用、303件のR6 PDFを補完
    {
        "agency_id": "gsdf_seibu",
        "agency_name": "西部方面会計隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.htm",
            "https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet001.htm",
            "https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet002.htm",
            "https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet003.htm",
            "https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet004.htm",
            # FY2024 PDF が存在する WARP スナップショット
            # sheet001=公共工事/競争, 002=公共工事/随契, 003=物品役務/競争, 004=物品役務/随契
            "https://warp.ndl.go.jp/20250610/20250607031330/https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet001.htm",
            "https://warp.ndl.go.jp/20250610/20250607031330/https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet002.htm",
            "https://warp.ndl.go.jp/20250610/20250607031330/https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet003.htm",
            "https://warp.ndl.go.jp/20250610/20250607031330/https://www.mod.go.jp/gsdf/wae/info/nyusatu/wa-fin/jh/tekisei.files/sheet004.htm",
        ],
    },
    # ── 6. 中央輸送隊 ─────────
    # tekiseika/kouhyou.html に全年度月別PDFリンクが集約されている（99件、FY2019-FY2025）
    # ファイル命名: R{rr}/{rr:02d}_{mm:02d}.pdf （現行）と R03/04_1.pdf （single-digit 月）の混在
    {
        "agency_id": "gsdf_ctrans",
        "agency_name": "中央輸送隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/yokohama/hp2015/06bosyu/nyusatu/tekiseika/kouhyou.html",
            "https://www.mod.go.jp/gsdf/yokohama/hp2015/06bosyu/nyusatu/tekiseika/",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/yokohama/hp2015/06bosyu/nyusatu/tekiseika/R{rr:02d}/{rr:02d}_{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ],
    },
    # ── 7. 教育訓練研究本部 ─────────
    # /img/ は HTTP 403。proc4.html に全PDFリンク掲載（file番号は不規則・1000番台あり）
    {
        "agency_id": "gsdf_tercom",
        "agency_name": "教育訓練研究本部",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/tercom/proc4.html",
            "https://www.mod.go.jp/gsdf/tercom/procurement.html",
        ],
        "url_patterns": [],
    },
    # ── 8. 関東補給処 ─────────
    # tyokai/honsyo/ には随契・一般競争の PDF が掲載。zuikeiitiran.html が索引ページ。
    # FY2024/2025 は月別 PDF (R6zuikei{mm}.pdf 等) またはまとめ PDF を URL パターンで試行。
    {
        "agency_id": "gsdf_eadep",
        "agency_name": "関東補給処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/honsyo/zuikeiitiran.html",
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/honsyo/",
            "https://www.mod.go.jp/gsdf/eae/eadep/",
            "https://www.mod.go.jp/gsdf/eae/eadep/keiyaku/",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/eae/eadep/tyokai/honsyo/R{ry}{kind}{mm}.pdf"
            for ry in (6, 7) for mm in range(1, 13)
            for kind in ("zuikei", "ippan")
        ] + [
            f"https://www.mod.go.jp/gsdf/eae/eadep/tyokai/honsyo/R{ry:02d}{kind}456789101112123.pdf"
            for ry in (6, 7) for kind in ("zuikei", "ippan")
        ],
    },
    # ── 8a. 関東補給処古賀支処 ─────────
    {
        "agency_id": "gsdf_eadep_koga",
        "agency_name": "関東補給処古賀支処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/koga/HP/kohyo.html",
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/koga/HP/",
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/koga/",
        ],
    },
    # ── 8b. 関東補給処用賀支処 ─────────
    {
        "agency_id": "gsdf_eadep_yooga",
        "agency_name": "関東補給処用賀支処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/yooga/jyouhou.html",
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/yooga/",
        ],
    },
    # ── 9. 関東補給処松戸支処 ─────────
    # matudo/ は1行（matudoHP2015/ へのリンクのみ）。matudoHP2015/ は403。
    # 正しいインデックス: keiyakujouhoukouhyou3.html（フレームの奥のページ）
    # PDFはすべて matudoHP2015/ 以下 (R4-R7 x 4様式)
    {
        "agency_id": "gsdf_eadep_matudo",
        "agency_name": "関東補給処松戸支処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/matudo/matudoHP2015/keiyakujouhoukouhyou3.html",
        ],
    },
    # ── 10. 北海道補給処 ─────────
    # nyuusatujouhou/ 直下は403。公表PDFは 070kouhyou07/kouhyou07.htm 経由でアクセス可
    {
        "agency_id": "gsdf_nadep",
        "agency_name": "北海道補給処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/nae/nadep/nyuusatujouhou/070kouhyou07/kouhyou07.htm",
        ],
    },
    # ── 11. 東北補給処 ─────────
    # dep/ 直下はフレームセット（PDFリンクなし）。実際の公表ページ: dep/koukyou.htm
    # 命名規則: FY2024(R6) は kouhyou{YY}{MM}.pdf（ハイフンなし）、
    #          FY2025(R7) は kouhyou{YY}-{MM}.pdf（ハイフンあり）の混在。
    {
        "agency_id": "gsdf_neadep",
        "agency_name": "東北補給処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/neae/koukoku/dep/",
            "https://www.mod.go.jp/gsdf/neae/koukoku/dep/koukyou.htm",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/neae/koukoku/dep/kouhyou{rr:02d}-{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ] + [
            f"https://www.mod.go.jp/gsdf/neae/koukoku/dep/kouhyou{rr:02d}{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ] + [
            f"https://www.mod.go.jp/gsdf/neae/koukoku/dep/koukyuo{rr:02d}{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ],
    },
    # ── 12. 関西補給処 ─────────
    # madep/, uji/, nyusatsu/ はすべて403。
    # 正しいインデックス: nyusatsu/newpage2.htm（標準HTML、PDF直リンクあり）
    # PDFは「公表データ」年度別まとめ型 (R5〜R7)。R4(FY2022)は未掲載。
    {
        "agency_id": "gsdf_madep",
        "agency_name": "関西補給処",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/mae/madep/uji/nyusatsu/newpage2.htm",
        ],
    },
    # ── 13. 東北方面会計隊 ─────────
    # fin/ はフレームセット（スクレイパーにはPDFリンク0件）。tekiseika_kouhyou/ は403。
    # 正しいインデックス: 年度別HTML (tekiseika_kouhyou_XX.html)
    #   → FY2022:172件、FY2023:247件、FY2024/2025も多数。PDFは同 rXX_nendo/ 以下。
    {
        "agency_id": "tohoku_kaikei",
        "agency_name": "東北方面会計隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/neae/koukoku/fin/tekiseika_kouhyou/r04_nendo/tekiseika_kouhyou_04.html",
            "https://www.mod.go.jp/gsdf/neae/koukoku/fin/tekiseika_kouhyou/r05_nendo/tekiseika_kouhyou_05.html",
            "https://www.mod.go.jp/gsdf/neae/koukoku/fin/tekiseika_kouhyou/r06_nendo/tekiseika_kouhyou_06.html",
            "https://www.mod.go.jp/gsdf/neae/koukoku/fin/tekiseika_kouhyou/r07_nendo/tekiseika_kouhyou_07.html",
        ],
    },
    # ── 14. 東部方面会計隊（HTML直接抽出） ─────
    # 4ページ構成: nyusatsu_{ekimu|kouji}.html, zuikei_{ekimu|kouji}.html
    # ※ kyousou_*.html は 404 → nyusatsu_* が正解
    {
        "agency_id": "gsdf_eafin",
        "agency_name": "東部方面会計隊",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/eae/kaikei/eafin/nyusatsu_ekimu.html",
            "https://www.mod.go.jp/gsdf/eae/kaikei/eafin/nyusatsu_kouji.html",
            "https://www.mod.go.jp/gsdf/eae/kaikei/eafin/zuikei_ekimu.html",
            "https://www.mod.go.jp/gsdf/eae/kaikei/eafin/zuikei_kouji.html",
        ],
        "scrape_html_tables": True,  # HTML テーブル直接抽出
    },
    # ── 15. 幹部候補生学校 ─────────
    # disclosure/ ページからPDFリンク自動収集 (img/disclosure/ は403)
    # PDFに contract_date がない場合 → URL"koukyou{RY}.{MM}.pdf"からFY推定
    # (load_gsdf.py の _fy_from_pdf_url() でフォールバック)
    {
        "agency_id": "gsdf_ocsh",
        "agency_name": "幹部候補生学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/ocsh/disclosure/",
        ],
        "url_fy_fallback": True,  # contract_date なし時 URL からFY推定
    },
    # ── 16. 富士学校 ─────────
    {
        "agency_id": "gsdf_fsh",
        "agency_name": "富士学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/fsh/",
            "https://www.mod.go.jp/gsdf/fsh/fin/",
            "https://www.mod.go.jp/gsdf/fsh/fin/jouhoukouhyou.html",
        ],
    },
    # ── 17. 高射学校 ─────────
    {
        "agency_id": "gsdf_aasch",
        "agency_name": "高射学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/aasch/aaspr-hp/sta-intro/draft/draft2.html",
            "https://www.mod.go.jp/gsdf/aasch/aaspr-hp/sta-intro/draft/announce/",
            "https://www.mod.go.jp/gsdf/aasch/",
        ],
    },
    # ── 18. 航空学校（明野） ─────────
    {
        "agency_id": "gsdf_akeno",
        "agency_name": "航空学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/akeno/html/fin/fin-koukai.html",
            "https://www.mod.go.jp/gsdf/akeno/img/img-fin/koukai/",
            "https://www.mod.go.jp/gsdf/akeno/img/img-fin/koukai/r4/",
            "https://www.mod.go.jp/gsdf/akeno/img/img-fin/koukai/r5/",
            "https://www.mod.go.jp/gsdf/akeno/img/img-fin/koukai/r6/",
            "https://www.mod.go.jp/gsdf/akeno/img/img-fin/koukai/r7/",
            "https://www.mod.go.jp/gsdf/akeno/img/img-fin/",
        ],
    },
    # ── 19. 通信学校（信学校）─────────
    # /fin/ane/ は 403。契約公表はjiyouhou.htm にリンク掲載（exh{RY}-{NN}.pdf）
    {
        "agency_id": "gsdf_sigsch",
        "agency_name": "通信学校（信）",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/sigsch/fin/jiyouhou.htm",
        ],
    },
    # ── 20. 小平駐屯地 ─────────
    # keiyaku/ は 403。koukoku.html に公表 PDFリンク掲載
    {
        "agency_id": "gsdf_kodaira",
        "agency_name": "小平駐屯地",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/kodaira/keiyaku/koukoku.html",
        ],
    },
    # ── 21. 衛生学校 ─────────
    {
        "agency_id": "gsdf_eisei",
        "agency_name": "衛生学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/mss/",
            "https://www.mod.go.jp/gsdf/mss/document/fin/",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/mss/document/fin/{rr:02d}_{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ],
    },
    # ── 22. 中央病院 ─────────
    # contents2.html=競争入札, contents3.html=随意契約 にFY別PDFリンク集約
    # ファイル名: buppinekimu-{kyousou|zuikei}_R{Y}.{M}.pdf, kouji-{kyousou|zuikei}_R{Y}.{M}.pdf
    {
        "agency_id": "gsdf_chosp",
        "agency_name": "中央病院",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/chosp/",
            "https://www.mod.go.jp/gsdf/chosp/fin/",
            "https://www.mod.go.jp/gsdf/chosp/fin/contents2.html",
            "https://www.mod.go.jp/gsdf/chosp/fin/contents3.html",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/chosp/fin/k{rr:02d}-{mm:02d}.pdf"
            for rr, mm in _months_4y_all()
        ] + [
            f"https://www.mod.go.jp/gsdf/chosp/fin/{prefix}_R{rr}.{mm}.pdf"
            for rr in (4, 5, 6, 7, 8) for mm in range(1, 13)
            for prefix in ("buppinekimu-kyousou", "buppinekimu-zuikei",
                           "kouji-kyousou", "kouji-zuikei")
        ],
    },
    # ── 23. 北宇都宮駐屯地 ─────────
    {
        "agency_id": "gsdf_kitautsu",
        "agency_name": "北宇都宮駐屯地",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/kitautunomiya/",
            "https://www.mod.go.jp/gsdf/kitautunomiya/keiyaku/",
            "https://www.mod.go.jp/gsdf/kitautunomiya/keiyaku/siryou/",
        ],
    },
    # ── 24. 施設学校 ─────────
    {
        "agency_id": "gsdf_essch",
        "agency_name": "施設学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/shisetsu/",
            "https://www.mod.go.jp/gsdf/shisetsu/es-hp/",
            "https://www.mod.go.jp/gsdf/shisetsu/es-hp/kaikei/",
        ],
    },
    # ── 25. 武器学校 ─────────
    {
        "agency_id": "gsdf_buki",
        "agency_name": "武器学校",
        "index_urls": [
            "https://www.mod.go.jp/gsdf/ord_sch/",
            "https://www.mod.go.jp/gsdf/ord_sch/07_fin/",
            "https://www.mod.go.jp/gsdf/ord_sch/07_fin/pdf/",
            "https://www.mod.go.jp/gsdf/ord_sch/07_fin/pdf/Joho/",
            "https://www.mod.go.jp/gsdf/ord_sch/07_fin/pdf/Joho/Buppin/",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/gsdf/ord_sch/{rr:02d}_fin/pdf/Joho/Buppin/{rr}-{mm}buppin{kind}.pdf"
            for rr, mm in _months_4y_all() for kind in ("kyousou", "zuikei")
        ],
    },
]
