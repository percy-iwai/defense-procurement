"""要求元判定ロジックの可視化と検証ページ。

ATLA中央調達契約の要求元判定（match_source）の優先順位、件数分布、
信頼度（confidence）、残存fallbackの抜粋等を表示する。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from _auth import require_password
require_password()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"
LOG_DIR = PROJECT_ROOT / "logs"

TEXT_COLOR = "#cdd6f4"
TEXT_DIM = "#bac2de"
ACCENT = "#7c83fd"

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
</style>
""", unsafe_allow_html=True)

st.title("🎯 要求元判定ロジック")
st.caption(
    "防衛装備庁（ATLA）経由の中央調達契約について、"
    "要求元（陸自・海自・空自・統幕等）をどう判定しているかを可視化。"
)

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()

# ─── ロジック説明 ───────────────────────────────────────────────────────────
st.header("1. 判定ロジック（優先順位順）")

LOGIC_TABLE = pd.DataFrame([
    {"順位": 1, "match_source": "agency_rule",
     "内容": "収集元 agency_id から非ATLA要求元を直接決定（例: msdf_asd→MSDF）",
     "信頼度": 1.0},
    {"順位": 2, "match_source": "agency_subrule",
     "内容": "ATLAサブ機関（atla_riku等）→ 仮処置で全部 ATLA（"
             "ラベル「装備庁（研究所等）」）",
     "信頼度": 0.5},
    {"順位": 3, "match_source": "choutatsuyotei_exact",
     "内容": "全FYのchoutatsuyoteiでNFKC正規化完全一致 + 単一org",
     "信頼度": 0.9},
    {"順位": "4a", "match_source": "choutatsuyotei_fuzzy (Δ0)",
     "内容": "同一FYの調達予定品目とfuzzy substring一致（全FY横断単一org）",
     "信頼度": 0.90},
    {"順位": "4b", "match_source": "choutatsuyotei_fuzzy (Δ1)",
     "内容": "Δ1 FY のfuzzy一致",
     "信頼度": 0.80},
    {"順位": "4c", "match_source": "choutatsuyotei_fuzzy (Δ2+)",
     "内容": "Δ2以上 FY のfuzzy一致",
     "信頼度": 0.65},
    {"順位": "4d", "match_source": "manual_analysis",
     "内容": "大型案件の手動オーバーライド辞書（行政事業レビュー参照）",
     "信頼度": 0.85},
    {"順位": 6, "match_source": "collision_month",
     "内容": "exact複数org → 契約月が調達予定月と一致するorgで解消",
     "信頼度": 0.7},
    {"順位": 7, "match_source": "collision_majority",
     "内容": "exact複数org → 多数決で解消",
     "信頼度": 0.5},
    {"順位": "7.5", "match_source": "equipment_master_branch",
     "内容": "装備品マスターのbranchがGSDF/MSDF/ASDF（JOINTは除外）",
     "信頼度": 0.7},
    {"順位": 8, "match_source": "fms_vendor_heuristic",
     "内容": "FMSベンダー軍種で便宜的に推定（米陸→GSDF, 米海→MSDF, 米空→ASDF）",
     "信頼度": 0.5},
    {"順位": 9, "match_source": "fallback_atla",
     "内容": "上記いずれにもマッチせず → ATLAのまま残存（要追加調査）",
     "信頼度": 0.3},
])
st.dataframe(LOGIC_TABLE, use_container_width=True, hide_index=True)

st.info(
    "**廃止されたロジック:** vendor_majority（重工等の大型ベンダーは"
    "複数機関に供給するため、ベンダーから要求元を一意に決められない）"
)

# ─── DB集計 ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_stats() -> dict:
    con = sqlite3.connect(DB_PATH)
    by_source = pd.read_sql_query("""
        SELECT cro.match_source AS match_source,
               COUNT(*) AS 件数,
               ROUND(SUM(c.contract_amount)/1e8) AS 金額_億,
               ROUND(AVG(cro.confidence), 2) AS 平均信頼度
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'
         GROUP BY cro.match_source
         ORDER BY 件数 DESC
    """, con)

    pivot = pd.read_sql_query("""
        SELECT cro.requesting_org AS 要求元,
               cro.match_source AS match_source,
               COUNT(*) AS 件数
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'
         GROUP BY cro.requesting_org, cro.match_source
    """, con)

    fy_source = pd.read_sql_query("""
        SELECT c.fiscal_year AS FY,
               cro.match_source AS match_source,
               COUNT(*) AS 件数
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'
         GROUP BY c.fiscal_year, cro.match_source
    """, con)

    fallback_top = pd.read_sql_query("""
        SELECT c.fiscal_year AS FY,
               c.contract_name AS 契約名,
               c.vendor_name AS ベンダー,
               ROUND(c.contract_amount/1e8, 1) AS 金額_億,
               c.contract_date AS 契約日,
               c.agency_id AS agency_id
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE cro.match_source = 'fallback_atla'
           AND (c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\')
         ORDER BY c.contract_amount DESC NULLS LAST
         LIMIT 100
    """, con)

    manual_hits = pd.read_sql_query("""
        SELECT cro.requesting_org AS 要求元,
               c.contract_name AS 契約名,
               ROUND(c.contract_amount/1e8, 1) AS 金額_億,
               c.fiscal_year AS FY
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE cro.match_source = 'manual_analysis'
           AND (c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\')
         ORDER BY c.contract_amount DESC NULLS LAST
    """, con)
    con.close()
    return {
        "by_source": by_source, "pivot": pivot, "fy_source": fy_source,
        "fallback_top": fallback_top, "manual_hits": manual_hits,
    }


stats = load_stats()

# ─── サマリー ───────────────────────────────────────────────────────────────
st.header("2. ATLA契約 30,659件 の判定結果")

total_cnt = int(stats["by_source"]["件数"].sum())
total_amt = int(stats["by_source"]["金額_億"].fillna(0).sum())
fallback_cnt = int(
    stats["by_source"].loc[stats["by_source"]["match_source"] == "fallback_atla", "件数"].sum()
    or 0
)
fallback_amt = int(
    stats["by_source"].loc[stats["by_source"]["match_source"] == "fallback_atla", "金額_億"].sum()
    or 0
)
high_conf_cnt = int(
    stats["by_source"][stats["by_source"]["平均信頼度"] >= 0.7]["件数"].sum()
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("総件数", f"{total_cnt:,}件")
c2.metric("総金額", f"{total_amt:,}億")
c3.metric("信頼度0.7以上", f"{high_conf_cnt:,}件",
          f"{100*high_conf_cnt/total_cnt:.1f}%")
c4.metric("fallback残存", f"{fallback_cnt:,}件",
          f"{fallback_amt:,}億",
          delta_color="inverse")

# ─── match_source 別件数 ────────────────────────────────────────────────────
st.subheader("2-1. match_source 別件数・金額")
st.dataframe(stats["by_source"], use_container_width=True, hide_index=True)

# ─── FY × match_source 積み上げ棒 ───────────────────────────────────────────
st.subheader("2-2. FY × match_source 積み上げ")
fig = px.bar(
    stats["fy_source"], x="FY", y="件数", color="match_source",
    barmode="stack",
    color_discrete_sequence=px.colors.qualitative.Set3,
    template="plotly_dark",
)
fig.update_layout(height=400, font=dict(color=TEXT_COLOR))
st.plotly_chart(fig, use_container_width=True)

# ─── 要求元 × match_source ヒートマップ ─────────────────────────────────────
st.subheader("2-3. 要求元 × match_source（件数）")
pivot_table = stats["pivot"].pivot(
    index="要求元", columns="match_source", values="件数"
).fillna(0).astype(int)
st.dataframe(pivot_table, use_container_width=True)

# ─── manual_analysis ヒット一覧 ─────────────────────────────────────────────
st.header("3. manual_analysis ヒット一覧")
st.caption(
    "`dev/manual_atla_overrides.py` の手動辞書がヒットした契約。"
    "辞書を追加すれば fallback_atla を減らせる。"
)
if len(stats["manual_hits"]) > 0:
    st.dataframe(stats["manual_hits"], use_container_width=True, hide_index=True)
else:
    st.info("manual_analysisヒットなし")

# ─── fallback_atla 上位 ────────────────────────────────────────────────────
st.header(f"4. fallback_atla 残存（要追加調査）— 上位100件")
st.caption(
    "判定不能としてATLAに残った契約。"
    "金額の大きい順。manual_overridesに追加するか、equipment_masterに装備品を登録すれば解決可能。"
)
st.dataframe(stats["fallback_top"], use_container_width=True, hide_index=True)
csv_bytes = stats["fallback_top"].to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "📥 fallback_atla 上位100件 CSV",
    data=csv_bytes,
    file_name="fallback_atla_top100.csv",
    mime="text/csv",
)

# ─── 再実行ログ ─────────────────────────────────────────────────────────────
st.header("5. 再実行履歴")
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_files = sorted(LOG_DIR.glob("recompute_atla_*.json"), reverse=True)[:10]
if log_files:
    log_rows = []
    for lf in log_files:
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            after = data.get("after", {})
            log_rows.append({
                "実行時刻": data.get("timestamp", lf.stem),
                "経過秒": data.get("elapsed_sec"),
                "総件数": after.get("total_contracts"),
                "総額_億": after.get("total_amount_oku"),
                "fallback件数": (after.get("by_source") or {}).get("fallback_atla", 0),
                "log": lf.name,
            })
        except Exception as e:
            log_rows.append({"実行時刻": lf.stem, "log": lf.name, "error": str(e)})
    st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)
else:
    st.info("実行履歴なし")
