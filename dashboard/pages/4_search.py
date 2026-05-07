"""契約データ検索ページ — procurement.db を直接 SQL 検索

- フリーワード（contract_name 部分一致, NFKC正規化）
- 年度 / 大区分 / 調達機関 でフィルタ
- 結果はテーブル表示（金額カンマ区切り）、上位500件まで
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
DB_PATH      = PROJECT_ROOT / "data" / "db" / "procurement.db"

TEXT_COLOR = "#cdd6f4"
TEXT_DIM   = "#bac2de"
ACCENT     = "#7c83fd"

MAX_RESULTS = 500

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

st.title("🔎 契約データ検索")
st.caption("procurement.db を対象にフリーワード・年度・大区分・機関で絞り込み検索します。")

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()


@st.cache_data(ttl=600)
def _load_filter_options() -> dict[str, list]:
    with sqlite3.connect(DB_PATH) as conn:
        fys = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT fiscal_year FROM contracts "
            "WHERE fiscal_year IS NOT NULL ORDER BY fiscal_year DESC"
        )]
        larges = [r[0] for r in conn.execute(
            "SELECT DISTINCT category_large FROM contracts "
            "WHERE category_large IS NOT NULL AND category_large != '' "
            "ORDER BY category_large"
        )]
        agencies = [r[0] for r in conn.execute(
            "SELECT DISTINCT agency_name FROM contracts "
            "WHERE agency_name IS NOT NULL AND agency_name != '' "
            "ORDER BY agency_name"
        )]
    return {"fy": fys, "large": larges, "agency": agencies}


def _norm(s: str) -> str:
    """NFKC正規化（全角→半角、合字統一など）。"""
    return unicodedata.normalize("NFKC", s or "").strip()


@st.cache_data(ttl=120, show_spinner=False)
def _search(
    keyword: str,
    fy: int | None,
    large: str | None,
    agency: str | None,
    limit: int,
) -> tuple[pd.DataFrame, int]:
    """検索本体。 (表示用DataFrame, ヒット総件数) を返す。

    キーワード・DB側 contract_name の両方を NFKC 正規化して比較する。
    DB側は SQLite に nfkc UDF を登録して `nfkc(contract_name) LIKE ?` で評価。
    Ｆ－３５Ａ（全角）↔ F-35A（半角）のような表記揺れを吸収できる。
    """
    where: list[str] = []
    params: list = []
    if keyword:
        where.append("nfkc(contract_name) LIKE ?")
        params.append(f"%{keyword}%")
    if fy is not None:
        where.append("fiscal_year = ?")
        params.append(fy)
    if large:
        where.append("category_large = ?")
        params.append(large)
    if agency:
        where.append("agency_name = ?")
        params.append(agency)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    def _sql_nfkc(s):
        return unicodedata.normalize("NFKC", s) if s else s

    with sqlite3.connect(DB_PATH) as conn:
        conn.create_function("nfkc", 1, _sql_nfkc, deterministic=True)
        total = conn.execute(
            f"SELECT COUNT(*) FROM contracts {where_sql}", params
        ).fetchone()[0]
        df = pd.read_sql_query(
            f"""SELECT contract_name, vendor_name, contract_amount,
                       agency_name, fiscal_year, contract_date,
                       bid_method, category_large, source_url
                FROM contracts
                {where_sql}
                ORDER BY contract_amount IS NULL, contract_amount DESC
                LIMIT ?""",
            conn, params=[*params, limit],
        )
    return df, int(total)


# ── フィルタUI ────────────────────────────────────────────
opts = _load_filter_options()

c1, c2 = st.columns([3, 1])
with c1:
    keyword_raw = st.text_input(
        "フリーワード（契約名に部分一致）", value="", key="search_kw",
        placeholder="例: 護衛艦 / レーダー / F-35",
    )
with c2:
    sel_fy = st.selectbox(
        "年度", options=[None, *opts["fy"]],
        format_func=lambda v: "（指定なし）" if v is None else f"FY{v}",
        key="search_fy",
    )

c3, c4 = st.columns(2)
with c3:
    sel_large = st.selectbox(
        "大区分", options=[None, *opts["large"]],
        format_func=lambda v: "（指定なし）" if v is None else v,
        key="search_large",
    )
with c4:
    sel_agency = st.selectbox(
        "調達機関", options=[None, *opts["agency"]],
        format_func=lambda v: "（指定なし）" if v is None else v,
        key="search_agency",
    )

keyword = _norm(keyword_raw)

# ── 検索実行 ─────────────────────────────────────────────
no_filter = not keyword and sel_fy is None and not sel_large and not sel_agency
if no_filter:
    st.info("条件を1つ以上指定してください。")
    st.stop()

with st.spinner("検索中..."):
    df, total = _search(keyword, sel_fy, sel_large, sel_agency, MAX_RESULTS)

shown = len(df)
amt_total_oku = df["contract_amount"].fillna(0).sum() / 1e8

m1, m2, m3 = st.columns(3)
m1.metric("ヒット件数", f"{total:,} 件")
m2.metric("表示件数", f"{shown:,} 件",
          delta=("上位500件のみ" if total > MAX_RESULTS else None),
          delta_color="off")
m3.metric("表示分の合計金額", f"{amt_total_oku:,.1f} 億円")

if total > MAX_RESULTS:
    st.warning(
        f"ヒットが {total:,} 件あります。金額降順で上位 {MAX_RESULTS} 件のみ表示します。"
        "条件を絞り込むと全件確認できます。"
    )

if df.empty:
    st.info("該当する契約はありませんでした。")
    st.stop()

# ── 結果テーブル ─────────────────────────────────────────
view = df.copy()
view["contract_amount"] = view["contract_amount"].map(
    lambda v: f"{int(v):,}" if pd.notna(v) else "-"
)
view = view.rename(columns={
    "contract_name":   "契約名",
    "vendor_name":     "受注企業",
    "contract_amount": "金額(円)",
    "agency_name":     "機関",
    "fiscal_year":     "年度",
    "contract_date":   "契約日",
    "bid_method":      "入札方式",
    "category_large":  "大区分",
    "source_url":      "出典URL",
})

st.dataframe(
    view,
    use_container_width=True,
    hide_index=True,
    height=600,
    column_config={
        "契約名":   st.column_config.TextColumn(width="large"),
        "受注企業": st.column_config.TextColumn(width="medium"),
        "金額(円)": st.column_config.TextColumn(width="small"),
        "機関":     st.column_config.TextColumn(width="medium"),
        "年度":     st.column_config.NumberColumn(format="FY%d", width="small"),
        "契約日":   st.column_config.TextColumn(width="small"),
        "入札方式": st.column_config.TextColumn(width="small"),
        "大区分":   st.column_config.TextColumn(width="small"),
        "出典URL": st.column_config.LinkColumn(width="small"),
    },
)

st.caption(
    f"並び順: 契約金額 降順（NULLは末尾）。"
    f"フリーワードと契約名を双方 NFKC 正規化（Ｆ－３５Ａ ↔ F-35A 等）して部分一致。"
)
