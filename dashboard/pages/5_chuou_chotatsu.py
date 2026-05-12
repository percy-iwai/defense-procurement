"""中央調達実績 分析ページ — H11(1999)〜R06(2024) の約26年間の推移を可視化。

データソース: data/chuou_chotatsu.db（dev/extract_chuou_chotatsu.py で生成）
"""
from __future__ import annotations

import re
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
    /* データ充足状況マトリクス */
    .status-matrix {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
    .status-matrix th, .status-matrix td {{ border: 1px solid #45475a; padding: 4px 8px; text-align: center; white-space: nowrap; }}
    .status-matrix th {{ background: #313244; color: {TEXT_COLOR}; font-weight: 600; }}
    .status-matrix td.sc-year {{ background: #1e1e2e; color: {TEXT_DIM}; text-align: left; font-size: 0.78rem; }}
    .status-matrix td.sc-ok {{ background: #1e3a2f; color: #a6e3a1; font-weight: 700; }}
    .status-matrix td.sc-partial {{ background: #3a341e; color: #f9e2af; font-weight: 700; }}
    .status-matrix td.sc-none {{ background: #2a1f2a; color: #585b70; }}
    .status-legend {{ display: flex; gap: 1.5rem; margin: 0.6rem 0 1rem; font-size: 0.82rem; }}
    .status-legend span {{ padding: 2px 10px; border-radius: 4px; font-weight: 600; }}
    .leg-ok      {{ background: #1e3a2f; color: #a6e3a1; }}
    .leg-partial {{ background: #3a341e; color: #f9e2af; }}
    .leg-none    {{ background: #2a1f2a; color: #585b70; }}
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
    # IHI グループ（石川島播磨重工業の後継・カタカナ読み統合）
    "石川島播磨重工業": "IHI",
    "アイ・エイチ・アイ": "IHI",
    "アイ・エイチ・アイ・エアロスペース": "IHIエアロスペース",
    "アイ・エイチ・アイ・マリンユナイテッド": "IHIマリンユナイテッド",
    "アイ・エイチ・アイマリンユナイテッド": "IHIマリンユナイテッド",
    # 三菱グループ
    "三菱重工": "三菱重工業",
    "三菱重工機械システム": "三菱重工業",
    # エネルギー会社（歴代名称 → ENEOS に統合）
    "新日本石油": "ENEOS",
    "JX日鉱日石エネルギー": "ENEOS",
    "JXエネルギー": "ENEOS",
    "JXTGエネルギー": "ENEOS",
    # 造船（三井造船+ユニバーサル造船 → 2013年 JMU に合併）
    "三井造船": "ジャパンマリンユナイテッド",
    "ユニバーサル造船": "ジャパンマリンユナイテッド",
    "マリンユナイテッド": "ジャパンマリンユナイテッド",
    # 富士重工業 → SUBARU（2017年改称）
    "富士重工業": "SUBARU",
    # コスモ石油（販売子会社統合）
    "コスモ石油マーケティング": "コスモ石油",
    # 東芝インフラ（東芝の分社→2018年 東芝インフラシステムズ設立）
    "東芝インフラシステムズ": "東芝",
    "東芝インフラ": "東芝",
    # GEアビエーション（Distribution は日本販社）
    "GEアビエーション・ディストリビューション・ジャパン": "GEアビエーション",
    # 昭和シェル → ENEOSグループに統合（2019年）
    "昭和シェル石油": "ENEOS",
}

# VENDOR_NORMALIZE の逆引き辞書（正規化名 → 統合前旧名称リスト）
_REVERSE_NORMALIZE: dict[str, list[str]] = {}
for _old_name, _canonical in VENDOR_NORMALIZE.items():
    _REVERSE_NORMALIZE.setdefault(_canonical, []).append(_old_name)

# 法人格表記の除去パターン（Unicode テキストに適用）
_LEGAL_SUFFIX_PATTERNS = [
    # 公的法人（前置のみ）
    (r"^国立研究開発法人\s*", ""),
    (r"^独立行政法人\s*", ""),
    # 財団法人系
    (r"^(?:公益|一般)?財団法人\s*", ""),
    (r"\s*(?:公益|一般)?財団法人$", ""),
    (r"\s*[（(]財[)）]\s*", ""),
    # 社団法人系
    (r"^(?:公益|一般)?社団法人\s*", ""),
    (r"\s*[（(]社[)）]\s*", ""),
    # 株式会社（前置・後置・略称）
    (r"^株式会社\s*", ""),
    (r"\s*株式会社\s*", ""),
    (r"\s*[（(]株[)）]\s*", ""),
    (r"\s*㈱\s*", ""),
    # 有限会社
    (r"^有限会社\s*", ""),
    (r"\s*有限会社\s*", ""),
    (r"\s*[（(]有[)）]\s*", ""),
]

# 脚注・ノイズ行の先頭文字列
_NOISE_PREFIXES = ("計数は", "金額は", "内局等", "プロは", "(企業")


def _strip_legal_suffix(name: str) -> str:
    """文字間スペース正規化（先に実行） + 法人格除去。

    ★スペース除去を suffix パターンより先に行う理由:
    「株 式 会 社 IHI」のようにスペース入りの法人格表記は、
    先にスペースを除去して「株式会社IHI」にしてから suffix パターンを当てる必要がある。
    """
    name = name.replace("　", " ")
    # STEP 1: 文字間スペース除去（suffix 除去より先に実行）
    # 全角文字間スペース（「三 菱 重 工 業」→「三菱重工業」、「株 式 会 社」→「株式会社」）
    name = re.sub(r"(?<=[^\x00-\x7f]) (?=[^\x00-\x7f])", "", name)
    # ASCII大文字間スペース（「I H I」→「IHI」、「S U B A R U」→「SUBARU」）
    name = re.sub(r"(?<=[A-Z]) (?=[A-Z])", "", name)
    # ASCII↔全角間スペース（「J X エネルギー」→「JXエネルギー」）
    name = re.sub(r"(?<=[A-Za-z0-9]) (?=[^\x00-\x7f])", "", name)
    name = re.sub(r"(?<=[^\x00-\x7f]) (?=[A-Za-z0-9])", "", name)
    # STEP 2: 法人格表記除去（スペース正規化後なので正しくマッチする）
    for pattern, repl in _LEGAL_SUFFIX_PATTERNS:
        name = re.sub(pattern, repl, name)
    return name.strip()


def _normalize_company(name: str) -> str:
    """企業名を年代横断で統合できる正規化名に変換する。

    1. \\n 以降を除去（法人番号・注釈を削除）
    2. NFKC 正規化（全角英数・記号を半角に統一）
    3. 脚注・ノイズ行を除外
    4. CP932 mojibake decode を試みる（Latin-1 として格納されたバイト列を復元）
    5. decode 成功時（H11-H27 garbled PDF）: NFKC再適用 + 法人格除去 → VENDOR_NORMALIZE
    6. Latin-1 encode 不可（R03-R06 正常 UTF-8）: 直接法人格除去 → VENDOR_NORMALIZE
    7. garbled で decode 不可: 文字間スペース除去のみ
    """
    # 法人番号行・注釈行を除去してから改行を連結（複数行カタカナ企業名を接続）
    name = re.sub(r"\n?\(法人番号[^)]*\)", "", name)
    name = re.sub(r"\n?（法人番号[^）]*）", "", name)
    name = name.replace("\n", "").strip()
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[（(]注\d+[)）]", "", name).strip()
    if not name:
        return ""
    for prefix in _NOISE_PREFIXES:
        if name.startswith(prefix):
            return ""
    if re.match(r"^\d+年度$", name):  # 「14年度」などのラベル行
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
        decoded = unicodedata.normalize("NFKC", decoded)
        clean = _strip_legal_suffix(decoded)
        return VENDOR_NORMALIZE.get(clean, clean)
    elif not is_latin1:
        # 正常 Unicode（R03-R06 など）→ 直接法人格除去
        clean = _strip_legal_suffix(name)
        return VENDOR_NORMALIZE.get(clean, clean)
    else:
        # garbled のまま（Latin-1だがCP932 decode失敗）→ 空白正規化のみ
        name = re.sub(r"(?<=[^\x00-\x7f]) (?=[^\x00-\x7f(（])", "", name)
        name = re.sub(r"(?<=[^\x00-\x7f]) (?=[)）])", "", name)
        name = re.sub(r"(?<=\b[A-Z]) (?=[A-Z])", "", name)
        name = re.sub(r"(?<=[A-Za-z0-9]) (?=[^\x00-\x7f])", "", name)
        name = re.sub(r"(?<=[^\x00-\x7f]) (?=[A-Za-z0-9])", "", name)
        return name.strip()


def _get_decoded_name(name: str) -> str:
    """CP932 decode + 法人格除去のみ。VENDOR_NORMALIZE は適用しない。
    [旧名] 表示用（正規化名と旧社名が異なる場合のみ使用）。"""
    name = re.sub(r"\n?\(法人番号[^)]*\)", "", name)
    name = re.sub(r"\n?（法人番号[^）]*）", "", name)
    name = name.replace("\n", "").strip()
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[（(]注\d+[)）]", "", name).strip()
    if not name:
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
        is_latin1 = False
    if decoded:
        return _strip_legal_suffix(unicodedata.normalize("NFKC", decoded))
    elif not is_latin1:
        return _strip_legal_suffix(name)
    else:
        return ""  # garbled—cannot recover original name


@st.cache_data(ttl=600)
def load_companies() -> pd.DataFrame:
    with sqlite3.connect(str(CHUOU_DB)) as con:
        df = pd.read_sql_query(
            "SELECT * FROM chuou_chotatsu_companies ORDER BY fiscal_year, rank", con
        )
    df["company_name_clean"] = df["company_name"].apply(_normalize_company)
    df["company_name_orig"] = df["company_name"].apply(_get_decoded_name)
    df = df[df["company_name_clean"] != ""].copy()
    df = (
        df.groupby(["fiscal_year", "company_name_clean"], as_index=False)
        .agg({
            "rank": "min",
            "amount_100m": lambda x: x.sum(min_count=1),
            "contracts_cnt": lambda x: x.sum(min_count=1),
            "share_pct": lambda x: x.sum(min_count=1),
            "source_file": "first",
            "company_name": "first",
            "company_name_orig": "first",
        })
    )
    return df


@st.cache_data(ttl=600)
def load_company_items() -> pd.DataFrame:
    """chuou_chotatsu_company_items テーブルから全データを読み込む。"""
    with sqlite3.connect(str(CHUOU_DB)) as con:
        try:
            return pd.read_sql_query(
                """SELECT fiscal_year, company_rank, company_name, item_name, item_order
                   FROM chuou_chotatsu_company_items
                   ORDER BY fiscal_year, company_rank, item_order""",
                con,
            )
        except Exception:
            return pd.DataFrame()


@st.cache_data(ttl=600)
def load_main_items() -> pd.DataFrame:
    """chuou_chotatsu_main_items テーブルから全データを読み込む。"""
    with sqlite3.connect(str(CHUOU_DB)) as con:
        try:
            return pd.read_sql_query(
                """SELECT fiscal_year, item_name, amount_100m, requesting_org, source_file
                   FROM chuou_chotatsu_main_items
                   ORDER BY fiscal_year, amount_100m DESC""",
                con,
            )
        except Exception:
            return pd.DataFrame()


@st.cache_data(ttl=600)
def load_data_status() -> pd.DataFrame:
    """各年度×5項目のデータ充足状況を返す。
    ○=DB格納済み（SQLで自動判定）、△=元データあり未取込（コード内定数）、×=元データなし。
    """
    with sqlite3.connect(str(CHUOU_DB)) as con:
        base = pd.read_sql_query(
            "SELECT fiscal_year, army_100m, method_competition_cnt "
            "FROM chuou_chotatsu_summary ORDER BY fiscal_year",
            con,
        )
        ci = pd.read_sql_query(
            "SELECT fiscal_year, COUNT(*) AS cnt FROM chuou_chotatsu_company_items "
            "GROUP BY fiscal_year",
            con,
        )
        mi = pd.read_sql_query(
            "SELECT fiscal_year, COUNT(*) AS cnt FROM chuou_chotatsu_main_items "
            "GROUP BY fiscal_year",
            con,
        )
        co = pd.read_sql_query(
            "SELECT fiscal_year, COUNT(*) AS cnt FROM chuou_chotatsu_companies "
            "GROUP BY fiscal_year",
            con,
        )

    df = (
        base
        .merge(ci.rename(columns={"cnt": "ci_cnt"}), on="fiscal_year", how="left")
        .merge(mi.rename(columns={"cnt": "mi_cnt"}), on="fiscal_year", how="left")
        .merge(co.rename(columns={"cnt": "co_cnt"}), on="fiscal_year", how="left")
        .fillna(0)
    )

    # 元データはあるがDB未格納の年度（△判定用）
    # H19-R05(FY2007-2023): 各 jisseki PDF に「調達要求元別」あり（cp932 decode で確認）
    # H18(FY2006): 特殊フォーマット（23p政策文書）、機関別セクション検出不可 → ×
    _SRC_ARMY     = set(range(2007, 2024))
    # H18(FY2006): 「随意契約」記載あり; R02-R04 gaikyo(FY2020-2022): 同
    _SRC_METHOD   = {2006, 2020, 2021, 2022}
    _SRC_CO_ITEMS = set(range(1999, 2007))  # H11-H18 HTML/PDF に企業別品目あり
    _SRC_MAIN     = {1997, 1998} | set(range(1999, 2005))  # Wayback HTML に主要品目あり

    def _s1(r):  # ①機関別
        return "○" if pd.notna(r.army_100m) and r.army_100m else (
            "△" if r.fiscal_year in _SRC_ARMY else "×")

    def _s2(r):  # ②品目別（company_items で代替）
        return "○" if r.ci_cnt > 0 else (
            "△" if r.fiscal_year in _SRC_CO_ITEMS else "×")

    def _s3(r):  # ③契約方式別
        return "○" if pd.notna(r.method_competition_cnt) and r.method_competition_cnt else (
            "△" if r.fiscal_year in _SRC_METHOD else "×")

    def _s4(r):  # ④主要調達品目
        return "○" if r.mi_cnt > 0 else (
            "△" if r.fiscal_year in _SRC_MAIN else "×")

    def _s5(r):  # ⑤上位20社
        return "○" if r.co_cnt >= 20 else ("△" if r.co_cnt > 0 else "×")

    df["s1"] = df.apply(_s1, axis=1)
    df["s2"] = df.apply(_s2, axis=1)
    df["s3"] = df.apply(_s3, axis=1)
    df["s4"] = df.apply(_s4, axis=1)
    df["s5"] = df.apply(_s5, axis=1)
    return df


df_sum = load_summary()
df_co  = load_companies()

# ── タブ ───────────────────────────────────────────────────────────
tab_trend, tab_top, tab_drill, tab_insight, tab_status, tab_small = st.tabs([
    "全体推移", "TOP企業推移", "企業ドリルダウン", "考察", "データ充足状況", "小口案件分析",
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

        # x軸カテゴリを fiscal_year の数値順で固定（H16 等が右端に飛ぶ問題を防止）
        def _fy_label(y: int) -> str:
            return f"R{y-2018:02d}({y})" if y >= 2019 else f"H{y-1988:02d}({y})"
        all_labels = [_fy_label(y) for y in sorted(df_co["fiscal_year"].unique())]

        if selected:
            fig3 = go.Figure()
            for co in selected:
                sub = df_co[df_co["company_name_clean"] == co].sort_values("fiscal_year").copy()
                if sub.empty:
                    continue
                sub["label"] = sub["fiscal_year"].apply(_fy_label)
                fig3.add_trace(go.Scatter(
                    x=sub["label"], y=sub["amount_100m"],
                    mode="lines+markers",
                    name=co,
                    hovertemplate=f"{co}: %{{y:,.0f}}億円<extra></extra>",
                ))
            fig3.update_layout(
                template="plotly_dark",
                height=700,
                xaxis=dict(
                    title="年度", tickangle=-45,
                    categoryorder="array", categoryarray=all_labels,
                ),
                yaxis=dict(title="調達額（億円）", tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=20, t=50, b=80),
            )
            st.plotly_chart(fig3, use_container_width=True)

        # ── ランク×年度 マトリクス表（全データ） ─────────────────────────
        st.markdown("#### 順位別・年度別 調達企業一覧（金額: 億円）")
        all_fys = sorted(df_co["fiscal_year"].unique())

        # FY → 総調達額（シェア計算用）
        _total_by_fy: dict[int, float] = {
            int(r["fiscal_year"]): float(r["total_100m"])
            for _, r in df_sum.iterrows()
            if pd.notna(r["total_100m"]) and r["total_100m"] > 0
        }

        # (fiscal_year, rank) → (正規化名, 旧名, 金額, シェア) のルックアップ
        _lookup: dict[tuple, tuple] = {}
        for _, row in df_co.iterrows():
            _orig = row.get("company_name_orig", "")
            _lookup[(int(row["fiscal_year"]), int(row["rank"]))] = (
                row["company_name_clean"],
                _orig if pd.notna(_orig) else "",
                row["amount_100m"],
                row["share_pct"],
            )

        # HTML 生成
        _css = """
<style>
.rank-matrix-wrap { overflow: auto; max-height: 540px; border: 1px solid #45475a; border-radius: 6px; }
.rank-matrix { border-collapse: collapse; font-size: 11px; white-space: nowrap; }
.rank-matrix th, .rank-matrix td { border: 1px solid #313244; padding: 3px 7px; }
.rank-matrix thead th {
    background: #1e1e2e; color: #89b4fa; font-weight: 600;
    position: sticky; top: 0; z-index: 2;
}
.rank-matrix th.rank-hdr {
    background: #1e1e2e; color: #89b4fa;
    position: sticky; left: 0; top: 0; z-index: 3;
}
.rank-matrix td.rank-idx {
    background: #1e1e2e; color: #a6e3a1; font-weight: 600;
    position: sticky; left: 0; z-index: 1; text-align: center;
}
.rank-matrix tbody tr:nth-child(odd)  td { background: #181825; color: #cdd6f4; }
.rank-matrix tbody tr:nth-child(even) td { background: #11111b; color: #cdd6f4; }
.rank-matrix tbody tr:nth-child(odd)  td.rank-idx { background: #1e1e2e; }
.rank-matrix tbody tr:nth-child(even) td.rank-idx { background: #1e1e2e; }
.rank-matrix td.no-data { color: #45475a; text-align: left; }
.rank-matrix tbody tr:hover td { background: #313244 !important; }
</style>
"""
        _hdr_cells = ['<th class="rank-hdr">順位</th>']
        for _fy in all_fys:
            _hdr_cells.append(f'<th>{_fy_label(_fy)}</th>')

        _body_rows: list[str] = []
        for _rank in range(1, 21):
            _cells = [f'<td class="rank-idx">{_rank}</td>']
            for _fy in all_fys:
                if (_fy, _rank) in _lookup:
                    _cln, _orig, _amt, _share = _lookup[(_fy, _rank)]
                    _orig_tag = f"[{_orig}]" if (_orig and _orig != _cln) else ""
                    _nd = f"{_cln}{_orig_tag}"
                    if pd.notna(_amt) and _amt > 0:
                        if pd.notna(_share) and _share > 0:
                            _sh = f"{_share:.1f}%"
                        elif _fy in _total_by_fy and _total_by_fy[_fy] > 0:
                            _sh = f"{_amt / _total_by_fy[_fy] * 100:.1f}%"
                        else:
                            _sh = "?"
                        _cells.append(f'<td>{_nd}（{_amt:,.0f}億円、{_sh}）</td>')
                    else:
                        _cells.append(f'<td>{_nd}</td>')
                else:
                    _cells.append('<td class="no-data">情報ナシ※</td>')
            _body_rows.append(f'<tr>{"".join(_cells)}</tr>')

        _html = (
            _css
            + '<div class="rank-matrix-wrap">'
            + '<table class="rank-matrix">'
            + f'<thead><tr>{"".join(_hdr_cells)}</tr></thead>'
            + f'<tbody>{"".join(_body_rows)}</tbody>'
            + '</table></div>'
        )
        st.markdown(_html, unsafe_allow_html=True)

        st.caption(
            f"企業データ保有年度数: {df_co['fiscal_year'].nunique()}年度（H06〜R06）、"
            f"延べ{len(df_co)}社件数。"
            "セル表示形式: 正規化後企業名[旧社名]（金額億円、シェア%）。旧社名は改称・合併前の名称（例: IHI[石川島播磨重工業]）。"
            "H06〜H10（1994〜1998）は H11（1999）年度報告書掲載の「過去5カ年順位」から復元。"
            "金額・シェア情報はなく順位のみ（順位20位超の企業はデータなし）。"
            "※「情報ナシ」: 当該年度にその順位に該当する企業が H11 上位20社に含まれないため不明。"
        )

        # ── 主な調達品 ドリルダウン ────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🔍 主な調達品（中央調達実績PDF記載データ）")

        _df_items_all = load_company_items()
        _ITEM_FYS = sorted(_df_items_all["fiscal_year"].unique().tolist()) if not _df_items_all.empty else []

        _ITEM_ICON_MAP = {
            ("護衛艦", "潜水艦", "補給艦", "掃海", "哨戒艦", "輸送艦"): "⚓",
            ("戦闘機", "哨戒機", "輸送機", "救難機", "練習機", "飛行機", "ヘリ", "回転翼", "UH-", "SH-", "P-1", "C-2", "F-", "T-", "US-2", "KC-"): "✈️",
            ("ミサイル", "誘導弾", "ロケット", "爆弾", "SDB", "弾薬"): "🚀",
            ("レーダー", "ソーナー", "通信", "システム", "ネットワーク", "電波", "警戒", "衛星", "C4I", "JADGE"): "📡",
            ("車両", "装甲", "戦車", "自走", "トラック", "軽装甲"): "🚛",
        }

        def _item_icon(name: str) -> str:
            for keywords, icon in _ITEM_ICON_MAP.items():
                if any(kw in name for kw in keywords):
                    return icon
            return "🛡️"

        _ITEM_CARD_CSS = """
<style>
.drill-header {
    display: flex; align-items: center; gap: 10px;
    background: #1e1e2e; border: 1px solid #45475a; border-radius: 8px;
    padding: 10px 14px; margin-bottom: 14px; font-size: 14px; color: #cdd6f4;
}
.drill-header .co-name { font-weight: 700; color: #89b4fa; font-size: 15px; }
.drill-header .co-rank { color: #a6e3a1; font-weight: 600; }
.drill-header .co-fy   { color: #b4befe; }
.item-cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px; margin-top: 4px;
}
.item-card {
    background: #24273a;
    border: 1px solid #45475a;
    border-left: 3px solid #89b4fa;
    border-radius: 10px;
    padding: 14px 14px 12px;
    display: flex; flex-direction: column; gap: 6px;
    transition: border-color 0.2s, background 0.2s;
}
.item-card:hover {
    background: #313244; border-left-color: #cba6f7;
}
.item-card-row { display: flex; align-items: center; gap: 8px; }
.item-card-icon { font-size: 22px; flex-shrink: 0; }
.item-card-num {
    color: #7f849c; font-size: 10px; font-weight: 700;
    letter-spacing: 0.08em; text-transform: uppercase;
}
.item-card-name {
    color: #cdd6f4; font-size: 12.5px; font-weight: 500;
    line-height: 1.45;
}
.no-items-note {
    color: #6c7086; font-size: 13px; padding: 16px 0;
    text-align: center; background: #181825;
    border-radius: 8px; border: 1px dashed #45475a;
}
</style>
"""
        st.markdown(_ITEM_CARD_CSS, unsafe_allow_html=True)

        if not _ITEM_FYS:
            st.markdown(
                '<div class="no-items-note">品目データが見つかりません</div>',
                unsafe_allow_html=True,
            )
        else:
            _col_fy2, _col_co2 = st.columns([1, 3])
            with _col_fy2:
                _sel_item_fy = st.selectbox(
                    "年度",
                    options=_ITEM_FYS[::-1],  # 新しい年度を先頭に
                    format_func=lambda y: f"R{y-2018:02d}（{y}年度）" if y >= 2019 else f"H{y-1988:02d}（{y}年度）",
                    key="item_fy_select",
                )
            _items_for_fy = _df_items_all[_df_items_all["fiscal_year"] == _sel_item_fy]
            _cos_for_fy = (
                _items_for_fy.sort_values("company_rank")[["company_rank", "company_name"]]
                .drop_duplicates("company_name")
            )
            with _col_co2:
                if _cos_for_fy.empty:
                    st.info("この年度の品目データがありません")
                    _sel_item_co = None
                else:
                    _co_opts = _cos_for_fy["company_name"].tolist()
                    _sel_item_co = st.selectbox(
                        "企業を選択",
                        options=_co_opts,
                        format_func=lambda n: f"{_cos_for_fy[_cos_for_fy['company_name']==n]['company_rank'].values[0]}位｜{n}",
                        key="item_co_select",
                    )

            if _sel_item_co:
                with st.spinner("品目データを読み込み中…"):
                    _items_rows = _items_for_fy[
                        _items_for_fy["company_name"] == _sel_item_co
                    ].sort_values("item_order")

                if _items_rows.empty:
                    st.markdown(
                        '<div class="no-items-note">この企業・年度の品目データがありません</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    _rank_val = int(_items_rows.iloc[0]["company_rank"])
                    _fy_lbl = f"R{_sel_item_fy-2018:02d}（{_sel_item_fy}年度）" if _sel_item_fy >= 2019 else f"H{_sel_item_fy-1988:02d}（{_sel_item_fy}年度）"
                    st.markdown(
                        f'<div class="drill-header">'
                        f'<span class="co-name">{_sel_item_co}</span>'
                        f'<span class="co-rank">第{_rank_val}位</span>'
                        f'<span class="co-fy">{_fy_lbl}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    _cards_html = '<div class="item-cards-grid">'
                    for _, _irow in _items_rows.iterrows():
                        _icon = _item_icon(str(_irow["item_name"]))
                        _order = int(_irow["item_order"])
                        _name  = str(_irow["item_name"])
                        _cards_html += (
                            f'<div class="item-card">'
                            f'<div class="item-card-row">'
                            f'<span class="item-card-icon">{_icon}</span>'
                            f'<span class="item-card-num">品目 {_order}</span>'
                            f'</div>'
                            f'<div class="item-card-name">{_name}</div>'
                            f'</div>'
                        )
                    _cards_html += '</div>'
                    st.markdown(_cards_html, unsafe_allow_html=True)

                    st.caption("出典: 防衛装備庁「中央調達実績」PDF（上位20社の主な調達品）")


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
            # 旧名称・統合前企業名の表示
            if sel_co in _REVERSE_NORMALIZE:
                aliases = " / ".join(_REVERSE_NORMALIZE[sel_co])
                st.caption(f"旧名称・統合前企業: **{aliases}**")

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


# ══════════════════════════════════════════════════════════════════
# Tab 5: データ充足状況マトリクス
# ══════════════════════════════════════════════════════════════════
with tab_status:
    st.subheader("データ充足状況マトリクス")
    st.caption(
        "各年度ごとに5カテゴリのデータ格納状況を示す。"
        "○=DB格納済み、△=元データにあるが未取込、×=元データ自体なし。"
    )

    st.markdown(
        '<div class="status-legend">'
        '<span class="leg-ok">○ DB格納済み</span>'
        '<span class="leg-partial">△ 元データあり・未取込</span>'
        '<span class="leg-none">× 元データなし</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    df_status = load_data_status()

    def _label_fy(y: int) -> str:
        if y >= 2019:
            return f"R{y-2018:02d}({y})"
        return f"H{y-1988:02d}({y})"

    def _cell(s: str) -> str:
        cls = {"○": "sc-ok", "△": "sc-partial", "×": "sc-none"}.get(s, "sc-none")
        return f'<td class="{cls}">{s}</td>'

    header_cols = [
        "年度",
        "①<br>機関別<br>(陸/海/空)",
        "②<br>品目別<br>(主な調達品)",
        "③<br>契約方式別<br>(競争/随意/FMS)",
        "④<br>主要<br>調達品目",
        "⑤<br>上位<br>20社",
    ]
    th_html = "".join(f"<th>{h}</th>" for h in header_cols)

    rows_html = ""
    for _, row in df_status.iterrows():
        fy = int(row["fiscal_year"])
        lbl = _label_fy(fy)
        rows_html += (
            f'<tr><td class="sc-year">{lbl}</td>'
            f'{_cell(row["s1"])}{_cell(row["s2"])}{_cell(row["s3"])}'
            f'{_cell(row["s4"])}{_cell(row["s5"])}</tr>'
        )

    st.markdown(
        f'<table class="status-matrix"><thead><tr>{th_html}</tr></thead>'
        f"<tbody>{rows_html}</tbody></table>",
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("""
**カテゴリの説明**

| # | 項目 | DBテーブル | 備考 |
|---|------|-----------|------|
| ① | 要求機関別（陸/海/空/他） | `summary.army_100m` 等 | FY2000-2005・FY2024は機関別金額あり |
| ② | 品目別（上位20社×主な調達品） | `chuou_chotatsu_company_items` | FY2007-2024は抽出済み |
| ③ | 契約方式別（競争/随意/FMS） | `summary.method_*` | R05/R06（FY2023-2024）のみ取込済み |
| ④ | 主要調達品目一覧 | `chuou_chotatsu_main_items` | FY2005・FY2007-2024は抽出済み |
| ⑤ | 上位20社（順位/件数/金額） | `chuou_chotatsu_companies` | FY1999-2024は全20社完備 |

△（元データあり・未取込）の主なケース:
- **①機関別 FY2021-2022**: 中央調達の概況PDFに記載あり、未抽出
- **③契約方式 FY2021-2022**: 同上
- **②品目別 FY1999-2006**: 旧防衛庁のWebページに「主な調達品」記載あり、未抽出
- **④主要品目 FY1997-2006**: HTML/PDFに主要調達品記載あり、部分的未抽出
""")

    # サマリーカウント表示
    total_fy = len(df_status)
    for col, label in [("s1","①機関別"), ("s2","②品目別"), ("s3","③契約方式"),
                       ("s4","④主要品目"), ("s5","⑤上位20社")]:
        counts = df_status[col].value_counts()
        ok  = counts.get("○", 0)
        tri = counts.get("△", 0)
        ng  = counts.get("×", 0)
        st.caption(f"{label}: ○{ok}年度 / △{tri}年度 / ×{ng}年度（全{total_fy}年度）")


# ══════════════════════════════════════════════════════════════════
# Tab 6: 小口案件分析
# ══════════════════════════════════════════════════════════════════
with tab_small:
    st.subheader("小口案件分析（主要調達品目・企業別契約単価）")

    st.info(
        "⚠️ **データの性質について**: 中央調達実績（上位20社）は大型装備品の集計データです。"
        "上位企業の最小調達額は約76億円/年、主要調達品目の大半は100億円超の大型案件です。"
        "このタブでは「相対的に小規模な案件」として、主要品目一覧（`main_items`）の"
        "金額帯別分布と、企業別の平均契約単価（`amount / contracts_cnt`）を分析します。"
        "金額=1.0億円のエントリは PDF 抽出上の番兵値（数値未解析）として除外しています。"
    )

    df_mi = load_main_items()

    # ── 金額帯別 主要品目分布グラフ ────────────────────────────────
    st.markdown("#### 主要調達品目の金額帯別分布（年度別）")

    if df_mi.empty:
        st.info("main_items データがありません。")
    else:
        # sentinel (amount=1.0) を除外
        df_mi_real = df_mi[df_mi["amount_100m"] > 1.0].copy()

        # 金額帯ラベルを付与
        _BANDS = [
            (2,    30,   "2〜30億円",    "#a6e3a1"),
            (31,   100,  "31〜100億円",  "#89b4fa"),
            (101,  500,  "101〜500億円", "#cba6f7"),
            (501,  99999,"501億円以上",  "#f38ba8"),
        ]

        def _band(v: float) -> str:
            for lo, hi, label, _ in _BANDS:
                if lo <= v <= hi:
                    return label
            return "不明"

        df_mi_real["金額帯"] = df_mi_real["amount_100m"].apply(_band)

        def _fy_lbl(y: int) -> str:
            return f"R{y-2018:02d}({y})" if y >= 2019 else f"H{y-1988:02d}({y})"

        df_mi_real["label"] = df_mi_real["fiscal_year"].apply(_fy_lbl)

        # 年度×帯 でカウント集計
        band_counts = (
            df_mi_real.groupby(["label", "fiscal_year", "金額帯"])
            .size().reset_index(name="件数")
        )
        band_counts = band_counts.sort_values("fiscal_year")
        all_labels_mi = [_fy_lbl(y) for y in sorted(df_mi_real["fiscal_year"].unique())]

        fig_band = go.Figure()
        for lo, hi, band_label, color in _BANDS:
            sub = band_counts[band_counts["金額帯"] == band_label]
            fig_band.add_trace(go.Bar(
                x=sub["label"], y=sub["件数"],
                name=band_label,
                marker_color=color,
                hovertemplate=f"{band_label}: %{{y}}件<extra></extra>",
            ))

        fig_band.update_layout(
            barmode="stack",
            template="plotly_dark",
            height=380,
            xaxis=dict(
                title="年度", tickangle=-45,
                categoryorder="array", categoryarray=all_labels_mi,
            ),
            yaxis=dict(title="品目件数"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=50, r=20, t=50, b=80),
        )
        st.plotly_chart(fig_band, use_container_width=True)

        st.caption(
            f"対象: {df_mi_real['fiscal_year'].nunique()}年度（"
            f"{sorted(df_mi_real['fiscal_year'].unique())[0]}〜"
            f"{sorted(df_mi_real['fiscal_year'].unique())[-1]}）の主要調達品目 {len(df_mi_real)}件。"
            "金額=1.0億円（PDF抽出番兵値）を除外。"
            "FY2015-2016・FY2019-2024 は main_items データなし（元PDFに品目別金額の記載がない年度）。"
        )

    # ── 小規模案件一覧表 ────────────────────────────────────────────
    st.markdown("#### 相対的小規模品目一覧（2〜50億円）")

    if not df_mi.empty:
        df_small_items = df_mi[(df_mi["amount_100m"] > 1.0) & (df_mi["amount_100m"] <= 50)].copy()
        df_small_items["label"] = df_small_items["fiscal_year"].apply(_fy_lbl)

        if df_small_items.empty:
            st.info("2〜50億円の品目はありません。")
        else:
            # 要求機関をcp932 decode で表示
            def _decode_org(s: str) -> str:
                if not isinstance(s, str) or not s:
                    return "—"
                try:
                    return s.encode("latin-1").decode("cp932")
                except Exception:
                    return s

            df_small_items["要求機関"] = df_small_items["requesting_org"].apply(_decode_org)

            st.dataframe(
                df_small_items[["label", "item_name", "amount_100m", "要求機関"]]
                .rename(columns={
                    "label": "年度",
                    "item_name": "品目名",
                    "amount_100m": "金額（億円）",
                })
                .sort_values(["年度", "金額（億円）"]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                f"全{len(df_small_items)}件。中央調達における「小規模」の目安として50億円以下を表示。"
                "品目名は PDF 抽出のためトランケートされている場合あり。"
            )

    # ── 企業別 契約単価分析 ────────────────────────────────────────
    st.markdown("#### 企業別 平均契約単価ランキング（小口契約集中度）")

    if df_co.empty:
        st.info("企業データがありません。")
    else:
        # 全年度分の contracts_cnt と amount を集計
        co_agg = (
            df_co[pd.notna(df_co["amount_100m"]) & (df_co["amount_100m"] > 0)
                  & pd.notna(df_co["contracts_cnt"]) & (df_co["contracts_cnt"] > 0)]
            .groupby("company_name_clean", as_index=False)
            .agg(
                total_amount=("amount_100m", "sum"),
                total_cnt=("contracts_cnt", "sum"),
                fy_count=("fiscal_year", "nunique"),
                avg_rank=("rank", "mean"),
            )
        )
        co_agg["平均単価（億円/件）"] = co_agg["total_amount"] / co_agg["total_cnt"]
        co_agg = co_agg.sort_values("平均単価（億円/件）")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**平均単価が低い企業（小口・多件数型）**")
            df_low = co_agg.head(15).copy()
            df_low["累積調達額（億円）"] = df_low["total_amount"].map("{:,.0f}".format)
            df_low["総件数"] = df_low["total_cnt"].map("{:.0f}".format)
            df_low["出現年度数"] = df_low["fy_count"]
            df_low["平均単価"] = df_low["平均単価（億円/件）"].map("{:.1f}億円/件".format)
            st.dataframe(
                df_low[["company_name_clean", "平均単価", "累積調達額（億円）", "総件数", "出現年度数"]]
                .rename(columns={"company_name_clean": "企業名"}),
                use_container_width=True,
                hide_index=True,
            )

        with col_b:
            st.markdown("**平均単価が高い企業（大口・少件数型）**")
            df_high = co_agg.tail(15).sort_values("平均単価（億円/件）", ascending=False).copy()
            df_high["累積調達額（億円）"] = df_high["total_amount"].map("{:,.0f}".format)
            df_high["総件数"] = df_high["total_cnt"].map("{:.0f}".format)
            df_high["出現年度数"] = df_high["fy_count"]
            df_high["平均単価"] = df_high["平均単価（億円/件）"].map("{:.1f}億円/件".format)
            st.dataframe(
                df_high[["company_name_clean", "平均単価", "累積調達額（億円）", "総件数", "出現年度数"]]
                .rename(columns={"company_name_clean": "企業名"}),
                use_container_width=True,
                hide_index=True,
            )

        # 単価分布 散布図（企業名×平均単価、バブル=累積調達額）
        fig_scatter = go.Figure()
        fig_scatter.add_trace(go.Scatter(
            x=co_agg["avg_rank"],
            y=co_agg["平均単価（億円/件）"],
            mode="markers+text",
            marker=dict(
                size=(co_agg["total_amount"] / co_agg["total_amount"].max() * 60 + 8).clip(8, 60),
                color=co_agg["平均単価（億円/件）"],
                colorscale="Turbo",
                showscale=True,
                colorbar=dict(title="単価（億/件）"),
                opacity=0.8,
            ),
            text=co_agg["company_name_clean"],
            textposition="top center",
            textfont=dict(size=9),
            hovertemplate=(
                "<b>%{text}</b><br>"
                "平均順位: %{x:.1f}位<br>"
                "平均単価: %{y:,.1f}億円/件<br>"
                "<extra></extra>"
            ),
        ))
        fig_scatter.update_layout(
            template="plotly_dark",
            height=500,
            xaxis=dict(title="平均順位（全年度）", autorange="reversed"),
            yaxis=dict(title="平均契約単価（億円/件）", tickformat=",.0f"),
            margin=dict(l=60, r=20, t=30, b=60),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
        st.caption(
            "バブルの大きさ = 累積調達総額。横軸 = 平均順位（左ほど上位）、縦軸 = 平均単価。"
            "平均単価が低い企業は件数が多く（修理・補給品等）、高い企業は1件あたりの装備品規模が大きい。"
        )

    # ── 考察 ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
### 考察: 大型調達機関における「小口案件」の意味

中央調達実績（防衛装備庁一括調達）は原則として **大型・複数年度の主要装備品調達** が対象であり、
数百億円〜数千億円規模の随意契約が大半を占める。このため「小口案件」は相対的な概念にとどまる。

**主要調達品目一覧の金額分布（FY2007-2018）**

PDFに金額記載がある年度（主に H19-H26・H29-H30）の主要品目 355件の中でも、
「2〜30億円」帯は約50件（14%）存在する。これらは単品・少量発注の試験機材、
小型センサー、訓練弾薬などが多い。一方で金額=1.0は全133件が番兵値（解析失敗）であり、
実態は数十〜数百億円の案件と推定される。

**企業別 平均契約単価の読み方**

- **単価の低い企業**（燃料・石油系）: ENEOS・コスモ石油・出光興産は1件あたり数十〜百億円台。
  件数が多く（30〜58件/累積）、毎年度の定期購入で構成比を稼いでいる。
- **単価の高い企業**（主要装備系）: ジャパンマリンユナイテッド・川崎重工業・三菱重工業は
  護衛艦・航空機・誘導弾など1件1,000億円超の大型案件を少数こなす構造。
- **中間的な企業**: 日本無線・住友重機械・富士通などは複数の修理・改造契約（百億円台）を
  コンスタントに受注するパターン。

**政策的含意**

随意契約率が金額ベースで80%超を占める中央調達では、
小口案件（競争入札で単価を下げやすい分野）の比率が低く、
防衛産業参入の機会は実績積み上げ型（試験・部品・燃料）に限られる。
R05(2023)以降の防衛費急増期においても、大型装備の追加発注は既存プレイヤーに集中する傾向が続いている。
""")

