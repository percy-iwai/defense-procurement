"""カバレッジチェック画面 — FY別カバレッジ分析 + 機関 × 月別 契約件数ヒートマップ。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

# ── スタイル ─────────────────────────────────────────────
TEXT_COLOR = "#cdd6f4"
TEXT_DIM   = "#bac2de"
st.markdown(
    f"""
    <style>
    .stApp, .stApp p, .stApp span, .stApp label, .stApp th, .stApp td {{
        color: {TEXT_COLOR};
    }}
    .stApp h1, .stApp h2, .stApp h3 {{ color: {TEXT_COLOR}; }}
    [data-testid="stCaptionContainer"] {{ color: {TEXT_DIM} !important; }}
    /* ヒートマップ表の文字サイズを小さく */
    [data-testid="stDataFrame"] td {{ font-size: 0.78rem !important; }}
    [data-testid="stDataFrame"] th {{ font-size: 0.78rem !important; white-space: nowrap; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🗓️ カバレッジチェック")
st.caption("各セル = 当該機関×当該月の契約件数。赤 = 0件（データなし）。")

# ── FY別カバレッジ分析 ─────────────────────────────────────
st.subheader("📊 FY別 収録カバレッジ分析")

# 予算定数（各FY予算概要）
_BUDGET_BY_FY = {
    2022: 34_980,   # R4予算概要 yosan_20220324.pdf P.56
    2023: 89_525,   # R5決算（会計検査院報告）
    2024: 93_625,   # R6予算概要 yosan_20240328.pdf P.58
    2025: 84_332,   # R7予算概要 yosan_20250402.pdf P.66
}
_NON_CONTRACT_BY_FY = {
    2022:  2_800,   # FY2024実績(7,500)から予算規模比例推定（34,980/93,625）
    2023:  7_300,   # 比例推定から電算機借料(契約)を除外
    2024:  7_500,   # 行政事業レビューDB突合確定値（電算機借料=契約のため除外済み）
    2025:  7_600,   # 比例推定
}
_FUYOU_BY_FY = {
    2022:   500,
    2023: 1_300,    # 会計検査院R5決算検査報告: 計画対象経費の不用額1,294億円
    2024: 1_200,    # R6決算（2025-11公表）
    2025:  None,    # 未公表
}


@st.cache_data(ttl=300)
def _load_fy_amounts() -> dict[int, tuple[int, float]]:
    """FY → (件数, 収録額億円)"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT fiscal_year, COUNT(*), SUM(contract_amount) "
            "FROM contracts GROUP BY fiscal_year"
        ).fetchall()
    return {r[0]: (r[1], (r[2] or 0) / 1e8) for r in rows if r[0] in _BUDGET_BY_FY}


cov_data = _load_fy_amounts()

cov_rows = []
for fy in [2022, 2023, 2024, 2025]:
    cnt, amt = cov_data.get(fy, (0, 0.0))
    budget = _BUDGET_BY_FY.get(fy)
    nc = _NON_CONTRACT_BY_FY.get(fy, 0)
    fu = _FUYOU_BY_FY.get(fy) or 0
    base = budget - nc - fu if budget else None
    cov = amt / base * 100 if base and base > 0 else None
    cov_rows.append({
        "年度": f"FY{fy}",
        "収録件数": cnt,
        "収録額(億円)": round(amt),
        "予算物件費(億円)": budget,
        "非契約系控除": nc,
        "不用額控除": f"{fu:,}" if fu else "未公表",
        "実質母数(億円)": base,
        "カバレッジ率": f"{cov:.1f}%" if cov is not None else "—",
        "_cov": cov,
        "_base": base,
        "_amt": amt,
    })

cov_df_full = pd.DataFrame(cov_rows)
cov_df_disp = cov_df_full.drop(columns=["_cov", "_base", "_amt"])

cov_col1, cov_col2 = st.columns([2, 3])
with cov_col1:
    st.dataframe(
        cov_df_disp,
        use_container_width=True,
        hide_index=True,
        column_config={
            "収録件数":      st.column_config.NumberColumn(format="%d"),
            "収録額(億円)": st.column_config.NumberColumn(format="%d"),
            "予算物件費(億円)": st.column_config.NumberColumn(format="%d"),
            "不用額控除":   st.column_config.TextColumn(label="△不用額(未執行残)"),
            "実質母数(億円)": st.column_config.NumberColumn(format="%d"),
        },
    )
with cov_col2:
    fig_cov = go.Figure()
    # 収録額 bar
    fig_cov.add_bar(
        x=[r["年度"] for r in cov_rows],
        y=[r["_amt"] for r in cov_rows],
        name="収録額(億円)",
        marker_color="#a6e3a1",
        text=[f"{r['_amt']:,.0f}億" for r in cov_rows],
        textposition="inside",
    )
    # 未収録推定 bar
    fig_cov.add_bar(
        x=[r["年度"] for r in cov_rows],
        y=[max(0, (r["_base"] or 0) - r["_amt"]) for r in cov_rows],
        name="未収録推定",
        marker_color="#45475a",
        text=[
            f"{max(0,(r['_base'] or 0)-r['_amt']):,.0f}億"
            if (r["_base"] or 0) > r["_amt"] else ""
            for r in cov_rows
        ],
        textposition="inside",
    )
    # カバレッジ率ライン (y2)
    fig_cov.add_scatter(
        x=[r["年度"] for r in cov_rows],
        y=[r["_cov"] for r in cov_rows],
        name="カバレッジ率(%)",
        mode="lines+markers+text",
        line=dict(color="#fab387", width=3),
        marker=dict(size=10),
        text=[f"{r['_cov']:.1f}%" if r["_cov"] else "—" for r in cov_rows],
        textposition="top center",
        yaxis="y2",
    )
    fig_cov.update_layout(
        template="plotly_dark", height=340, barmode="stack",
        yaxis=dict(title="億円"),
        yaxis2=dict(title="カバレッジ率(%)", overlaying="y", side="right",
                    showgrid=False, range=[0, 120]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig_cov, use_container_width=True)

st.caption(
    "**カバレッジ率** = 収録額 ÷ 実質母数（物件費(契約ベース) − 非契約系 − 不用額）。"
    "FY2023不用額: 会計検査院R5決算検査報告（計画対象経費1,294億円）。"
    "非契約系: HNS・光熱水料・補助金・借料等（FY2024実績7,500億からFY2023は予算規模比例推定）。"
    "FY2025不用額は未公表のため0として計算。"
    "出典: 防衛省予算概要 R4〜R7 各年度版、会計検査院決算検査報告。"
)

with st.expander("📚 出典・算出根拠"):
    st.markdown("""
| 年度 | 予算物件費(契約ベース) | 出典 |
|------|-------:|------|
| FY2022 | 34,980億円 | 令和4年度予算概要 yosan_20220324.pdf P.56 |
| FY2023 | 89,525億円 | 令和5年度予算概要 yosan_20230328.pdf P.62 |
| FY2024 | 93,625億円 | 令和6年度予算概要 yosan_20240328.pdf P.58 |
| FY2025 | 84,332億円 | 令和7年度予算概要 yosan_20250402.pdf P.66 |

**FY2023 物件費(契約ベース) 89,525億円 内訳** (yosan_20230328.pdf P.62):

| 費目 | 金額(億円) | 構成比 |
|------|----------:|--------|
| 維持費等（修理費25,198含む） | 30,375 | 33.9% |
| 装備品等購入費 | 21,487 | 24.0% |
| 航空機購入費 | 9,552 | 10.7% |
| 研究開発費 | 8,968 | 10.0% |
| 施設整備費等 | 5,903 | 6.6% |
| 基地対策経費等 | 5,122 | 5.7% |
| その他（電子計算機等借料等） | 4,354 | 4.9% |
| 艦船建造費等 | 3,765 | 4.2% |
| **合計** | **89,525** | **100%** |

**△ 不用額（執行されなかった予算残）**:

| 年度 | 金額 | 根拠・主因 |
|------|-----:|----------|
| FY2022 | 500億円 | 概算 |
| FY2023 | 1,300億円 | 会計検査院R5決算検査報告（計画対象経費の不用額1,294億円）。主因: 航空機修理費減・人員不充足 |
| FY2024 | 1,200億円 | R6決算（2025-11公表）。主因: 競争入札落差・自衛隊員採用数不足 |
| FY2025 | 未公表 | — |

**△ 非契約系（財計第2017号対象外）**:

*FY2024 確定値 7,500億円内訳*（行政事業レビューDB突合、電算機借料=契約のため除外済み）:

| 費目 | 推定額 | 主な内容 |
|------|-------:|---------|
| 基地対策経費等 | ~3,300億 | HNS（同盟強靱化予算）・補助金・交付金・賃金・借料（RS 15事業から分類） |
| 光熱水料等（営舎費中） | ~1,624億 | 電力・水道（月次少額、公表閾値以下） |
| 借料（施設用地地代・漁業補償） | ~1,345億 | 防衛施設用地の民有地地主への地代＋漁業補償（訓練海域）（P.49: 「防衛施設用地等の借上経費、水面を使用して訓練を行うことによる漁業補償等」） |
| 補助金①装備移転等 | ~400億 | 防衛装備移転三原則に基づく輸出支援補助金 |
| 補助金②サイバー防衛 | ~71億 | サイバーセキュリティ対策補助金 |
| 補助金③GIGO | ~42億 | 地方公共団体情報システム標準化補助金（防衛省分） |
| 教育訓練費 | ~390億 | 研修参加費・謝金・小額委託 |
| 医療費等 | ~320億 | 社会保険診療報酬支払基金経由 |
| **合計** | **≈7,500億** | |

*FY2023 推定値 7,300億円内訳*（一般物件費 yosan_20230328.pdf P.60 + 推定）:

| 費目 | 推定額 | 内訳 |
|------|-------:|------|
| HNS（同盟強靱化予算/在日米軍駐留経費負担） | ~2,000億 | 基地対策経費中（一般物件費: 1,922億） |
| 光熱水料等（営舎費中） | ~1,600億 | 光熱水料・燃料費（月次少額、公表閾値以下） |
| 基地借料・漁業補償 | ~1,500億 | 防衛施設用地地主への地代＋漁業補償（一般物件費: 施設の借料・補償経費等1,455億のうち借料分） |
| 補助金①装備移転（P.37確認）| ~400億 | 防衛装備移転推進のための基金・補助金（FY2023: 400億、FY2024と同額） |
| 補助金②基地周辺対策等 | ~1,100億 | 住宅防音補助・周辺環境整備交付金・周辺整備調整交付金等 |
| 教育訓練費・医療費等 | ~700億 | 研修参加費・謝金・診療報酬 |
| **合計** | **≈7,300億** | ※電算機借料等は財計2017号対象の調達契約のため除外 |
    """)

st.divider()

if not DB_PATH.exists():
    st.error("DBが見つかりません")
    st.stop()


# ── データロード ─────────────────────────────────────────
@st.cache_data(ttl=120)
def _load_monthly() -> pd.DataFrame:
    """契約の種別を「公共工事」「物品・役務」に分類。

    判別基準: ソースファイル名・URLパスで判定（防衛省の公表慣行に準拠）
      - `_K.xls(x)` (Kouji) / `_kouji` / `kouji_` / `nyusatsu_kouji` / `zuikei_kouji`
        / `koujijiltuseki` / `koukoku/kouji` を含む → 公共工事
      - 上記に該当しないもの → 物品・役務
    contract_type / contract_name のキーワードはフォールバックのみ。
    """
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT
                agency_id,
                agency_name,
                agency_category,
                fiscal_year,
                substr(contract_date, 1, 4) || '-' || substr(contract_date, 5, 2) AS ym,
                CASE
                  -- ソースファイル/URLパス判定（防衛省命名規則ベース、広めに包摂）
                  WHEN lower(source_url) LIKE '%_k.xlsx%'        -- _K.xlsx (Kouji)
                    OR lower(source_url) LIKE '%_k.xls%'         -- _K.xls
                    OR lower(source_url) LIKE '%/kouji/%'        -- /kouji/
                    OR lower(source_url) LIKE '%kouji-%'         -- kouji-
                    OR lower(source_url) LIKE '%kouji_%'         -- kouji_
                    OR lower(source_url) LIKE '%_kouji%'         -- _kouji
                    OR lower(source_url) LIKE '%-kouzi%'         -- -kouzi (古い表記)
                    OR lower(source_url) LIKE '%_kouzi%'
                    OR lower(source_url) LIKE '%/kouzi/%'
                    OR lower(source_url) LIKE '%kensetukouzi%'   -- 建設工事 (北部方面)
                    OR lower(source_url) LIKE '%kensetsu_kouji%'
                    OR lower(source_url) LIKE '%koujijiltuseki%' -- 工事実績
                    OR lower(source_url) LIKE '%mafin/k/%'       -- 中部方面会計隊 /k/ ディレクトリ
                    OR lower(source_url) LIKE '%/info/k%'        -- 東部方面 (zuikei_kouji 等を別パスで)
                    OR lower(source_url) LIKE '%nyusatsu_kouji%'
                    OR lower(source_url) LIKE '%zuikei_kouji%'
                    OR lower(source_url) LIKE '%kg_jiseki%'      -- 工 jiseki
                    OR lower(source_url) LIKE '%/kouji-%'
                    OR lower(source_url) LIKE '%-kouji.pdf%'
                    THEN '公共工事'
                  -- contract_type に「工事」明示
                  WHEN contract_type LIKE '%工事%' THEN '公共工事'
                  -- フォールバック: 一括公表ファイル内の混在ケース
                  WHEN contract_name LIKE '%工事%'
                       AND contract_name NOT LIKE '%製造請負%'
                       AND contract_name NOT LIKE '%建造%'
                       AND contract_name NOT LIKE '%付帯工事%'  -- 付帯工事は本契約に従属
                       THEN '公共工事'
                  ELSE '物品・役務'
                END                          AS kind,
                COUNT(*)                     AS cnt
            FROM contracts
            WHERE contract_date IS NOT NULL
              AND length(contract_date) >= 6
              AND fiscal_year IS NOT NULL
            GROUP BY agency_id, agency_name, agency_category, fiscal_year, ym, kind
            """,
            conn,
        )


@st.cache_data(ttl=120)
def _load_all_agencies() -> pd.DataFrame:
    """DB に存在する全機関一覧（contract_date がなくても agency_id があれば登録）。"""
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT DISTINCT agency_id, agency_name, agency_category
            FROM contracts
            ORDER BY agency_category, agency_id
            """,
            conn,
        )


@st.cache_data(ttl=120)
def _load_no_date_counts() -> pd.DataFrame:
    """contract_date が NULL の件数（機関別）。"""
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT agency_id, COUNT(*) AS no_date_cnt
            FROM contracts
            WHERE contract_date IS NULL
            GROUP BY agency_id
            """,
            conn,
        )


raw       = _load_monthly()
agencies  = _load_all_agencies()
no_date   = _load_no_date_counts()

# ── フィルタ UI ──────────────────────────────────────────
fy_all = sorted(raw["fiscal_year"].dropna().unique().tolist(), reverse=True)
cat_all = sorted(agencies["agency_category"].dropna().unique().tolist())

col_fy, col_cat, col_kind, col_opt = st.columns([3, 3, 2, 2])
with col_fy:
    sel_fy = st.multiselect("年度", fy_all, default=fy_all, key="cov_fy")
with col_cat:
    sel_cat = st.multiselect("カテゴリ", cat_all, default=cat_all, key="cov_cat")
with col_kind:
    sel_kind = st.radio(
        "種別",
        ["全体", "物品・役務", "公共工事"],
        index=0,
        horizontal=False,
        key="cov_kind",
    )
with col_opt:
    show_nodate = st.checkbox("日付なし件数列を表示", value=True, key="cov_nodate")
    show_total  = st.checkbox("月計列を表示", value=True, key="cov_total")

if not sel_fy:
    st.info("年度を選択してください")
    st.stop()

# ── 月列を構築 ───────────────────────────────────────────
months_ordered: list[str] = []
for fy in sorted(sel_fy):
    for mm in list(range(4, 13)) + list(range(1, 4)):
        cy = fy if mm >= 4 else fy + 1
        ym = f"{cy}-{mm:02d}"
        if ym not in months_ordered:
            months_ordered.append(ym)
months_ordered = sorted(set(months_ordered))  # 時系列順

# ── フィルタ適用 ─────────────────────────────────────────
filtered = raw[raw["fiscal_year"].isin(sel_fy)].copy()
if sel_kind in ("物品・役務", "公共工事"):
    filtered = filtered[filtered["kind"] == sel_kind]
agencies_f = agencies[agencies["agency_category"].isin(sel_cat)].copy()

# ── ピボット ─────────────────────────────────────────────
pivot = filtered.pivot_table(
    index=["agency_category", "agency_id", "agency_name"],
    columns="ym",
    values="cnt",
    aggfunc="sum",
    fill_value=0,
)

# 全機関（データなし機関も含む）
all_idx = pd.MultiIndex.from_arrays(
    [agencies_f["agency_category"], agencies_f["agency_id"], agencies_f["agency_name"]],
    names=["agency_category", "agency_id", "agency_name"],
)
pivot = pivot.reindex(index=all_idx, fill_value=0)

# 月列を揃える（対象月以外を除去、不足月は0）
for m in months_ordered:
    if m not in pivot.columns:
        pivot[m] = 0
pivot = pivot[months_ordered]

# カテゴリフィルタ
pivot = pivot.loc[
    pivot.index.get_level_values("agency_category").isin(sel_cat)
]

# ── 日付なし列・月計列を追加 ──────────────────────────────
pivot = pivot.reset_index()
pivot = pivot.sort_values(
    ["agency_category", "agency_id"]
).reset_index(drop=True)

if show_nodate:
    pivot = pivot.merge(no_date, on="agency_id", how="left")
    pivot["no_date_cnt"] = pivot["no_date_cnt"].fillna(0).astype(int)
if show_total:
    pivot["月計"] = pivot[months_ordered].sum(axis=1)

# ── 番号付け ─────────────────────────────────────────────
pivot.insert(0, "No.", range(1, len(pivot) + 1))

# ── 列名整理 ─────────────────────────────────────────────
rename_map = {
    "agency_category": "カテゴリ",
    "agency_id":       "機関ID",
    "agency_name":     "機関名",
}
if show_nodate:
    rename_map["no_date_cnt"] = "日付なし"
pivot = pivot.rename(columns=rename_map)

# ── スタイル定義 ─────────────────────────────────────────
def _cell_style(val: object) -> str:
    try:
        v = int(val)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return "background-color: #3b1111; color: #ff6b6b; font-weight: 600"
    if v < 5:
        return "background-color: #3b2b00; color: #ffd93d"
    if v < 30:
        return "background-color: #1a3a2a; color: #6bcb77"
    return "background-color: #0d2a18; color: #2edf78; font-weight: 600"


def _total_style(val: object) -> str:
    try:
        v = int(val)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return "background-color: #3b1111; color: #ff6b6b; font-weight: 700"
    return "background-color: #1a2540; color: #7c83fd; font-weight: 700"


style_cols = [c for c in months_ordered if c in pivot.columns]

styler = pivot.style.map(_cell_style, subset=style_cols)

if show_total and "月計" in pivot.columns:
    styler = styler.map(_total_style, subset=["月計"])

if show_nodate and "日付なし" in pivot.columns:
    styler = styler.map(
        lambda v: "color: #fab387; font-style: italic" if int(v or 0) > 0 else "",
        subset=["日付なし"],
    )

# ── 凡例 ────────────────────────────────────────────────
lc1, lc2, lc3, lc4 = st.columns(4)
lc1.markdown("🔴 **0件** — データなし")
lc2.markdown("🟡 **1〜4件** — 少量")
lc3.markdown("🟢 **5〜29件** — 通常")
lc4.markdown("💚 **30件以上** — 十分")

# 種別ごとの件数サマリ（フィルタ後）
_kind_filtered = raw[raw["fiscal_year"].isin(sel_fy)]
_kind_filtered = _kind_filtered.merge(agencies_f[["agency_id"]], on="agency_id")
_total_goods = int(_kind_filtered.loc[_kind_filtered["kind"] == "物品・役務", "cnt"].sum())
_total_works = int(_kind_filtered.loc[_kind_filtered["kind"] == "公共工事", "cnt"].sum())
st.markdown(
    f"**{len(pivot):,} 機関 × {len(months_ordered)} ヶ月** "
    f"| 種別: **{sel_kind}** "
    f"| 期間総件数 — 物品・役務: **{_total_goods:,}** ／ 公共工事: **{_total_works:,}**"
)

# ── テーブル表示 ─────────────────────────────────────────
col_cfg: dict = {
    "No.":   st.column_config.NumberColumn(width=50),
    "カテゴリ": st.column_config.TextColumn(width=130),
    "機関ID":  st.column_config.TextColumn(width=160),
    "機関名":  st.column_config.TextColumn(width=160),
}
for m in months_ordered:
    col_cfg[m] = st.column_config.NumberColumn(label=m[5:] + "月", width=48)
if show_total and "月計" in pivot.columns:
    col_cfg["月計"] = st.column_config.NumberColumn(width=65)
if show_nodate and "日付なし" in pivot.columns:
    col_cfg["日付なし"] = st.column_config.NumberColumn(width=72)

st.dataframe(
    styler,
    use_container_width=True,
    height=min(80 + len(pivot) * 36, 900),
    hide_index=True,
    column_config=col_cfg,
)

# ── サマリ ────────────────────────────────────────────────
st.divider()
sc1, sc2, sc3 = st.columns(3)
total_cells = len(pivot) * len(months_ordered)
zero_cells  = int((pivot[style_cols] == 0).sum().sum()) if style_cols else 0
filled_cells = total_cells - zero_cells
fill_pct = filled_cells / total_cells * 100 if total_cells > 0 else 0

sc1.metric("機関数", f"{len(pivot):,}")
sc2.metric("データあり月セル", f"{filled_cells:,} / {total_cells:,}")
sc3.metric("月別充填率", f"{fill_pct:.1f}%")

# ── 0件機関リスト ─────────────────────────────────────────
zero_agencies = pivot[pivot[style_cols].sum(axis=1) == 0][["No.", "カテゴリ", "機関ID", "機関名"]]
if not zero_agencies.empty:
    with st.expander(f"⚠️ 対象期間に月別データ0件の機関 ({len(zero_agencies)}機関)"):
        st.dataframe(zero_agencies, hide_index=True, use_container_width=True)
        st.caption("contract_date が NULL のレコードのみ存在する可能性があります。「日付なし」列で確認。")
