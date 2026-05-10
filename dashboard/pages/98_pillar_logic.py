"""7本柱分類判定ロジックの解説ページ。

防衛力整備計画の7本柱（P1〜P7）および共通基盤（P8）への契約分類がどのような
ロジックで行われているかをステップごとに図解し、KEYWORD_RULES の全ルールも
一覧・検索できるビューワーを提供する。
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from _auth import require_password  # noqa: E402

require_password()

PROJECT_ROOT   = DASHBOARD_DIR.parent
DB_PATH        = PROJECT_ROOT / "data" / "db" / "procurement.db"
CORRECTIONS_CSV = PROJECT_ROOT / "data" / "manual" / "pillar_corrections_pending.csv"

# ── KEYWORD_RULES の読み込み ─────────────────────────────────────────────────
_RULES_LOADED = False
_KEYWORD_RULES_RAW: list = []
_import_err = ""
try:
    _dev_dir = str(PROJECT_ROOT / "dev")
    if _dev_dir not in sys.path:
        sys.path.insert(0, _dev_dir)
    from assign_pillar_fy2023 import _KEYWORD_RULES_RAW as _KR
    _KEYWORD_RULES_RAW = list(_KR)
    _RULES_LOADED = True
except Exception as _e:
    _import_err = str(_e)

# ── ピラー定義マスター ────────────────────────────────────────────────────────
PILLAR_DEFS = [
    # (code, name_short, description, examples, color)
    ("P1",  "スタンド・オフ防衛能力",
     "射程の長いミサイルで、敵の脅威圏外から島嶼・艦艇等を攻撃できる反撃能力の整備。",
     "12式地対艦誘導弾能力向上型・トマホーク・高速滑空弾・JSM",
     "#e57373"),
    ("P2",  "統合防空ミサイル防衛能力",
     "弾道ミサイル・巡航ミサイル・航空機等を多層防御で迎撃するシステムの整備。",
     "イージス艦（SM-3/SM-6）・PAC-3・LTAMDS・E-2D早期警戒機",
     "#ff8a65"),
    ("P3",  "無人アセット防衛能力",
     "偵察・攻撃・後方支援などに用いる無人機（UAV/UUV/USV/UGV）の開発・取得。",
     "RQ-4グローバルホーク・シーガーディアン・UUV・スウォーム技術",
     "#ce93d8"),
    ("P41", "宇宙領域把握 〈P4サブ〉",
     "宇宙状況監視（SSA）・通信衛星・早期警戒衛星など宇宙ドメイン能力の整備。",
     "Xバンド衛星通信（きらめき）・SSA衛星・SDA研究衛星",
     "#7986cb"),
    ("P42", "サイバー防衛 〈P4サブ〉",
     "クラウド・ゼロトラスト・DII等のサイバー防衛インフラおよびネットワーク防衛能力。",
     "中央クラウド整備・空自クラウド・DII・防衛SGW",
     "#4dd0e1"),
    ("P43", "電磁波・主要装備 〈P4サブ〉",
     "電磁波戦装備と、陸海空の主要装備品（艦艇・航空機・車両等）の取得。",
     "護衛艦（FFM）・F-35A/B・次期戦闘機（GCAP）・電子戦装置・SH-60K",
     "#4fc3f7"),
    ("P5",  "指揮統制・情報関連機能",
     "C4ISR・戦術データリンク・情報収集・SIGINT・認知戦対処等の指揮統制インフラ。",
     "JADGE・Link-16・MSII・野外通信システム・情報本部GRQ系装置",
     "#81c784"),
    ("P6",  "機動展開能力・国民保護",
     "南西諸島等への迅速な部隊展開・輸送能力と国民保護のための装備・施設整備。",
     "輸送艦・KC-46A空中給油機・LCU・コンテナトレーラー",
     "#a5d6a7"),
    ("P71", "弾薬・誘導弾の確保 〈P7サブ〉",
     "必要量の弾薬・誘導弾の取得・備蓄拡充。消耗品としての弾薬在庫の積み増し。",
     "155mm榴弾・魚雷・機雷・AIM-9X・誘導弾補用品",
     "#fff176"),
    ("P72", "装備品等の可動率向上 〈P7サブ〉",
     "予備部品・定期修理・PBL（成果払い）等による装備品の稼働率・即応性の向上。",
     "F-15/F-35定期修理・ペトリオット定期修理・補用部品・ALGS",
     "#ffd54f"),
    ("P73", "施設強靱化・後方 〈P7サブ〉",
     "地下化・えん体化・分散パッド化などによる基地施設の抗堪性向上と後方支援。",
     "格納庫強化工事・弾薬庫新設・掩体整備・係留施設整備",
     "#ffb74d"),
    ("P81", "防衛生産基盤強化 〈P8サブ〉",
     "サプライチェーン強化・製造工程効率化・防衛産業の競争力・海外移転促進。",
     "製造工程効率化特定取組・防衛産業育成支援",
     "#bcaaa4"),
    ("P82", "研究開発 〈P8サブ〉",
     "将来の防衛装備品開発に向けた基礎・応用・技術実証研究。試作・FTB化等を含む。",
     "次期戦闘機（GCAP）開発・高出力レーザ実証装置・スウォーム研究（P3との競合に注意）",
     "#b0bec5"),
    ("P83", "基地対策 〈P8サブ〉",
     "米軍基地周辺の騒音対策・家屋防音・土地賃貸借等の基地周辺対策事業。",
     "家屋防音工事・土地賃借料（RDB系機関）・飛行場周辺整備",
     "#90a4ae"),
    ("P84", "教育訓練・燃料等 〈P8サブ〉",
     "教育訓練費・航空燃料（JP-8等）・潤滑油など消耗品調達。クラウド「借上」との混同注意。",
     "JP-8（航空燃料）・灯油・軽油・訓練弾・演習費",
     "#80cbc4"),
    ("P85", "米軍再編関係経費 〈P8サブ〉",
     "普天間代替施設（辺野古埋立・キャンプ・シュワブ）・馬毛島基地・グアム移転等の工事。",
     "シュワブ工事（辺野古沖埋立）・馬毛島基地建設・FCLP施設整備",
     "#aed581"),
]

PILLAR_LABEL = {
    1: "P1", 2: "P2", 3: "P3", 4: "P4",
    41: "P41", 42: "P42", 43: "P43",
    5: "P5", 6: "P6", 7: "P7",
    71: "P71", 72: "P72", 73: "P73",
    8: "P8", 81: "P81", 82: "P82", 83: "P83", 84: "P84", 85: "P85",
}

PILLAR_NAME = {
    "P1": "スタンド・オフ防衛能力",
    "P2": "統合防空ミサイル防衛能力",
    "P3": "無人アセット防衛能力",
    "P4": "領域横断作戦能力",
    "P41": "宇宙領域把握",
    "P42": "サイバー防衛",
    "P43": "電磁波・主要装備",
    "P5": "指揮統制・情報関連機能",
    "P6": "機動展開能力・国民保護",
    "P7": "持続性・強靱性",
    "P71": "弾薬・誘導弾の確保",
    "P72": "装備品等の可動率向上",
    "P73": "施設強靱化・後方",
    "P8": "防衛生産・技術基盤（共通基盤）",
    "P81": "防衛生産基盤強化",
    "P82": "研究開発",
    "P83": "基地対策",
    "P84": "教育訓練・燃料等",
    "P85": "米軍再編関係経費",
}

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
.step4 { background: #2a1a2f; border-color: #ab47bc; }
.step5 { background: #2f1a1a; border-color: #f44336; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 700;
    margin-left: 6px;
}
.badge-green  { background: #2d6a2d; color: #a5d6a7; }
.badge-orange { background: #6a4a1a; color: #ffcc80; }
.badge-blue   { background: #1a3a5c; color: #90caf9; }
.badge-purple { background: #3a1a5c; color: #ce93d8; }
.badge-red    { background: #5c1a1a; color: #ef9a9a; }
.arrow-center { text-align: center; font-size: 1.4rem; color: #bac2de; margin: 4px 0; }
.notice-box {
    background: #2f2a1a;
    border: 1px solid #ff9800;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 8px 0;
    font-size: 0.88rem;
    line-height: 1.6;
}
.pillar-chip {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 4px;
    font-size: 0.78rem;
    font-weight: 700;
    margin-right: 4px;
    background: #313244;
    color: #cdd6f4;
}
</style>
""", unsafe_allow_html=True)

st.title("🏛️ 7本柱分類判定ロジック")
st.caption(
    "防衛力整備計画の7本柱（P1〜P7）および共通基盤（P8）への契約分類の仕組みを解説します。"
    "読者向けの説明資料としても、作業時の参照資料としても使えます。"
)

# ══════════════════════════════════════════════════════════════════════════════
# 1. 概要
# ══════════════════════════════════════════════════════════════════════════════
st.header("分類の基本方針")

st.markdown("""
各契約を防衛力整備計画の7本柱（P1〜P7）および共通基盤（P8）に紐付けるにあたり、
次の優先順位で分類を決定する。

| 優先度 | 手法 | 説明 |
|-------|------|------|
| 1 | **事業名 fuzzy matching** | 調達予定品目表・行政事業レビューの事業名と契約名を rapidfuzz で突合（threshold=78） |
| 2 | **KEYWORD_RULES** | 契約名のキーワードを全ルールでスキャン。**confidence 最大のルールが勝つ** |
| 3 | **セマンティック埋め込み** | multilingual-e5-large によるコサイン類似度（threshold=0.80）。FY2023未分類に適用済み |
| 4 | **手動修正** | `pillar_corrections_pending.csv` による上書き（ピラーレビュービューワーで記録） |
| — | **未分類** | いずれの手法でもマッチしない契約（NDMC医療器材・汎用消耗品等が残存） |

**重要な原則**：
- すべての契約名は照合前に **NFKC正規化**（全角英数→半角）する。ルールのキーワードも同様に正規化済み。
- 複数の KEYWORD_RULES がヒットした場合、**confidence が最も高いルールを採用**する。
- セマンティック埋め込みは誤分類リスクがあるため、**threshold=0.80** を採用
  （0.75では NDMC医療器材のP43誤分類が多発）。
""")

# ══════════════════════════════════════════════════════════════════════════════
# 2. 7本柱（+共通基盤）の定義
# ══════════════════════════════════════════════════════════════════════════════
st.header("7本柱＋共通基盤の定義")

st.markdown("""
防衛力整備計画（令和5年度〜令和9年度）に示された防衛力強化の7つの重点分野と共通基盤。
「P8共通基盤」は研究開発・防衛産業基盤・基地対策・教育訓練等の横断的な支援カテゴリ。
""")

# テーブル形式で表示（DataFrame）
pillar_rows = []
for code, name_short, desc, examples, _ in PILLAR_DEFS:
    parent = code[:2] if len(code) > 2 else ""
    if len(code) > 2:
        indent_code = f"　└ {code}"
    else:
        indent_code = code
    pillar_rows.append({
        "ピラーコード": indent_code,
        "名称": name_short,
        "内容": desc,
        "代表的な案件例": examples,
    })

df_pillar = pd.DataFrame(pillar_rows)
st.dataframe(
    df_pillar,
    use_container_width=True,
    hide_index=True,
    column_config={
        "ピラーコード": st.column_config.TextColumn(width="small"),
        "名称": st.column_config.TextColumn(width="medium"),
        "内容": st.column_config.TextColumn(width="large"),
        "代表的な案件例": st.column_config.TextColumn(width="large"),
    },
)

# ══════════════════════════════════════════════════════════════════════════════
# 3. 分類フロー図
# ══════════════════════════════════════════════════════════════════════════════
st.header("分類フロー（1契約につき）")

st.markdown("各契約は以下のフローで分類される。早い段階でマッチすると、以降のステップはスキップされる。")

st.markdown("""
<div class="step-box step1">
<b>Step 1　NFKC正規化</b>
<span class="badge badge-green">前処理</span><br><br>
契約名に含まれる全角英数字・記号を半角に統一（NFKC正規化）。<br>
例: 「Ｆ－３５Ａ」→「F-35A」、「ＵＡＶ」→「UAV」<br>
KEYWORD_RULES のキーワードも起動時に同じ正規化を実施済み。
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼</div>', unsafe_allow_html=True)

st.markdown("""
<div class="step-box step2">
<b>Pass 1　事業名 fuzzy matching（最優先）</b>
<span class="badge badge-orange">優先度1</span><br><br>
<code>defense_pillar_jigyou</code> と <code>pillar_mapping_sources</code> に登録された事業名コーパス
（合計≈2,500件）と契約名を <b>rapidfuzz token_set_ratio</b> で突合。<br>
スコア ≥ 78 の場合、対応する pillar_id を採用（<code>match_method = fuzzy_jigyou</code>）。<br><br>
例：「12式地対艦誘導弾能力向上型の取得」→ P1（スタンドオフ）
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼ fuzzy 不一致の場合</div>', unsafe_allow_html=True)

st.markdown("""
<div class="step-box step2">
<b>Pass 2　KEYWORD_RULES スキャン（キーワードマッチング）</b>
<span class="badge badge-orange">優先度2</span><br><br>
全 KEYWORD_RULES エントリを順番にスキャンし、<b>ヒットしたすべてのルール</b>のうち
<b>confidence が最大のものを採用</b>（<code>match_method = keyword_rule</code>）。<br><br>
サブルール：<br>
&nbsp;&nbsp;• <b>org_maintenance fallback</b>：GSDF/MSDF/ASDF/ATLAで「維持・整備・修理」系 → P72（conf=0.60）<br>
&nbsp;&nbsp;• <b>org_fuel fallback</b>：同機関で「燃料・灯油・軽油」系 → P84（conf=0.60）<br>
&nbsp;&nbsp;• <b>ATLA research fallback</b>：ATLAで「研究・試作・開発」系 → P82（conf=0.58）<br><br>
例：「護衛艦（FFM）搭載レーダ」→ P43「護衛艦」(0.75) と P43「レーダ」(0.75) が競合 → P43採用
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼ keyword 不一致の場合</div>', unsafe_allow_html=True)

st.markdown("""
<div class="step-box step3">
<b>Pass 3　セマンティック埋め込みマッチング（後処理）</b>
<span class="badge badge-blue">優先度3</span><br><br>
<code>intfloat/multilingual-e5-large</code> モデルによるコサイン類似度でピラーのpassageと照合。<br>
<code>assign_pillar_semantic.py --threshold 0.80</code> で FY2023 未分類契約に適用済み。<br><br>
⚠️ <b>精度上の注意</b>：threshold=0.80 でも NDMC 医療器材（超音波診断装置等）が
P43（電磁波・主要装備）に誤分類される事例あり。NDMC除外フィルターの追加を検討中。
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼ いずれも不一致</div>', unsafe_allow_html=True)

st.markdown("""
<div class="step-box step4">
<b>未分類（unclassified）</b>
<span class="badge badge-purple">残存</span><br><br>
いずれの手法でもマッチしない契約。FY2023では <b>18,655件</b> が未分類で残存。<br>
主な内訳：NDMC医療器材、一般消耗品、汎用物品役務など。
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="arrow-center">▼ 随時</div>', unsafe_allow_html=True)

st.markdown("""
<div class="step-box step5">
<b>手動修正（上書き）</b>
<span class="badge badge-red">オーバーライド</span><br><br>
「ピラーレビュービューワー」で記録した修正指示が
<code>data/manual/pillar_corrections_pending.csv</code> に保存される。<br>
修正は次回の再分類実行時に contract_pillar へ反映される。<br><br>
現在の保留修正件数：
""", unsafe_allow_html=True)

# 保留修正件数を表示
if CORRECTIONS_CSV.exists():
    try:
        df_corr = pd.read_csv(CORRECTIONS_CSV, encoding="utf-8-sig")
        pending = len(df_corr)
        st.markdown(f'<span style="color:#ef9a9a;font-weight:600">{pending:,}件</span>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<span style="color:#bac2de">（読み込みエラー）</span>', unsafe_allow_html=True)
else:
    st.markdown('<span style="color:#bac2de">0件（ファイルなし）</span>', unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# 4. KEYWORD_RULES ビューワー
# ══════════════════════════════════════════════════════════════════════════════
st.header("KEYWORD_RULES ビューワー")
st.caption(
    "assign_pillar_fy2023.py の _KEYWORD_RULES_RAW から読み込んだ全ルール一覧。"
    "ピラーコード・confidence・org_filter でフィルタリングできます。"
)

if not _RULES_LOADED:
    st.warning(
        f"KEYWORD_RULES の読み込みに失敗しました。\n"
        f"エラー: `{_import_err}`\n\n"
        "assign_pillar_fy2023.py が `dev/` フォルダに存在し、"
        "依存ライブラリ（rapidfuzz 等）がインストール済みか確認してください。"
    )
else:
    # DataFrame 構築
    rules_rows = []
    for raw in _KEYWORD_RULES_RAW:
        kws: list[str] = raw[0]
        l1: int = raw[1]
        l2 = raw[2] if raw[2] is not None else None
        conf: float = raw[3]
        org_filter = raw[4] if len(raw) > 4 else None

        pillar_code = f"P{l2}" if l2 is not None else f"P{l1}"
        pillar_name = PILLAR_NAME.get(pillar_code, "")

        kws_display = "、".join(kws[:12])
        if len(kws) > 12:
            kws_display += f"… （他{len(kws)-12}件）"

        org_str = "、".join(sorted(org_filter)) if org_filter else "全機関"

        rules_rows.append({
            "ピラー": pillar_code,
            "名称": pillar_name,
            "confidence": conf,
            "org_filter": org_str,
            "キーワード一覧": kws_display,
            "キーワード数": len(kws),
        })

    df_rules = pd.DataFrame(rules_rows)

    # フィルター UI
    fc1, fc2, fc3 = st.columns([2, 2, 3])
    with fc1:
        pillar_opts = ["（すべて）"] + sorted(df_rules["ピラー"].unique().tolist())
        sel_pillar = st.selectbox("ピラーでフィルター", pillar_opts, key="rules_pillar_filter")
    with fc2:
        conf_min = st.slider(
            "confidence 下限", min_value=0.50, max_value=0.95, value=0.50, step=0.01,
            key="rules_conf_filter",
        )
    with fc3:
        kw_search = st.text_input(
            "キーワード検索（部分一致）", placeholder="例: 護衛艦、定期修理、クラウド",
            key="rules_kw_search",
        )

    df_filtered = df_rules.copy()
    if sel_pillar != "（すべて）":
        df_filtered = df_filtered[df_filtered["ピラー"] == sel_pillar]
    df_filtered = df_filtered[df_filtered["confidence"] >= conf_min]
    if kw_search:
        df_filtered = df_filtered[
            df_filtered["キーワード一覧"].str.contains(kw_search, na=False)
        ]

    st.caption(f"{len(df_filtered)} / {len(df_rules)} ルール表示中")
    st.dataframe(
        df_filtered[["ピラー", "名称", "confidence", "org_filter", "キーワード一覧", "キーワード数"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "ピラー":       st.column_config.TextColumn(width="small"),
            "名称":         st.column_config.TextColumn(width="medium"),
            "confidence":   st.column_config.NumberColumn(format="%.2f", width="small"),
            "org_filter":   st.column_config.TextColumn(label="org_filter", width="small"),
            "キーワード一覧": st.column_config.TextColumn(width="large"),
            "キーワード数":  st.column_config.NumberColumn(format="%d", width="small"),
        },
    )

# ══════════════════════════════════════════════════════════════════════════════
# 5. 重要な分類判断ポイント
# ══════════════════════════════════════════════════════════════════════════════
st.header("重要な分類判断ポイント")

with st.expander("F-35・次期戦闘機の分類 — P43（機体取得）vs P82（開発費）", expanded=True):
    st.markdown("""
**原則：機体の「量産取得」はP43、「開発費」はP82。**

| 契約名パターン | 分類 | 根拠 |
|-------------|------|------|
| 「戦闘機（F-35A）の取得」 | **P43** (conf=0.85) | jigyou_review / 予算書で P43（電磁波・主要装備）に本計上 |
| 「次期戦闘機の開発」「GCAPの開発」 | **P82** (conf=0.90) | 予算書 p40「次期戦闘機の開発（1,023億）」は P82 本計上 |
| 「次期戦闘機」（単独） | **P43** (conf=0.88) | jigyou_review / hakusho で P43 本計上が多数 |
| 「F-15能力向上（量産改修）」 | **P43** (conf=0.85) | 改修キット取得 ≠ 施設強靭化（P73 でない） |
| 「高出力レーザ実証装置」 | **P82** (conf=0.83) | 「実証装置」キーワードで P82 確定 |

**ルール設計のポイント**：P82「次期戦闘機の開発」(0.90) > P43「次期戦闘機」(0.88) となるよう
conf を設定し、「開発」が明示された場合は P82 が必ず勝つようにしている。
""")

with st.expander("弾薬取得（P71）・維持整備（P72）・機体取得（P43）の分離", expanded=True):
    st.markdown("""
**同一装備品でも「何を調達するか」で分類が変わる。**

| 契約名パターン | 分類 | 判断根拠 |
|-------------|------|---------|
| 「ペトリオットミサイルの取得」 | **P71** (「ミサイル」0.70) | 弾薬・誘導弾の在庫補充 |
| 「ペトリオット定期修理」 | **P72** (conf=0.89) | 高優先ルール。P2「ペトリオット」(0.82) に勝つ |
| 「ペトリオットシステム一式の取得」 | **P2** (「ペトリオット」0.82) | システム本体の新規調達 |
| 「F-35A ALGS（自律型後方支援）」 | **P72** (conf=0.88) | 維持整備インフラ |
| 「AIM-9X サイドワインダー」 | **P71** (conf=0.78) | 短距離AAM ≒ 弾薬カテゴリ |
| 「AIM-120 AMRAAM」 | **P1** (conf=0.75) | スタンドオフAAM（射程優先） |

**ルールの競合解決例**：「SeaRAM 定期整備」→ P2「SeaRAM」(0.88) vs P72「定期修理」(0.89)
→ **P72 が勝つ**（維持整備として正しい）。
""")

with st.expander("クラウド・セキュリティ → P42（「借上」との混同に注意）", expanded=False):
    st.markdown("""
**クラウド・IaaS・PaaS・SaaS は P42（サイバー防衛）に分類する。**

```
P42 キーワード (conf=0.78):
  クラウド、IaaS、PaaS、SaaS、ゼロトラスト、DII、セキュリティ強化 ...
```

**注意点：「借上」キーワードのトラップ**

P84 汎用燃料・訓練（conf=0.62）の旧ルールには「借上」が含まれていた。
しかし「クラウド（SaaS/IaaS）の借上」「電算機の借上」は P42 であり、
「タクシー借上」が P84。**conf の差で P42（0.78）> P84（0.62）となるため
実際には正しく P42 が適用される**が、ルール追加時は conf の相対関係に注意。

参照：yosan FY2023 p21「中央クラウド整備（434億）・空自クラウド整備（756億）等」→ P42
""")

with st.expander("宇宙 → P41（P3「無人アセット」でなく領域横断に分類）", expanded=False):
    st.markdown("""
**「宇宙」キーワードは P41（宇宙領域把握）に分類する。P3（無人アセット）ではない。**

```
P41 キーワード (conf=0.82):
  宇宙、衛星、SSA、宇宙作戦、SDA、宇宙状況把握、コンステレーション ...
```

**混乱しやすいケース**：
- `SDA`（Space Domain Awareness）研究衛星 → P41（宇宙状況把握 = 領域横断）
- `SDA`（Space Development Agency, 米国）起源の研究 → P82（研究開発）の場合あり
- 宇宙航空研究開発機構との共同研究 → P82（研究開発 conf=0.75）vs P41（宇宙 conf=0.82）
  → **P41 が勝つ**（conf が高い）

**「即応型マルチミッション実証衛星」はなぜ fallback_atla？**
→ atla_research fallback（P82, conf=0.58）が適用されるが、確証が取れなかったため fallback_atla を維持。
""")

with st.expander("P83（基地対策・RDB専用）vs P73（施設強靱化）の分離", expanded=False):
    st.markdown("""
**「施設工事」は P73 が基本。ただし RDB（地方防衛局）の賃貸借・騒音対策は P83。**

```
P83 高優先ルール (conf=0.85, org_filter={"RDB"}):
  賃貸借、土地賃貸、移転補償、家屋防音、飛行場周辺

P83 全機関ルール (conf=0.75):
  騒音対策、防音工事、基地対策、基地周辺、住宅防音

P73 高信頼ルール (conf=0.68):
  地下化、えん体、格納庫強化、施設工事、建設工事 ...
```

**設計の意図**：
- 「賃貸借」は一般的な施設使用権（P73）と混同しやすいため、**RDB限定**で P83 (0.85) を適用。
- 全機関に「賃貸借」→ P73 を適用すると、GSDF の基地賃借料が P83 に誤分類される。
- P85（米軍再編）の「シュワブ」は conf=0.92（最高優先）でどのルールにも勝つ。
""")

# ══════════════════════════════════════════════════════════════════════════════
# 6. DB 実績
# ══════════════════════════════════════════════════════════════════════════════
st.header("現在のDB分類実績")

if not DB_PATH.exists():
    st.error(f"DBが見つかりません: {DB_PATH}")
    st.stop()


@st.cache_data(ttl=300)
def _load_pillar_stats() -> dict:
    with sqlite3.connect(DB_PATH) as con:
        df_method = pd.read_sql_query("""
            SELECT match_method, fiscal_year, COUNT(*) AS 件数
            FROM contract_pillar
            GROUP BY match_method, fiscal_year
            ORDER BY fiscal_year, 件数 DESC
        """, con)

        df_l1 = pd.read_sql_query("""
            SELECT cp.fiscal_year, cp.pillar_l1_code AS l1,
                   COUNT(*) AS 件数,
                   ROUND(SUM(c.contract_amount)/1e8) AS 金額_億
            FROM contract_pillar cp
            JOIN contracts c ON cp.contract_id = c.id
            WHERE cp.pillar_l1_code IS NOT NULL
            GROUP BY cp.fiscal_year, cp.pillar_l1_code
            ORDER BY cp.fiscal_year, cp.pillar_l1_code
        """, con)

        df_total = pd.read_sql_query("""
            SELECT fiscal_year,
                   COUNT(*) AS total,
                   SUM(CASE WHEN pillar_l1_code IS NOT NULL THEN 1 ELSE 0 END) AS classified
            FROM contract_pillar
            GROUP BY fiscal_year
            ORDER BY fiscal_year
        """, con)

    return {"method": df_method, "l1": df_l1, "total": df_total}


try:
    stats = _load_pillar_stats()

    # ── 分類カバレッジサマリー ────────────────────────────────────────────────
    st.subheader("FY別 分類カバレッジ")
    df_total = stats["total"]
    if df_total.empty:
        st.info("contract_pillar テーブルにデータがありません。")
    else:
        cols = st.columns(len(df_total))
        for col, (_, row) in zip(cols, df_total.iterrows()):
            fy = int(row["fiscal_year"])
            total = int(row["total"])
            cls = int(row["classified"])
            rate = cls / total * 100 if total else 0
            col.metric(
                f"FY{fy}",
                f"{cls:,}件 分類済み",
                delta=f"{rate:.1f}% ({total:,}件中)",
            )

    # ── 判定手法別件数 ─────────────────────────────────────────────────────────
    st.subheader("判定手法（match_method）別件数")
    df_method = stats["method"]
    if not df_method.empty:
        METHOD_LABEL = {
            "fuzzy_jigyou":      "Pass1：事業名fuzzy matching",
            "keyword_rule":      "Pass2：KEYWORD_RULES",
            "semantic_embedding": "Pass3：セマンティック埋め込み",
            "manual_correction": "手動修正",
            "unclassified":      "未分類",
        }
        pivot = df_method.pivot_table(
            index="match_method", columns="fiscal_year", values="件数", fill_value=0
        ).reset_index()
        pivot.insert(0, "手法", pivot["match_method"].map(lambda m: METHOD_LABEL.get(m, m)))
        pivot = pivot.drop(columns=["match_method"])
        st.dataframe(pivot, use_container_width=True, hide_index=True)

    # ── L1ピラー別件数・金額 ──────────────────────────────────────────────────
    st.subheader("ピラー別 件数・金額（L1分類）")
    df_l1 = stats["l1"]
    if not df_l1.empty:
        df_l1["ピラー"] = df_l1["l1"].map(lambda v: f"P{int(v)}" if pd.notna(v) else "未分類")
        df_l1["名称"] = df_l1["ピラー"].map(lambda p: PILLAR_NAME.get(p, ""))
        display_df = df_l1[["fiscal_year", "ピラー", "名称", "件数", "金額_億"]].rename(
            columns={"fiscal_year": "FY"}
        )
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "FY":     st.column_config.NumberColumn(format="FY%d", width="small"),
                "ピラー": st.column_config.TextColumn(width="small"),
                "名称":   st.column_config.TextColumn(width="medium"),
                "件数":   st.column_config.NumberColumn(format="%d"),
                "金額_億": st.column_config.NumberColumn(format="%.0f 億", width="small"),
            },
        )

except Exception as e:
    st.warning(f"DB 読み込みエラー: {e}")

# ── 参照スクリプト ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("関連スクリプト")
st.markdown("""
| スクリプト | 役割 | 実行方法 |
|-----------|------|---------|
| `dev/assign_pillar_fy2023.py` | FY単位の keyword+fuzzy 分類（KEYWORD_RULES の本体） | `python dev/assign_pillar_fy2023.py [--dry-run]` |
| `dev/assign_pillar_semantic.py` | セマンティック埋め込み（未分類への後処理） | `python dev/assign_pillar_semantic.py --threshold 0.80` |
| `dev/reclassify_p4_p7.py` | P4/P7 親ピラー→サブピラーへの再分類（実行済み） | — |
| `dashboard/pages/97_pillar_review.py` | 手動修正のビューワー（pillar_corrections_pending.csv への記録） | ダッシュボードから |

`TARGET_FY` を変更して `assign_pillar_fy2023.py` を実行すると FY2024/FY2025 にも展開できる。
""")
