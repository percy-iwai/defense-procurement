"""中央調達実績 分析ページ — H11(1999)〜R06(2024) の約26年間の推移を可視化。

データソース: data/chuou_chotatsu.db（dev/extract_chuou_chotatsu.py で生成）
"""
from __future__ import annotations

import re
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

PROJECT_ROOT = DASHBOARD_DIR.parent
CHUOU_DB = PROJECT_ROOT / "data" / "chuou_chotatsu.db"

TEXT_COLOR = "#cdd6f4"
TEXT_DIM   = "#bac2de"

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

st.title("📈 中央調達実績分析")
st.caption(
    "防衛省中央調達（防衛装備庁経由）の年度別集計データ。"
    "H11(1999)〜R06(2024) の約26年間。"
)

if not CHUOU_DB.exists():
    st.error(
        f"chuou_chotatsu.db が見つかりません: {CHUOU_DB}\n\n"
        "以下を実行してDBを生成してください:\n"
        "```\npython dev/extract_chuou_chotatsu.py\n```"
    )
    st.stop()


# ── データ読み込み ─────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_summary() -> pd.DataFrame:
    with sqlite3.connect(str(CHUOU_DB)) as con:
        df = pd.read_sql_query(
            "SELECT * FROM chuou_chotatsu_summary ORDER BY fiscal_year", con
        )
    def _label(y: int) -> str:
        if y >= 2019:
            return f"R{y - 2018:02d}({y})"
        return f"H{y - 1988:02d}({y})"
    df["label"] = df["fiscal_year"].apply(_label)
    df["yoy_pct"] = df["total_100m"].pct_change() * 100
    return df


# ── 企業名正規化 ─────────────────────────────────────────────────

VENDOR_NORMALIZE: dict[str, str] = {
    "三菱重工": "三菱重工業",
    "石川島播磨重工業": "IHI",
    "JX日鉱日石エネルギー": "JXエネルギー",
    "JXTGエネルギー": "JXエネルギー",
    "コスモ石油マーケティング": "コスモ石油",
    "アイ・エイチ・アイ エアロスペース": "IHIエアロスペース",
    "アイ・エイチ・アイ マリンユナイテッド": "IHIマリンユナイテッド",
}

# 法人格表記の除去パターン（Unicode テキストに適用）
_LEGAL_SUFFIX_PATTERNS = [
    (r"^(?:公益)?財団法人\s*", ""),
    (r"\s*(?:公益)?財団法人$", ""),
    (r"\s*[（(]財[)）]\s*", ""),
    (r"^(?:公益|一般)?社団法人\s*", ""),
    (r"\s*[（(]社[)）]\s*", ""),
    (r"^株式会社\s*", ""),
    (r"\s*株式会社\s*", ""),
    (r"\s*[（(]株[)）]\s*", ""),
    (r"\s*㈱\s*", ""),
    (r"^有限会社\s*", ""),
    (r"\s*有限会社\s*", ""),
    (r"\s*[（(]有[)）]\s*", ""),
]


def _strip_legal_suffix(name: str) -> str:
    """全角スペース正規化 + 法人格表記除去。"""
    name = name.replace("　", " ")
    for pattern, repl in _LEGAL_SUFFIX_PATTERNS:
        name = re.sub(pattern, repl, name)
    return name.strip()


def _normalize_company(name: str) -> str:
    """企業名を年代横断で統合できる正規化名に変換する。

    1. \\n 以降を除去（法人番号・注釈を削除）
    2. 脚注行を除外
    3. CP932 mojibake decode を試みる（Latin-1 として格納されたバイト列を復元）
    4. decode 成功時（H11-H27 garbled PDF）: 法人格除去 → VENDOR_NORMALIZE 適用
    5. Latin-1 encode 不可（R03-R06 正常 UTF-8）: 直接法人格除去 → VENDOR_NORMALIZE 適用
    6. garbled で decode 不可: 文字間スペース除去のみ（日本語テキスト取り出し不可）
    """
    name = name.split("\n")[0].strip()
    name = re.sub(r"[（(]注\d+[)）]", "", name).strip()
    if name.startswith("計数は") or name.startswith("内局等") or not name:
        return ""

    decoded = None
    is_latin1 = True
    try:
        raw = name.encode("latin-1")
        try:
            decoded = raw.decode("cp932")
        except UnicodeDecodeError:
            pass
    except UnicodeEncodeError:
        is_latin1 = False  # 非 Latin-1 文字を含む → 正常 Unicode テキスト

    if decoded:
        # CP932 decode 成功（H11-H27 PDF の garbled 名）
        clean = _strip_legal_suffix(decoded)
        return VENDOR_NORMALIZE.get(clean, clean)
    elif not is_latin1:
        # 正常 Unicode（R03-R06 など）→ 直接法人格除去
        clean = _strip_legal_suffix(name)
        return VENDOR_NORMALIZE.get(clean, clean)
    else:
        # Latin-1 エンコード可能だが CP932 decode 失敗 → garbled のまま空白正規化のみ
        name = re.sub(r"(?<=[^\x00-\x7f]) (?=[^\x00-\x7f(（])", "", name)
        name = re.sub(r"(?<=[^\x00-\x7f]) (?=[)）])", "", name)
        name = re.sub(r"(?<=\b[A-Z]) (?=[A-Z])", "", name)
        name = re.sub(r"(?<=[A-Za-z0-9]) (?=[^\x00-\x7f])", "", name)
        name = re.sub(r"(?<=[^\x00-\x7f]) (?=[A-Za-z0-9])", "", name)
        return name.strip()


@st.cache_data(ttl=600)
def load_companies() -> pd.DataFrame:
    with sqlite3.connect(str(CHUOU_DB)) as con:
        df = pd.read_sql_query(
            "SELECT * FROM chuou_chotatsu_companies ORDER BY fiscal_year, rank", con
        )
    df["company_name_clean"] = df["company_name"].apply(_normalize_company)
    df = df[df["company_name_clean"] != ""].copy()
    df = (
        df.groupby(["fiscal_year", "company_name_clean"], as_index=False)
        .agg({
            "rank": "min",
            "amount_100m": "sum",
            "contracts_cnt": "sum",
            "share_pct": "sum",
            "source_file": "first",
            "company_name": "first",
        })
    )
    return df


df_sum = load_summary()
df_co  = load_companies()

# ── タブ ───────────────────────────────────────────────────────────
tab_trend, tab_top, tab_drill, tab_insight = st.tabs([
    "全体推移", "TOP企業推移", "企業ドリルダウン", "考察",
])


# ══════════════════════════════════════════════════════════════════
# Tab 1: 全体調達額推移
# ══════════════════════════════════════════════════════════════════
with tab_trend:
    st.subheader("中央調達額の推移（H11〜R06）")

    JISSEKI_TYPES = {"jisseki", "seed", "seed_corrected", "estimate"}
    df_plot = df_sum[df_sum["data_type"].isin(JISSEKI_TYPES)].sort_values("fiscal_year")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_plot["label"],
        y=df_plot["total_100m"],
        mode="lines+markers",
        name="中央調達額",
        line=dict(color="#89b4fa", width=2),
        marker=dict(size=7, color="#89b4fa"),
        hovertemplate="%{x}<br>%{y:,.0f}億円<extra></extra>",
    ))

    fig.add_shape(
        type="line", x0="R05(2023)", x1="R05(2023)", y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(width=2, dash="dash", color="#f38ba8"),
    )
    fig.add_annotation(
        x="R05(2023)", y=1, yref="paper",
        text="防衛費倍増加速（R05）",
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(color="#f38ba8"),
    )

    fig.update_layout(
        template="plotly_dark",
        height=480,
        xaxis=dict(title="年度", tickangle=-45, tickfont=dict(size=10)),
        yaxis=dict(title="調達額（億円）", tickformat=",.0f"),
        margin=dict(l=60, r=20, t=50, b=80),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # メトリクス
    c1, c2, c3, c4 = st.columns(4)
    r06 = df_sum[df_sum["fiscal_year"] == 2024]
    r05 = df_sum[df_sum["fiscal_year"] == 2023]
    r04 = df_sum[df_sum["fiscal_year"] == 2022]
    h17 = df_sum[df_sum["fiscal_year"] == 2005]
    if not r06.empty:
        c1.metric("R06(2024) 調達総額", f"{r06.iloc[0]['total_100m']:,.0f}億円")
    if not r05.empty:
        c2.metric("R05(2023) 調達総額", f"{r05.iloc[0]['total_100m']:,.0f}億円")
    if not r04.empty and not r05.empty:
        ratio = r05.iloc[0]['total_100m'] / r04.iloc[0]['total_100m']
        c3.metric("R04→R05 変化率", f"{ratio:.1f}倍")
    if not h17.empty and not r04.empty:
        c4.metric("H17→R04 安定期（約15年）", f"{r04.iloc[0]['total_100m']:,.0f}億円")

    st.caption(
        "全年度（H11〜R06）を実績・確定・推計値として表示。"
        "H11(1999) は Wayback Machine HTML からの推計補完値。"
        "H18(2006) は公文書確定値（seed）。"
        "R03/R04 は概況 PDF から抽出（seed）。"
    )


# ══════════════════════════════════════════════════════════════════
# Tab 2: TOP企業推移
# ══════════════════════════════════════════════════════════════════
with tab_top:
    st.subheader("上位企業 調達額推移")

    if df_co.empty:
        st.info("企業データがありません。")
    else:
        co_year_counts = (
            df_co.groupby("company_name_clean")["fiscal_year"]
            .nunique().sort_values(ascending=False)
        )
        top_companies = co_year_counts.head(30).index.tolist()

        selected = st.multiselect(
            "企業を選択（複数可）",
            options=top_companies,
            default=top_companies[:min(8, len(top_companies))],
        )

        if selected:
            fig3 = go.Figure()
            for co in selected:
                sub = df_co[df_co["company_name_clean"] == co].sort_values("fiscal_year").copy()
                if sub.empty:
                    continue
                sub["label"] = sub["fiscal_year"].apply(
                    lambda y: f"R{y-2018:02d}({y})" if y >= 2019 else f"H{y-1988:02d}({y})"
                )
                fig3.add_trace(go.Scatter(
                    x=sub["label"], y=sub["amount_100m"],
                    mode="lines+markers",
                    name=co,
                    hovertemplate=f"{co}: %{{y:,.0f}}億円<extra></extra>",
                ))
            fig3.update_layout(
                template="plotly_dark",
                height=700,
                xaxis=dict(title="年度", tickangle=-45),
                yaxis=dict(title="調達額（億円）", tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=20, t=50, b=80),
            )
            st.plotly_chart(fig3, use_container_width=True)

        st.caption(
            f"企業データ保有年度数: {df_co['fiscal_year'].nunique()}年度、"
            f"延べ{len(df_co)}社件数。"
            "企業名は年代横断で正規化済み（CP932 mojibake 復元・表記揺れ吸収）。"
        )


# ══════════════════════════════════════════════════════════════════
# Tab 3: 企業ドリルダウン
# ══════════════════════════════════════════════════════════════════
with tab_drill:
    st.subheader("企業別 調達実績ドリルダウン")

    if df_co.empty:
        st.info("企業データがありません。")
    else:
        co_list = (
            df_co.groupby("company_name_clean")["fiscal_year"]
            .nunique()
            .sort_values(ascending=False)
            .index.tolist()
        )
        sel_co = st.selectbox("企業を選択", options=co_list)

        if sel_co:
            sub = df_co[df_co["company_name_clean"] == sel_co].sort_values("fiscal_year").copy()
            sub["label"] = sub["fiscal_year"].apply(
                lambda y: f"R{y-2018:02d}({y})" if y >= 2019 else f"H{y-1988:02d}({y})"
            )

            c1, c2 = st.columns(2)

            with c1:
                fig_rank = go.Figure(go.Scatter(
                    x=sub["label"], y=sub["rank"],
                    mode="lines+markers",
                    marker=dict(size=8, color="#89b4fa"),
                    line=dict(color="#89b4fa"),
                    hovertemplate="順位: %{y}位<extra></extra>",
                ))
                fig_rank.update_layout(
                    template="plotly_dark",
                    title="順位推移",
                    yaxis=dict(autorange="reversed", title="順位"),
                    xaxis=dict(tickangle=-45),
                    height=300,
                    margin=dict(l=50, r=10, t=40, b=60),
                )
                st.plotly_chart(fig_rank, use_container_width=True)

            with c2:
                fig_amt = go.Figure(go.Bar(
                    x=sub["label"], y=sub["amount_100m"],
                    marker_color="#a6e3a1",
                    hovertemplate="金額: %{y:,.0f}億円<extra></extra>",
                ))
                fig_amt.update_layout(
                    template="plotly_dark",
                    title="調達額推移",
                    yaxis=dict(title="億円", tickformat=",.0f"),
                    xaxis=dict(tickangle=-45),
                    height=300,
                    margin=dict(l=50, r=10, t=40, b=60),
                )
                st.plotly_chart(fig_amt, use_container_width=True)

            st.dataframe(
                sub[["label", "rank", "contracts_cnt", "amount_100m", "share_pct",
                      "company_name_clean", "source_file"]]
                .rename(columns={
                    "label": "年度", "rank": "順位",
                    "contracts_cnt": "件数", "amount_100m": "金額（億円）",
                    "share_pct": "構成比(%)", "company_name_clean": "正規化企業名",
                    "source_file": "データソース",
                }),
                use_container_width=True,
                hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════
# Tab 4: 考察
# ══════════════════════════════════════════════════════════════════
with tab_insight:
    st.subheader("防衛費急増と中央調達の相関")

    fig_ins = go.Figure()
    jisseki_types = {"jisseki", "seed", "seed_corrected", "estimate"}
    df_j = df_sum[df_sum["data_type"].isin(jisseki_types)].sort_values("fiscal_year")

    if not df_j.empty:
        fig_ins.add_trace(go.Scatter(
            x=df_j["label"], y=df_j["total_100m"],
            mode="lines+markers", name="実績・確定値",
            line=dict(color="#89b4fa", width=2),
            marker=dict(size=7),
            hovertemplate="%{x}: %{y:,.0f}億円<extra></extra>",
        ))
    fig_ins.add_shape(
        type="line", x0="R05(2023)", x1="R05(2023)", y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(width=2, dash="dash", color="#f38ba8"),
    )
    fig_ins.add_annotation(
        x="R05(2023)", y=1, yref="paper",
        text="R05: 3.3倍急増",
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(color="#f38ba8"),
    )
    fig_ins.update_layout(
        template="plotly_dark", height=380,
        xaxis=dict(title="年度", tickangle=-45, tickfont=dict(size=9)),
        yaxis=dict(title="中央調達額（億円）", tickformat=",.0f"),
        margin=dict(l=60, r=20, t=30, b=80),
    )
    st.plotly_chart(fig_ins, use_container_width=True)

    st.markdown("""
### 時代区分別 考察

**① 安定期（H11〜R04: 1999〜2022）**

約15年間、中央調達額は概ね **1.1〜1.8兆円/年** の範囲で推移。
防衛費全体（約5兆円/年）に対して中央調達が占める割合は20〜30%程度。
随意契約が金額ベースで80%超を占め、三菱重工・三菱電機・川崎重工・日本電気などの
大手重工・電機メーカーが固定的に上位を占めてきた。

**② 防衛力強化加速期（R05〜R06: 2023〜2024）**

2022年12月、政府は「防衛力整備計画（5年間・総額43兆円）」を閣議決定。
R05(2023)の中央調達額は **5.6兆円** と前年比 **+3.3倍** の急増。
R06(2024)も5.8兆円台を維持し、防衛費増強が契約実績として顕在化した。

---

### 主要企業のポジション（R06実績）

| 順位 | 企業 | 金額 | 構成比 |
|------|------|-----:|------:|
| 1 | 三菱重工業 | 14,567億円 | 25.1% |
| 2 | 川崎重工業 | 6,383億円 | 11.0% |
| 3 | 三菱電機 | 4,956億円 | 8.6% |
| 4 | 日本電気 | 3,117億円 | 5.4% |

上位4社で中央調達の約50%を占有。護衛艦・航空機・誘導弾などの
大型装備品は **随意契約（相手方限定）** が前提のため、
既存プレイヤーの寡占構造が維持されやすい。

---

### 防衛産業参入を検討する企業向け 市場分析

**市場規模と成長性**
- 中央調達（装備庁経由）: 5.8兆円/年（R06）
- 地方調達（各機関直接）: 2〜3兆円/年（推定）
- 合計: **約8〜9兆円/年** の市場（防衛力整備計画の5年間43兆円ペース）

**参入障壁**
1. **技術認定要件**: 武器等製造法/火薬類取締法に基づく工場認可（2〜5年）
2. **随意契約の壁**: 既存メーカーとの長期関係性、仕様書へのロックイン
3. **維持整備義務**: 装備品の製品ライフサイクル30年以上（航空機・艦船）

**参入機会（新興企業にも開かれた領域）**

| 分野 | 規模感 | 参入難易度 |
|------|--------|-----------|
| IT・サイバー（P42） | 年1,000〜2,000億 | ★★☆（資格取得が主要ハードル）|
| 無人アセット・ドローン（P3） | 急増中 | ★★☆（新設規格、先行者利益あり）|
| 維持整備・MRO（P72） | 年2兆円超 | ★★★（長期契約、技術蓄積必要）|
| 弾薬・補給品（P71） | 急増中 | ★★★（火薬法・輸出規制）|
| 宇宙・衛星（P41） | 年2,000〜3,000億 | ★★☆（商業宇宙との連携余地あり）|

*(P番号は防衛力整備計画の7本柱分類)*
""")

    st.info(
        "📌 このページのデータは `data/chuou_chotatsu.db` から読み込んでいます。"
        "更新するには `python dev/extract_chuou_chotatsu.py` を再実行してください。"
    )
