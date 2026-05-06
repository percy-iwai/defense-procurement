"""航空自衛隊（ASDF）機関設定。

戦略:
- index_urls: 機関トップ/契約情報ページからPDF/Excelリンク自動抽出
- url_patterns: 命名規則が明確な機関は全列挙（404スキップ）
- source_format: "excel" | "pdf" (default) | "html"
- scrape_html_tables: True の機関はHTMLテーブル直接抽出
- is_warp: True の機関はWARP経由アクセス（asdf_3dep）
- skip: True の機関は画像PDFのためスキップ
"""
from __future__ import annotations

BASE_2DEP = "https://www.mod.go.jp/asdf/2dep/pdf/koukyo"
# FY2022 (04xx) はlive 404 → WARP 20230715スナップ経由で取得
WARP_BASE_2DEP = "https://warp.ndl.go.jp/20230715/20230715000000id_/"
WARP_BASE_3DEP = (
    "https://warp.ndl.go.jp/20250510/20250509054434/"
    "https://www.mod.go.jp/asdf/3dep/prd/kakusyukouhyou/koukyou/"
)
BASE_NYUTABARU = "https://www.mod.go.jp/asdf/nyutabaru/08cyoutatsu/pdf/tekiseika/"
BASE_HOFUMINAMI = "https://www.mod.go.jp/asdf/hofuminami/koukoku/kohyo/"
BASE_YOKOTA = "https://www.mod.go.jp/asdf/yokota/"
BASE_GIFU_ACD = "https://www.mod.go.jp/asdf/gifu/acd/"
BASE_HAMAMATSU = "https://www.mod.go.jp/asdf/hamamatsu/choutatsu/koukoku/"


def _2dep_patterns() -> list[str]:
    """第2補給処: kou_{nyu|zui}_{RR}{MM}.xlsx (RR=04-07, MM=01-12)
    FY2022 (RR=04) はlive 404 → WARP 20230715スナップ経由
    """
    out = []
    for rr in ("04", "05", "06", "07"):
        for mm in (f"{m:02d}" for m in range(1, 13)):
            for typ in ("nyu", "zui"):
                live = f"{BASE_2DEP}/kou_{typ}_{rr}{mm}.xlsx"
                if rr == "04":
                    out.append(f"{WARP_BASE_2DEP}{live}")
                else:
                    out.append(live)
    return out


def _3dep_warp_patterns() -> list[str]:
    """第3補給処（WARP）: collect_3dep_warp.py 由来の正確なパス
    競争: koukyou_excell/nyuusatu/kouhyou-n-{RYMM}.xlsx
    随意: koukyou_excell/zuikei/kouhyou-z-{RYMM}.xlsx
    RYMM = Reiwa2桁年 + 月2桁 (例: 0604 = 令和6年4月)
    スナップショット: coll=20250510 / ts=20250509054434 (深夜日付またぎ)
    対象: FY2022(RR05), FY2023(RR05/06), FY2024(RR06), FY2025一部(RR07)
    注: 04月は競争入札なし（zuikeiのみ）
    """
    out = []
    for rr in ("05", "06", "07"):
        for mm in range(1, 13):
            mm_s = f"{mm:02d}"
            yymm = rr + mm_s
            # 随意契約（全月）
            out.append(f"{WARP_BASE_3DEP}koukyou_excell/zuikei/kouhyou-z-{yymm}.xlsx")
            # 競争入札（4月以外）
            if mm != 4:
                out.append(f"{WARP_BASE_3DEP}koukyou_excell/nyuusatu/kouhyou-n-{yymm}.xlsx")
    return out


def _nyutabaru_patterns() -> list[str]:
    """新田原基地: tekiseika{YYMM}.pdf (YYMM = 西暦下2桁+月)
    FY2022: 2204-2303, FY2023: 2304-2403, FY2024: 2404-2503, FY2025: 2504-2603
    例外: 2311 → tekiseika2311-1.pdf
    """
    out = []
    # YYMM pairs: FY2022-FY2025 の各月
    for yy in range(22, 27):  # 22-26
        for mm in range(1, 13):
            ym = f"{yy:02d}{mm:02d}"
            if ym == "2311":
                out.append(f"{BASE_NYUTABARU}tekiseika2311-1.pdf")
            else:
                out.append(f"{BASE_NYUTABARU}tekiseika{ym}.pdf")
    return out


def _hofuminami_patterns() -> list[str]:
    """防府南基地: {RY}-{MM}.pdf (RY = Reiwa年)
    FY2022: R4年4月〜R5年3月, FY2023: R5年4月〜R6年3月
    FY2024: R6年4月〜R7年3月, FY2025: R7年4月〜R8年3月
    """
    out = []
    for ry in range(4, 9):  # 令和4-8年
        for mm in range(1, 13):
            out.append(f"{BASE_HOFUMINAMI}{ry}-{mm}.pdf")
    return out


_GIFU_WARP_COLL = "20250610"
_GIFU_WARP_TS   = "20250603193125"
_GIFU_WARP_BASE = f"https://warp.ndl.go.jp/{_GIFU_WARP_COLL}/{_GIFU_WARP_TS}/{BASE_GIFU_ACD}"


def _gifu_acd_patterns() -> list[str]:
    """岐阜基地: /acd/ サブディレクトリのPDFパターン
    命名: R{RY}{MM}choko.pdf / choko2.pdf / chokosai.pdf
    新形式(FY2025〜): {YYYY}_{MM}_Koukai.pdf
    FY2024有効: R604〜R607 → 現在404（削除済み）、WARP (20250610/20250603193125) に収録
      - R{RY}{MM}choutatsukouhyou.pdf (R605/R606/R607 のみ確認済み)
      - 0604choutatsujouhou_060627.pdf (R6年4月分)
    """
    out: set[str] = set()
    # 旧形式: R{RY}{MM}{suffix}.pdf
    for ry in range(4, 9):  # 令和4-8年
        for mm in range(1, 13):
            mm_s = f"{mm:02d}"
            for sfx in ("choko", "choko2", "chokosai"):
                out.add(f"{BASE_GIFU_ACD}R{ry}{mm_s}{sfx}.pdf")
    # 新形式: {YYYY}_{MM}_Koukai.pdf (FY2025以降 2025年9月〜確認済み)
    for yr in range(2024, 2027):
        for mm in range(1, 13):
            out.add(f"{BASE_GIFU_ACD}{yr}_{mm:02d}_Koukai.pdf")
    # WARP (20250610/20250603193125): FY2024 全月分（ユーザー確認済み）
    # 4月: 0604choutatsujouhou_060627.pdf
    out.add(f"{_GIFU_WARP_BASE}0604choutatsujouhou_060627.pdf")
    # 5〜7月: choutatsukouhyou
    for mm in (5, 6, 7):
        out.add(f"{_GIFU_WARP_BASE}R6{mm:02d}choutatsukouhyou.pdf")
    # 8月: choko3, 9月: choko3, 10月: choko4
    out.add(f"{_GIFU_WARP_BASE}R608choko3.pdf")
    out.add(f"{_GIFU_WARP_BASE}R609choko3.pdf")
    out.add(f"{_GIFU_WARP_BASE}R610choko4.pdf")
    # 11〜12月, 翌1〜2月: choko2
    out.add(f"{_GIFU_WARP_BASE}R611choko2.pdf")
    out.add(f"{_GIFU_WARP_BASE}R612choko2.pdf")
    out.add(f"{_GIFU_WARP_BASE}R701choko2.pdf")
    out.add(f"{_GIFU_WARP_BASE}R702choko2.pdf")
    return sorted(out)


def _hamamatsu_patterns() -> list[str]:
    """浜松基地: 掲載日ベースの月次PDFパターン
    基底URL: /asdf/hamamatsu/choutatsu/koukoku/
    命名: r6kokyo{YYYYMMDD}.pdf (令和6年度公表)
    確認済み: 20240612, 20240704, 20240801(画像PDF), 20240905(画像PDF),
              20241002, 20241202, 20250107, 20250203
    """
    return [
        BASE_HAMAMATSU + "r6kokyo20240612.pdf",   # 4/5月分
        BASE_HAMAMATSU + "r6kokyo20240704.pdf",   # 5/6月分
        BASE_HAMAMATSU + "r6kokyo20240801.pdf",   # 7月分（画像PDF）
        BASE_HAMAMATSU + "r6kokyo20240905.pdf",   # 8月分（画像PDF 6.9MB）
        BASE_HAMAMATSU + "r6kokyo20241002.pdf",   # 8月/9月分
        BASE_HAMAMATSU + "r6kokyo20241202.pdf",   # 11月/12月分（追加確認）
        BASE_HAMAMATSU + "r6kokyo20250107.pdf",   # 12月/1月分（追加確認）
        BASE_HAMAMATSU + "r6kokyo20250203.pdf",   # 12月/3月分
    ]


BASE_CHITOSE_ACS = "https://www.mod.go.jp/asdf/chitose/acs/"
BASE_IRUMA_IMG = "https://www.mod.go.jp/asdf/iruma/bosyu/raising/images/"
BASE_KOMATSU = "https://www.mod.go.jp/asdf/komatsu/6/third/chotatsu_pdf/kouhyou/"
BASE_KUMAGAYA = "https://www.mod.go.jp/asdf/kumagaya/"
BASE_TSUIKI = "https://www.mod.go.jp/asdf/tsuiki/choutatsu/cyoutatujyouhou/"
BASE_FUCHU_JYOHO = "https://www.mod.go.jp/asdf/fuchu/acs/jyoho/"
BASE_SHIZUHAMA = "https://www.mod.go.jp/asdf/shizuhama/choutatsu/pdf/"
BASE_MATSUSHIMA_IMG = "https://www.mod.go.jp/asdf/matsushima/tyotatu/kouhyou/images/"
BASE_AKITA = "https://www.mod.go.jp/asdf/akita/sp/choutatsu/pdf/"
BASE_NARA = "https://www.mod.go.jp/asdf/nara/05procurement/03release/images/01kokyo/"
BASE_NIIGATA = "https://www.mod.go.jp/asdf/niigata/procurement/third/images/kouhyou_pdf/"
BASE_MEGURO = "https://www.mod.go.jp/asdf/meguro/choutatsu/pdf/"
BASE_HYAKURI = "https://www.mod.go.jp/asdf/hyakuri/acs/2-7_procurement/kouhyou/"


def _chitose_patterns() -> list[str]:
    """千歳基地: /acs/ 複数命名形式
    - tekiseiR{ry}.{mm}.pdf (R5〜R7)
    - koukyoutyoutatuR{ry}.{mm}.pdf (R7 April〜)
    - koukyoutyoutatutekiseika{YYMM}.pdf / {YYYYMM}.pdf
    """
    out: set[str] = set()
    for ry in range(4, 9):
        for mm in range(1, 13):
            out.add(f"{BASE_CHITOSE_ACS}tekiseiR{ry}.{mm}.pdf")
            out.add(f"{BASE_CHITOSE_ACS}tekiseiR{ry}.{mm}-1.pdf")
            out.add(f"{BASE_CHITOSE_ACS}koukyoutyoutatuR{ry}.{mm}.pdf")
    for yy in range(22, 27):
        for mm in range(1, 13):
            ym4 = f"{yy:02d}{mm:02d}"
            ym6 = f"20{yy:02d}{mm:02d}"
            out.add(f"{BASE_CHITOSE_ACS}koukyoutyoutatutekiseika{ym4}.pdf")
            out.add(f"{BASE_CHITOSE_ACS}koukyoutyoutatutekiseika{ym6}.pdf")
            out.add(f"{BASE_CHITOSE_ACS}koukyoutyoutatutekiseikakouhyou{ym6}.pdf")
    return sorted(out)


def _iruma_patterns() -> list[str]:
    """入間基地: /bosyu/raising/images/{YYMM}[suffix]kouhyou.pdf
    YY=Reiwa 2桁, MM=2桁, suffix=数字または空
    """
    out: set[str] = set()
    for ry in range(4, 9):
        rr = f"{ry:02d}"
        for mm in range(1, 13):
            mm_s = f"{mm:02d}"
            # 標準形式: 0404kouhyou.pdf
            out.add(f"{BASE_IRUMA_IMG}{rr}{mm_s}kouhyou.pdf")
            # バリアント: 番号付き
            for sfx in ("2", "3", "4"):
                out.add(f"{BASE_IRUMA_IMG}{rr}{mm_s}{sfx}kouhyou.pdf")
            # kouhyou2 variant: 0610kouhyou2.pdf
            out.add(f"{BASE_IRUMA_IMG}{rr}{mm_s}kouhyou2.pdf")
    return sorted(out)


def _komatsu_patterns() -> list[str]:
    """小松基地: /6/third/chotatsu_pdf/kouhyou/kou{ry}.{mm}.pdf
    ry = Reiwa年 (single digit), mm = month (no leading zero)
    """
    out: list[str] = []
    for ry in range(4, 9):
        for mm in range(1, 13):
            out.append(f"{BASE_KOMATSU}kou{ry}.{mm}.pdf")
    return out


def _tsuiki_patterns() -> list[str]:
    """築城基地: /choutatsu/cyoutatujyouhou/r{ry}/{mm}.pdf
    ry = lowercase reiwa, mm = month (no leading zero)
    """
    out: list[str] = []
    for ry in range(4, 9):
        for mm in range(1, 13):
            out.append(f"{BASE_TSUIKI}r{ry}/{mm}.pdf")
    return out


def _fuchu_patterns() -> list[str]:
    """府中基地: /acs/jyoho/kisho{ry:02d}-j{mm}[suffix].pdf
    命名: kisho04-j{mm}.pdf, kisho05-j{mm}.pdf, kisho06-j{mm}kekka.pdf, etc.
    特殊: kisho05-j0511.pdf, kisho05-j0512.pdf, kisho05-j0601.pdf
    """
    out: set[str] = set()
    for ry in range(4, 9):
        rr = f"{ry:02d}"
        for mm in range(1, 13):
            base = f"{BASE_FUCHU_JYOHO}kisho{rr}-j{mm}"
            # 基本
            out.add(f"{base}.pdf")
            # kekka 付き (FY2024以降)
            out.add(f"{base}kekka.pdf")
            # nyusatukekka 付き
            out.add(f"{base}nyusatukekka.pdf")
    # 特殊形式: kisho05-j{YYMM}.pdf
    for ym in ("0511", "0512", "0601"):
        out.add(f"{BASE_FUCHU_JYOHO}kisho05-j{ym}.pdf")
    # 3kekka variant
    out.add(f"{BASE_FUCHU_JYOHO}kisho05-j3kekka.pdf")
    return sorted(out)


def _shizuhama_patterns() -> list[str]:
    """静浜基地: /choutatsu/pdf/koukyoutyoutatuR{ry}_{mm}.pdf
    命名: アンダースコア区切り, mm は先頭ゼロなし
    特殊: R7.8.pdf, R7.9.pdf (ドット形式), R6_9.1.pdf (サブインデックス付き)
    """
    out: set[str] = set()
    for ry in range(4, 9):
        for mm in range(1, 13):
            # アンダースコア形式 (標準)
            out.add(f"{BASE_SHIZUHAMA}koukyoutyoutatuR{ry}_{mm}.pdf")
            # ドット形式
            out.add(f"{BASE_SHIZUHAMA}koukyoutyoutatuR{ry}.{mm}.pdf")
            # .1 サブインデックス
            out.add(f"{BASE_SHIZUHAMA}koukyoutyoutatuR{ry}_{mm}.1.pdf")
    return sorted(out)


def _matsushima_patterns() -> list[str]:
    """松島基地: /tyotatu/kouhyou/images/ 複数命名形式
    実ファイル調査（2026-05）で確認されたパターン:
    - r6-kohyo{mm}.pdf (FY2024 4-6月の古い形式)
    - R{ry}{mm}choutatsukouhyou.pdf / R{ry}{mm:02d}choutatsukouhyou.pdf
    - R{ry}{mm_s}_choutatsukouhyou.pdf (大文字R+ゼロ埋め+アンダースコア)
    - R{ry}{mm_s}_choutatsujouhou.pdf (jouhou バリアント)
    - r{ry}{mm_s}_choutatsukouhyou.pdf / r{ry}{mm_s}_choutasukouhyou.pdf (typo)
    - R{ry}_{mm}choutatsukouhyou.pdf (R6_1形式)
    - R{ry}{mm}choutatsukouhyou_{yyyymm}*.pdf (日付サフィックス付き)
    - r{ry}.{mm}.{dd}-{N}.pdf (ドット形式・複数ファイル)
    """
    out: set[str] = set()
    base = BASE_MATSUSHIMA_IMG
    for ry in range(4, 9):
        for mm in range(1, 13):
            mm_s = f"{mm:02d}"
            # 旧形式 r6-kohyo{mm}.pdf (R6 early months)
            if ry == 6:
                out.add(f"{base}r{ry}-kohyo{mm}.pdf")
            # sep="" or "_", mm 非ゼロ埋め
            for sep in ("", "_"):
                pfx_u = f"R{ry}{sep}{mm}"
                pfx_l = f"r{ry}{sep}{mm}"
                out.add(f"{base}{pfx_u}choutatsukouhyou.pdf")
                out.add(f"{base}{pfx_l}choutatsukouhyou.pdf")
                out.add(f"{base}{pfx_u}chotatsukouhyou.pdf")
                out.add(f"{base}{pfx_l}chotatsukouhyou.pdf")
                out.add(f"{base}{pfx_u}choutatsujouhou.pdf")
            # ゼロ埋め2桁 mm variants (大文字R / 小文字r)
            out.add(f"{base}R{ry}{mm_s}choutatsukouhyou.pdf")
            out.add(f"{base}R{ry}{mm_s}_choutatsukouhyou.pdf")
            out.add(f"{base}R{ry}{mm_s}_choutatsujouhou.pdf")
            out.add(f"{base}r{ry}{mm_s}_choutatsukouhyou.pdf")
            out.add(f"{base}r{ry}{mm_s}_choutasukouhyou.pdf")    # typo variant
    # 日付サフィックス付き既知ファイル（indexから取得できない場合の補完）
    out.add(f"{base}R607choutatsukouhyou_060913.pdf")
    out.add(f"{base}r611_choutasukouhyou.pdf")
    return sorted(out)


def _akita_patterns() -> list[str]:
    """秋田分屯基地: /sp/choutatsu/pdf/R{ry}tekiseika{mm}.pdf
    mm = 先頭ゼロなし (1-12)
    """
    out: list[str] = []
    for ry in range(4, 9):
        for mm in range(1, 13):
            out.append(f"{BASE_AKITA}R{ry}tekiseika{mm}.pdf")
    return out


def _nara_patterns() -> list[str]:
    """奈良基地: /05procurement/03release/images/01kokyo/{RYMMDD}.pdf
    RY = Reiwa年 2桁, MM = 月2桁, DD = 日2桁 (00=月次総括)
    """
    out: list[str] = []
    for ry in range(4, 9):
        rr = f"{ry:02d}"
        for mm in range(1, 13):
            mm_s = f"{mm:02d}"
            # 月次総括 (DD=00)
            out.append(f"{BASE_NARA}{rr}{mm_s}00.pdf")
            # 特定日版
            for dd in ("15", "18", "20"):
                out.append(f"{BASE_NARA}{rr}{mm_s}{dd}.pdf")
    return out


def _niigata_patterns() -> list[str]:
    """新潟分屯基地: /procurement/third/images/kouhyou_pdf/{YYMM}.pdf
    YY = Reiwa年 2桁, MM = 月2桁
    """
    out: list[str] = []
    for ry in range(4, 9):
        rr = f"{ry:02d}"
        for mm in range(1, 13):
            out.append(f"{BASE_NIIGATA}{rr}{mm:02d}.pdf")
    return out


def _meguro_patterns() -> list[str]:
    """目黒基地: /choutatsu/pdf/tekisei-{mm}.pdf
    mm = 先頭ゼロなし (1-12)
    新形式: tekisei{YYYY}-{mm}.pdf (2025年〜)
    """
    out: set[str] = set()
    for mm in range(1, 13):
        out.add(f"{BASE_MEGURO}tekisei-{mm}.pdf")
    for yr in range(2024, 2027):
        for mm in range(1, 13):
            out.add(f"{BASE_MEGURO}tekisei{yr}-{mm}.pdf")
    return sorted(out)


def _hyakuri_patterns() -> list[str]:
    """百里基地: /acs/2-7_procurement/kouhyou/{ry}-{mm}koukyou.pdf
    ry = Reiwa年 (single digit), mm = month (no leading zero)
    注: 元DB URLは // (二重スラッシュ) だが単一スラッシュで試みる
    """
    out: list[str] = []
    for ry in range(4, 9):
        for mm in range(1, 13):
            out.append(f"{BASE_HYAKURI}{ry}-{mm}koukyou.pdf")
    return out


def _kumagaya_patterns() -> list[str]:
    """熊谷基地: 複数命名形式 (ルート直下)
    - R{ry}_{mm}[suffix].pdf (GCC, PA, VCC_2, _2, _3, RRRR, etc.)
    - R{ry}.{mm}.pdf (ドット形式)
    - op_bupin{YYYYMM}.pdf
    """
    out: set[str] = set()
    for ry in range(4, 9):
        for mm in range(1, 13):
            # アンダースコア形式
            base = f"{BASE_KUMAGAYA}R{ry}_{mm}"
            out.add(f"{base}.pdf")
            for sfx in ("_GCC", "_PA", "_VCC_2", "_2", "_3", "_RRRR", "_R"):
                out.add(f"{base}{sfx}.pdf")
            # ドット形式
            out.add(f"{BASE_KUMAGAYA}R{ry}.{mm}.pdf")
    # op_bupin形式
    for yr in range(2022, 2026):
        for mm in range(1, 13):
            ym = f"{yr}{mm:02d}"
            ym2 = f"{yr}{mm}"
            out.add(f"{BASE_KUMAGAYA}op_bupin{ym}.pdf")
            out.add(f"{BASE_KUMAGAYA}op_bupin{ym2}.pdf")
            out.add(f"{BASE_KUMAGAYA}op_bupin{ym}_2.pdf")
            out.add(f"{BASE_KUMAGAYA}op_kokyo_construction{ym}.pdf")
            out.add(f"{BASE_KUMAGAYA}op_kokyo_constrution{ym}.pdf")  # typo variant
    return sorted(out)


# FY2024 横田基地の既知ファイル（掲載日プレフィックス付き）
_YOKOTA_FY2024 = [
    "060516_chotatsuApr06.pdf",
    "060701_chotatsuMay06.pdf",
    "060815_chotatsuJun06.pdf",
    "060906_chotatsuJul06.pdf",
    "061003_chotatsuAug06.pdf",
    "061106_chotatsuSep06.pdf",
    "061210_chotatsuOct06.pdf",  # 404の可能性あり
    "070107_chotatsuNov06.pdf",  # 404の可能性あり
    "070206_chotatsuDec06.pdf",
    "070306_chotatsuJan07.pdf",
    "070407_chotatsuFeb07.pdf",
    # Mar07 is FY2024も含む可能性
    "070507_chotatsuMar07.pdf",
]

ASDF_AGENCIES: list[dict] = [
    # ══════════════════════════════════════
    # 大規模機関
    # ══════════════════════════════════════

    # 1. 第2補給処（最大規模 Excel月次）
    {
        "agency_id": "asdf_2dep",
        "agency_name": "第2補給処",
        "index_urls": [
            "https://www.mod.go.jp/asdf/2dep/pdf/koukyo/",
        ],
        "url_patterns": _2dep_patterns(),
        "source_format": "excel",
    },

    # 2. 第3補給処（Excel + WARP必須）
    # WARP coll=20250510 / ts=20250509054434 (深夜クロールのため日付またぎ)
    # 構造: koukyou_excell/nyuusatu/kouhyou-n-{RYMM}.xlsx (競争)
    #        koukyou_excell/zuikei/kouhyou-z-{RYMM}.xlsx (随意)
    {
        "agency_id": "asdf_3dep",
        "agency_name": "第3補給処",
        "index_urls": [
            WARP_BASE_3DEP,
            WARP_BASE_3DEP + "koukyou_excell/nyuusatu/",
            WARP_BASE_3DEP + "koukyou_excell/zuikei/",
        ],
        "url_patterns": _3dep_warp_patterns(),
        "source_format": "excel",
        "is_warp": True,
    },

    # 3. 第4補給処（PDF: kouhyou.html からリンク収集）
    # rakusatu{RY}.{MM}.pdf / rakusatsu{RY}.{MM}.pdf (命名ゆれあり)
    {
        "agency_id": "asdf_4dep",
        "agency_name": "第4補給処",
        "index_urls": [
            "https://www.mod.go.jp/asdf/4dep/kouhyou.html",
        ],
        "url_patterns": [],
    },

    # 4. 市ヶ谷基地（航空幕僚監部系 大規模）
    # tyoutatsu1: 124 PDFs (入札公告・落札結果), tyoutatsu2: 14 PDFs
    {
        "agency_id": "asdf_ichigaya",
        "agency_name": "市ヶ谷基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/ichigaya/tyoutatsu/tyoutatsu1/index.html",
            "https://www.mod.go.jp/asdf/ichigaya/tyoutatsu2/index.html",
            "https://www.mod.go.jp/asdf/ichigaya/hoka/hoka.htm",
        ],
        "url_patterns": [],
    },

    # ══════════════════════════════════════
    # 中規模基地（PDF・インデックス）
    # ══════════════════════════════════════

    # 5. 千歳基地（/acs/ 複数命名形式）
    {
        "agency_id": "asdf_chitose",
        "agency_name": "千歳基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/chitose/acs/",
        ],
        "url_patterns": _chitose_patterns(),
    },

    # 6. 三沢基地（/offer/public_offering/kouhyou/R{ry}{mm:02d}.pdf）
    # FY2022/2023 (R4/R5) は通常PDF → 収集可能
    # FY2024 (R6) は画像PDF → パース失敗で0件になるが無害
    # FY2025 (R7) の一部は通常PDF確認済み (R706,R711,R712)
    {
        "agency_id": "asdf_misawa",
        "agency_name": "三沢基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/misawa/offer/public_offering/kouhyou/",
        ],
        "url_patterns": [
            f"https://www.mod.go.jp/asdf/misawa/offer/public_offering/kouhyou/R{ry}{mm:02d}.pdf"
            for ry in range(4, 9) for mm in range(1, 13)
        ],
    },

    # 7. 入間基地（/bosyu/raising/images/ 月次PDF）
    {
        "agency_id": "asdf_iruma",
        "agency_name": "入間基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/iruma/bosyu/raising/images/",
        ],
        "url_patterns": _iruma_patterns(),
    },

    # 8. 松島基地（/tyotatu/kouhyou/images/ 複数命名形式）
    # images/ は HTTP 403 → kouhyou/ (200) でリンク一覧取得
    {
        "agency_id": "asdf_matsushima",
        "agency_name": "松島基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/matsushima/tyotatu/kouhyou/",
        ],
        "url_patterns": _matsushima_patterns(),
    },

    # 9. 百里基地（/acs/2-7_procurement/kouhyou/ 月次PDF）
    # 注: 元DBのURLは // (二重スラッシュ) だが単一スラッシュで試みる
    {
        "agency_id": "asdf_hyakuri",
        "agency_name": "百里基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/hyakuri/acs/2-7_procurement/kouhyou/",
            "https://www.mod.go.jp/asdf/hyakuri/acs/2-7_procurement//kouhyou/",
        ],
        "url_patterns": _hyakuri_patterns(),
    },

    # 10. 小松基地（/6/third/chotatsu_pdf/kouhyou/kou{ry}.{mm}.pdf）
    {
        "agency_id": "asdf_komatsu",
        "agency_name": "小松基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/komatsu/6/third/chotatsu_pdf/kouhyou/",
        ],
        "url_patterns": _komatsu_patterns(),
    },

    # 11. 岐阜基地（/acd/サブディレクトリ: FY2024 11-3月は削除済み404, FY2025〜は取得可能）
    # 注: R611choko2, R612choko2, R701choko, R702choko2 は削除確認済み(2026-04-30)
    {
        "agency_id": "asdf_gifu",
        "agency_name": "岐阜基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/gifu/acd/",
        ],
        "url_patterns": _gifu_acd_patterns(),
    },

    # 12. 浜松基地（掲載日ベース月次PDF: /choutatsu/koukoku/r6kokyo{YYYYMMDD}.pdf）
    {
        "agency_id": "asdf_hamamatsu",
        "agency_name": "浜松基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/hamamatsu/choutatsu/koukoku/",
        ],
        "url_patterns": _hamamatsu_patterns(),
    },

    # 13. 横田基地（月別PDFパターン）
    {
        "agency_id": "asdf_yokota",
        "agency_name": "横田基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/yokota/",
        ],
        "url_patterns": [
            BASE_YOKOTA + fname for fname in _YOKOTA_FY2024
        ],
    },

    # ══════════════════════════════════════
    # HTML テーブル機関
    # ══════════════════════════════════════

    # 14. 小牧基地（Excel Web Archive HTML: chotatsu.files/sheet003.htm）
    {
        "agency_id": "asdf_komaki",
        "agency_name": "小牧基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/komaki/tyoutatu/chotatsu/chotatsu.files/sheet003.htm",
        ],
        "url_patterns": [],
        "scrape_html_tables": True,
    },

    # 15. 木更津分屯基地（HTML: /acs/index.html）
    {
        "agency_id": "asdf_kisarazu",
        "agency_name": "木更津分屯基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/kisarazu/acs/index.html",
        ],
        "url_patterns": [],
        "scrape_html_tables": True,
    },

    # ══════════════════════════════════════
    # 小規模基地（PDF・インデックス）
    # ══════════════════════════════════════

    # 16. 新潟分屯基地（/procurement/third/images/kouhyou_pdf/{YYMM}.pdf）
    {
        "agency_id": "asdf_niigata",
        "agency_name": "新潟分屯基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/niigata/procurement/third/images/kouhyou_pdf/",
        ],
        "url_patterns": _niigata_patterns(),
    },

    # 17. 府中基地（/acs/jyoho/kisho{ry}-j{mm}[kekka].pdf）
    {
        "agency_id": "asdf_fuchu",
        "agency_name": "府中基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/fuchu/acs/jyoho/",
        ],
        "url_patterns": _fuchu_patterns(),
    },

    # 18. 奈良基地（/05procurement/03release/images/01kokyo/{RYMMDD}.pdf）
    {
        "agency_id": "asdf_nara",
        "agency_name": "奈良基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/nara/05procurement/03release/images/01kokyo/",
        ],
        "url_patterns": _nara_patterns(),
    },

    # 19. 築城基地（/choutatsu/cyoutatujyouhou/r{ry}/{mm}.pdf）
    {
        "agency_id": "asdf_tsuiki",
        "agency_name": "築城基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/tsuiki/choutatsu/cyoutatujyouhou/",
        ],
        "url_patterns": _tsuiki_patterns(),
    },

    # 20. 防府北基地（/choutatsu/kekka_0{ry}.html HTMLテーブル）
    {
        "agency_id": "asdf_hofukita",
        "agency_name": "防府北基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/hofukita/choutatsu/kekka_05.html",
            "https://www.mod.go.jp/asdf/hofukita/choutatsu/kekka_06.html",
            "https://www.mod.go.jp/asdf/hofukita/choutatsu/kekka_07.html",
            "https://www.mod.go.jp/asdf/hofukita/choutatsu/kekka_08.html",
        ],
        "url_patterns": [],
        "scrape_html_tables": True,
    },

    # 21. 防府南基地（月次PDFパターン）
    {
        "agency_id": "asdf_hofuminami",
        "agency_name": "防府南基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/hofuminami/",
            "https://www.mod.go.jp/asdf/hofuminami/koukoku/kohyo/",
        ],
        "url_patterns": _hofuminami_patterns(),
    },

    # 22. 美保基地（単一HTML: /kaikeitai_tyoutatu/choutatujouhou.html）
    {
        "agency_id": "asdf_miho",
        "agency_name": "美保基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/miho/kaikeitai_tyoutatu/choutatujouhou.html",
        ],
        "url_patterns": [],
        "scrape_html_tables": True,
    },

    # 23. 熊谷基地（ルート直下 複数命名形式 + HTML）
    {
        "agency_id": "asdf_kumagaya",
        "agency_name": "熊谷基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/kumagaya/",
        ],
        "url_patterns": _kumagaya_patterns(),
    },

    # 24. 静浜基地（/choutatsu/pdf/koukyoutyoutatuR{ry}_{mm}.pdf）
    {
        "agency_id": "asdf_shizuhama",
        "agency_name": "静浜基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/shizuhama/choutatsu/pdf/",
        ],
        "url_patterns": _shizuhama_patterns(),
    },

    # 25. 秋田分屯基地（/sp/choutatsu/pdf/R{ry}tekiseika{mm}.pdf）
    {
        "agency_id": "asdf_akita",
        "agency_name": "秋田分屯基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/akita/sp/choutatsu/pdf/",
        ],
        "url_patterns": _akita_patterns(),
    },

    # 26. 目黒基地（/choutatsu/pdf/tekisei-{mm}.pdf）
    {
        "agency_id": "asdf_meguro",
        "agency_name": "目黒基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/meguro/choutatsu/pdf/",
        ],
        "url_patterns": _meguro_patterns(),
    },

    # 27. 芦屋基地（画像PDF → スキップ）
    {
        "agency_id": "asdf_ashiya",
        "agency_name": "芦屋基地",
        "index_urls": [],
        "url_patterns": [],
        "skip": True,
        "skip_reason": "全ファイル画像スキャンPDF（OCR必要）",
    },

    # 28. 春日基地（second/kaikei/ が403 → 収集不可確定）
    # 原DB: 0件。tyoutatujyouhou.htm は入札結果PDFのみ（画像PDF工事系）
    {
        "agency_id": "asdf_kasuga",
        "agency_name": "春日基地",
        "index_urls": [],
        "url_patterns": [],
        "skip": True,
        "skip_reason": "second/kaikei/ 403・標準公表書式ページ未発見",
    },

    # 29. 新田原基地（月次PDFパターン）
    {
        "agency_id": "asdf_nyutabaru",
        "agency_name": "新田原基地",
        "index_urls": [
            "https://www.mod.go.jp/asdf/nyutabaru/08cyoutatsu/pdf/tekiseika/",
        ],
        "url_patterns": _nyutabaru_patterns(),
    },
]


if __name__ == "__main__":
    total_patterns = sum(len(a.get("url_patterns", [])) for a in ASDF_AGENCIES)
    print(f"機関数: {len(ASDF_AGENCIES)}")
    print(f"URLパターン合計: {total_patterns}")
    for a in ASDF_AGENCIES:
        n = len(a.get("url_patterns", []))
        skip = " [SKIP]" if a.get("skip") else ""
        warp = " [WARP]" if a.get("is_warp") else ""
        html = " [HTML]" if a.get("scrape_html_tables") else ""
        fmt = f" [{a.get('source_format','pdf').upper()}]" if a.get("source_format","pdf") != "pdf" else ""
        print(f"  {a['agency_id']:<22} patterns={n:>4}{skip}{warp}{html}{fmt}")
