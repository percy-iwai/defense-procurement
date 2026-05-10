"""ピラーレビュービューワー — 全契約をピラー別×金額降順で一覧・精査するためのビュー。

FY・大項目(L1)・中項目(L2) でフィルタリングし、分類の誤りや漏れを確認する。
contract_pillar を LEFT JOIN しているため未分類（UNCLS）も表示される。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from _auth import require_password  # noqa: E402

require_password()

PROJECT_ROOT = DASHBOARD_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

TEXT_COLOR = "#cdd6f4"
TEXT_DIM   = "#bac2de"
ACCENT     = "#89b4fa"

L2_LABELS: dict[int, str] = {
    41: "P41 宇宙",
    42: "P42 サイバー",
    43: "P43 車両・艦船・航空機",
    71: "P71 弾薬・誘導弾",
    72: "P72 維持整備",
    73: "P73 施設強靱化",
    81: "P81 防衛生産基盤",
    82: "P82 研究開発",
    83: "P83 基地対策",
    84: "P84 教育訓練・燃料",
    85: "P85 米軍再編",
}

L1_TO_L2: dict[int, list[int]] = {
    4: [41, 42, 43],
    7: [71, 72, 73],
    8: [81, 82, 83, 84, 85],
}

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
    <style>
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li,
    .stApp th, .stApp td {{ color: {TEXT_COLOR}; }}
    .stApp h1, .stApp h2, .stApp h3 {{ color: {TEXT_COLOR}; }}
    [data-testid="stMetricValue"] {{ color: {TEXT_COLOR}; font-weight: 600; }}
    [data-testid="stMetricLabel"] {{ color: {TEXT_DIM}; font-size: 0.85rem; }}
    [data-testid="stCaptionContainer"] {{ color: {TEXT_DIM} !important; }}
    [data-testid="stDataFrame"] td {{ font-size: 0.78rem !important; }}
    [data-testid="stDataFrame"] th {{ font-size: 0.78rem !important; white-space: nowrap; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🔍 ピラーレビュービューワー")
st.caption(
    "全契約をピラー別・金額降順で一覧。分類の精査・誤分類の発見に使用する。"
    " contract_pillar を LEFT JOIN しているため未分類（UNCLS）も含む。"
)

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()


# ── データ読み込み ────────────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def _load_contracts(fys: tuple[int, ...]) -> pd.DataFrame:
    """指定FYの全契約を contract_pillar LEFT JOIN して取得（金額降順）。"""
    fy_ph = ",".join("?" * len(fys))
    sql = f"""
        SELECT
            c.id,
            c.fiscal_year,
            cp.pillar_l1_code,
            cp.pillar_l2_code,
            c.contract_name,
            c.agency_name,
            c.agency_id,
            ROUND(c.contract_amount / 1e8, 1)   AS amount_oku,
            cp.match_method,
            cp.match_source,
            cp.confidence
        FROM contracts c
        LEFT JOIN contract_pillar cp ON cp.contract_id = c.id
        WHERE c.fiscal_year IN ({fy_ph})
        ORDER BY c.contract_amount DESC NULLS LAST
    """
    with sqlite3.connect(str(DB_PATH)) as conn:
        return pd.read_sql_query(sql, conn, params=list(fys))


# ── フィルター UI ─────────────────────────────────────────────────────────────
col_fy, col_l1, col_l2 = st.columns([1, 2, 2])

with col_fy:
    sel_fy = st.multiselect(
        "📅 FY", [2022, 2023, 2024, 2025], default=[2023], key="pr_fy"
    )
if not sel_fy:
    st.warning("FYを1つ以上選択してください。")
    st.stop()

df_all = _load_contracts(tuple(sorted(sel_fy)))

all_l1_codes = sorted(df_all["pillar_l1_code"].dropna().astype(int).unique().tolist())
all_l2_codes = sorted(df_all["pillar_l2_code"].dropna().astype(int).unique().tolist())

with col_l1:
    l1_opts = ["全て", "未分類"] + [f"P{c}" for c in all_l1_codes]
    sel_l1 = st.multiselect(
        "🏛️ 大項目(L1)", l1_opts, default=["全て"], key="pr_l1"
    )
    if not sel_l1:
        sel_l1 = ["全て"]

# 選択された L1 コードを整数リストに変換
selected_l1_ints = [
    int(x[1:]) for x in sel_l1 if x.startswith("P") and x[1:].isdigit()
]

# L2 オプションを L1 選択に連動
if "全て" in sel_l1:
    avail_l2 = all_l2_codes
else:
    avail_l2 = sorted(
        {l2c for l1c in selected_l1_ints for l2c in L1_TO_L2.get(l1c, []) if l2c in all_l2_codes}
    )

with col_l2:
    if avail_l2:
        l2_opts = ["全て"] + [f"P{c}" for c in avail_l2]
        sel_l2 = st.multiselect(
            "📂 中項目(L2)",
            l2_opts,
            default=["全て"],
            key="pr_l2",
            format_func=lambda x: (
                L2_LABELS.get(int(x[1:]), x) if x != "全て" else "全て"
            ),
        )
        if not sel_l2:
            sel_l2 = ["全て"]
    else:
        sel_l2 = ["全て"]
        st.selectbox("📂 中項目(L2)", ["(L2なし)"], disabled=True, key="pr_l2_none")


# ── フィルター適用 ────────────────────────────────────────────────────────────
df = df_all.copy()

if "全て" not in sel_l1:
    mask = pd.Series(False, index=df.index)
    if "未分類" in sel_l1:
        mask |= df["pillar_l1_code"].isna()
    if selected_l1_ints:
        mask |= df["pillar_l1_code"].isin(selected_l1_ints)
    df = df[mask]

if "全て" not in sel_l2 and avail_l2:
    sel_l2_ints = [int(x[1:]) for x in sel_l2 if x.startswith("P") and x[1:].isdigit()]
    df = df[df["pillar_l2_code"].isin(sel_l2_ints)]


# ── サマリーメトリクス ────────────────────────────────────────────────────────
n_classified = int(df["pillar_l1_code"].notna().sum())
n_uncls      = int(df["pillar_l1_code"].isna().sum())
amt_total    = float(df["amount_oku"].fillna(0).sum())

mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("件数",      f"{len(df):,}件")
mc2.metric("契約額合計", f"{amt_total:,.1f}億")
mc3.metric("分類済み",  f"{n_classified:,}件")
mc4.metric("未分類",    f"{n_uncls:,}件")


# ── 表示用 DataFrame 整形 ────────────────────────────────────────────────────
def _build_display(src: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "#": range(1, len(src) + 1),
            "L1": src["pillar_l1_code"].apply(
                lambda x: f"P{int(x)}" if pd.notna(x) else "UNCLS"
            ),
            "L2": src["pillar_l2_code"].apply(
                lambda x: f"P{int(x)}" if pd.notna(x) else ""
            ),
            "契約名":     src["contract_name"].fillna(""),
            "機関":       src["agency_name"].fillna(""),
            "契約額(億)": src["amount_oku"],
            "分類方法":   src["match_method"].fillna("unclassified"),
            "match_source": src["match_source"].fillna(""),
            "conf":       src["confidence"],
            "ID":         src["id"].astype(int),
        }
    ).reset_index(drop=True)


disp = _build_display(df)

_COL_CFG = {
    "#":            st.column_config.NumberColumn("#",            width="small"),
    "L1":           st.column_config.TextColumn("L1",             width="small"),
    "L2":           st.column_config.TextColumn("L2",             width="small"),
    "契約名":       st.column_config.TextColumn("契約名",          width="large"),
    "機関":         st.column_config.TextColumn("機関",            width="medium"),
    "契約額(億)":   st.column_config.NumberColumn("契約額(億)",    format="%.1f", width="small"),
    "分類方法":     st.column_config.TextColumn("分類方法",        width="small"),
    "match_source": st.column_config.TextColumn("match_source",   width="medium"),
    "conf":         st.column_config.NumberColumn("conf",          format="%.3f", width="small"),
    "ID":           st.column_config.NumberColumn("ID",            width="small"),
}

st.dataframe(
    disp,
    use_container_width=True,
    hide_index=True,
    height=700,
    column_config=_COL_CFG,
)

fy_range = (
    f"FY{min(sel_fy)}"
    if len(sel_fy) == 1
    else f"FY{min(sel_fy)}–{max(sel_fy)}"
)
st.caption(
    f"表示: {len(disp):,}件 / 読込: {len(df_all):,}件 | {fy_range}"
    " | デフォルト: 契約額降順（列ヘッダークリックでソート変更）"
)
