"""FY別 収録状況・カバレッジ分析ページ。

app.py から切り出し。procurement.db を直接参照して FY 別の
収録件数・金額・予算との比較・ウォーターフォール図を表示する。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from _auth import require_password  # noqa: E402

require_password()

# ── パス ────────────────────────────────────────────────────────────
PROC_DB = DASHBOARD_DIR.parent / "data" / "db" / "procurement.db"

# ── カラーテーマ ─────────────────────────────────────────────────────
PLOT_TEMPLATE = "plotly_dark"
ACCENT_2 = "#fab387"
ACCENT_3 = "#a6e3a1"
TEXT_COLOR = "#cdd6f4"
TEXT_DIM = "#bac2de"

st.markdown(
    f"""
    <style>
    .stApp, .stApp p, .stApp span, .stApp label, .stApp th, .stApp td {{
        color: {TEXT_COLOR};
    }}
    .stApp h1, .stApp h2, .stApp h3 {{ color: {TEXT_COLOR}; }}
    [data-testid="stCaptionContainer"] {{ color: {TEXT_DIM} !important; }}
    [data-testid="stMetricValue"] {{ color: {TEXT_COLOR}; font-weight: 600; }}
    [data-testid="stDataFrame"] td {{ font-size: 0.85rem !important; }}
    [data-testid="stDataFrame"] th {{ font-size: 0.85rem !important; white-space: nowrap; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ── 予算定数（各FY予算書より） ───────────────────────────────────────
_BUDGET: dict[int, int] = {
    2022: 34_980,
    2023: 89_525,
    2024: 93_625,
    2025: 84_332,
}
_NON_CONTRACT: dict[int, int] = {
    2022:  2_800,
    2023:  7_300,
    2024:  7_500,
    2025:  7_600,
}
_FUYOU: dict[int, int | None] = {
    2022:    500,
    2023:  1_300,
    2024:  1_200,
    2025:   None,
}


def _effective_base(fy: int) -> int | None:
    b = _BUDGET.get(fy)
    nc = _NON_CONTRACT.get(fy)
    fu = _FUYOU.get(fy)
    if b is None or nc is None:
        return None
    return b - nc - (fu or 0)


# ── FY 別集計 ─────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_fy_stats() -> dict[int, dict]:
    with sqlite3.connect(PROC_DB) as conn:
        df = pd.read_sql_query(
            "SELECT fiscal_year, contract_amount FROM contracts", conn
        )
    df["amount_oku"] = df["contract_amount"].fillna(0) / 1e8
    stats: dict[int, dict] = {}
    for fy in [2022, 2023, 2024, 2025]:
        cnt = int((df["fiscal_year"] == fy).sum())
        amt = float(df.loc[df["fiscal_year"] == fy, "amount_oku"].sum())
        base = _effective_base(fy)
        cov = amt / base * 100 if base else None
        stats[fy] = {"count": cnt, "amount": amt, "base": base, "coverage": cov}
    return stats


# ════════════════════════════════════════════════════════════════════
# 描画
# ════════════════════════════════════════════════════════════════════
st.title("📊 収録状況・カバレッジ分析")
st.caption("出典: 防衛省・自衛隊 各機関 公開調達情報（財計第2017号）/ 防衛省予算概要各年度版")

fy_stats = _load_fy_stats()

# ── FY 別 収録状況・カバレッジ比較 ───────────────────────────────────
st.subheader("📊 FY別 収録状況・カバレッジ比較")

fy_rows = []
for fy in [2022, 2023, 2024, 2025]:
    s = fy_stats[fy]
    fy_rows.append({
        "年度": f"FY{fy}",
        "収録件数": s["count"],
        "収録額(億円)": round(s["amount"], 0),
        "予算(億円)": _BUDGET.get(fy),
        "実質母数(億円)": s["base"],
        "カバレッジ率": f"{s['coverage']:.1f}%" if s["coverage"] is not None else "—",
    })
fy_comp_df = pd.DataFrame(fy_rows)

cov_c1, cov_c2 = st.columns([2, 3])
with cov_c1:
    st.dataframe(
        fy_comp_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "収録件数":       st.column_config.NumberColumn(format="%d"),
            "収録額(億円)":   st.column_config.NumberColumn(format="%.0f"),
            "予算(億円)":     st.column_config.NumberColumn(format="%d"),
            "実質母数(億円)": st.column_config.NumberColumn(format="%d"),
        },
    )
with cov_c2:
    cov_fig_df = pd.DataFrame({
        "年度": [f"FY{fy}" for fy in [2022, 2023, 2024, 2025]],
        "収録額": [fy_stats[fy]["amount"] for fy in [2022, 2023, 2024, 2025]],
        "未収録推定": [
            max(0, (fy_stats[fy]["base"] or 0) - fy_stats[fy]["amount"])
            for fy in [2022, 2023, 2024, 2025]
        ],
    })
    fig_cov = go.Figure()
    fig_cov.add_bar(
        x=cov_fig_df["年度"], y=cov_fig_df["収録額"],
        name="収録額", marker_color=ACCENT_3,
        text=cov_fig_df["収録額"].map(lambda v: f"{v:,.0f}億"),
        textposition="inside",
    )
    fig_cov.add_bar(
        x=cov_fig_df["年度"], y=cov_fig_df["未収録推定"],
        name="未収録推定", marker_color="#45475a",
        text=cov_fig_df["未収録推定"].map(lambda v: f"{v:,.0f}億" if v > 0 else ""),
        textposition="inside",
    )
    cov_vals = [fy_stats[fy]["coverage"] for fy in [2022, 2023, 2024, 2025]]
    fig_cov.add_scatter(
        x=[f"FY{fy}" for fy in [2022, 2023, 2024, 2025]],
        y=cov_vals,
        name="カバレッジ率(%)", mode="lines+markers+text",
        line=dict(color=ACCENT_2, width=3), marker=dict(size=10),
        text=[f"{v:.1f}%" if v else "—" for v in cov_vals],
        textposition="top center",
        yaxis="y2",
    )
    fig_cov.update_layout(
        template=PLOT_TEMPLATE, height=320, barmode="stack",
        yaxis=dict(title="億円"),
        yaxis2=dict(title="カバレッジ率(%)", overlaying="y", side="right",
                    showgrid=False, range=[0, 120]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig_cov, use_container_width=True)
st.caption(
    "実質母数 = 物件費（契約ベース）− 非契約系（光熱水・補助金等）− 不用額。"
    "FY2025不用額は未公表のため0として計算。"
    "FY2025は3月分が未公開につき未収録のため、収録額・カバレッジ率は暫定値。"
)

st.divider()

# ── カバレッジ分析（FY選択） ─────────────────────────────────────────
cov_h1, cov_h2 = st.columns([4, 1])
with cov_h1:
    st.subheader("📐 カバレッジ分析")
with cov_h2:
    sel_cov_fy = st.selectbox(
        "年度", [2025, 2024, 2023, 2022], index=1,
        format_func=lambda x: f"FY{x}",
        key="cov_wf_fy", label_visibility="collapsed",
    )

_sel_budget = _BUDGET.get(sel_cov_fy, 0)
_sel_nc     = _NON_CONTRACT.get(sel_cov_fy, 0)
_sel_fu     = _FUYOU.get(sel_cov_fy) or 0
_sel_base   = _effective_base(sel_cov_fy) or 0
_sel_amount = fy_stats[sel_cov_fy]["amount"]
_sel_count  = fy_stats[sel_cov_fy]["count"]
_sel_cov    = fy_stats[sel_cov_fy]["coverage"] or 0.0

col_waterfall, col_gap = st.columns([3, 2])

with col_waterfall:
    fig_wf = go.Figure(go.Waterfall(
        name="億円", orientation="v",
        measure=["absolute", "relative", "relative", "total", "absolute"],
        x=["物件費（契約ベース）", "△非契約系", "△不用額", "実質契約母数", "DB収録額"],
        y=[_sel_budget, -_sel_nc, -_sel_fu, 0, _sel_amount],
        connector={"line": {"color": "#45475a", "width": 1}},
        decreasing={"marker": {"color": "#f38ba8"}},
        increasing={"marker": {"color": "#a6e3a1"}},
        totals={"marker": {"color": "#89dceb"}},
        texttemplate="%{y:,.0f}億",
        textposition="outside",
    ))
    fig_wf.update_layout(
        template=PLOT_TEMPLATE, height=380,
        title=dict(text=f"FY{sel_cov_fy} カバレッジ計算", font=dict(size=13)),
        yaxis=dict(title="億円"),
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    st.plotly_chart(fig_wf, use_container_width=True)
    if sel_cov_fy == 2025:
        st.caption("※FY2025 は3月分が未公開につき未収録のため、DB収録額・カバレッジ率は暫定値。")

with col_gap:
    st.markdown("**差し引き一覧**")
    cov_detail = [
        ("物件費（契約ベース）", f"{_sel_budget:,}億", TEXT_COLOR),
        ("△ 非契約系",          f"▲{_sel_nc:,}億",    "#f38ba8"),
    ]
    if sel_cov_fy == 2024:
        cov_detail += [
            ("　光熱水料等（電力・水道）",     "　~1,624億", TEXT_DIM),
            ("　基地対策等（HNS・交付金）",    "　~3,300億", TEXT_DIM),
            ("　借料（施設用地地代・漁業補償）","　~1,345億", TEXT_DIM),
            ("　教育訓練費",                   "　  ~390億", TEXT_DIM),
            ("　医療費等",                     "　  ~320億", TEXT_DIM),
            ("　補助金①装備移転等",            "　  ~400億", TEXT_DIM),
            ("　補助金②サイバー防衛",          "　   ~71億", TEXT_DIM),
            ("　補助金③GIGO",                 "　   ~42億", TEXT_DIM),
        ]
    elif sel_cov_fy == 2023:
        cov_detail += [
            ("　HNS（在日米軍駐留経費）",  "　~2,000億", TEXT_DIM),
            ("　光熱水料等（営舎費中）",    "　~1,600億", TEXT_DIM),
            ("　基地借料・漁業補償",        "　~1,500億", TEXT_DIM),
            ("　補助金①装備移転（P.37）",  "　  ~400億", TEXT_DIM),
            ("　補助金②基地周辺対策等",    "　~1,100億", TEXT_DIM),
            ("　教育訓練費・医療費等",      "　  ~700億", TEXT_DIM),
        ]
    _fu_disp = f"▲{_sel_fu:,}億" if _sel_fu else "—（未公表）"
    cov_detail += [
        ("△ 不用額（未執行残）",         _fu_disp,              "#f38ba8"),
        ("＝ 実質契約対象母数",          f"≈{_sel_base:,}億",    "#89dceb"),
        (f"DB収録額（FY{sel_cov_fy}）",  f"{_sel_amount:,.0f}億","#a6e3a1"),
        ("カバレッジ率",                 f"{_sel_cov:.1f}%",     "#a6e3a1"),
    ]
    for label, val, color in cov_detail:
        is_header = any(label.startswith(p) for p in ("＝", "DB", "カバレッジ", "物件費"))
        border_top = "border-top: 2px solid #45475a;" if is_header else ""
        st.markdown(
            f'<div style="display:flex; justify-content:space-between; padding:2px 4px; {border_top}">'
            f'<span style="color:{color}; font-size:0.83rem">{label}</span>'
            f'<span style="color:{color}; font-size:0.83rem; font-weight:600">{val}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.caption("出典: structural_db_exclusions.md")

_budget_src = {
    2022: "令和4年度予算概要 P.62",
    2023: "会計検査院 令和5年度決算検査報告",
    2024: "令和6年度予算概要 yosan_20240328.pdf P.58",
    2025: "令和7年度予算概要 yosan_20250402.pdf P.66",
}
with st.expander("📚 出典・参考資料"):
    _fu_src = (
        "R6年度決算 官房長官会見（朝日新聞/日刊ゲンダイ 2025-11-18〜20）" if sel_cov_fy == 2024
        else "会計検査院R5決算検査報告（計画対象経費の不用額1,294億円）" if sel_cov_fy == 2023
        else "概算値"
    )
    _nc_src = (
        "行政事業レビューDB330事業突合 + 費目別vendor検証" if sel_cov_fy == 2024
        else "FY2024実績から予算規模比例推定"
    )
    st.markdown(f"""
- **物件費（契約ベース）{_sel_budget:,}億**: {_budget_src.get(sel_cov_fy, "")}
- **不用額{_sel_fu:,}億**: {_fu_src}
- **非契約系{_sel_nc:,}億**: {_nc_src}
- **DB収録額（FY{sel_cov_fy}）**: `data/db/procurement.db` より動的取得（{_sel_amount:,.0f}億 / {_sel_count:,}件）
- 詳細: `data/manual/coverage_budget_breakdown.md`
    """)
