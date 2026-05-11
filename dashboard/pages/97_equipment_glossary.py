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

# Top30 等から equipment_id クエリパラメータ付きで直接リンクされた場合に対応
_qp_eq_id: str = st.query_params.get("equipment_id", "")

# ── パス ────────────────────────────────────────────────────────────
from _db import PROC_DB  # noqa: E402
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
if _qp_eq_id:
    # 直接リンクモード: クエリパラメータで指定された装備品のみ表示
    filt = filt[filt["equipment_id"] == _qp_eq_id]
    if filt.empty:
        st.warning(f"装備品 ID '{_qp_eq_id}' が見つかりません。全一覧を表示します。")
        filt = df_eq.copy()
    else:
        name_direct = filt.iloc[0]["name_ja"]
        st.info(f"🔗 直接リンク表示: **{name_direct}** ／ [← 全一覧に戻る](/equipment_glossary)")
else:
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

# 行政事業レビュー概要を filt にマージ
_jr_ids = tuple(filt["jigyou_review_id"].dropna().unique().tolist())
if _jr_ids:
    _jr = _load_jigyou_review(_jr_ids)
    if not _jr.empty:
        filt = filt.merge(
            _jr[["id", "overview", "rs_url"]].rename(columns={"id": "jigyou_review_id"}),
            on="jigyou_review_id",
            how="left",
        )
    else:
        filt["overview"] = None
        filt["rs_url"] = None
else:
    filt["overview"] = None
    filt["rs_url"] = None

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

        # 行政事業レビュー概要（インライン）
        overview_raw = str(row.get("overview", "") or "")
        rs_url_val   = str(row.get("rs_url", "") or "")
        if overview_raw:
            ov_text  = overview_raw[:160] + ("…" if len(overview_raw) > 160 else "")
            ov_link  = (
                f' <a href="{rs_url_val}" target="_blank" '
                f'style="color:#7c83fd;font-size:0.74rem">レビューシート↗</a>'
                if rs_url_val else ""
            )
            overview_html = (
                f'<div style="font-size:0.76rem;color:{TEXT_DIM};'
                f'margin-top:3px;line-height:1.45">{ov_text}{ov_link}</div>'
            )
        else:
            overview_html = ""

        rows_html.append(
            f'<tr style="border-bottom:1px solid #313244">'
            f'<td style="padding:5px 8px">'
            f'<span style="font-weight:600">{name_ja}</span>{overview_html}</td>'
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
        "🏛️ = 防衛省公式ページ　📖 = Wikipedia　📄 = 防衛白書。"
        "装備品名の下のテキストは行政事業レビュー概要（照合済みのみ）。"
        "リンクのない装備品は未登録（今後追加予定）。"
    )

    with st.expander("📊 カテゴリ別内訳"):
        cat_cnt = (
            filt.groupby("category", dropna=False)
            .agg(件数=("equipment_id", "count"))
            .reset_index()
            .sort_values("件数", ascending=False)
            .rename(columns={"category": "カテゴリ"})
        )
        st.dataframe(cat_cnt, use_container_width=True, hide_index=True)
