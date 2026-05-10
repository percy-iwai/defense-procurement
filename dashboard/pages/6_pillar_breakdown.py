"""防衛力強化7本柱+共通基盤 ブレークダウン画面。

defense_pillar.db (新設) を ATTACH した接続経由で:
  - defense_pillar_master の階層表示
  - 大項目(L1)別の契約金額集計 (procurement.contracts と LIKE JOIN)
  - 中項目(L2)別の jigyou 件数 / sources 件数
  - ソース別件数内訳

重要: 契約金額集計は jigyou_name のサブストリング JOIN なので「概算」レベル。
精緻な紐付けには contract_id ベースのテーブルが今後必要。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# dashboard/ を sys.path に追加 (pages から _auth, _db を import するため)
DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from _auth import require_password  # noqa: E402
from _db import connect_with_pillar  # noqa: E402

require_password()

# ── スタイル ─────────────────────────────────────────────
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
    [data-testid="stDataFrame"] td {{ font-size: 0.85rem !important; }}
    [data-testid="stDataFrame"] th {{ font-size: 0.85rem !important; white-space: nowrap; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏛️ 防衛力強化7本柱+共通基盤 ブレークダウン")
st.caption(
    "defense_pillar.db を `ATTACH DATABASE ... AS pillar` した接続経由で集計。"
    " 契約金額は jigyou_name のサブストリング JOIN による概算。"
)


# ── 階層マスタ ────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_master() -> pd.DataFrame:
    with connect_with_pillar() as conn:
        return pd.read_sql(
            """
            SELECT
                m.pillar_id, m.level, m.name, m.parent_id, m.display_order, m.notes,
                (SELECT COUNT(*) FROM pillar.defense_pillar_jigyou
                 WHERE pillar_id = m.pillar_id) AS jigyou_count,
                (SELECT COUNT(*) FROM pillar.pillar_mapping_sources
                 WHERE pillar_id = m.pillar_id) AS sources_count
            FROM pillar.defense_pillar_master m
            ORDER BY m.display_order
            """,
            conn,
        )


# ── L1別 契約金額集計（procurement.contracts × pillar.defense_pillar_jigyou） ──
@st.cache_data(ttl=300)
def _load_l1_contract_agg(fy_filter: tuple[int, ...] | None = None) -> pd.DataFrame:
    """L1柱別の契約件数+金額（jigyou_name サブストリング JOIN）。

    各契約は最大1件の柱にのみカウント (DISTINCT contract_id) — 同一契約が複数柱に
    マッチした場合は pillar_id 最小のものに割り当てて二重カウントを防ぐ。
    """
    sql = """
        WITH matched AS (
            SELECT
                c.id AS contract_id,
                c.fiscal_year,
                c.contract_amount,
                MIN(parent_pid) AS pillar_id
            FROM contracts c
            JOIN (
                SELECT
                    j.jigyou_name,
                    -- L2 の場合は親L1 を取る; L1 の場合はそのまま
                    COALESCE(p.parent_id, j.pillar_id) AS parent_pid
                FROM pillar.defense_pillar_jigyou j
                LEFT JOIN pillar.defense_pillar_master p ON p.pillar_id = j.pillar_id
            ) jp ON c.contract_name LIKE '%' || jp.jigyou_name || '%'
        """
    if fy_filter:
        placeholders = ",".join("?" * len(fy_filter))
        sql += f" WHERE c.fiscal_year IN ({placeholders})"
    sql += """
            GROUP BY c.id
        )
        SELECT
            m.pillar_id,
            m.name AS pillar_name,
            COUNT(matched.contract_id) AS n_contracts,
            COALESCE(SUM(matched.contract_amount), 0) / 1e8 AS oku_yen
        FROM pillar.defense_pillar_master m
        LEFT JOIN matched ON matched.pillar_id = m.pillar_id
        WHERE m.level = 1
        GROUP BY m.pillar_id, m.name, m.display_order
        ORDER BY m.display_order
    """
    with connect_with_pillar() as conn:
        return pd.read_sql(sql, conn, params=fy_filter or [])


# ── ソース別件数 ─────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_source_breakdown() -> pd.DataFrame:
    with connect_with_pillar() as conn:
        return pd.read_sql(
            """
            SELECT
                source_type,
                COUNT(*) AS n,
                COUNT(DISTINCT jigyou_name_norm) AS unique_jigyou,
                MIN(fiscal_year) AS fy_min,
                MAX(fiscal_year) AS fy_max
            FROM pillar.pillar_mapping_sources
            GROUP BY source_type
            ORDER BY n DESC
            """,
            conn,
        )


# ── L2 ぶら下げ件数 ─────────────────────────────────────
@st.cache_data(ttl=300)
def _load_l2_for(parent_id: int) -> pd.DataFrame:
    with connect_with_pillar() as conn:
        return pd.read_sql(
            """
            SELECT
                m.pillar_id, m.name,
                (SELECT COUNT(*) FROM pillar.defense_pillar_jigyou
                 WHERE pillar_id = m.pillar_id) AS jigyou_count,
                (SELECT COUNT(*) FROM pillar.pillar_mapping_sources
                 WHERE pillar_id = m.pillar_id) AS sources_count
            FROM pillar.defense_pillar_master m
            WHERE m.parent_id = ?
            ORDER BY m.display_order
            """,
            conn,
            params=[parent_id],
        )


# ── サンプル jigyou (柱選択時) ───────────────────────────
@st.cache_data(ttl=300)
def _load_jigyou_samples(pillar_id: int, limit: int = 50) -> pd.DataFrame:
    with connect_with_pillar() as conn:
        return pd.read_sql(
            """
            SELECT j.fiscal_year, j.jigyou_name, j.source_file,
                   j.legacy_pillar_id, j.legacy_pillar_name
            FROM pillar.defense_pillar_jigyou j
            WHERE j.pillar_id = ?
            ORDER BY j.fiscal_year DESC, j.jigyou_name
            LIMIT ?
            """,
            conn,
            params=[pillar_id, limit],
        )


# ============================================================
#  描画
# ============================================================

# ── FY フィルタ ──
st.subheader("⚙️ 集計条件")
all_fys = [2022, 2023, 2024, 2025]
sel_fys = st.multiselect(
    "対象FY (契約金額集計のみに適用)", all_fys, default=all_fys, key="pb_fys"
)
fy_tuple = tuple(sel_fys) if sel_fys else None

# ── L1集計バーチャート ─────────────────────────────────
st.subheader("📊 大項目(L1)別 契約金額・件数")
l1 = _load_l1_contract_agg(fy_tuple)
if not l1.empty:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=l1["pillar_name"],
            y=l1["oku_yen"],
            text=[f"{v:,.0f}億" for v in l1["oku_yen"]],
            textposition="outside",
            marker_color="#89b4fa",
            name="契約金額(億円)",
        )
    )
    fig.update_layout(
        plot_bgcolor="#1e1e2e",
        paper_bgcolor="#1e1e2e",
        font=dict(color=TEXT_COLOR),
        height=420,
        margin=dict(l=20, r=20, t=20, b=80),
        yaxis=dict(title="契約金額 (億円)", gridcolor="#45475a"),
        xaxis=dict(tickangle=-25),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        l1.rename(
            columns={
                "pillar_id": "ID",
                "pillar_name": "大項目",
                "n_contracts": "契約件数",
                "oku_yen": "契約金額(億円)",
            }
        ).style.format({"契約金額(億円)": "{:,.0f}", "契約件数": "{:,}"}),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "⚠️ 契約金額は `contract_name LIKE '%jigyou_name%'` のサブストリングJOIN概算。"
        "同一契約が複数柱にマッチした場合は pillar_id 最小に割り当て (二重計上回避)。"
    )
else:
    st.info("該当データなし。")


# ── 階層マスタ ──────────────────────────────────────────
st.subheader("🌳 defense_pillar_master 階層")
master = _load_master()


def _format_master_row(row):
    if row["level"] == 2:
        return f"　└ P{row['pillar_id']:>3} {row['name']}"
    return f"P{row['pillar_id']:>3} {row['name']}"


master_disp = master.copy()
master_disp["階層"] = master_disp.apply(_format_master_row, axis=1)
master_disp = master_disp.rename(
    columns={
        "pillar_id": "ID",
        "level": "L",
        "parent_id": "親ID",
        "jigyou_count": "jigyou件数",
        "sources_count": "sources件数",
        "notes": "備考",
    }
)[["階層", "ID", "L", "親ID", "jigyou件数", "sources件数", "備考"]]

st.dataframe(
    master_disp.style.format(
        {"jigyou件数": "{:,}", "sources件数": "{:,}", "親ID": "{:.0f}"}, na_rep="—"
    ),
    use_container_width=True,
    hide_index=True,
    height=620,
)


# ── L2サブ柱詳細 (P4 / P7 / P8) ────────────────────────
st.subheader("🔍 中項目(L2)詳細")
parent_options = master[master["level"] == 1]
parent_options = parent_options[
    parent_options["pillar_id"].isin(
        master[master["parent_id"].notna()]["parent_id"].unique()
    )
]
parent_choice = st.selectbox(
    "親(L1)を選択",
    parent_options["pillar_id"].tolist(),
    format_func=lambda p: f"P{p} {parent_options[parent_options['pillar_id']==p]['name'].iloc[0]}",
    key="pb_parent",
)

l2 = _load_l2_for(int(parent_choice))
if not l2.empty:
    cols = st.columns(len(l2))
    for col, (_, row) in zip(cols, l2.iterrows()):
        with col:
            st.metric(
                f"P{row['pillar_id']} {row['name']}",
                f"{row['jigyou_count']:,} jigyou",
                delta=f"{row['sources_count']:,} sources",
                delta_color="off",
            )
else:
    st.info("中項目なし。")


# ── ソース別件数 ─────────────────────────────────────────
st.subheader("📦 ソース別 jigyou 登録状況")
src = _load_source_breakdown()
if not src.empty:
    src_disp = src.copy()
    src_disp["FY範囲"] = src_disp.apply(
        lambda r: f"FY{int(r['fy_min'])}-{int(r['fy_max'])}"
        if pd.notna(r["fy_min"])
        else "—",
        axis=1,
    )
    src_disp = src_disp.rename(
        columns={
            "source_type": "ソース",
            "n": "rows",
            "unique_jigyou": "unique jigyou",
        }
    )[["ソース", "rows", "unique jigyou", "FY範囲"]]
    st.dataframe(
        src_disp.style.format({"rows": "{:,}", "unique jigyou": "{:,}"}),
        use_container_width=True,
        hide_index=True,
    )


# ── jigyou サンプル (任意の柱を選択) ─────────────────────
st.subheader("📝 jigyou サンプル")
all_pillar_choice = st.selectbox(
    "柱を選択",
    master["pillar_id"].tolist(),
    format_func=lambda p: (
        f"{'  └ ' if master[master['pillar_id']==p]['level'].iloc[0] == 2 else ''}"
        f"P{p} {master[master['pillar_id']==p]['name'].iloc[0]}"
    ),
    key="pb_pillar_sample",
)
samples = _load_jigyou_samples(int(all_pillar_choice), limit=100)
if not samples.empty:
    st.caption(f"{len(samples)} 件 (最大100件)")
    st.dataframe(
        samples.rename(
            columns={
                "fiscal_year": "FY",
                "jigyou_name": "事業名",
                "source_file": "出典PDF",
                "legacy_pillar_id": "旧ID",
                "legacy_pillar_name": "旧柱名",
            }
        ),
        use_container_width=True,
        hide_index=True,
        height=400,
    )
else:
    st.info("該当する jigyou がありません。")


# ── フッタ ───────────────────────────────────────────────
st.markdown("---")
with st.expander("ℹ️ DB構成 / 集計ロジック"):
    st.markdown(
        """
**DB分割構成:**
- `data/db/procurement.db` — 契約・行政事業レビュー・装備品マスタなど
- `data/db/defense_pillar.db` — 7本柱+共通基盤マスタ・jigyouマッピング・多ソース履歴

接続は `dashboard/_db.py` の `connect_with_pillar()` 経由で取得。
`ATTACH DATABASE 'data/db/defense_pillar.db' AS pillar` 済みなので
クエリ内では `pillar.defense_pillar_jigyou` のように参照する。

**契約金額集計の方法:**
1. `pillar.defense_pillar_jigyou` の jigyou_name (またはL2→親L1) を取り出し
2. `contracts.contract_name LIKE '%jigyou_name%'` でマッチ
3. 同一契約が複数柱にマッチした場合は `MIN(pillar_id)` で1柱に割り当て (二重計上回避)
   - SQL内で `contracts` は無修飾 (procurement.db が main schema)、pillar 系は `pillar.` 修飾
4. L1 別に COUNT / SUM(contract_amount)

将来的には `contract_id × pillar_id` の正規化テーブルを作って精緻化する想定。

**legacy_pillar_id:**
旧体系(P1-P23)の値を保持。新体系(8大項目+10中項目)へリマップした履歴の追跡用。
"""
    )
