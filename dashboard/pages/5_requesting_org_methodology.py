"""要求元判定ロジックの解説ページ。

地方調達（パターンA）と中央調達（パターンB）の2パターンで要求元をどう判定するかを
ステップごとに図解し、DBの実績件数も表示する。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from _auth import require_password
require_password()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
from _db import PROC_DB as DB_PATH  # noqa: E402

# ── スタイル ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp th, .stApp td {
    color: #cdd6f4;
}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #cdd6f4; }
[data-testid="stMetricValue"] { color: #cdd6f4; font-weight: 600; }
[data-testid="stMetricLabel"] { color: #bac2de; font-size: 0.85rem; }
[data-testid="stCaptionContainer"] { color: #bac2de !important; }
[data-testid="stDataFrame"] td { font-size: 0.78rem !important; }
[data-testid="stDataFrame"] th { font-size: 0.78rem !important; white-space: nowrap; }

.pattern-box {
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 10px;
    font-size: 0.95rem;
    line-height: 1.7;
}
.pattern-a { background: #1e3a5f; border: 2px solid #5b9bd5; }
.pattern-b { background: #3a1e5f; border: 2px solid #a07fd5; }
.step-box {
    border-radius: 8px;
    padding: 14px 16px;
    margin: 8px 0;
    border-left: 5px solid;
    font-size: 0.9rem;
    line-height: 1.6;
}
.step1 { background: #1a2f1a; border-color: #4caf50; }
.step2 { background: #2f2a1a; border-color: #ff9800; }
.step3 { background: #1a2a2f; border-color: #03a9f4; }
.step4 { background: #2f1a1a; border-color: #f44336; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 700;
    margin-left: 6px;
}
.badge-green { background: #2d6a2d; color: #a5d6a7; }
.badge-orange { background: #6a4a1a; color: #ffcc80; }
.badge-blue { background: #1a3a5c; color: #90caf9; }
.badge-red { background: #5c1a1a; color: #ef9a9a; }
.badge-gray { background: #3a3a3a; color: #bdbdbd; }
.arrow-center { text-align: center; font-size: 1.4rem; color: #bac2de; margin: 4px 0; }
</style>
""", unsafe_allow_html=True)

st.title("🎯 要求元判定ロジック")
st.caption(
    "防衛省調達データにおいて、各契約の「要求元」（陸自・海自・空自・装備庁等）を"
    "どのように判定しているかを解説します。"
)

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()

# ── DB集計 ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_stats() -> dict:
    con = sqlite3.connect(DB_PATH)

    by_source = pd.read_sql_query("""
        SELECT cro.match_source,
               COUNT(*) AS 件数,
               ROUND(SUM(c.contract_amount)/1e8) AS 金額_億
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         GROUP BY cro.match_source
         ORDER BY 件数 DESC
    """, con)

    by_org = pd.read_sql_query("""
        SELECT cro.requesting_org AS 要求元,
               COUNT(*) AS 件数,
               ROUND(SUM(c.contract_amount)/1e8) AS 金額_億
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE c.agency_id = 'atla' OR c.agency_id LIKE 'atla\\_%' ESCAPE '\\'
         GROUP BY cro.requesting_org
         ORDER BY 件数 DESC
    """, con)

    fallback_top = pd.read_sql_query("""
        SELECT c.fiscal_year AS FY,
               c.contract_name AS 契約名,
               c.vendor_name AS ベンダー,
               ROUND(c.contract_amount/1e8, 1) AS 金額_億,
               c.contract_date AS 契約日
          FROM contract_requesting_org cro
          JOIN contracts c ON c.id = cro.contract_id
         WHERE cro.match_source = 'fallback_atla'
         ORDER BY c.contract_amount DESC NULLS LAST
         LIMIT 50
    """, con)

    con.close()
    return {"by_source": by_source, "by_org": by_org, "fallback_top": fallback_top}

stats = load_stats()

def _cnt(source: str | list[str]) -> int:
    df = stats["by_source"]
    if isinstance(source, str):
        source = [source]
    return int(df.loc[df["match_source"].isin(source), "件数"].sum())

total_cnt = int(stats["by_source"]["件数"].sum())
cnt_a = _cnt(["agency_rule", "agency_subrule"])
cnt_b_step1 = _cnt(["choutatsuyotei_exact", "choutatsuyotei_fuzzy",
                     "collision_majority", "collision_month"])
cnt_b_step2 = _cnt(["jigyou_review", "manual_analysis"])
cnt_b_step3 = _cnt(["kenkyuu_hyouka", "mod_research", "ref_url_inference",
                     "equipment_master_branch", "fms_vendor_heuristic", "name_keyword"])
cnt_b_step4 = _cnt(["fallback_atla"])

# ══════════════════════════════════════════════════════════════════════════════
# 概要：2パターンの並列表示
# ══════════════════════════════════════════════════════════════════════════════
st.header("判定の2パターン")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown(f"""
<div class="pattern-box pattern-a">
<b>🏢 パターン A：地方調達</b><br>
各部隊・機関が自ら調達を行うケース。<br><br>
調達情報が掲載されている <b>URL のドメイン・パス</b>から<br>
要求元を <b>直接確定</b> できる。<br><br>
例：<code>www.mod.go.jp/msdf/...</code> → <b>海上自衛隊</b><br>
例：航空装備研究所URL → <b>装備庁（研究所等）</b><br><br>
<span style="color:#90caf9">現在の収録件数：<b>{cnt_a:,}件</b></span>
</div>
""", unsafe_allow_html=True)

with col_b:
    cnt_b_total = cnt_b_step1 + cnt_b_step2 + cnt_b_step3 + cnt_b_step4
    st.markdown(f"""
<div class="pattern-box pattern-b">
<b>🏛️ パターン B：中央調達（防衛装備庁）</b><br>
防衛装備庁調達事業部が一元管理するケース。<br><br>
URL だけでは <b>どの自衛隊の装備か分からない</b>ため、<br>
複数の外部情報源を照合して要求元を絞り込む。<br><br>
Step 1〜4 の順に照合を試みる。<br><br>
<span style="color:#ce93d8">現在の収録件数：<b>{cnt_b_total:,}件</b></span>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# パターン A 詳細
# ══════════════════════════════════════════════════════════════════════════════
st.header("パターン A：地方調達の判定方法")

with st.expander("詳細を見る", expanded=False):
    st.markdown("""
各機関のウェブサイトに掲載された調達情報は、機関固有のドメインまたはパスに配置されている。
このURLパターンを解析することで、要求元を確実に特定できる。

| 収集元の例 | URL パターン | 判定される要求元 |
|-----------|------------|---------------|
| 海上自衛隊横須賀地方総監部 | `msdf.mil.go.jp/...` | 海上自衛隊 (MSDF) |
| 陸上自衛隊補給統制本部 | `gsdf.mil.go.jp/...` | 陸上自衛隊 (GSDF) |
| 航空自衛隊第2補給処 | `asdf.mil.go.jp/...` | 航空自衛隊 (ASDF) |
| 防衛装備庁航空装備研究所 | `mod.go.jp/atla/aeri/...` | 装備庁（研究所等）|
| 地方防衛局 | `mod.go.jp/rdb/...` | 地方防衛局 (RDB) |

**agency_subrule について**：防衛装備庁のサブ機関（`atla_kanbo`、`atla_riku`等）は
ATLAのドメイン内にあるが、パス構造から担当部署を絞り込める。現在は暫定的に
「装備庁（研究所等）」として分類している。
""")

    cnt_rule = _cnt("agency_rule")
    cnt_sub = _cnt("agency_subrule")
    m1, m2 = st.columns(2)
    m1.metric("agency_rule（URLで直接確定）", f"{cnt_rule:,}件")
    m2.metric("agency_subrule（ATLAサブ機関）", f"{cnt_sub:,}件")

# ══════════════════════════════════════════════════════════════════════════════
# パターン B 詳細
# ══════════════════════════════════════════════════════════════════════════════
st.header("パターン B：中央調達の判定フロー")

st.markdown("""
防衛装備庁調達事業部が契約する案件（`agency_id = atla`）は、URLだけでは
陸自・海自・空自のどれの装備かが判別できない。以下の4ステップで順次照合する。
""")

# ── Step 1 ────────────────────────────────────────────────────────────────────
cnt_exact = _cnt("choutatsuyotei_exact")
cnt_fuzzy = _cnt("choutatsuyotei_fuzzy")
cnt_col_maj = _cnt("collision_majority")
cnt_col_mon = _cnt("collision_month")

st.markdown(f"""
<div class="step-box step1">
<b>Step 1　調達予定品目表との照合</b>
<span class="badge badge-green">最優先</span><br><br>
防衛装備庁が毎年度公表する「調達予定品目一覧」と契約名を突合する。<br>
品目表には <b>要求元（陸自・海自・空自・装備庁）</b> が明記されている。<br><br>
&nbsp;&nbsp;• <b>完全一致</b>（NFKC正規化）：{cnt_exact:,}件を確定<br>
&nbsp;&nbsp;• <b>部分一致・FY近傍</b>（fuzzy matching）：{cnt_fuzzy:,}件を確定<br>
&nbsp;&nbsp;• 複数FYに同一品名が複数orgで登録 →
  契約月照合（{cnt_col_mon:,}件）or 多数決（{cnt_col_maj:,}件）で解消<br><br>
<b>Step 1 合計：{cnt_exact + cnt_fuzzy + cnt_col_maj + cnt_col_mon:,}件</b>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼</div>', unsafe_allow_html=True)

# ── Step 2 ────────────────────────────────────────────────────────────────────
cnt_jr = _cnt("jigyou_review")
cnt_ma = _cnt("manual_analysis")

st.markdown(f"""
<div class="step-box step2">
<b>Step 2　行政事業レビュー・手動辞書との照合</b>
<span class="badge badge-orange">補完</span><br><br>
各事業の担当部局（○○担当、○○幕僚長等）から要求元を推定する。<br>
大型案件については手動で割当辞書を整備している。<br><br>
&nbsp;&nbsp;• <b>行政事業レビュー照合</b>（jigyou_review）：{cnt_jr:,}件<br>
&nbsp;&nbsp;• <b>手動辞書オーバーライド</b>（manual_analysis）：{cnt_ma:,}件<br><br>
<b>Step 2 合計：{cnt_jr + cnt_ma:,}件</b>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼</div>', unsafe_allow_html=True)

# ── Step 3 ────────────────────────────────────────────────────────────────────
cnt_kh = _cnt("kenkyuu_hyouka")
cnt_mr = _cnt("mod_research")
cnt_rui = _cnt("ref_url_inference")
cnt_emb = _cnt("equipment_master_branch")
cnt_fms = _cnt("fms_vendor_heuristic")
cnt_nk = _cnt("name_keyword")

st.markdown(f"""
<div class="step-box step3">
<b>Step 3　ヒューリスティック推定</b>
<span class="badge badge-blue">補助</span><br><br>
上記ステップで特定できない場合、以下の補助情報を組み合わせて推定する。<br><br>
&nbsp;&nbsp;• <b>事前事後評価書</b>（総務省ポータル）：担当部局から推定 {cnt_kh:,}件<br>
&nbsp;&nbsp;• <b>mod.go.jp 調査</b>（Web参照・URL推論）：{cnt_mr + cnt_rui:,}件<br>
&nbsp;&nbsp;• <b>装備品マスター</b>：装備品の所属branch（GSDF/MSDF/ASDF）から推定 {cnt_emb:,}件<br>
&nbsp;&nbsp;• <b>FMSベンダー</b>：米陸軍省→陸自、米海軍省→海自、米空軍省→空自 {cnt_fms:,}件<br>
&nbsp;&nbsp;• <b>契約名キーワード</b>：「護衛艦」「戦車」等の固有語から推定 {cnt_nk:,}件<br><br>
<b>Step 3 合計：{cnt_kh + cnt_mr + cnt_rui + cnt_emb + cnt_fms + cnt_nk:,}件</b>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼</div>', unsafe_allow_html=True)

# ── Step 4 ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="step-box step4">
<b>Step 4　最終フォールバック（仮割当）</b>
<span class="badge badge-red">残存</span><br><br>
Step 1〜3 のいずれでも要求元を特定できなかった場合、暫定的に
<b>「要求元未解決（中央調達）」</b>として仮割当する。<br><br>
研究開発・ATLA固有調達・判定困難な秘密調達等が該当する。<br>
追加情報（品目表の拡充・手動辞書への登録）で順次解消できる。<br><br>
<b>現在の仮割当残存：{cnt_b_step4:,}件</b>
</div>
""", unsafe_allow_html=True)

# ── 出典URL ───────────────────────────────────────────────────────────────────
st.subheader("参照している外部情報源")

src_col1, src_col2 = st.columns(2)
with src_col1:
    st.markdown("**Step 1：調達予定品目表**")
    st.link_button(
        "防衛装備庁 調達予定品目一覧",
        "https://www.mod.go.jp/atla/chotatsu/chotatsuyotei/index.html",
    )
    st.caption("毎年度、品目名・要求元・予定金額が掲載される。FY2015〜2026の12年分を収録済み。")

    st.markdown("**Step 2：行政事業レビュー**")
    st.link_button(
        "防衛省 行政事業レビュー",
        "https://www.mod.go.jp/j/approach/agenda/meeting/jigyou_review/index.html",
    )
    st.caption("各事業の担当部局・予算規模が記載される。")

with src_col2:
    st.markdown("**Step 3：事前事後評価書（研究開発系）**")
    st.link_button(
        "総務省 政策評価ポータル（防衛省）",
        "https://www.soumu.go.jp/main_sosiki/hyouka/gyousei_n/",
    )
    st.caption("研究開発案件の担当部局（陸・海・空・装備庁）が記載される。")

    st.markdown("**Step 3：FMS調達実績**")
    st.link_button(
        "防衛装備庁 FMS調達実績",
        "https://www.mod.go.jp/atla/souhon/supply/jisseki/",
    )
    st.caption("対米有償軍事援助（FMS）の調達元省庁から要求元を推定。")

# ══════════════════════════════════════════════════════════════════════════════
# DB実績
# ══════════════════════════════════════════════════════════════════════════════
st.header("現在のDB収録実績")

# サマリー指標
m1, m2, m3, m4 = st.columns(4)
m1.metric("全契約数", f"{total_cnt:,}件")
m2.metric("パターンA（地方調達）", f"{cnt_a:,}件")
m3.metric("パターンB（中央調達）", f"{cnt_b_step1+cnt_b_step2+cnt_b_step3+cnt_b_step4:,}件")
m4.metric("うち仮割当（fallback）", f"{cnt_b_step4:,}件", delta=f"{100*cnt_b_step4/(cnt_b_step1+cnt_b_step2+cnt_b_step3+cnt_b_step4):.1f}%", delta_color="inverse")

# パターンBの要求元別内訳
st.subheader("中央調達の要求元別内訳")
with st.expander("要求元別の件数・金額を見る", expanded=True):
    st.dataframe(
        stats["by_org"].rename(columns={"要求元": "要求元（推定）"}),
        use_container_width=True,
        hide_index=True,
    )

# match_source 別の詳細
st.subheader("判定手法（match_source）別の件数")

SOURCE_LABEL = {
    "agency_rule": "パターンA：URL直接確定",
    "agency_subrule": "パターンA：ATLAサブ機関",
    "choutatsuyotei_exact": "Step1：調達予定 完全一致",
    "choutatsuyotei_fuzzy": "Step1：調達予定 部分一致",
    "collision_majority": "Step1：複数候補→多数決",
    "collision_month": "Step1：複数候補→月照合",
    "jigyou_review": "Step2：行政事業レビュー",
    "manual_analysis": "Step2：手動辞書",
    "kenkyuu_hyouka": "Step3：事前事後評価書",
    "mod_research": "Step3：mod.go.jp調査",
    "ref_url_inference": "Step3：URL推論",
    "equipment_master_branch": "Step3：装備品マスター",
    "fms_vendor_heuristic": "Step3：FMSベンダー",
    "name_keyword": "Step3：契約名キーワード",
    "fallback_atla": "Step4：フォールバック（仮割当）",
}

df_display = stats["by_source"].copy()
df_display.insert(
    0, "判定手法",
    df_display["match_source"].map(lambda s: SOURCE_LABEL.get(s, s))
)
df_display = df_display.drop(columns=["match_source"])
st.dataframe(df_display, use_container_width=True, hide_index=True)

# フォールバック上位
st.subheader(f"仮割当（fallback）残存 — 上位50件（金額順）")
st.caption("Step 1〜3 で判定できず、要求元未解決（中央調達）として仮割当された契約。"
           "品目表への追加や手動辞書登録で解消できる可能性がある。")

if len(stats["fallback_top"]) > 0:
    st.dataframe(stats["fallback_top"], use_container_width=True, hide_index=True)
    csv_bytes = stats["fallback_top"].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 fallback上位50件 CSV",
        data=csv_bytes,
        file_name="fallback_atla_top50.csv",
        mime="text/csv",
    )
else:
    st.info("fallback_atlaなし")
