"""主要装備品 解説図鑑ページ。

equipment_master テーブルの装備品を一覧表示し、branch / category でフィルタできる。
解説 URL（公式・Wikipedia・防衛白書）があればリンクボタンを表示する。
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

# ── パス ────────────────────────────────────────────────────────────
PROC_DB = DASHBOARD_DIR.parent / "data" / "db" / "procurement.db"
JR_DB   = DASHBOARD_DIR.parent / "data" / "db" / "jigyou_review.db"

# ── スタイル ─────────────────────────────────────────────────────────
TEXT_COLOR = "#cdd6f4"
TEXT_DIM = "#bac2de"
ACCENT = "#7c83fd"

st.markdown(
    f"""
    <style>
    .stApp, .stApp p, .stApp span, .stApp label, .stApp th, .stApp td {{
        color: {TEXT_COLOR};
    }}
    .stApp h1, .stApp h2, .stApp h3 {{ color: {TEXT_COLOR}; }}
    [data-testid="stCaptionContainer"] {{ color: {TEXT_DIM} !important; }}
    [data-testid="stDataFrame"] td {{ font-size: 0.82rem !important; }}
    [data-testid="stDataFrame"] th {{ font-size: 0.82rem !important; white-space: nowrap; }}
    a, a:visited {{ color: {ACCENT}; text-decoration: none; }}
    a:hover {{ color: #a5b4fc; text-decoration: underline; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ── branch 表示名 ────────────────────────────────────────────────────
_BRANCH_LABELS: dict[str, str] = {
    "GSDF":     "陸上自衛隊",
    "MSDF":     "海上自衛隊",
    "ASDF":     "航空自衛隊",
    "ATLA":     "防衛装備庁",
    "JS":       "統合幕僚監部",
    "DIH":      "情報本部",
    "JOINT":    "統合・共通",
    "RDB":      "地方防衛局",
    "NDMC":     "防衛医科大学校",
    "NDA":      "防衛大学校",
    "NAIKYOKU": "内部部局",
}


@st.cache_data(ttl=600)
def _load_equipment() -> pd.DataFrame:
    with sqlite3.connect(PROC_DB) as conn:
        df = pd.read_sql_query(
            """SELECT equipment_id, name_ja, name_en, branch, category,
                      ref_url_official, ref_url_wikipedia, ref_url_hakusho,
                      keywords, jigyou_review_id
               FROM equipment_master
               ORDER BY branch, category, name_ja""",
            conn,
        )
    df["branch_label"] = df["branch"].map(_BRANCH_LABELS).fillna(df["branch"].fillna("不明"))
    df["best_url"] = df["ref_url_official"].fillna(
        df["ref_url_wikipedia"].fillna(df["ref_url_hakusho"])
    )
    return df


@st.cache_data(ttl=600)
def _load_jigyou_review(ids: tuple[str, ...]) -> pd.DataFrame:
    """jigyou_review.db から指定IDの事業概要を取得。"""
    if not ids or not JR_DB.exists():
        return pd.DataFrame()
    placeholders = ",".join("?" * len(ids))
    with sqlite3.connect(JR_DB) as conn:
        df = pd.read_sql_query(
            f"""SELECT id, name, overview, purpose, rs_url, fiscal_year
                FROM projects
                WHERE id IN ({placeholders})""",
            conn,
            params=list(ids),
        )
    return df


# ════════════════════════════════════════════════════════════════════
# 描画
# ════════════════════════════════════════════════════════════════════
st.title("🔭 主要装備品 解説図鑑")
st.caption("equipment_master テーブルに登録されている装備品の一覧。📖 リンクは公式・Wikipedia・防衛白書の優先順。")

df_eq = _load_equipment()

# ── フィルタ ─────────────────────────────────────────────────────────
fil1, fil2, fil3 = st.columns([2, 2, 3])
with fil1:
    branches = ["すべて"] + sorted(df_eq["branch_label"].dropna().unique().tolist())
    sel_branch = st.selectbox("要求元（branch）", branches, key="eq_branch")
with fil2:
    cats_all = sorted(df_eq["category"].dropna().unique().tolist())
    categories = ["すべて"] + cats_all
    sel_cat = st.selectbox("カテゴリ", categories, key="eq_cat")
with fil3:
    kw = st.text_input("キーワード検索（装備品名・keywords）", key="eq_kw")

filt = df_eq.copy()
if sel_branch != "すべて":
    filt = filt[filt["branch_label"] == sel_branch]
if sel_cat != "すべて":
    filt = filt[filt["category"] == sel_cat]
if kw:
    mask = (
        filt["name_ja"].str.contains(kw, na=False, case=False)
        | filt["name_en"].fillna("").str.contains(kw, na=False, case=False)
        | filt["keywords"].fillna("").str.contains(kw, na=False, case=False)
    )
    filt = filt[mask]

st.caption(f"{len(filt):,} 件 / 全{len(df_eq):,}件")

# ── カスタム HTML テーブル ────────────────────────────────────────────
if filt.empty:
    st.info("条件に一致する装備品がありません。")
else:
    rows_html: list[str] = []
    for _, row in filt.iterrows():
        name_ja  = str(row["name_ja"] or "")
        name_en  = str(row["name_en"] or "")
        branch   = str(row["branch_label"] or "—")
        cat      = str(row["category"] or "—")
        best_url = str(row["best_url"] or "")

        # URL 列: 公式・Wikipedia・白書それぞれ別アイコン
        url_parts: list[str] = []
        if row["ref_url_official"]:
            url_parts.append(
                f'<a href="{row["ref_url_official"]}" target="_blank" '
                f'title="公式" style="color:#7c83fd">🏛️</a>'
            )
        if row["ref_url_wikipedia"]:
            url_parts.append(
                f'<a href="{row["ref_url_wikipedia"]}" target="_blank" '
                f'title="Wikipedia" style="color:#89dceb">📖</a>'
            )
        if row["ref_url_hakusho"]:
            url_parts.append(
                f'<a href="{row["ref_url_hakusho"]}" target="_blank" '
                f'title="防衛白書" style="color:#a6e3a1">📄</a>'
            )
        if row.get("jigyou_review_id"):
            url_parts.append('<span title="行政事業レビュー照合済み" style="cursor:default">📋</span>')
        url_cell = " ".join(url_parts) if url_parts else "—"

        rows_html.append(
            f'<tr style="border-bottom:1px solid #313244">'
            f'<td style="padding:5px 8px;font-weight:600">{name_ja}</td>'
            f'<td style="padding:5px 8px;color:{TEXT_DIM};font-size:0.78rem">{name_en}</td>'
            f'<td style="padding:5px 8px;font-size:0.82rem">{branch}</td>'
            f'<td style="padding:5px 8px;font-size:0.82rem">{cat}</td>'
            f'<td style="padding:5px 8px;text-align:center">{url_cell}</td>'
            f'</tr>'
        )

    html = (
        '<div style="overflow-x:auto;max-height:70vh;overflow-y:auto">'
        f'<table style="border-collapse:collapse;width:100%;font-size:0.85rem;color:{TEXT_COLOR}">'
        '<thead style="position:sticky;top:0;z-index:2;background:#1e1e2e">'
        '<tr style="border-bottom:2px solid #45475a;color:{TEXT_DIM}">'
        '<th style="padding:5px 8px;text-align:left;min-width:160px">装備品名（和名）</th>'
        '<th style="padding:5px 8px;text-align:left;min-width:130px">英名</th>'
        '<th style="padding:5px 8px;text-align:left">要求元</th>'
        '<th style="padding:5px 8px;text-align:left">カテゴリ</th>'
        '<th style="padding:5px 8px;text-align:center;min-width:80px">解説リンク</th>'
        '</tr>'
        '</thead>'
        '<tbody>'
        + "".join(rows_html)
        + '</tbody></table></div>'
    )
    st.markdown(html, unsafe_allow_html=True)

    st.caption(
        "🏛️ = 防衛省公式ページ　📖 = Wikipedia　📄 = 防衛白書　📋 = 行政事業レビュー照合済み。"
        "リンクのない装備品は未登録（今後追加予定）。"
    )

    # ── 行政事業レビュー 照合済み概要 ────────────────────────────────────
    jr_ids_in_view = filt["jigyou_review_id"].dropna().unique().tolist()
    if jr_ids_in_view:
        with st.expander(f"📋 行政事業レビュー 照合済み概要（{len(jr_ids_in_view)} 件）"):
            jr_df = _load_jigyou_review(tuple(jr_ids_in_view))
            if not jr_df.empty:
                # equipment_master と結合して装備品名を付加
                eq_jr = filt[filt["jigyou_review_id"].notna()][
                    ["equipment_id", "name_ja", "jigyou_review_id"]
                ].merge(
                    jr_df.rename(columns={"id": "jigyou_review_id"}),
                    on="jigyou_review_id",
                    how="left",
                )
                for _, r in eq_jr.sort_values("name_ja").iterrows():
                    proj_name = str(r.get("name", ""))
                    overview  = str(r.get("overview", "") or "")
                    purpose   = str(r.get("purpose", "") or "")
                    rs_url    = str(r.get("rs_url", "") or "")
                    fy        = int(r.get("fiscal_year", 0) or 0)
                    eq_name   = str(r.get("name_ja", ""))

                    link = f'　<a href="{rs_url}" target="_blank" style="color:#7c83fd;font-size:0.8rem">行政事業レビューシート →</a>' if rs_url else ""
                    st.markdown(
                        f'<div style="margin:4px 0 2px;font-weight:600;color:{TEXT_COLOR}">'
                        f'{eq_name} '
                        f'<span style="font-size:0.78rem;color:{TEXT_DIM};font-weight:400">▸ {proj_name}（FY{fy}）</span>'
                        f'{link}</div>',
                        unsafe_allow_html=True,
                    )
                    if overview:
                        st.markdown(
                            f'<div style="font-size:0.82rem;color:{TEXT_DIM};margin-left:8px;margin-bottom:6px">'
                            f'{overview[:300]}{"…" if len(overview) > 300 else ""}</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.info("行政事業レビューデータを読み込めません。")

    with st.expander("📊 カテゴリ別内訳"):
        cat_cnt = (
            filt.groupby("category", dropna=False)
            .agg(件数=("equipment_id", "count"))
            .reset_index()
            .sort_values("件数", ascending=False)
            .rename(columns={"category": "カテゴリ"})
        )
        st.dataframe(cat_cnt, use_container_width=True, hide_index=True)
