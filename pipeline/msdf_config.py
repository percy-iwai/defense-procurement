"""海上自衛隊 (MSDF) 各機関のソースURL設定。

ライブURLは「ローリングウィンドウ」方式（補給処系）と安定（小規模基地）が混在。
履歴データはWARP（warp.ndl.go.jp）またはWayback（web.archive.org）スナップショットから取得。

WARP/Wayback URL 形式:
  https://warp.ndl.go.jp/{coll}/{ts}id_/{url}
  https://web.archive.org/web/{ts}id_/{url}
"""
from __future__ import annotations

# ── ヘルパー: WARP/Wayback URL 構築 ────────────────────
def _warp(ts: str, url: str, coll: str | None = None) -> str:
    coll = coll or ts[:8]
    return f"https://warp.ndl.go.jp/{coll}/{ts}id_/{url}"


def _wb(ts: str, url: str) -> str:
    return f"https://web.archive.org/web/{ts}id_/{url}"


# ── 小規模基地（直接URL、WARP不要） ──────────────────────
# CLAUDE.md より: msdf_k4/sk/d1/k1/sa/s1 は直接取得可
SMALL_BASES = [
    {
        "agency_id": "msdf_k4",
        "agency_name": "第31整備補給隊",
        "category_mid": "呉地方総監部",
        "category_sub": "第31整備補給隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/k4/nyuusatsu/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/k4/nyuusatsu/RAKUSATSU_B.xlsx",
        ],
    },
    {
        "agency_id": "msdf_sk",
        "agency_name": "沖縄基地隊",
        "category_mid": "佐世保地方総監部",
        "category_sub": "沖縄基地隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/RAKUSATSU_B.xlsx",
        ],
        "warp_urls": [
            # FY2024前半（4月〜9月）
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/RAKUSATSU_B.xlsx"),
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/ZUIKEI_B.xlsx"),
            # FY2024後半（〜2025-03）
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/RAKUSATSU_B.xlsx"),
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/ZUIKEI_B.xlsx"),
            # FY2024完結スナップ
            _warp("20250605184840", "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/RAKUSATSU_B.xlsx"),
            _warp("20250605184840", "https://www.mod.go.jp/msdf/bukei/sk/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_d1",
        "agency_name": "函館基地隊",
        "category_mid": "大湊地方総監部",
        "category_sub": "函館基地隊",
        # 個別ファイル番号方式 (HTMLから抽出)
        "live_urls": [
            f"https://www.mod.go.jp/msdf/bukei/d1/nyuusatsu/03-0-0000-0000-{n:04d}.xlsx"
            for n in [1, 2, 3, 4, 6, 8, 13, 14, 15, 16, 18]
        ] + [
            "https://www.mod.go.jp/msdf/bukei/d1/RAKUSATSU_B.xlsx",
        ],
        "warp_urls": [
            # FY2024前半
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/d1/RAKUSATSU_B.xlsx"),
            # FY2024後半
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/d1/RAKUSATSU_B.xlsx"),
            # FY2024完結
            _warp("20250705083548", "https://www.mod.go.jp/msdf/bukei/d1/RAKUSATSU_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_k1",
        "agency_name": "阪神基地隊",
        "category_mid": "舞鶴地方総監部",
        "category_sub": "阪神基地隊",
        # keiyakukeka/ サブディレクトリ（nyuusatsu/ ではない）
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/k1/keiyakukeka/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/k1/keiyakukeka/RAKUSATSU_B.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/k1/keiyakukeka_main_K1.html",
            "https://www.mod.go.jp/msdf/bukei/k1/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/k1/keiyakukeka/kk_jiseki.html",
        ],
    },
    # ── 追加: 大湊系小規模基地 ──────────────────
    {
        "agency_id": "msdf_dw",
        "agency_name": "稚内基地分遣隊",
        "category_mid": "大湊地方総監部",
        "category_sub": "稚内基地分遣隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/dw/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/dw/ZUIKEI_B.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/dw/keiyakukeka_main_DW.html",
            "https://www.mod.go.jp/msdf/bukei/dw/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/dw/keiyakukeka/kk_jiseki.html",
        ],
    },
    {
        "agency_id": "msdf_dy",
        "agency_name": "余市防衛隊本部",
        "category_mid": "大湊地方総監部",
        "category_sub": "余市防衛隊本部",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/dy/nyuusatsu/RAKUSATSU_B.xls",
            "https://www.mod.go.jp/msdf/bukei/dy/nyuusatsu/ZUIKEI_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/dy/keiyakukeka_main_DY.html",
            "https://www.mod.go.jp/msdf/bukei/dy/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/dy/keiyakukeka/kk_jiseki.html",
        ],
    },
    # ── 追加: 横須賀系小規模基地 ─────────────────
    {
        "agency_id": "msdf_y6",
        "agency_name": "厚木航空基地隊",
        "category_mid": "横須賀地方総監部",
        "category_sub": "厚木航空基地隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/y6/nyuusatsu/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/y6/nyuusatsu/RAKUSATSU_B.xlsx",
        ],
        # y6: kg/kk_jiseki.html はキャリ keiyakukeka/ 配下と root の両方にある
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/y6/keiyakukeka_main_Y6.html",
            "https://www.mod.go.jp/msdf/bukei/y6/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y6/kk_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y6/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y6/keiyakukeka/kk_jiseki.html",
        ],
        "warp_urls": [
            # FY2024 月次スナップ（y0と同パターン）
            *[_warp(ts, "https://www.mod.go.jp/msdf/bukei/y6/nyuusatsu/RAKUSATSU_B.xlsx")
              for ts in [
                  "20240110044353", "20240207142742", "20240307133606", "20240407071815",
                  "20240507065526", "20240608034532", "20240708061105", "20240807163911",
                  "20240907173557", "20241006101914", "20241105222410", "20241206014804",
              ]],
            # FY2024完結スナップ（ZUIKEI_B は累積ファイル）
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/y6/nyuusatsu/ZUIKEI_B.xlsx"),
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/y6/nyuusatsu/RAKUSATSU_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_y2",
        "agency_name": "館山航空基地隊",
        "category_mid": "横須賀地方総監部",
        "category_sub": "館山航空基地隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/y2/nyuusatsu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/y2/nyuusatsu/ZUIKEI_B.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/y2/keiyakukeka_main_Y2.html",
            "https://www.mod.go.jp/msdf/bukei/y2/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y2/kk_jiseki.html",
        ],
    },
    # ── 追加: 呉系小規模基地 ────────────────────
    {
        "agency_id": "msdf_k2",
        "agency_name": "徳島航空基地隊",
        "category_mid": "呉地方総監部",
        "category_sub": "徳島航空基地隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/k2/nyuusatsu/ZUIKEI_B.xls",
            "https://www.mod.go.jp/msdf/bukei/k2/nyuusatsu/RAKUSATSU_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/k2/keiyakukeka_main_K2.html",
            "https://www.mod.go.jp/msdf/bukei/k2/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/k2/keiyakukeka/kk_jiseki.html",
        ],
    },
    {
        "agency_id": "msdf_k7",
        "agency_name": "第24航空隊",
        "category_mid": "呉地方総監部",
        "category_sub": "第24航空隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/k7/nyuusatsu/ZUIKEI_B.xls",
            "https://www.mod.go.jp/msdf/bukei/k7/nyuusatsu/RAKUSATSU_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/k7/keiyakukeka_main_K7.html",
            "https://www.mod.go.jp/msdf/bukei/k7/kg_jiseki.html",  # k7 は root配下
            "https://www.mod.go.jp/msdf/bukei/k7/kk_jiseki.html",
        ],
    },
    {
        "agency_id": "msdf_s3",
        "agency_name": "第201整備補給隊",
        "category_mid": "呉地方総監部",
        "category_sub": "第201整備補給隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/ZUIKEI_B.xlsx",
        ],
        "warp_urls": [
            # FY2024前半
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/RAKUSATSU_B.xlsx"),
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/ZUIKEI_B.xlsx"),
            # FY2024後半
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/RAKUSATSU_B.xlsx"),
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/ZUIKEI_B.xlsx"),
            # FY2024完結
            _warp("20250605184652", "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/RAKUSATSU_B.xlsx"),
            _warp("20250605184652", "https://www.mod.go.jp/msdf/bukei/s3/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
    },
    # ── 追加: 佐世保系小規模基地 ─────────────────
    {
        "agency_id": "msdf_st",
        "agency_name": "対馬防備隊本部",
        "category_mid": "佐世保地方総監部",
        "category_sub": "対馬防備隊本部",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/st/nyuusatsu/RAKUSATSU_K.xls",
            "https://www.mod.go.jp/msdf/bukei/st/nyuusatsu/RAKUSATSU_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/st/keiyakukeka_main_ST.html",
            "https://www.mod.go.jp/msdf/bukei/st/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/st/keiyakukeka/kk_jiseki.html",
        ],
    },
    {
        "agency_id": "msdf_s2",
        "agency_name": "鹿屋航空基地隊",
        "category_mid": "佐世保地方総監部",
        "category_sub": "鹿屋航空基地隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/s2/nyuusatsu/ZUIKEI_B.xls",
            "https://www.mod.go.jp/msdf/bukei/s2/nyuusatsu/RAKUSATSU_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/s2/keiyakukeka_main_S2.html",
            "https://www.mod.go.jp/msdf/bukei/s2/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/s2/keiyakukeka/kk_jiseki.html",
        ],
    },
    {
        "agency_id": "msdf_sn",
        "agency_name": "那覇航空基地隊",
        "category_mid": "佐世保地方総監部",
        "category_sub": "那覇航空基地隊",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/sn/keiyakukeka/RAKUSATSU_B.xls",
            "https://www.mod.go.jp/msdf/bukei/sn/keiyakukeka/ZUIKEI_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/sn/keiyakukeka_main_SN.html",
        ],
    },
    {
        "agency_id": "msdf_sa",
        "agency_name": "奄美基地分遣隊",
        "category_mid": "佐世保地方総監部",
        "category_sub": "奄美基地分遣隊",
        # ZUIKEI は .xls
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/sa/nyuusatsu/ZUIKEI_B.xls",
            "https://www.mod.go.jp/msdf/bukei/sa/nyuusatsu/RAKUSATSU_B.xlsx",
        ],
    },
    {
        "agency_id": "msdf_s1",
        "agency_name": "下関基地隊",
        "category_mid": "呉地方総監部",
        "category_sub": "下関基地隊",
        # s1 は keiyakusyorui.xlsx + 旧 .xls 形式
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/s1/nyuusatsu/keiyakusyorui.xlsx",
            "https://www.mod.go.jp/msdf/bukei/s1/nyuusatsu/ZUIKEI_B.xls",
            "https://www.mod.go.jp/msdf/bukei/s1/nyuusatsu/RAKUSATSU_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/s1/keiyakukeka_main_S1.html",
            "https://www.mod.go.jp/msdf/bukei/s1/keiyakukeka/kg_jiseki.html",
        ],
    },
]


# ── 主要8機関（ローリングウィンドウ→WARP/Wayback必須） ──
# ライブURLでは最新月分しか取れない。歴史データはCLAUDE.md記載のスナップショットから
MAJOR_AGENCIES = [
    {
        "agency_id": "msdf_y0",
        "agency_name": "横須賀地方総監部",
        "category_mid": "横須賀地方総監部",
        "category_sub": "",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/RAKUSATSU_K.xlsx",
            "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/ZUIKEI_B.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/y0/keiyakukeka_main_Y0.html",
            "https://www.mod.go.jp/msdf/bukei/y0/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y0/keiyakukeka/kk_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y0/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/y0/kk_jiseki.html",
        ],
        # FY2024 月別 WARP スナップ（CLAUDE.md 確認済み）
        "warp_urls": [
            # RAKUSATSU_B 月別
            *[_warp(ts, "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/RAKUSATSU_B.xlsx")
              for ts in [
                  "20240110044353","20240207142742","20240307133606","20240407071815",
                  "20240507065526","20240608034532","20240708061105","20240807163911",
                  "20240907173557","20241006101914","20241105222410","20241206014804",
              ]],
            # ZUIKEI_B 最新スナップ (FY2024確認済み)
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
        # FY2022/2023 はWayback
        "wayback_urls": [
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/RAKUSATSU_B.xlsx"),
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/y0/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_k0",
        "agency_name": "呉地方総監部",
        "category_mid": "呉地方総監部",
        "category_sub": "",
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/RAKUSATSU_K.xlsx",
            "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/ZUIKEI_K.xlsx",
        ],
        "warp_urls": [
            *[_warp(ts, "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/RAKUSATSU_B.xlsx")
              for ts in [
                  "20240207142858","20240307133753","20240407071936","20240507065704",
                  "20240608034716","20240708061257","20240807164051","20240907173734",
                  "20241006102053","20241105222559","20241206014942",
              ]],
            _warp("20250605184652", "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
        "wayback_urls": [
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/RAKUSATSU_B.xlsx"),
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/k0/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_s0",
        "agency_name": "佐世保地方総監部",
        "category_mid": "佐世保地方総監部",
        "category_sub": "",
        # CLAUDE.md: s0 は .xls (旧形式), root直下 (no nyuusatsu/)
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/s0/RAKUSATSU_B.xls",
            "https://www.mod.go.jp/msdf/bukei/s0/RAKUSATSU_K.xls",
            "https://www.mod.go.jp/msdf/bukei/s0/ZUIKEI_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/s0/keiyakukeka_main_S0.html",
            "https://www.mod.go.jp/msdf/bukei/s0/keiyakukeka/kk_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/s0/kk_jiseki.html",  # root: 12 PDFs
        ],
        "warp_urls": [
            _warp("20241006101840", "https://www.mod.go.jp/msdf/bukei/s0/RAKUSATSU_B.xls"),
            _warp("20250605184840", "https://www.mod.go.jp/msdf/bukei/s0/ZUIKEI_B.xls"),
        ],
        "wayback_urls": [
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/s0/RAKUSATSU_B.xls"),
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/s0/ZUIKEI_B.xls"),
        ],
    },
    {
        "agency_id": "msdf_m0",
        "agency_name": "舞鶴地方総監部",
        "category_mid": "舞鶴地方総監部",
        "category_sub": "",
        # nyuusatsu/ と keiyakukeka/ の2系統
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/m0/nyuusatsu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/m0/nyuusatsu/RAKUSATSU_K.xlsx",
            "https://www.mod.go.jp/msdf/bukei/m0/nyuusatsu/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/m0/nyuusatsu/ZUIKEI_K.xlsx",
            "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka/ZUIKEI_B.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka_main_M0.html",
            "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka/kk_jiseki.html",
        ],
        "warp_urls": [
            _warp("20250705083727", "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka/RAKUSATSU_B.xlsx"),
            _warp("20250705083727", "https://www.mod.go.jp/msdf/bukei/m0/keiyakukeka/ZUIKEI_B.xlsx"),
        ],
        "wayback_urls": [
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/m0/nyuusatsu/RAKUSATSU_B.xlsx"),
            _wb("20230226070917", "https://www.mod.go.jp/msdf/bukei/m0/nyuusatsu/ZUIKEI_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_d0",
        "agency_name": "大湊地方総監部",
        "category_mid": "大湊地方総監部",
        "category_sub": "",
        # CLAUDE.md: d0 のみ nyuusatu (no s)
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/RAKUSATSU_K.xlsx",
            "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/ZUIKEI_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/ZUIKEI_K.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/d0/keiyakukeka_main_D0.html",
            "https://www.mod.go.jp/msdf/bukei/d0/keiyakukeka/kk_jiseki.html",
        ],
        "warp_urls": [
            _warp("20250705083548", "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/ZUIKEI_B.xlsx"),
            _warp("20241006101842", "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/ZUIKEI_B.xlsx"),
            _warp("20241006101842", "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/RAKUSATSU_B.xlsx"),
        ],
        "wayback_urls": [
            _wb("20230226070924", "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/RAKUSATSU_B.xlsx"),
            _wb("20230226070924", "https://www.mod.go.jp/msdf/bukei/d0/nyuusatu/ZUIKEI_B.xlsx"),
        ],
    },
    {
        "agency_id": "msdf_t2",
        "agency_name": "補給本部",
        "category_mid": "補給本部",
        "category_sub": "",
        # xls (旧形式)
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls",
            "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_K.xls",
            "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/t2/keiyakukeka_main_T2.html",
            "https://www.mod.go.jp/msdf/bukei/t2/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/t2/keiyakukeka/kk_jiseki.html",
        ],
        "warp_urls": [
            # FY2024前半（4月〜9月）
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            # FY2024後半（〜1月）
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20250205000000", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            # FY2024完結（3月まで含む）
            _warp("20250602172338", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20250602172338", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            # FY2024 月次補完（追加スナップ）
            _warp("20240407071815", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20241006101914", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20241206014804", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
        ],
        "wayback_urls": [
            # FY2022
            _wb("20220515081303", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20221116152126", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20220515081303", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            _wb("20221116152126", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            # FY2023
            _wb("20230226070921", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20230813122748", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20230226070921", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            _wb("20230813122748", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            # FY2024 Wayback 月次補完（追加）
            _wb("20240511042127", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20240511042127", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            _wb("20250126021315", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20250126021315", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
            _wb("20250307231022", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20250307231022", "https://www.mod.go.jp/msdf/bukei/t2/nyuusatsu/ZUIKEI_B.xls"),
        ],
    },
    {
        "agency_id": "msdf_asd",
        "agency_name": "航空補給処",
        "category_mid": "航空補給処",
        "category_sub": "",
        # CLAUDE.md: zd path (not asd), nyusatsu (no extra u)
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx",
            "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_K.xlsx",
            "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/ZUIKEI_B.xlsx",
        ],
        "index_urls": [
            "https://www.mod.go.jp/msdf/bukei/zd/keiyakukeka_main_ZD.html",
            "https://www.mod.go.jp/msdf/bukei/zd/keiyakukeka/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/zd/keiyakukeka/kk_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/zd/kg_jiseki.html",
            "https://www.mod.go.jp/msdf/bukei/zd/kk_jiseki.html",
        ],
        "warp_urls": [
            _warp("20250602172346", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx"),
            _warp("20250602172346", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/ZUIKEI_B.xlsx"),
            _warp("20240505000000", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx"),
            _warp("20240905000000", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx"),
            # FY2022
            _warp("20221105000000", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx"),
            _warp("20221105000000", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/ZUIKEI_B.xlsx"),
            # FY2023
            _warp("20230505000000", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx"),
            _warp("20230505000000", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/ZUIKEI_B.xlsx"),
            # FY2024 月次スナップ補完（y0と同パターン、サイズ差分あり確認済み）
            *[_warp(ts, "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx")
              for ts in [
                  "20240407071815", "20240507065526", "20240608034532", "20240708061105",
                  "20240807163911", "20240907173557", "20241006101914", "20241105222410",
                  "20241206014804",
              ]],
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/ZUIKEI_B.xlsx"),
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/zd/nyusatsu/RAKUSATSU_B.xlsx"),
        ],
        "wayback_urls": [],
    },
    {
        "agency_id": "msdf_yd",
        "agency_name": "艦船補給処",
        "category_mid": "艦船補給処",
        "category_sub": "",
        # xls (旧形式)
        "live_urls": [
            "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls",
            "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/ZUIKEI_B.xls",
        ],
        "warp_urls": [
            _warp("20250602172338", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20250602172338", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/ZUIKEI_B.xls"),
            # FY2024
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls"),
            _warp("20241005000000", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/ZUIKEI_B.xls"),
            _warp("20240805000000", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls"),
            # FY2024 月次スナップ補完（サイズ差分あり確認済み）
            *[_warp(ts, "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls")
              for ts in [
                  "20240407071815", "20240507065526", "20240608034532", "20240708061105",
                  "20240807163911", "20240907173557", "20241006101914", "20241105222410",
                  "20241206014804",
              ]],
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/ZUIKEI_B.xls"),
            _warp("20250705083617", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls"),
        ],
        "wayback_urls": [
            _wb("20230225173329", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/RAKUSATSU_B.xls"),
            _wb("20230225173329", "https://www.mod.go.jp/msdf/bukei/yd/nyuusatsu/ZUIKEI_B.xls"),
        ],
    },
]


def all_agencies() -> list[dict]:
    return SMALL_BASES + MAJOR_AGENCIES


def all_sources(agency: dict) -> list[tuple[str, str]]:
    """Return [(url, source_kind)] — kind ∈ {'live','warp','wayback'}."""
    out = []
    for u in agency.get("live_urls", []):
        out.append((u, "live"))
    for u in agency.get("warp_urls", []) or []:
        out.append((u, "warp"))
    for u in agency.get("wayback_urls", []) or []:
        out.append((u, "wayback"))
    return out
