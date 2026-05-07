"""行政事業レビュー（事業ベース）ダッシュボード — 防衛省。

データソース: data/db/jigyou_review.db (RSシステム https://rssystem.go.jp/api/projects/ から取得)
契約ベース DB (data/db/procurement.db) とは別建て。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from _auth import require_password
require_password()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "jigyou_review.db"

# ── スタイル ─────────────────────────────────────────────
PLOT_TEMPLATE = "plotly_dark"
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
    [data-testid="stDataFrame"] td {{ font-size: 0.8rem !important; }}
    [data-testid="stDataFrame"] th {{ font-size: 0.8rem !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)

if not DB_PATH.exists():
    st.error("DBが見つかりません。`python -m pipeline.fetch_jigyou_payments` を実行してください。")
    st.stop()

# ── 利用可能FY確認 ────────────────────────────────────────
@st.cache_data(ttl=300)
def _available_fys() -> list[int]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT DISTINCT fiscal_year FROM projects ORDER BY fiscal_year DESC"
        ).fetchall()
    return [r[0] for r in rows]

available_fys = _available_fys()
if not available_fys:
    st.error("事業データが空です。ETL を実行してください。")
    st.stop()

# ── ヘッダー + FY選択 ────────────────────────────────────
h_col, fy_col = st.columns([5, 1])
with h_col:
    st.title("📋 行政事業レビュー — 防衛省")
    st.caption(
        "データソース: 行政事業レビュー見える化サイト（[RSシステム](https://rssystem.go.jp/project)）API。"
        "事業ベースで予算・確定額・主要支出先を集計。契約ベースDB (procurement.db) とは別建て。"
    )
with fy_col:
    sel_fy = st.selectbox(
        "年度",
        available_fys,
        index=0,
        format_func=lambda x: f"FY{x}",
        key="jr_fy",
        label_visibility="collapsed",
    )


# ── データロード ─────────────────────────────────────────
@st.cache_data(ttl=120)
def _load_projects(fy: int) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT
                id, project_number, name, organization_name,
                requested_amount, finalized_amount,
                finalized_amount_initial, finalized_amount_supplementary,
                finalized_amount_carried_forward,
                previous_year_execution_amount, previous_year_execution_rate,
                top_payee_name, top_payee_corporate_number, top_payee_amount,
                start_year, end_year, sheet_type, rs_url, overview, purpose
            FROM projects WHERE fiscal_year=?
            """,
            conn,
            params=(fy,),
        )


@st.cache_data(ttl=120)
def _load_budget_history() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            "SELECT project_id, fiscal_year, initial_budgets_total_amount, execution_amount FROM budget_history",
            conn,
        )


@st.cache_data(ttl=120)
def _load_payments(fy: int) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT p.project_id, p.payee_name, p.corporate_number, p.amount,
                   p.cost_type, j.name AS project_name, j.finalized_amount AS proj_finalized,
                   j.organization_name
            FROM payments p JOIN projects j ON p.project_id=j.id
            WHERE j.fiscal_year=? AND p.amount IS NOT NULL
            """,
            conn,
            params=(fy,),
        )


@st.cache_data(ttl=120)
def _payments_coverage(fy: int) -> int:
    """payments テーブルに行のある事業数。"""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(DISTINCT p.project_id) FROM payments p "
            "JOIN projects j ON p.project_id=j.id WHERE j.fiscal_year=?",
            (fy,),
        ).fetchone()[0]


df = _load_projects(sel_fy)
df_bh = _load_budget_history()

if df.empty:
    st.warning(f"FY{sel_fy} の事業データが空です。ETL を実行してください。")
    st.stop()

# 単位変換: 円 → 億円
for col in ("requested_amount", "finalized_amount",
            "finalized_amount_initial", "finalized_amount_supplementary",
            "finalized_amount_carried_forward",
            "previous_year_execution_amount", "top_payee_amount"):
    df[f"{col}_oku"] = (df[col].fillna(0) / 1e8).round(1)

# ── サマリ KPI ───────────────────────────────────────────
total_proj = len(df)
total_finalized = df["finalized_amount"].fillna(0).sum() / 1e8
total_requested = df["requested_amount"].fillna(0).sum() / 1e8
total_prev_exec = df["previous_year_execution_amount"].fillna(0).sum() / 1e8
avg_size = total_finalized / total_proj if total_proj > 0 else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("事業数", f"{total_proj:,}")
c2.metric("確定額合計", f"{total_finalized:,.0f} 億円")
c3.metric("要求額合計", f"{total_requested:,.0f} 億円")
c4.metric("平均規模", f"{avg_size:,.0f} 億円/事業")

# ── 年度間比較バー ───────────────────────────────────────
st.divider()
with st.expander("📊 年度間比較（確定額・事業数）", expanded=False):
    @st.cache_data(ttl=300)
    def _fy_summary() -> pd.DataFrame:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                """
                SELECT fiscal_year,
                       COUNT(*) AS 事業数,
                       ROUND(SUM(finalized_amount)/1e8, 0) AS 確定額_億
                FROM projects GROUP BY fiscal_year ORDER BY fiscal_year
                """,
                conn,
            )

    df_fys = _fy_summary()
    col_bar1, col_bar2 = st.columns(2)
    with col_bar1:
        fig_cnt = px.bar(df_fys, x="fiscal_year", y="事業数",
                         text="事業数", template=PLOT_TEMPLATE, height=280,
                         labels={"fiscal_year": "年度"})
        fig_cnt.update_traces(textposition="outside")
        fig_cnt.update_layout(xaxis=dict(tickmode="array", tickvals=df_fys["fiscal_year"].tolist()))
        st.plotly_chart(fig_cnt, use_container_width=True)
    with col_bar2:
        fig_amt = px.bar(df_fys, x="fiscal_year", y="確定額_億",
                         text="確定額_億", template=PLOT_TEMPLATE, height=280,
                         labels={"fiscal_year": "年度", "確定額_億": "確定額（億円）"})
        fig_amt.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
        fig_amt.update_layout(xaxis=dict(tickmode="array", tickvals=df_fys["fiscal_year"].tolist()))
        st.plotly_chart(fig_amt, use_container_width=True)

# ── フィルタ ─────────────────────────────────────────────
st.divider()
col_search, col_org = st.columns([3, 3])
with col_search:
    keyword = st.text_input("🔎 事業名キーワード", value="", key="jr_kw")
with col_org:
    orgs = sorted(df["organization_name"].dropna().unique().tolist())
    sel_orgs = st.multiselect("所管組織", orgs, default=[], key="jr_org")

filtered = df.copy()
if keyword:
    filtered = filtered[filtered["name"].str.contains(keyword, case=False, na=False)]
if sel_orgs:
    filtered = filtered[filtered["organization_name"].isin(sel_orgs)]

# ── 機関別集計 ───────────────────────────────────────────
st.subheader("🏛️ 所管組織別 事業数・金額")
org_agg = (
    filtered.groupby("organization_name", dropna=False)
            .agg(事業数=("id", "count"),
                 確定額_億=("finalized_amount", lambda s: s.fillna(0).sum() / 1e8))
            .reset_index()
            .sort_values("確定額_億", ascending=False)
)
org_agg["確定額_億"] = org_agg["確定額_億"].round(1)

if not org_agg.empty:
    fig = px.bar(
        org_agg.head(20),
        y="organization_name", x="確定額_億",
        orientation="h",
        text="確定額_億",
        labels={"organization_name": "組織", "確定額_億": "確定額（億円）"},
        template=PLOT_TEMPLATE,
        height=600,
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    fig.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

# ── 事業一覧 ─────────────────────────────────────────────
st.divider()
st.subheader(f"📊 事業一覧 ({len(filtered):,}件) — FY{sel_fy}")

show_cols = ["project_number", "name", "overview", "purpose", "organization_name",
             "requested_amount_oku", "finalized_amount_oku",
             "previous_year_execution_amount_oku",
             "top_payee_name", "top_payee_amount_oku", "rs_url"]
display = filtered[show_cols].copy()
display = display.rename(columns={
    "project_number": "事業番号",
    "name": "事業名",
    "overview": "概要",
    "purpose": "目的",
    "organization_name": "組織",
    "requested_amount_oku": "要求額(億)",
    "finalized_amount_oku": "確定額(億)",
    "previous_year_execution_amount_oku": "前年執行額(億)",
    "top_payee_name": "主要支出先",
    "top_payee_amount_oku": "支出先額(億)",
    "rs_url": "RS",
})
display = display.sort_values("確定額(億)", ascending=False).reset_index(drop=True)
display.insert(0, "No.", range(1, len(display) + 1))

st.dataframe(
    display,
    use_container_width=True,
    height=600,
    hide_index=True,
    column_config={
        "No.": st.column_config.NumberColumn(width=50),
        "事業番号": st.column_config.TextColumn(width=80),
        "事業名": st.column_config.TextColumn(width=250),
        "概要": st.column_config.TextColumn(width=300),
        "目的": st.column_config.TextColumn(width=300),
        "組織": st.column_config.TextColumn(width=150),
        "要求額(億)": st.column_config.NumberColumn(format="%.1f", width=90),
        "確定額(億)": st.column_config.NumberColumn(format="%.1f", width=90),
        "前年執行額(億)": st.column_config.NumberColumn(format="%.1f", width=110),
        "主要支出先": st.column_config.TextColumn(width=180),
        "支出先額(億)": st.column_config.NumberColumn(format="%.1f", width=100),
        "RS": st.column_config.LinkColumn("RS", display_text="🔗", width=60),
    },
)

# ── 詳細支出先 (payments テーブル) ────────────────────────
st.divider()
st.subheader("💼 詳細支出先 (contractor-payments API より)")

pay_covered = _payments_coverage(sel_fy)

if pay_covered == 0:
    st.info(
        f"FY{sel_fy} の詳細支出先データはまだ取得していません。"
        f"`python -m pipeline.fetch_jigyou_payments --fy {sel_fy}` を実行してください。"
    )
else:
    pay_raw = _load_payments(sel_fy)
    st.caption(
        f"事業 {pay_covered}/{total_proj} の詳細支出先を取得済み（{len(pay_raw):,} 行）。"
        "※ amount > 事業確定額×1.5 のレコードは複数年度契約の総額または異常値の可能性があるためデフォルト除外"
    )

    pay_raw["amt_oku"] = pay_raw["amount"] / 1e8
    pay_raw["proj_oku"] = pay_raw["proj_finalized"].fillna(0) / 1e8
    include_outliers = st.checkbox("年度跨ぎ契約・異常値も含めて表示", value=False, key="jr_pay_outliers")
    if include_outliers:
        pay_filtered = pay_raw.copy()
    else:
        pay_filtered = pay_raw[
            (pay_raw["proj_finalized"] > 0)
            & (pay_raw["amount"] <= pay_raw["proj_finalized"] * 1.5)
        ].copy()

    filtered_pids = set(filtered["id"])
    pay_filtered = pay_filtered[pay_filtered["project_id"].isin(filtered_pids)]

    payee_agg = (
        pay_filtered.groupby("payee_name")
        .agg(事業数=("project_id", "nunique"),
             件数=("payee_name", "count"),
             金額_億=("amt_oku", "sum"))
        .reset_index()
        .sort_values("金額_億", ascending=False)
        .head(20)
    )
    payee_agg["金額_億"] = payee_agg["金額_億"].round(1)

    if not payee_agg.empty:
        fig2 = px.bar(
            payee_agg,
            y="payee_name", x="金額_億",
            orientation="h", text="金額_億",
            labels={"payee_name": "支出先", "金額_億": "金額（億円）"},
            template=PLOT_TEMPLATE, height=600,
        )
        fig2.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
        fig2.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig2, use_container_width=True)

    with st.expander(f"🔎 詳細支出先テーブル（フィルタ後 {len(pay_filtered):,}行）", expanded=False):
        show = pay_filtered[["project_name", "organization_name", "payee_name",
                             "corporate_number", "amt_oku", "proj_oku"]].copy()
        show = show.rename(columns={
            "project_name": "事業名", "organization_name": "組織",
            "payee_name": "支出先", "corporate_number": "法人番号",
            "amt_oku": "支出額(億)", "proj_oku": "事業確定額(億)",
        })
        show = show.sort_values("支出額(億)", ascending=False).reset_index(drop=True)
        show.insert(0, "No.", range(1, len(show) + 1))
        st.dataframe(
            show, use_container_width=True, height=500, hide_index=True,
            column_config={
                "No.": st.column_config.NumberColumn(width=50),
                "事業名": st.column_config.TextColumn(width=280),
                "組織": st.column_config.TextColumn(width=180),
                "支出先": st.column_config.TextColumn(width=200),
                "法人番号": st.column_config.TextColumn(width=130),
                "支出額(億)": st.column_config.NumberColumn(format="%.2f", width=100),
                "事業確定額(億)": st.column_config.NumberColumn(format="%.1f", width=110),
            },
        )

# ── 注記 ─────────────────────────────────────────────────
st.divider()
with st.expander("ℹ️ データソースと限界"):
    st.markdown(
        f"""
- **データソース**: 行政事業レビュー見える化サイト [RSシステム](https://rssystem.go.jp/project)。
  防衛省所管事業 (FY2022〜FY2024) を `/api/projects/` API で全件取得し、`data/db/jigyou_review.db` に格納。
- **取得粒度**: 一覧APIで取得可能な基本情報＋主要支出先(Top1社)のみ。
  各事業の詳細支出先 (主な契約先一覧) は `payments` テーブルに別途格納。
  現在 FY2024 のみ全件取得済み（FY2022/2023 は `pipeline/fetch_jigyou_payments.py` で追加取得可能）。
- **「契約ベース」DB との違い**:
  - 契約ベース (`procurement.db`): 個別契約レコード (誰が誰にいくらで何を売ったか)
  - 事業ベース (本DB): 事業の予算・執行額・主要支出先 (補助金・基金・拠出金も含む)
- **金額**: 「確定額」= 初期予算 + 補正予算 + 繰越額の合算（事業の実投入予算）
        """
    )
