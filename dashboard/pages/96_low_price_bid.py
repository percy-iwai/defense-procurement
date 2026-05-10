"""低価格入札分析ページ — 契約価格÷予定価格 < 70% の案件を可視化する。

- グローバルFYフィルター（st.session_state["global_fy"]）を参照
- 調達区分フィルター（全て / 中央調達のみ / 地方調達のみ）
  - 中央調達 = agency_id='atla'（防衛装備庁 調達事業部）
    ※ ATLAは随意契約が大半で予定価格非公表が多く、対象件数は少ない
  - 地方調達 = それ以外の全機関（各自衛隊・研究所・試験場含む）
- 「全ベンダーTOP200」と「ベンダー別（全件）」の2モード
- 落札率を色分け（<50%赤 / 50-70%橙 / >=70%緑）
"""
from __future__ import annotations

import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

from _auth import require_password
require_password()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

TEXT_COLOR = "#cdd6f4"
TEXT_DIM   = "#bac2de"
ACCENT     = "#7c83fd"

ORG_LABELS: dict[str, str] = {
    "MSDF":     "海上自衛隊",
    "GSDF":     "陸上自衛隊",
    "ASDF":     "航空自衛隊",
    "ATLA":     "防衛装備庁",
    "JS":       "統合幕僚監部",
    "DIH":      "情報本部",
    "NAIKYOKU": "防衛省内局",
    "NDMC":     "防衛医科大",
    "NDA":      "防衛大学校",
    "NIDS":     "防衛研究所",
    "RDB":      "地方防衛局",
    "KANSATSU": "防衛監察本部",
}

_ALL_FYS = [2022, 2023, 2024, 2025]

# 中央調達の agency_id（防衛装備庁 調達事業部のみ）
_CENTRAL_AGENCY_ID = "atla"

st.markdown(f"""
<style>
.stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp th, .stApp td {{
    color: {TEXT_COLOR};
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: {TEXT_COLOR}; }}
[data-testid="stMetricValue"] {{ color: {TEXT_COLOR}; font-weight: 600; }}
[data-testid="stMetricLabel"] {{ color: {TEXT_DIM}; font-size: 0.85rem; }}
[data-testid="stCaptionContainer"] {{ color: {TEXT_DIM} !important; }}
[data-testid="stDataFrame"] td {{ font-size: 0.78rem !important; }}
[data-testid="stDataFrame"] th {{ font-size: 0.78rem !important; white-space: nowrap; }}
a, a:visited {{ color: {ACCENT}; text-decoration: none; }}
a:hover {{ color: #a5b4fc; text-decoration: underline; }}
</style>
""", unsafe_allow_html=True)

st.title("⚠️ 低価格入札分析")
st.caption(
    "契約価格 ÷ 予定価格 < 70% の案件を一覧します。"
    "予定価格が公表されていない案件は除外されます。"
)

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


# ── データ読み込み ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def _load_low_price(fys: tuple[int, ...]) -> pd.DataFrame:
    """低価格入札データ（ca/ep < 70%）をFY指定で全件取得する。

    award_rate カラムは 0〜100 / 0〜1 / 円額 など複数スケールが混在しているため使用しない。
    WHERE 句で estimated_price > 0 AND contract_amount IS NOT NULL を保証しているので
    ratio_pct は常に ca/ep*100 で算出できる。
    """
    fy_placeholders = ",".join("?" * len(fys))
    sql = f"""
        SELECT
            c.id,
            c.fiscal_year,
            c.agency_id,
            c.agency_name,
            c.contract_name,
            c.vendor_name,
            c.contract_amount,
            c.estimated_price,
            CAST(c.contract_amount AS REAL) / c.estimated_price * 100 AS ratio_pct,
            c.bid_method,
            c.contract_date,
            c.source_url,
            cro.requesting_org
        FROM contracts c
        LEFT JOIN contract_requesting_org cro ON cro.contract_id = c.id
        WHERE c.estimated_price IS NOT NULL
          AND c.estimated_price > 0
          AND c.contract_amount IS NOT NULL
          AND c.fiscal_year IN ({fy_placeholders})
          AND CAST(c.contract_amount AS REAL) / c.estimated_price * 100 < 70
        ORDER BY ratio_pct ASC
    """
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(sql, conn, params=list(fys))
    df["requesting_org_label"] = df["requesting_org"].map(ORG_LABELS).fillna(df["requesting_org"])
    return df


# ── 色分け ───────────────────────────────────────────────────────────────────

def _color_ratio(val: float) -> str:
    if val < 50:
        return "background-color: #3d1a20; color: #f38ba8;"
    elif val < 70:
        return "background-color: #3d2b14; color: #fab387;"
    else:
        return "background-color: #1a3020; color: #a6e3a1;"


def _style_df(df: pd.DataFrame, ratio_col: str = "落札率(%)") -> pd.DataFrame.style:
    return df.style.applymap(_color_ratio, subset=[ratio_col])


# ── 表示用DataFrame整形 ──────────────────────────────────────────────────────

def _format_df(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["年度"]           = df["fiscal_year"].astype(str).apply(lambda y: f"FY{y}")
    out["機関"]           = df["agency_name"]
    out["要求元"]         = df["requesting_org_label"]
    out["案件名"]         = df["contract_name"]
    out["ベンダー"]       = df["vendor_name"]
    out["予定価格(万円)"] = (df["estimated_price"] / 10_000).round(1)
    out["契約価格(万円)"] = (df["contract_amount"] / 10_000).round(1)
    out["落札率(%)"]      = df["ratio_pct"].round(2)
    out["入札方式"]       = df["bid_method"]
    out["契約日"]         = df["contract_date"]
    return out


_COLUMN_CONFIG = {
    "案件名":           st.column_config.TextColumn(width="large"),
    "ベンダー":         st.column_config.TextColumn(width="medium"),
    "機関":             st.column_config.TextColumn(width="medium"),
    "要求元":           st.column_config.TextColumn(width="small"),
    "予定価格(万円)":   st.column_config.NumberColumn(format="%.1f"),
    "契約価格(万円)":   st.column_config.NumberColumn(format="%.1f"),
    "落札率(%)":        st.column_config.NumberColumn(format="%.2f"),
}

# ── メイン ──────────────────────────────────────────────────────────────────

# グローバルFYフィルター
active_fys: list[int] = list(st.session_state.get("global_fy") or _ALL_FYS)
active_fys_tuple = tuple(sorted(active_fys))

df_all = _load_low_price(active_fys_tuple)

# ── 調達区分フィルター ────────────────────────────────────────────────────────
choutatu_mode = st.selectbox(
    "調達区分",
    options=["全て", "中央調達のみ", "地方調達のみ"],
    index=0,
    key="choutatu_mode",
    help=(
        "中央調達：防衛装備庁 調達事業部（agency_id='atla'）が契約締結した案件。"
        "地方調達：各自衛隊部隊・研究所・試験場・他省庁機関が自ら締結した案件"
        "（atla_kanbo, atla_riku 等の装備庁サブ機関も地方調達に分類）。"
    ),
)

if choutatu_mode == "中央調達のみ":
    df_view = df_all[df_all["agency_id"] == _CENTRAL_AGENCY_ID].copy()
elif choutatu_mode == "地方調達のみ":
    df_view = df_all[df_all["agency_id"] != _CENTRAL_AGENCY_ID].copy()
else:
    df_view = df_all

# ── サマリーメトリクス ────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("対象件数", f"{len(df_view):,}件")
if not df_view.empty:
    c2.metric("最低落札率", f"{df_view['ratio_pct'].min():.1f}%")
    c3.metric("平均落札率", f"{df_view['ratio_pct'].mean():.1f}%")
    savings = ((df_view["estimated_price"] - df_view["contract_amount"]) / 1e8).sum()
    c4.metric("予定比節減額計", f"{savings:,.0f}億円")

st.divider()

# ── タブ切り替え ──────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📋 全ベンダーTOP200", "🔍 ベンダー別（全件）"])

# ─── TAB1: 全ベンダーTOP200 ───────────────────────────────────────────────────
with tab1:
    st.subheader("落札率が最も低い上位200件")
    st.caption(
        f"対象FY: {', '.join(f'FY{y}' for y in sorted(active_fys_tuple))}"
        f"　調達区分: {choutatu_mode}　／　予定価格 > 0 の案件のみ"
    )

    if df_view.empty:
        st.info("該当データがありません。")
    else:
        top200 = df_view.head(200).copy()
        st.dataframe(
            _style_df(_format_df(top200)),
            use_container_width=True,
            hide_index=True,
            height=700,
            column_config=_COLUMN_CONFIG,
        )
        st.caption(
            f"表示: {len(top200):,}件 / 全{len(df_view):,}件　"
            "※ 落札率 = 契約価格 ÷ 予定価格 × 100（予定価格が公表されている案件のみ対象）"
        )

# ─── TAB2: ベンダー別（全件） ─────────────────────────────────────────────────
with tab2:
    st.subheader("ベンダー別 低価格入札一覧（全件）")

    # df_view から件数降順でベンダーリストを生成（別クエリ不要）
    vendor_counts = (
        df_view[df_view["vendor_name"].notna()]
        .groupby("vendor_name")["id"]
        .count()
        .sort_values(ascending=False)
    )
    vendors = vendor_counts.index.tolist()

    if not vendors:
        st.info("該当データがありません。")
    else:
        filter_text = st.text_input(
            "ベンダー名を入力して絞り込み（部分一致）",
            placeholder="例: 三菱、NEC、富士通 ...",
            key="vendor_filter",
        )

        if filter_text.strip():
            norm_filter = _norm(filter_text.strip())
            filtered_vendors = [v for v in vendors if norm_filter.lower() in _norm(v).lower()]
        else:
            filtered_vendors = vendors

        if not filtered_vendors:
            st.warning("一致するベンダーが見つかりません。")
        else:
            selected_vendor = st.selectbox(
                f"ベンダーを選択（{len(filtered_vendors)}社）",
                options=filtered_vendors,
                format_func=lambda v: f"{v}　（{vendor_counts.get(v, 0)}件）",
                key="vendor_select",
            )

            df_vendor = df_view[df_view["vendor_name"] == selected_vendor].copy()

            # サマリーメトリクス
            v1, v2, v3 = st.columns(3)
            v1.metric("低価格入札件数", f"{len(df_vendor)}件")
            if not df_vendor.empty:
                v2.metric("最低落札率", f"{df_vendor['ratio_pct'].min():.1f}%")
                v3.metric("平均落札率", f"{df_vendor['ratio_pct'].mean():.1f}%")

            # FY別件数（横並び）
            if not df_vendor.empty:
                fy_counts = (
                    df_vendor.groupby("fiscal_year")["id"]
                    .count()
                    .rename("件数")
                    .to_frame()
                    .T
                )
                fy_counts.columns = [f"FY{c}" for c in fy_counts.columns]
                fy_counts.index = ["件数"]
                st.dataframe(fy_counts, use_container_width=False, hide_index=False)

            st.divider()

            if df_vendor.empty:
                st.info("該当データがありません。")
            else:
                st.dataframe(
                    _style_df(_format_df(df_vendor.reset_index(drop=True))),
                    use_container_width=True,
                    hide_index=True,
                    height=700,
                    column_config=_COLUMN_CONFIG,
                )
