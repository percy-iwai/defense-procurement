"""defense_pillar.db ビューワー — 柱別集計・ピラー階層マスタ・事業名マッピング・分類根拠検索。

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
import plotly.graph_objects as go
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from _auth import require_password  # noqa: E402

require_password()

PROJECT_ROOT      = DASHBOARD_DIR.parent
PILLAR_DB_PATH    = PROJECT_ROOT / "data" / "db" / "defense_pillar.db"
from _db import PROC_DB as PROC_DB_PATH  # noqa: E402

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


# ── 柱別集計用データ ─────────────────────────────────────────────────────────

# FY2023 柱別予算額（契約ベース、単位：億円）
# 出典: 防衛省「令和5年度予算の概要」/ 防衛力整備計画
_BUDGET_FY2023: dict[int, float] = {
    1: 14207.0,
    2:  9867.0,
    3:  1827.0,
    4: 16250.0,
    5:  4588.0,
    6:  2696.0,
    7: 33687.0,
    8: 21795.0,
}
# FY2024 予算（契約ベース・億円） — 令和6年度予算概要 P.7 より抽出
_BUDGET_FY2024: dict[int, float] = {
    1:  7127.0,
    2: 12284.0,
    3:  1146.0,
    4: 16401.0,
    5:  4248.0,
    6:  5653.0,
    7: 29422.0,
    8: 17336.0,
}
# FY2025 予算（契約ベース・億円） — 令和7年度予算概要 P.7 より抽出
_BUDGET_FY2025: dict[int, float] = {
    1:  9390.0,
    2:  5331.0,
    3:  1110.0,
    4: 16119.0,
    5:  3852.0,
    6:  4545.0,
    7: 27525.0,
    8: 16459.0,
}
_BUDGET_ALL: dict[int, dict[int, float]] = {
    2023: _BUDGET_FY2023,
    2024: _BUDGET_FY2024,
    2025: _BUDGET_FY2025,
}

# L1 大項目の表示名（contract_pillar の pillar_l1_code に対応）
_L1_NAMES: dict[int, str] = {
    1: "P1 スタンド・オフ防衛能力",
    2: "P2 統合防空ミサイル防衛能力",
    3: "P3 無人アセット防衛能力",
    4: "P4 領域横断作戦能力",
    5: "P5 指揮統制・情報関連機能",
    6: "P6 機動展開能力・国民保護",
    7: "P7 持続性・強靱性",
    8: "P8 防衛力を支える基盤",
}


@st.cache_data(ttl=600)
def _load_pillar_summary(fy: int, chuo_only: bool = False) -> pd.DataFrame:
    """指定FYの L1 柱別集計（DB金額・件数）を返す。未分類行を末尾に追加。"""
    _atla_clause = "AND c.agency_id LIKE 'atla%'" if chuo_only else ""
    with sqlite3.connect(str(PROC_DB_PATH)) as conn:
        df = pd.read_sql_query(
            f"""
            SELECT
                cp.pillar_l1_code,
                COUNT(*)                              AS 件数,
                ROUND(SUM(c.contract_amount) / 1e8, 1) AS DB金額_億
            FROM contract_pillar cp
            JOIN contracts c ON cp.contract_id = c.id
            WHERE c.fiscal_year = ?
              {_atla_clause}
            GROUP BY cp.pillar_l1_code
            ORDER BY cp.pillar_l1_code
            """,
            conn,
            params=(fy,),
        )
    rows = []
    for _, r in df[df["pillar_l1_code"].notna()].iterrows():
        code = int(r["pillar_l1_code"])
        budget = _BUDGET_ALL.get(fy, {}).get(code)
        cov = round(r["DB金額_億"] / budget * 100, 1) if budget and budget > 0 else None
        rows.append({
            "ピラー":        _L1_NAMES.get(code, f"P{code}"),
            "件数":          int(r["件数"]),
            "DB金額（億円）": r["DB金額_億"],
            "予算額（億円）": budget,
            "カバレッジ（%）": cov,
        })
    # 未分類（pillar_l1_code IS NULL）
    unc = df[df["pillar_l1_code"].isna()]
    if not unc.empty:
        rows.append({
            "ピラー":         "未分類",
            "件数":           int(unc["件数"].sum()),
            "DB金額（億円）":  round(unc["DB金額_億"].sum(), 1),
            "予算額（億円）":  None,
            "カバレッジ（%）": None,
        })
    return pd.DataFrame(rows)


df_master  = _load_master()
df_sources = _load_sources()

chuo_only = st.checkbox(
    "中央契約のみ集計（ATLA）",
    value=False,
    key="pdb_chuo",
    help="防衛装備庁（ATLA）が調達した契約のみ集計します（柱別集計・年度比較タブに適用）",
)

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
tab0, tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 柱別集計", "🗂️ ピラー階層マスタ", "📋 事業名マッピングDB", "🔍 分類根拠検索",
     "📈 年度比較"]
)


# ─── TAB 0: 柱別集計 ─────────────────────────────────────────────────────────
with tab0:
    st.subheader("柱別集計（contract_pillar × contracts）")
    st.caption(
        "procurement.db の contract_pillar テーブルを集計。"
        "予算額・カバレッジは FY2023/2024/2025（契約ベース）。"
        "DB金額・予算額ともに契約ベース（歳出ベースと混同しないこと）。"
    )

    sel_fy0 = st.selectbox(
        "FY 選択",
        options=[2025, 2024, 2023, 2022],
        index=0,  # default: 2025
        format_func=lambda x: f"FY{x}（令和{x - 2018}年度）",
        key="pillar_summary_fy",
    )

    if not PROC_DB_PATH.exists():
        st.error(f"procurement.db が見つかりません: {PROC_DB_PATH}")
    else:
        df_summary = _load_pillar_summary(sel_fy0, chuo_only)

        # 分類済み / 未分類 の分割
        _classified   = df_summary[df_summary["ピラー"] != "未分類"]
        _unclassified = df_summary[df_summary["ピラー"] == "未分類"]

        total_cnt      = int(df_summary["件数"].sum())
        classified_amt = float(_classified["DB金額（億円）"].sum())
        unc_amt        = float(_unclassified["DB金額（億円）"].sum()) if not _unclassified.empty else 0.0
        total_amt      = classified_amt + unc_amt

        # メトリクス行
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("総件数（FY）",       f"{total_cnt:,}件")
        mc2.metric("全体DB金額",         f"{total_amt:,.0f}億円")
        mc3.metric("分類済みDB金額",     f"{classified_amt:,.0f}億円")
        mc4.metric("未分類DB金額",       f"{unc_amt:,.0f}億円")

        st.divider()

        # 表示用 DataFrame — None を "—" に変換
        disp = df_summary.copy()
        disp["予算額（億円）"]  = disp["予算額（億円）"].apply(
            lambda v: f"{v:,.0f}" if v is not None and not (isinstance(v, float) and pd.isna(v)) else "—"
        )
        disp["カバレッジ（%）"] = disp["カバレッジ（%）"].apply(
            lambda v: f"{v:.1f}%" if v is not None and not (isinstance(v, float) and pd.isna(v)) else "—"
        )

        st.dataframe(
            disp,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ピラー":         st.column_config.TextColumn("ピラー", width="large"),
                "件数":           st.column_config.NumberColumn("件数", format="%d", width="small"),
                "DB金額（億円）": st.column_config.NumberColumn("DB金額（億円）", format="%.1f", width="medium"),
                "予算額（億円）": st.column_config.TextColumn("予算額（億円）", width="medium"),
                "カバレッジ（%）": st.column_config.TextColumn("カバレッジ（%）", width="small"),
            },
        )

        _fy_budget = _BUDGET_ALL.get(sel_fy0, {})
        if _fy_budget:
            budget_total = sum(_fy_budget.values())
            overall_cov  = round(classified_amt / budget_total * 100, 1)
            st.caption(
                f"FY{sel_fy0} 予算総額（8本柱合計）: {budget_total:,.0f}億円　"
                f"／　分類済みDB金額: {classified_amt:,.0f}億円　"
                f"／　全体カバレッジ: **{overall_cov:.1f}%**"
            )
        else:
            st.info("FY2022 は予算データ未登録のため予算額・カバレッジは「—」表示。")


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


# ─── TAB 4: 年度比較 ─────────────────────────────────────────────────────────
with tab4:
    st.subheader("FY2023/2024/2025 年度比較")
    st.caption(
        "各FYの分類済みDB金額と予算額を並べて比較。"
        "予算額・DB金額ともに契約ベース（億円）。"
    )

    if not PROC_DB_PATH.exists():
        st.error(f"procurement.db が見つかりません: {PROC_DB_PATH}")
    else:
        _compare_fys = [2023, 2024, 2025]
        _compare_rows = []
        for _cfy in _compare_fys:
            _df = _load_pillar_summary(_cfy, chuo_only)
            for _, _r in _df[_df["ピラー"] != "未分類"].iterrows():
                _compare_rows.append({
                    "FY":             _cfy,
                    "ピラー":          _r["ピラー"],
                    "DB金額（億円）":  _r["DB金額（億円）"],
                    "予算額（億円）":  _r["予算額（億円）"],
                })
        df_cmp = pd.DataFrame(_compare_rows)

        # ── 横棒グラフ: FYごとのP1-P8 DB金額 ────────────────────────────────
        pillar_order = [_L1_NAMES[k] for k in sorted(_L1_NAMES.keys())]
        _colors = {"2023": "#4fc3f7", "2024": "#81c784", "2025": "#ffb74d"}

        fig = go.Figure()
        for _cfy in _compare_fys:
            _sub = df_cmp[df_cmp["FY"] == _cfy].set_index("ピラー")["DB金額（億円）"]
            _vals = [float(_sub.get(p, 0) or 0) for p in pillar_order]
            fig.add_trace(go.Bar(
                name=f"FY{_cfy} DB金額",
                y=pillar_order,
                x=_vals,
                orientation="h",
                marker_color=_colors[str(_cfy)],
            ))

        fig.update_layout(
            barmode="group",
            height=480,
            margin=dict(l=10, r=20, t=30, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#cdd6f4"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(title="DB金額（億円）", gridcolor="#45475a"),
            yaxis=dict(gridcolor="#45475a"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── サマリーテーブル: FY×ピラー カバレッジ ───────────────────────────
        st.subheader("FY別カバレッジ早見表")
        _tbl_rows = []
        for _cfy in _compare_fys:
            _df_s = _load_pillar_summary(_cfy, chuo_only)
            _cls  = _df_s[_df_s["ピラー"] != "未分類"]
            _unc  = _df_s[_df_s["ピラー"] == "未分類"]
            _bgt  = sum(_BUDGET_ALL.get(_cfy, {}).values())
            _db   = float(_cls["DB金額（億円）"].sum())
            _unc_db = float(_unc["DB金額（億円）"].sum()) if not _unc.empty else 0.0
            _total  = int(_df_s["件数"].sum())
            _cls_cnt = int(_cls["件数"].sum())
            _cov = round(_db / _bgt * 100, 1) if _bgt else None
            _tbl_rows.append({
                "FY":               _cfy,
                "総件数":           _total,
                "分類済み件数":     _cls_cnt,
                "分類率（件数%）":  round(_cls_cnt / _total * 100, 1) if _total else None,
                "分類済みDB金額（億円）": _db,
                "未分類DB金額（億円）":   _unc_db,
                "予算総額（億円）": _bgt if _bgt else None,
                "カバレッジ（%）":  _cov,
            })
        df_tbl = pd.DataFrame(_tbl_rows)
        st.dataframe(
            df_tbl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "FY":                      st.column_config.NumberColumn(format="FY%d", width="small"),
                "総件数":                  st.column_config.NumberColumn(format="%d"),
                "分類済み件数":            st.column_config.NumberColumn(format="%d"),
                "分類率（件数%）":         st.column_config.NumberColumn(format="%.1f%%"),
                "分類済みDB金額（億円）":  st.column_config.NumberColumn(format="%.0f"),
                "未分類DB金額（億円）":    st.column_config.NumberColumn(format="%.0f"),
                "予算総額（億円）":        st.column_config.NumberColumn(format="%.0f"),
                "カバレッジ（%）":         st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
