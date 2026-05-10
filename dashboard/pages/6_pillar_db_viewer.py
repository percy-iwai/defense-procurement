"""defense_pillar.db ビューワー — ピラー階層マスタ・事業名マッピング・分類根拠検索。

テーブル:
  defense_pillar_master   : L1/L2 階層と名称（19件）
  defense_pillar_jigyou   : 事業名×ピラーマッピング（826件）
  pillar_mapping_sources  : ソース別マッピング（2,649件）
"""
from __future__ import annotations

import sqlite3
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from _auth import require_password  # noqa: E402

require_password()

PROJECT_ROOT   = DASHBOARD_DIR.parent
PILLAR_DB_PATH = PROJECT_ROOT / "data" / "db" / "defense_pillar.db"

TEXT_COLOR = "#cdd6f4"
TEXT_DIM   = "#bac2de"

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

st.title("🏛️ 7本柱DBビューワー")
st.caption(
    "defense_pillar.db のピラー階層マスタ・事業名マッピング・分類根拠を閲覧・検索するビュー。"
)

if not PILLAR_DB_PATH.exists():
    st.error(f"defense_pillar.db が見つかりません: {PILLAR_DB_PATH}")
    st.stop()


# ── データ読み込み ────────────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def _load_master() -> pd.DataFrame:
    with sqlite3.connect(str(PILLAR_DB_PATH)) as conn:
        return pd.read_sql_query(
            "SELECT pillar_id, level, name, parent_id, notes "
            "FROM defense_pillar_master ORDER BY level, pillar_id",
            conn,
        )


@st.cache_data(ttl=600)
def _load_sources() -> pd.DataFrame:
    with sqlite3.connect(str(PILLAR_DB_PATH)) as conn:
        return pd.read_sql_query(
            """
            SELECT
                s.id,
                s.source_type,
                s.fiscal_year,
                s.pillar_id,
                m.name          AS pillar_name,
                s.jigyou_name,
                s.amount_hyoku_yen,
                s.confidence,
                s.notes,
                s.source_url,
                s.raw_context
            FROM pillar_mapping_sources s
            LEFT JOIN defense_pillar_master m ON m.pillar_id = s.pillar_id
            ORDER BY s.source_type, s.fiscal_year NULLS LAST, s.pillar_id
            """,
            conn,
        )


df_master  = _load_master()
df_sources = _load_sources()

_l1 = df_master[df_master["level"] == 1].set_index("pillar_id")["name"].to_dict()
_l2 = df_master[df_master["level"] == 2].set_index("pillar_id")["name"].to_dict()
_all_names = {**_l1, **_l2}


def _pillar_label(code: int | float | None) -> str:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return "—"
    c = int(code)
    name = _all_names.get(c, "")
    return f"P{c} {name}" if name else f"P{c}"


# ソース種別の表示名
_SRC_LABEL: dict[str, str] = {
    "jigyou_review":        "行政事業レビュー",
    "yosan":                "予算概要",
    "hakusho":              "防衛白書",
    "bukai":                "分科会PDF",
    "seibi_keikaku_gaiyou": "整備計画概要",
    "hyouka":               "政策評価書",
}

_all_source_types   = sorted(df_sources["source_type"].dropna().unique().tolist())
_all_pillar_ids     = sorted(df_sources["pillar_id"].dropna().unique().astype(int).tolist())
_all_fys_int        = sorted(df_sources["fiscal_year"].dropna().unique().astype(int).tolist())

# ── タブ ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(
    ["🗂️ ピラー階層マスタ", "📋 事業名マッピングDB", "🔍 分類根拠検索"]
)


# ─── TAB 1: ピラー階層マスタ ──────────────────────────────────────────────────
with tab1:
    st.subheader("ピラー階層マスタ（defense_pillar_master）")

    l1_rows = df_master[df_master["level"] == 1].sort_values("pillar_id")
    l2_rows = df_master[df_master["level"] == 2].sort_values("pillar_id")

    hier_rows: list[dict] = []
    for _, l1 in l1_rows.iterrows():
        hier_rows.append({
            "コード":   f"P{int(l1['pillar_id'])}",
            "レベル":   "L1 大項目",
            "名称":     l1["name"],
            "親コード": "—",
            "備考":     l1["notes"] or "",
        })
        for _, l2 in l2_rows[l2_rows["parent_id"] == l1["pillar_id"]].iterrows():
            hier_rows.append({
                "コード":   f"  └ P{int(l2['pillar_id'])}",
                "レベル":   "L2 中項目",
                "名称":     l2["name"],
                "親コード": f"P{int(l1['pillar_id'])}",
                "備考":     l2["notes"] or "",
            })

    st.dataframe(
        pd.DataFrame(hier_rows),
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config={
            "コード":   st.column_config.TextColumn(width="small"),
            "レベル":   st.column_config.TextColumn(width="small"),
            "名称":     st.column_config.TextColumn(width="large"),
            "親コード": st.column_config.TextColumn(width="small"),
            "備考":     st.column_config.TextColumn(width="medium"),
        },
    )
    st.caption(f"L1 大項目: {len(l1_rows)}件 / L2 中項目: {len(l2_rows)}件")


# ─── TAB 2: 事業名マッピングDB ────────────────────────────────────────────────
with tab2:
    st.subheader("事業名マッピングDB（pillar_mapping_sources）")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("総件数",     f"{len(df_sources):,}件")
    m2.metric("ソース種別", f"{df_sources['source_type'].nunique()}種")
    m3.metric("対象FY数",   f"{df_sources['fiscal_year'].dropna().nunique()}年度")
    amt_total = df_sources["amount_hyoku_yen"].fillna(0).sum()
    m4.metric("掲載金額計", f"{amt_total:,.0f}億円")

    st.divider()

    fc1, fc2, fc3 = st.columns([2, 2, 2])
    with fc1:
        sel_src = st.multiselect(
            "ソース種別",
            options=_all_source_types,
            default=_all_source_types,
            format_func=lambda x: _SRC_LABEL.get(x, x),
            key="pdb_src",
        )
    with fc2:
        sel_fy = st.multiselect(
            "FY（未選択=全て）",
            options=_all_fys_int,
            default=[],
            format_func=lambda x: f"FY{x}",
            key="pdb_fy",
        )
    with fc3:
        sel_pillar = st.multiselect(
            "ピラー（未選択=全て）",
            options=_all_pillar_ids,
            default=[],
            format_func=_pillar_label,
            key="pdb_pillar",
        )

    kw2 = st.text_input(
        "🔍 事業名フリーワード（部分一致）",
        key="pdb_kw",
        placeholder="例: F-35　護衛艦　弾薬",
    )

    # フィルター適用
    view2 = df_sources.copy()
    if sel_src:
        view2 = view2[view2["source_type"].isin(sel_src)]
    if sel_fy:
        view2 = view2[view2["fiscal_year"].isin(sel_fy)]
    if sel_pillar:
        view2 = view2[view2["pillar_id"].isin(sel_pillar)]
    if kw2.strip():
        norm_kw = unicodedata.normalize("NFKC", kw2.strip()).lower()
        view2 = view2[
            view2["jigyou_name"].fillna("").apply(
                lambda x: norm_kw in unicodedata.normalize("NFKC", x).lower()
            )
        ]

    st.caption(f"表示: {len(view2):,}件 / 全{len(df_sources):,}件")

    _SRC_COL_CFG = {
        "ソース":   st.column_config.TextColumn(width="small"),
        "FY":       st.column_config.NumberColumn(format="%d", width="small"),
        "ピラーID": st.column_config.NumberColumn(format="%d", width="small"),
        "ピラー名": st.column_config.TextColumn(width="medium"),
        "事業名":   st.column_config.TextColumn(width="large"),
        "金額(億)": st.column_config.NumberColumn(format="%.1f", width="small"),
        "conf":     st.column_config.NumberColumn(format="%.2f", width="small"),
        "備考":     st.column_config.TextColumn(width="medium"),
    }

    st.dataframe(
        view2[["source_type", "fiscal_year", "pillar_id", "pillar_name",
               "jigyou_name", "amount_hyoku_yen", "confidence", "notes"]].rename(columns={
            "source_type":      "ソース",
            "fiscal_year":      "FY",
            "pillar_id":        "ピラーID",
            "pillar_name":      "ピラー名",
            "jigyou_name":      "事業名",
            "amount_hyoku_yen": "金額(億)",
            "confidence":       "conf",
            "notes":            "備考",
        }),
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config=_SRC_COL_CFG,
    )


# ─── TAB 3: 分類根拠検索 ─────────────────────────────────────────────────────
with tab3:
    st.subheader("分類根拠検索")
    st.caption(
        "契約名・装備品名を入力すると pillar_mapping_sources から関連エントリを検索します。"
        "スペース区切りで AND 検索。assign_pillar_fy2023.py の突合確認に使えます。"
    )

    query = st.text_input(
        "検索クエリ",
        key="pdb_q",
        placeholder="例: 護衛艦 ソーナー　/　F-35　/　弾薬 誘導弾",
    )

    sc1, sc2 = st.columns([1, 3])
    with sc1:
        min_conf = st.slider("最低信頼度", 0.0, 1.0, 0.0, 0.05, key="pdb_min_conf")
    with sc2:
        search_src = st.multiselect(
            "ソース種別（未選択=全て）",
            options=_all_source_types,
            default=[],
            format_func=lambda x: _SRC_LABEL.get(x, x),
            key="pdb_search_src",
        )

    if not query.strip():
        st.info("検索クエリを入力してください。")
    else:
        tokens = [
            unicodedata.normalize("NFKC", t).lower()
            for t in query.strip().split()
            if t.strip()
        ]

        res = df_sources.copy()
        if search_src:
            res = res[res["source_type"].isin(search_src)]
        if min_conf > 0:
            res = res[res["confidence"].fillna(0) >= min_conf]

        res = res[
            res["jigyou_name"].fillna("").apply(
                lambda x: all(
                    t in unicodedata.normalize("NFKC", x).lower() for t in tokens
                )
            )
        ]

        st.metric("ヒット件数", f"{len(res):,}件")

        if res.empty:
            st.warning("該当するエントリが見つかりませんでした。")
        else:
            st.dataframe(
                res[["source_type", "fiscal_year", "pillar_id", "pillar_name",
                     "jigyou_name", "amount_hyoku_yen", "confidence", "notes",
                     "raw_context"]].rename(columns={
                    "source_type":      "ソース",
                    "fiscal_year":      "FY",
                    "pillar_id":        "ピラーID",
                    "pillar_name":      "ピラー名",
                    "jigyou_name":      "事業名",
                    "amount_hyoku_yen": "金額(億)",
                    "confidence":       "conf",
                    "notes":            "備考",
                    "raw_context":      "文脈",
                }),
                use_container_width=True,
                hide_index=True,
                height=600,
                column_config={
                    "ソース":   st.column_config.TextColumn(width="small"),
                    "FY":       st.column_config.NumberColumn(format="%d", width="small"),
                    "ピラーID": st.column_config.NumberColumn(format="%d", width="small"),
                    "ピラー名": st.column_config.TextColumn(width="medium"),
                    "事業名":   st.column_config.TextColumn(width="large"),
                    "金額(億)": st.column_config.NumberColumn(format="%.1f", width="small"),
                    "conf":     st.column_config.NumberColumn(format="%.2f", width="small"),
                    "備考":     st.column_config.TextColumn(width="medium"),
                    "文脈":     st.column_config.TextColumn(width="large"),
                },
            )
