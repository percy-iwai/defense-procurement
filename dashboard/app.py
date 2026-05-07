"""防衛省・自衛隊 調達情報ダッシュボード — トップページ単一構成"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── パス ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "db" / "procurement.db"

# ── カラーテーマ ─────────────────────────────────────────────────────
PLOT_TEMPLATE = "plotly_dark"
ACCENT        = "#7c83fd"
ACCENT_2      = "#fab387"
ACCENT_3      = "#a6e3a1"
COLOR_SEQ     = px.colors.qualitative.Vivid
TEXT_COLOR    = "#cdd6f4"
TEXT_DIM      = "#bac2de"
NAVY          = "#1e1e2e"
RED_BG        = "#3b1111"

# ── カバレッジ定数（各FY予算書より） ──────────────────────────────
# 物件費（契約ベース）億円
_BUDGET = {
    2022: 34_980,   # R4予算概要 yosan_20220324.pdf P.56
    2023: 89_525,   # R5決算検査報告（会計検査院）
    2024: 93_625,   # R6予算概要 yosan_20240328.pdf P.58
    2025: 84_332,   # R7予算概要 yosan_20250402.pdf P.66
}
# 非契約系（光熱水料・補助金・借料等）― FY2024実績から他FYは概算
_NON_CONTRACT = {
    2022:  2_800,   # R4: 予算規模比例推定（FY2024比 7,500×34,980/93,625）
    2023:  7_300,   # R5: 比例推定から電算機借料(契約)を除外（HNS+光熱水+借料+補助金+教育医療）
    2024:  7_500,   # FY2024確定値（行政事業レビューDB突合、電算機借料=契約のため除外済み）
    2025:  7_600,   # R7: 比例推定
}
# 不用額（執行されなかった予算残）
_FUYOU = {
    2022:    500,   # R4決算概算
    2023:  1_300,   # 会計検査院R5決算検査報告: 計画対象経費の不用額1,294億円
    2024:  1_200,   # R6決算（朝日新聞/日刊ゲンダイ 2025-11）
    2025:   None,   # 未公表
}

_BUDGET_FY2024  = _BUDGET[2024]
_NON_CONTRACT_FY2024 = _NON_CONTRACT[2024]
_FUYOU_FY2024   = _FUYOU[2024]
_EFFECTIVE_BASE = _BUDGET_FY2024 - _NON_CONTRACT_FY2024 - _FUYOU_FY2024   # ≈84,925

def _effective_base(fy: int) -> int | None:
    """実質契約対象母数（非契約系・不用額控除後）。"""
    b = _BUDGET.get(fy)
    nc = _NON_CONTRACT.get(fy)
    fu = _FUYOU.get(fy)
    if b is None or nc is None:
        return None
    return b - nc - (fu or 0)

# ════════════════════════════════════════════════════════════════════
# ページ設定
# ════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="ダッシュボード",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from _auth import require_password
require_password()

st.markdown(f"""
<style>
.stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp th, .stApp td {{
    color: {TEXT_COLOR};
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: {TEXT_COLOR}; }}
[data-testid="stMetricValue"] {{
    font-size: 1.6rem; color: {TEXT_COLOR}; font-weight: 600;
}}
[data-testid="stMetricLabel"] {{ color: {TEXT_DIM}; font-size: 0.85rem; }}
[data-testid="stCaptionContainer"] {{ color: {TEXT_DIM} !important; }}
[data-testid="stDataFrame"] td {{ font-size: 0.78rem !important; }}
[data-testid="stDataFrame"] th {{ font-size: 0.78rem !important; white-space: nowrap; }}
a, a:visited {{ color: {ACCENT}; text-decoration: none; }}
a:hover {{ color: #a5b4fc; text-decoration: underline; }}
/* URLマトリクス */
table.url-matrix {{
    border-collapse: collapse; font-size: 0.75rem; width: 100%;
}}
table.url-matrix th, table.url-matrix td {{
    border: 1px solid #313244; padding: 3px 6px;
    white-space: nowrap; vertical-align: middle; text-align: center;
    color: {TEXT_COLOR};
}}
table.url-matrix th {{
    background: #1e1e2e; font-weight: 600;
    position: sticky; top: 0; z-index: 2;
}}
table.url-matrix td.agency-cell {{
    background: #181825; font-weight: 600; text-align: left;
    min-width: 110px; max-width: 150px;
    overflow: hidden; text-overflow: ellipsis;
}}
table.url-matrix td.cat-cell {{
    background: #1e1e2e; text-align: left; width: 80px; font-size: 0.72rem;
}}
table.url-matrix td.has-link {{ background: #1a2a1a; }}
table.url-matrix td.no-data {{ background: #2a1a1a; color: #585b70; }}
table.url-matrix td.no-data::after {{ content: "－"; color: #45475a; }}
table.url-matrix a {{
    display: block; overflow: hidden; text-overflow: ellipsis;
    max-width: 90px; font-size: 0.72rem; color: {ACCENT};
}}
</style>
""", unsafe_allow_html=True)

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()


# ════════════════════════════════════════════════════════════════════
# ヘルパー
# ════════════════════════════════════════════════════════════════════
def _normalize_bid(bid) -> str:
    _MAP = {
        "一般": "一般競争入札", "一般契約": "一般競争入札",
        "一般入札": "一般競争入札", "一 般": "一般競争入札",
        "一般（制限付）": "一般競争入札", "一般 競争 入札": "一般競争入札",
        "一般（制限付き）": "一般競争入札", "一般競争 入札": "一般競争入札",
        "一般契約（総合評価）": "総合評価落札方式",
        "公募型指名競争": "指名競争入札",
    }
    _ZUII_KW = ("会計法", "技術的適性", "ため。", "プロポーザル方式\n会計")
    if bid is None or (isinstance(bid, float) and pd.isna(bid)):
        return "不明"
    b = str(bid).replace("\n", " ").strip()
    if b in _MAP:
        return _MAP[b]
    if any(k in b for k in _ZUII_KW):
        return "随意契約"
    if b in ("－", "〃", "〇", ""):
        return "不明"
    return b[:30]


def _normalize_vendor(name) -> str | None:
    if not name or (isinstance(name, float) and pd.isna(name)):
        return None
    n = unicodedata.normalize("NFKC", str(name))
    n = re.sub(r"[（(]株[)）]|㈱", "株式会社", n)
    n = re.sub(r"[（(]有[)）]|㈲", "有限会社", n)
    n = re.sub(r"[（(]合[)）]", "合同会社", n)
    m = re.match(r"^(株式会社|有限会社|合同会社|合名会社|合資会社)\s*(.+)$", n)
    if m and not re.search(r"株式会社|有限会社|合同会社", m.group(2)):
        n = m.group(2).strip() + m.group(1)
    return re.sub(r"\s+", " ", n).strip() or None


def _branch(aid: str) -> str:
    for prefix, label in [
        ("atla", "ATLA"), ("asdf", "ASDF"), ("msdf", "MSDF"),
        ("gsdf", "GSDF"), ("rdb", "RDB"), ("ndmc", "NDMC"),
        ("js", "統幕"), ("dih", "情本"), ("naikyoku", "内局"),
    ]:
        if aid.startswith(prefix):
            return label
    return "その他"


def _classify_url(url: str) -> tuple[str, str]:
    s = url.lower()
    fn = s.rsplit("/", 1)[-1]
    if any(k in s for k in (
        "kouji", "koji", "kensetu", "kensetsu", "kenchiku", "koukyo",
        "-k.", "_k.", "_k_", "-k-", "constraction", "construction",
        "rakusatsu_k", "zuikei_k", "koukyou_k", "koukyou-k",
    )):
        cat = "公共工事"
    elif any(k in s for k in (
        "busshi", "yakumu", "bukhin", "buppin",
        "-b.", "_b.", "_b_", "-b-",
        "rakusatsu_b", "zuikei_b", "koukyou_b", "koukyou-b",
    )):
        cat = "物品役務"
    else:
        cat = "不明"
    if any(k in s for k in (
        "zuikei", "zuii", "zuiken", "kouhyou-z", "kou_zui", "/zui/",
        "zuikei_b", "zuikei_k",
    )) and "kyoso_kijun" not in s:
        bid = "随契"
    elif any(k in s for k in (
        "kyoso", "nyuusatu", "rakusatu", "kouhyou-n", "kou_nyu", "/nyu/",
        "rakusatsu_b", "rakusatsu_k", "n-b.", "n-k.", "_n-", "-n-",
    )) or any(k in fn for k in ("kyousou", "rakusatsu", "nyuusatsu")):
        bid = "競争"
    elif any(k in fn for k in ("zuikei", "zuii")):
        bid = "随契"
    else:
        bid = "不明"
    return cat, bid


# ════════════════════════════════════════════════════════════════════
# キャッシュ付きデータロード
# ════════════════════════════════════════════════════════════════════
# 機関名の表示名上書き（DB側のリネーム漏れ・キャッシュ残留に備える防御層）
_AGENCY_NAME_OVERRIDES = {
    "防衛装備庁本庁":   "防衛装備庁 調達事業部（中央調達）",
    "防衛装備庁（旧）": "防衛装備庁 調達事業部（中央調達）",
}


@st.cache_data(ttl=300)
def _load_contracts() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            """SELECT id, fiscal_year, contract_date, agency_id, agency_name,
                      agency_category, contract_type, contract_name,
                      vendor_name, contract_amount, bid_method, source_url,
                      category_large, category_mid, category_small
               FROM contracts""",
            conn,
        )
    df["agency_name"]  = df["agency_name"].replace(_AGENCY_NAME_OVERRIDES)
    df["amount_oku"]   = df["contract_amount"].fillna(0) / 1e8
    df["bid_display"]  = df["bid_method"].map(_normalize_bid)
    df["vendor_norm"]  = df["vendor_name"].map(_normalize_vendor)
    return df


@st.cache_data(ttl=300)
def _load_budget() -> pd.DataFrame:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                "SELECT * FROM budget_reference ORDER BY fiscal_year", conn
            )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def _load_url_summary() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """SELECT agency_id, MIN(agency_name) AS agency_name,
                      fiscal_year, source_url, COUNT(*) AS record_count
               FROM contracts
               WHERE source_url IS NOT NULL AND fiscal_year = 2024
               GROUP BY agency_id, fiscal_year, source_url""",
            conn,
        )


@st.cache_data(ttl=120)
def _load_url_months() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """SELECT source_url,
                      CAST(SUBSTR(contract_date,5,2) AS INTEGER) AS month,
                      COUNT(*) AS cnt
               FROM contracts
               WHERE source_url IS NOT NULL
                 AND contract_date IS NOT NULL AND LENGTH(contract_date) = 8
                 AND fiscal_year = 2024
               GROUP BY source_url, month""",
            conn,
        )


@st.dialog("組織別ドリルダウン", width="large")
def show_sunburst_drilldown(sub: pd.DataFrame, title: str) -> None:
    st.subheader(title)
    if sub.empty:
        st.info("該当データなし")
        return
    summary_amt = sub["contract_amount"].fillna(0).sum()
    st.caption(f"{len(sub):,}件 / 総額 {summary_amt / 1e8:,.1f}億円")
    view = sub[[
        "fiscal_year", "contract_date", "agency_name",
        "contract_name", "contract_amount", "bid_display",
        "source_url",
    ]].copy()
    view = view.sort_values("contract_amount", ascending=False, na_position="last")
    view["contract_amount"] = view["contract_amount"].map(
        lambda v: f"{int(v):,}" if pd.notna(v) else "-"
    )
    view = view.rename(columns={
        "fiscal_year": "年度", "contract_date": "契約日",
        "agency_name": "機関", "contract_name": "契約名",
        "contract_amount": "金額(円)", "bid_display": "入札方式",
        "source_url": "出典URL",
    })
    st.dataframe(view, use_container_width=True, hide_index=True, height=500)


@st.dialog("ドリルダウン", width="large")
def show_vendor_drilldown(sub: pd.DataFrame, title: str) -> None:
    st.subheader(title)
    if sub.empty:
        st.info("該当データなし")
        return
    summary_amt = sub["contract_amount"].fillna(0).sum()
    st.caption(f"{len(sub):,}件 / {summary_amt:,.0f}円")
    view = sub[[
        "fiscal_year", "contract_date", "agency_name",
        "contract_name", "contract_amount", "bid_display",
        "agency_category", "source_url",
    ]].copy()
    view = view.sort_values("contract_amount", ascending=False, na_position="last")
    view["contract_amount"] = view["contract_amount"].map(
        lambda v: f"{int(v):,}" if pd.notna(v) else "-"
    )
    view = view.rename(columns={
        "fiscal_year": "年度", "contract_date": "契約日",
        "agency_name": "機関", "contract_name": "契約名",
        "contract_amount": "金額(円)", "bid_display": "入札方式",
        "agency_category": "カテゴリ", "source_url": "出典URL",
    })
    st.dataframe(view, use_container_width=True, hide_index=True, height=480)


def main():
    # ════════════════════════════════════════════════════════════════════
    # ヘッダー
    # ════════════════════════════════════════════════════════════════════
    st.title("🛡️ 防衛省・自衛隊 調達情報ダッシュボード")

    with st.spinner("データ読み込み中..."):
        df   = _load_contracts()
        budget = _load_budget()

    total_records  = len(df)

    # FY別集計
    fy_stats: dict[int, dict] = {}
    for fy in [2022, 2023, 2024, 2025]:
        cnt = int((df["fiscal_year"] == fy).sum())
        amt = float(df.loc[df["fiscal_year"] == fy, "amount_oku"].sum())
        base = _effective_base(fy)
        cov = amt / base * 100 if base else None
        fy_stats[fy] = {"count": cnt, "amount": amt, "base": base, "coverage": cov}

    fy24_count     = fy_stats[2024]["count"]
    fy24_amount    = fy_stats[2024]["amount"]
    fy24_cov_pct   = fy_stats[2024]["coverage"] or 0.0

    st.caption(
        f"出典: 防衛省・自衛隊 各機関 公開調達情報（財計第2017号）"
        f"　|　収録期間: FY2022〜FY2025　|　総収録: {total_records:,}件 /"
        f" {df['amount_oku'].sum():,.0f}億円"
        f"　|　最終更新: 2026-05-03"
    )



    # ── KPI ─────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("総収録件数",      f"{total_records:,} 件")
    k2.metric("総収録金額",      f"{df['amount_oku'].sum():,.0f} 億円")
    k3.metric("FY2024 収録額",   f"{fy24_amount:,.0f} 億円")
    k4.metric("FY2024 カバレッジ", f"{fy24_cov_pct:.1f}%",
              delta=f"{fy24_amount:,.0f} / {_EFFECTIVE_BASE:,}億",
              help="DB額 ÷ 実質契約対象母数（非契約系・不用額控除後）")
    k5.metric("収録機関数",      f"{df['agency_id'].nunique():,} 機関")

    st.divider()

    # ── チャート 2列 ─────────────────────────────────────────────────
    ch1, ch2 = st.columns([3, 2])

    with ch1:
        st.subheader("📈 年度別トレンド")
        by_fy = (
            df.groupby("fiscal_year", as_index=False)
            .agg(件数=("id", "count"), 総額_億円=("amount_oku", "sum"))
            .sort_values("fiscal_year")
        )
        fig_trend = go.Figure()
        fig_trend.add_bar(
            x=by_fy["fiscal_year"], y=by_fy["総額_億円"],
            name="総額(億円)", marker_color=ACCENT, yaxis="y",
            text=by_fy["総額_億円"].map(lambda v: f"{v:,.0f}"),
            textposition="outside",
        )
        fig_trend.add_scatter(
            x=by_fy["fiscal_year"], y=by_fy["件数"],
            name="件数", mode="lines+markers",
            line=dict(color=ACCENT_2, width=3), marker=dict(size=10), yaxis="y2",
        )
        fig_trend.update_layout(
            template=PLOT_TEMPLATE, height=360,
            xaxis=dict(title="年度", dtick=1),
            yaxis=dict(title="総額(億円)"),
            yaxis2=dict(title="件数", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig_trend, use_container_width=True)
        st.caption("※FY2025 は3月分が未公開につき未収録（暫定値）。")

    with ch2:
        st.subheader("🏛️ 組織別（全FY）")
        sun_df = (
            df.assign(
                調達区分=df["agency_id"].map(
                    lambda x: "中央契約" if x == "atla" else "地方契約"
                ),
                大区分=df["agency_category"].fillna("その他"),
                機関名=df["agency_name"].fillna("不明"),
            )
            .groupby(["調達区分", "大区分", "機関名"], as_index=False)
            .agg(総額_億円=("amount_oku", "sum"))
        )
        fig_cat = px.sunburst(
            sun_df,
            path=["調達区分", "大区分", "機関名"],
            values="総額_億円",
            template=PLOT_TEMPLATE,
            height=440,
            color_discrete_sequence=COLOR_SEQ,
        )
        fig_cat.update_traces(
            texttemplate="%{label}<br>%{percentParent:.0%}",
            hovertemplate="%{label}<br>%{value:,.0f}億円 (%{percentRoot:.1%})<extra></extra>",
            insidetextorientation="radial",
        )
        fig_cat.update_layout(margin=dict(l=0, r=0, t=20, b=0))
        sel_sun = st.plotly_chart(
            fig_cat, use_container_width=True,
            on_select="rerun", key="sunburst_org",
        )
        st.caption("セグメントをクリックするとその組織の契約一覧を表示します。")
        pts_sun = sel_sun.get("selection", {}).get("points", []) if sel_sun else []
        if pts_sun:
            pt = pts_sun[0]
            clicked_id = pt.get("id", "") or pt.get("label", "")
            parts = [p for p in clicked_id.split("/") if p] if clicked_id else []
            filt = df.assign(
                調達区分=df["agency_id"].map(
                    lambda x: "中央契約" if x == "atla" else "地方契約"
                ),
                大区分=df["agency_category"].fillna("その他"),
                機関名=df["agency_name"].fillna("不明"),
            )
            title_parts: list[str] = []
            if len(parts) >= 1:
                filt = filt[filt["調達区分"] == parts[0]]
                title_parts.append(parts[0])
            if len(parts) >= 2:
                filt = filt[filt["大区分"] == parts[1]]
                title_parts.append(parts[1])
            if len(parts) >= 3:
                filt = filt[filt["機関名"] == parts[2]]
                title_parts.append(parts[2])
            if not filt.empty:
                show_sunburst_drilldown(filt, " > ".join(title_parts))

    st.divider()

    # ── 受注企業 Top30（年度セレクタ + クリックでドリルダウン）─────
    ven_h1, ven_h2 = st.columns([3, 1])
    with ven_h1:
        st.subheader("🏭 受注企業 Top30")
    with ven_h2:
        fy_options = ["全年度", "FY2025", "FY2024", "FY2023", "FY2022"]
        sel_fy = st.selectbox(
            "年度", fy_options,
            index=fy_options.index("FY2024"),
            key="vendor_top30_fy",
            label_visibility="collapsed",
        )

    if sel_fy == "全年度":
        df_v = df.copy()
        scope_label = "全年度"
    else:
        target_fy = int(sel_fy.replace("FY", ""))
        df_v = df[df["fiscal_year"] == target_fy].copy()
        scope_label = sel_fy

    top_vendors = (
        df_v.dropna(subset=["vendor_norm"])
        .groupby("vendor_norm", as_index=False)
        .agg(件数=("id", "count"), 総額_億円=("amount_oku", "sum"))
        .sort_values("総額_億円", ascending=False)
        .head(30)
    )

    if top_vendors.empty:
        st.info(f"{scope_label} の受注企業データがありません。")
    else:
        tv_sorted = top_vendors.sort_values("総額_億円", ascending=True)
        fig_vendor = px.bar(
            tv_sorted,
            x="総額_億円", y="vendor_norm", orientation="h",
            text="総額_億円",
            color="総額_億円", color_continuous_scale="Blues",
            template=PLOT_TEMPLATE, height=720,
            labels={"vendor_norm": "企業", "総額_億円": "総額（億円）"},
            custom_data=["vendor_norm", "件数"],
            hover_data={"vendor_norm": False, "総額_億円": ":,.1f", "件数": ":,"},
        )
        fig_vendor.update_traces(texttemplate="%{text:,.1f}", textposition="outside")
        fig_vendor.update_layout(
            coloraxis_showscale=False,
            margin=dict(l=10, r=10, t=20, b=10),
            yaxis=dict(categoryorder="total ascending"),
        )
        sel = st.plotly_chart(
            fig_vendor, use_container_width=True,
            on_select="rerun", key=f"vendor_chart_{sel_fy}",
        )
        pts = sel.get("selection", {}).get("points", []) if sel else []
        if pts:
            vendor = pts[0].get("y") or (pts[0].get("customdata") or [None])[0]
            if vendor:
                sub = df_v[df_v["vendor_norm"] == vendor]
                show_vendor_drilldown(sub, f"受注企業: {vendor}（{scope_label}）")
        vendor_caption = "バー（または企業名）をクリックすると、その企業の契約一覧をモーダル表示します。"
        if sel_fy == "FY2025":
            vendor_caption += " ※FY2025 は3月分が未公開につき未収録。"
        st.caption(vendor_caption)

    st.divider()

    # ── 大型契約 Top30（金額順）────────────────────────────────────────
    big_h1, big_h2 = st.columns([3, 1])
    with big_h1:
        st.subheader("🏆 大型契約 Top30")
    with big_h2:
        big_fy_options = ["全年度", "FY2025", "FY2024", "FY2023", "FY2022"]
        sel_big_fy = st.selectbox(
            "年度", big_fy_options,
            index=big_fy_options.index("FY2024"),
            key="big_contracts_fy",
            label_visibility="collapsed",
        )

    if sel_big_fy == "全年度":
        df_big = df.copy()
    else:
        target_big_fy = int(sel_big_fy.replace("FY", ""))
        df_big = df[df["fiscal_year"] == target_big_fy].copy()

    big_top = (
        df_big.dropna(subset=["contract_amount"])
        .nlargest(30, "contract_amount")
        [["contract_name", "vendor_norm", "amount_oku",
          "agency_name", "fiscal_year", "contract_date"]]
        .rename(columns={
            "contract_name": "契約名",
            "vendor_norm":   "受注企業",
            "amount_oku":    "金額(億円)",
            "agency_name":   "機関",
            "fiscal_year":   "年度",
            "contract_date": "契約日",
        })
        .reset_index(drop=True)
    )

    if big_top.empty:
        st.info(f"{sel_big_fy} の大型契約データがありません。")
    else:
        big_top.insert(0, "順位", range(1, len(big_top) + 1))
        st.dataframe(
            big_top,
            use_container_width=True, hide_index=True, height=600,
            column_config={
                "順位":      st.column_config.NumberColumn(format="%d", width="small"),
                "金額(億円)": st.column_config.NumberColumn(format="%.1f"),
                "年度":      st.column_config.NumberColumn(format="FY%d", width="small"),
                "契約名":    st.column_config.TextColumn(width="large"),
                "受注企業":  st.column_config.TextColumn(width="medium"),
                "機関":      st.column_config.TextColumn(width="medium"),
                "契約日":    st.column_config.TextColumn(width="small"),
            },
        )
        big_caption = "契約金額（円）降順。NULL（単価契約等）は除外。"
        if sel_big_fy == "FY2025":
            big_caption += " ※FY2025 は3月分が未公開につき未収録。"
        st.caption(big_caption)

    st.divider()

    # ── FY横断カバレッジ比較 ──────────────────────────────────────────
    st.subheader("📊 FY別 収録状況・カバレッジ比較")

    fy_rows = []
    for fy in [2022, 2023, 2024, 2025]:
        s = fy_stats[fy]
        budget_val = _BUDGET.get(fy)
        base_val = s["base"]
        cov = s["coverage"]
        fy_rows.append({
            "年度": f"FY{fy}",
            "収録件数": s["count"],
            "収録額(億円)": round(s["amount"], 0),
            "予算(億円)": budget_val,
            "実質母数(億円)": base_val,
            "カバレッジ率": f"{cov:.1f}%" if cov is not None else "—",
        })
    fy_comp_df = pd.DataFrame(fy_rows)

    cov_c1, cov_c2 = st.columns([2, 3])
    with cov_c1:
        st.dataframe(
            fy_comp_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "収録件数":    st.column_config.NumberColumn(format="%d"),
                "収録額(億円)": st.column_config.NumberColumn(format="%.0f"),
                "予算(億円)":  st.column_config.NumberColumn(format="%d"),
                "実質母数(億円)": st.column_config.NumberColumn(format="%d"),
            },
        )
    with cov_c2:
        # 収録額 vs 実質母数の積み上げ棒グラフ
        cov_fig_df = pd.DataFrame({
            "年度": [f"FY{fy}" for fy in [2022, 2023, 2024, 2025]],
            "収録額": [fy_stats[fy]["amount"] for fy in [2022, 2023, 2024, 2025]],
            "未収録推定": [
                max(0, (s["base"] or 0) - fy_stats[fy]["amount"])
                for fy, s in [(fy, fy_stats[fy]) for fy in [2022, 2023, 2024, 2025]]
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
        # カバレッジ率ライン（第2軸）
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
        "出典: 防衛省予算概要各年度版。"
    )

    st.divider()

    # ── カバレッジ分析（FY選択対応）────────────────────────────────────────
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
    _sel_amount = fy_stats.get(sel_cov_fy, {}).get("amount", 0.0)
    _sel_count  = fy_stats.get(sel_cov_fy, {}).get("count", 0)
    _sel_cov    = fy_stats.get(sel_cov_fy, {}).get("coverage") or 0.0

    col_waterfall, col_gap = st.columns([3, 2])

    with col_waterfall:
        wf_labels   = ["物件費（契約ベース）", "△非契約系", "△不用額", "実質契約母数", "DB収録額"]
        wf_measures = ["absolute", "relative", "relative", "total", "absolute"]
        wf_values   = [_sel_budget, -_sel_nc, -_sel_fu, 0, _sel_amount]

        fig_wf = go.Figure(go.Waterfall(
            name="億円",
            orientation="v",
            measure=wf_measures,
            x=wf_labels,
            y=wf_values,
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
            ("△ 非契約系",          f"▲{_sel_nc:,}億", "#f38ba8"),
        ]
        if sel_cov_fy == 2024:
            cov_detail += [
                ("　光熱水料等（電力・水道）", "　~1,624億", TEXT_DIM),
                ("　基地対策等（HNS・交付金）","　~3,300億", TEXT_DIM),
                ("　借料（施設用地地代・漁業補償）", "　~1,345億", TEXT_DIM),
                ("　教育訓練費",               "　  ~390億", TEXT_DIM),
                ("　医療費等",                 "　  ~320億", TEXT_DIM),
                ("　補助金①装備移転等",        "　  ~400億", TEXT_DIM),
                ("　補助金②サイバー防衛",      "　   ~71億", TEXT_DIM),
                ("　補助金③GIGO",             "　   ~42億", TEXT_DIM),
            ]
        elif sel_cov_fy == 2023:
            cov_detail += [
                ("　HNS（在日米軍駐留経費）",      "　~2,000億", TEXT_DIM),
                ("　光熱水料等（営舎費中）",        "　~1,600億", TEXT_DIM),
                ("　基地借料・漁業補償",            "　~1,500億", TEXT_DIM),
                ("　補助金①装備移転（P.37）",      "　  ~400億", TEXT_DIM),
                ("　補助金②基地周辺対策等",        "　~1,100億", TEXT_DIM),
                ("　教育訓練費・医療費等",          "　  ~700億", TEXT_DIM),
            ]
        _fu_disp = f"▲{_sel_fu:,}億" if _sel_fu else "—（未公表）"
        cov_detail += [
            ("△ 不用額（未執行残）", _fu_disp, "#f38ba8"),
            ("＝ 実質契約対象母数", f"≈{_sel_base:,}億", "#89dceb"),
            (f"DB収録額（FY{sel_cov_fy}）", f"{_sel_amount:,.0f}億", "#a6e3a1"),
            ("カバレッジ率", f"{_sel_cov:.1f}%", "#a6e3a1"),
        ]
        for label, val, color in cov_detail:
            is_header = label.startswith("＝") or label.startswith("DB") or label.startswith("カバレッジ") or label.startswith("物件費")
            border_top = "border-top: 2px solid #45475a;" if is_header else ""
            st.markdown(
                f'<div style="display:flex; justify-content:space-between; '
                f'padding:2px 4px; {border_top}">'
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
        _nc_src = "行政事業レビューDB330事業突合 + 費目別vendor検証" if sel_cov_fy == 2024 else "FY2024実績から予算規模比例推定"
        st.markdown(f"""
- **物件費（契約ベース）{_sel_budget:,}億**: {_budget_src.get(sel_cov_fy, "")}
- **不用額{_sel_fu:,}億**: {_fu_src}
- **非契約系{_sel_nc:,}億**: {_nc_src}
- **DB収録額（FY{sel_cov_fy}）**: `data/db/procurement.db` より動的取得（{_sel_amount:,.0f}億 / {_sel_count:,}件）
- 詳細: `data/manual/coverage_budget_breakdown.md`
        """)

pg = st.navigation(
    {
        "": [
            st.Page(main, title="トップページ", icon="🏠", default=True),
            st.Page("pages/1_url_matrix.py", title="URLマトリクス", icon="📊"),
            st.Page("pages/4_search.py", title="検索", icon="🔎"),
        ],
        "その他（参考）": [
            st.Page("pages/3_jigyou_review.py", title="行政事業レビュー", icon="🔍"),
        ],
    }
)
pg.run()
