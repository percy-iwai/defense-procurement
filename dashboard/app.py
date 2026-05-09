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

from _db import connect_with_pillar

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

_ALL_FYS = [2022, 2023, 2024, 2025]  # 収録FY一覧

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
def _load_equipment_map() -> pd.DataFrame:
    """contract_id → 装備品名・解説URL のマッピング。

    複数 equipment にマッチする契約は最高 confidence を採用。SQLite の
    MIN/MAX bare-column 規約により MAX(confidence) と同じ行の equipment_id を返す。
    解説URLは 3層優先順位：
      1. ref_url_official   防衛省公式 装備品個別ページ（最具体）
      2. ref_url_wikipedia  Wikipedia 記事
      3. ref_url_hakusho    防衛白書の品目紹介ページ（フォールバック）
    """
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """SELECT ce.contract_id,
                      em.name_ja AS equipment_name,
                      COALESCE(em.ref_url_official, em.ref_url_wikipedia, em.ref_url_hakusho) AS ref_url
               FROM (
                   SELECT contract_id, equipment_id, MAX(confidence) AS confidence
                   FROM contract_equipment
                   GROUP BY contract_id
               ) ce
               LEFT JOIN equipment_master em ON ce.equipment_id = em.equipment_id""",
            conn,
        )


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


_REQ_ORG_LABELS = {
    "MSDF":     "海上自衛隊",
    "GSDF":     "陸上自衛隊",
    "ASDF":     "航空自衛隊",
    "RDB":      "地方防衛局",
    "JS":       "統合幕僚監部",
    "NAIKYOKU": "内部部局",
    "DIH":      "情報本部",
    "NDMC":     "防衛医科大学校",
    "NDA":      "防衛大学校",
    "KANSATSU": "監察本部",
    "NIDS":     "防衛研究所",
}

@st.cache_data(ttl=300)
def _load_requesting_org(fiscal_years: tuple[int, ...]) -> pd.DataFrame:
    placeholders = ",".join("?" * len(fiscal_years))
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            f"""SELECT
                 CASE
                   WHEN cro.requesting_org = 'ATLA' AND cro.match_source = 'fallback_atla'
                     THEN '要求元未解決（中央調達）'
                   WHEN cro.requesting_org = 'ATLA'
                     THEN '装備庁（研究所等）'
                   ELSE cro.requesting_org
                 END AS display_org,
                 COUNT(*) AS cnt,
                 COALESCE(SUM(c.contract_amount), 0) / 1e8 AS oku
               FROM contracts c
               JOIN contract_requesting_org cro ON c.rowid = cro.contract_id
               WHERE c.fiscal_year IN ({placeholders})
               GROUP BY display_org
               ORDER BY SUM(c.contract_amount) DESC""",
            conn,
            params=fiscal_years,
        )
    df["org_label"] = df["display_org"].map(_REQ_ORG_LABELS).fillna(df["display_org"])
    return df


@st.cache_data(ttl=600)
def _load_pillar_jigyou_names() -> dict[str, list[int]]:
    """jigyou_name → L1 pillar_id リストのマッピング。defense_pillar.db がない場合は空dict。"""
    try:
        with connect_with_pillar() as conn:
            df = pd.read_sql_query(
                """
                SELECT j.jigyou_name,
                       COALESCE(p.parent_id, j.pillar_id) AS l1_pillar_id
                FROM pillar.defense_pillar_jigyou j
                LEFT JOIN pillar.defense_pillar_master p ON p.pillar_id = j.pillar_id
                WHERE j.jigyou_name IS NOT NULL AND LENGTH(j.jigyou_name) >= 4
                """,
                conn,
            )
        result: dict[str, list[int]] = {}
        for _, row in df.iterrows():
            name = str(row["jigyou_name"]).strip()
            pid = int(row["l1_pillar_id"])
            if name not in result:
                result[name] = []
            if pid not in result[name]:
                result[name].append(pid)
        return result
    except Exception:
        return {}


def _get_pillar_codes(contract_name: str, pillar_map: dict[str, list[int]]) -> list[int]:
    if not contract_name or not pillar_map:
        return []
    matched: set[int] = set()
    for jname, pids in pillar_map.items():
        if jname in contract_name:
            matched.update(pids)
    return sorted(matched)


@st.cache_data(ttl=300)
def _load_top20_contracts(fiscal_years: tuple[int, ...], requesting_org: str) -> pd.DataFrame:
    """要求元別 金額上位TOP20契約（装備品情報込み）。"""
    placeholders = ",".join("?" * len(fiscal_years))
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            f"""
            SELECT c.rowid AS contract_id, c.contract_name, c.vendor_name,
                   c.contract_amount, c.agency_name, c.contract_date,
                   cro.match_source, cro.confidence,
                   em.name_ja AS equipment_name,
                   COALESCE(em.ref_url_official, em.ref_url_wikipedia, em.ref_url_hakusho) AS ref_url
            FROM contracts c
            JOIN contract_requesting_org cro ON c.rowid = cro.contract_id
            LEFT JOIN (
                SELECT contract_id, equipment_id, MAX(confidence) AS max_conf
                FROM contract_equipment
                GROUP BY contract_id
            ) best_ce ON c.rowid = best_ce.contract_id
            LEFT JOIN equipment_master em ON best_ce.equipment_id = em.equipment_id
            WHERE c.fiscal_year IN ({placeholders})
              AND CASE
                    WHEN cro.requesting_org = 'ATLA' AND cro.match_source = 'fallback_atla'
                      THEN '要求元未解決（中央調達）'
                    WHEN cro.requesting_org = 'ATLA'
                      THEN '装備庁（研究所等）'
                    ELSE cro.requesting_org
                  END = ?
            ORDER BY c.contract_amount DESC NULLS LAST
            LIMIT 20
            """,
            conn,
            params=(*fiscal_years, requesting_org),
        )


@st.dialog("要求元ドリルダウン", width="large")
def show_requesting_org_drilldown(fiscal_years: tuple[int, ...], requesting_org: str, label: str) -> None:
    _fys_str = " / ".join(f"FY{y}" for y in fiscal_years)
    st.subheader(f"要求元: {label}（{_fys_str}） — 金額TOP20")

    placeholders = ",".join("?" * len(fiscal_years))
    with sqlite3.connect(DB_PATH) as conn:
        total_row = conn.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(c.contract_amount), 0)
               FROM contracts c
               JOIN contract_requesting_org cro ON c.rowid = cro.contract_id
               WHERE c.fiscal_year IN ({placeholders})
                 AND CASE
                       WHEN cro.requesting_org = 'ATLA' AND cro.match_source = 'fallback_atla'
                         THEN '要求元未解決（中央調達）'
                       WHEN cro.requesting_org = 'ATLA'
                         THEN '装備庁（研究所等）'
                       ELSE cro.requesting_org
                     END = ?""",
            (*fiscal_years, requesting_org),
        ).fetchone()
    total_cnt, total_amt = total_row
    st.caption(f"全 {total_cnt:,} 件 / 総額 {total_amt / 1e8:,.1f} 億円 — 金額上位TOP20を表示")

    top20 = _load_top20_contracts(fiscal_years, requesting_org)
    if top20.empty:
        st.info("該当データなし")
        return

    pillar_map = _load_pillar_jigyou_names()

    rows_html: list[str] = []
    for rank, (_, row) in enumerate(top20.iterrows(), 1):
        cname   = str(row.get("contract_name") or "")
        vendor  = str(row.get("vendor_name") or "—")
        amt_val = row.get("contract_amount")
        amt     = f"{amt_val / 1e8:.1f}" if pd.notna(amt_val) else "—"
        agency  = str(row.get("agency_name") or "")
        date_raw = str(row.get("contract_date") or "")
        date_str = (
            f"{date_raw[:4]}/{date_raw[4:6]}/{date_raw[6:]}"
            if len(date_raw) == 8 else date_raw
        )
        eq_name = str(row.get("equipment_name") or "")
        ref_url = str(row.get("ref_url") or "")

        if eq_name and ref_url:
            eq_cell = (
                f'<a href="{ref_url}" target="_blank" style="color:#7c83fd">'
                f'📖 {eq_name[:18]}</a>'
            )
        elif ref_url:
            eq_cell = f'<a href="{ref_url}" target="_blank" style="color:#7c83fd">📖</a>'
        elif eq_name:
            eq_cell = eq_name[:20]
        else:
            eq_cell = "—"

        pillar_ids = _get_pillar_codes(cname, pillar_map)
        badge_html = " ".join(
            f'<span style="background:#313244;padding:1px 6px;border-radius:4px;'
            f'font-size:0.72rem;color:#cdd6f4">P{pid}</span>'
            for pid in pillar_ids[:3]
        )

        cname_disp  = (cname[:50]  + "…") if len(cname)  > 50 else cname
        vendor_disp = (vendor[:18] + "…") if len(vendor) > 18 else vendor
        agency_disp = (agency[:16] + "…") if len(agency) > 16 else agency

        rows_html.append(
            f'<tr style="border-bottom:1px solid #313244">'
            f'<td style="text-align:center;color:#bac2de;padding:4px 6px">{rank}</td>'
            f'<td style="padding:4px 6px" title="{cname}">{cname_disp}</td>'
            f'<td style="padding:4px 6px;color:#bac2de" title="{vendor}">{vendor_disp}</td>'
            f'<td style="padding:4px 6px;text-align:right;font-weight:600">{amt}</td>'
            f'<td style="padding:4px 6px;font-size:0.78rem;color:#bac2de" title="{agency}">{agency_disp}</td>'
            f'<td style="padding:4px 6px;font-size:0.78rem;color:#bac2de">{date_str}</td>'
            f'<td style="padding:4px 6px;font-size:0.78rem">{eq_cell}</td>'
            f'<td style="padding:4px 6px">{badge_html}</td>'
            f'</tr>'
        )

    html = (
        '<div style="overflow-x:auto">'
        '<table style="border-collapse:collapse;width:100%;font-size:0.82rem;color:#cdd6f4">'
        '<thead>'
        '<tr style="border-bottom:2px solid #45475a;color:#bac2de;background:#1e1e2e">'
        '<th style="padding:4px 6px">#</th>'
        '<th style="padding:4px 6px;text-align:left">契約名</th>'
        '<th style="padding:4px 6px;text-align:left">受注企業</th>'
        '<th style="padding:4px 6px;text-align:right">金額(億)</th>'
        '<th style="padding:4px 6px;text-align:left">機関</th>'
        '<th style="padding:4px 6px;text-align:left">契約日</th>'
        '<th style="padding:4px 6px;text-align:left">装備品</th>'
        '<th style="padding:4px 6px;text-align:left">ピラー</th>'
        '</tr>'
        '</thead>'
        '<tbody>'
        + "".join(rows_html)
        + '</tbody></table></div>'
    )
    st.markdown(html, unsafe_allow_html=True)
    st.caption(
        "📖 リンクは装備品解説（公式・Wikipedia・防衛白書）。"
        "ピラーはP{n}形式（防衛力強化7本柱）。"
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
    eq_map = _load_equipment_map()
    view = (
        sub[["id", "fiscal_year", "contract_date", "agency_name",
             "contract_name", "contract_amount", "bid_display",
             "agency_category", "source_url"]].copy()
        .merge(eq_map, left_on="id", right_on="contract_id", how="left")
        .drop(columns=["id", "contract_id"])
    )
    view = view.sort_values("contract_amount", ascending=False, na_position="last")
    view["contract_amount"] = view["contract_amount"].map(
        lambda v: f"{int(v):,}" if pd.notna(v) else "-"
    )
    view = view.rename(columns={
        "fiscal_year": "年度", "contract_date": "契約日",
        "agency_name": "機関", "contract_name": "契約名",
        "contract_amount": "金額(円)", "bid_display": "入札方式",
        "agency_category": "カテゴリ", "source_url": "出典URL",
        "equipment_name": "装備品", "ref_url": "解説",
    })
    st.dataframe(
        view, use_container_width=True, hide_index=True, height=480,
        column_config={
            "装備品": st.column_config.TextColumn(width="small"),
            "解説":   st.column_config.LinkColumn(width="small", display_text="📖"),
        },
    )


def main():
    # ── ダイアログ管理: 1スクリプトラン内で1つだけ開く ──────────────────
    # 複数ウィジェットが同時にトリガーした場合、後のセクション（最終書き込み）が優先。
    # 実際の dialog 呼び出しは main() 末尾の dispatch ブロックで一括処理する。
    _dlg_type: str | None = None
    _dlg_args: dict = {}

    # ── グローバルFYフィルター読み込み ────────────────────────────────────
    _active_fys: list[int] = list(st.session_state.get("global_fy") or _ALL_FYS)
    _is_filtered = set(_active_fys) != set(_ALL_FYS)

    # ════════════════════════════════════════════════════════════════════
    # ヘッダー
    # ════════════════════════════════════════════════════════════════════
    st.title("🛡️ 防衛省・自衛隊 調達情報ダッシュボード")

    with st.spinner("データ読み込み中..."):
        df_all = _load_contracts()
        budget = _load_budget()

    # グローバルFYフィルタを適用（変更がある場合のみコピーして絞り込む）
    if _is_filtered:
        df = df_all[df_all["fiscal_year"].isin(_active_fys)].copy()
        _fy_label = " / ".join(f"FY{y}" for y in sorted(_active_fys))
        st.info(f"📅 年度フィルター適用中: **{_fy_label}**（サイドバーで変更できます）", icon="📅")
    else:
        df = df_all

    total_records  = len(df)

    # FY別集計
    fy_stats: dict[int, dict] = {}
    for fy in [2022, 2023, 2024, 2025]:
        cnt = int((df["fiscal_year"] == fy).sum())
        amt = float(df.loc[df["fiscal_year"] == fy, "amount_oku"].sum())
        base = _effective_base(fy)
        cov = amt / base * 100 if base else None
        fy_stats[fy] = {"count": cnt, "amount": amt, "base": base, "coverage": cov}

    # KPI3/4 動的ラベル・数値（グローバルフィルター連動）
    if len(_active_fys) == 1:
        _kpi_fy     = _active_fys[0]
        _kpi_label  = f"FY{_kpi_fy}"
        _kpi_amount = fy_stats[_kpi_fy]["amount"]
        _kpi_base   = _effective_base(_kpi_fy) or 0
        _kpi_cov    = fy_stats[_kpi_fy]["coverage"] or 0.0
    else:
        _kpi_label  = "選択期間"
        _kpi_amount = sum(fy_stats[fy]["amount"] for fy in _active_fys)
        _kpi_base   = sum((_effective_base(fy) or 0) for fy in _active_fys)
        _kpi_cov    = _kpi_amount / _kpi_base * 100 if _kpi_base else 0.0

    _period_label = (
        f"FY{_active_fys[0]}" if len(_active_fys) == 1
        else f"FY{min(_active_fys)}〜FY{max(_active_fys)}" if _active_fys
        else "FY2022〜FY2025"
    )
    st.caption(
        f"出典: 防衛省・自衛隊 各機関 公開調達情報（財計第2017号）"
        f"　|　収録期間: {_period_label}　|　表示: {total_records:,}件 /"
        f" {df['amount_oku'].sum():,.0f}億円"
        f"　|　最終更新: 2026-05-03"
    )

    # ── KPI ─────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("総収録件数",               f"{total_records:,} 件")
    k2.metric("総収録金額",               f"{df['amount_oku'].sum():,.0f} 億円")
    k3.metric(f"{_kpi_label} 収録額",     f"{_kpi_amount:,.0f} 億円")
    k4.metric(f"{_kpi_label} カバレッジ", f"{_kpi_cov:.1f}%",
              delta=f"{_kpi_amount:,.0f} / {_kpi_base:,}億",
              help="DB額 ÷ 実質契約対象母数（非契約系・不用額控除後）")
    k5.metric("収録機関数",               f"{df['agency_id'].nunique():,} 機関")

    st.divider()

    # ── チャート 2列 ─────────────────────────────────────────────────
    ch1, ch2 = st.columns([3, 2])

    with ch1:
        st.subheader("📈 年度別トレンド（全年度）")
        by_fy = (
            df_all.groupby("fiscal_year", as_index=False)
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
            xaxis=dict(title="年度", dtick=1, fixedrange=True),
            yaxis=dict(title="総額(億円)", fixedrange=True),
            yaxis2=dict(title="件数", overlaying="y", side="right", showgrid=False, fixedrange=True),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig_trend, use_container_width=True, config={"displayModeBar": False})
        st.caption("※FY2025 は3月分が未公開につき未収録（暫定値）。")

    with ch2:
        _sun_fy_label = " / ".join(f"FY{y}" for y in sorted(_active_fys)) if _is_filtered else "全FY"
        st.subheader(f"🏛️ 組織別（{_sun_fy_label}）")
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
                _dlg_type = "sunburst"
                _dlg_args = {"sub": filt, "title": " > ".join(title_parts)}

    st.divider()

    # ── 要求元別 調達規模 ───────────────────────────────────────────
    st.subheader("🎯 要求元別 調達規模（簡易分類）")

    _req_fys = tuple(sorted(_active_fys))
    req_df = _load_requesting_org(_req_fys)
    if req_df.empty:
        st.info("要求元データがありません。")
    else:
        label_to_display  = dict(zip(req_df["org_label"], req_df["display_org"]))
        display_to_label  = dict(zip(req_df["display_org"], req_df["org_label"]))
        cnt_by_display    = dict(zip(req_df["display_org"], req_df["cnt"]))

        # 円グラフ（全幅）
        fig_pie = px.pie(
            req_df,
            values="oku", names="org_label",
            template=PLOT_TEMPLATE, height=440,
            color_discrete_sequence=COLOR_SEQ,
            hole=0.35,
        )
        fig_pie.update_traces(
            texttemplate="%{label}<br>%{percent:.0%}",
            hovertemplate="%{label}<br>%{value:,.0f}億円 (%{percent:.1%})<extra></extra>",
            textposition="inside",
        )
        fig_pie.update_layout(
            showlegend=True,
            legend=dict(orientation="v", yanchor="middle", y=0.5, x=1.02),
            margin=dict(l=0, r=0, t=20, b=0),
        )
        sel_pie = st.plotly_chart(
            fig_pie, use_container_width=True,
            on_select="rerun", key="req_pie_chart",
            config={"displayModeBar": False},
        )

        # セレクトボックス（円グラフクリックの代替）
        st.caption("下のセレクトボックスで要求元を選択するとTOP20を表示します。")
        org_box_opts = [""] + req_df["display_org"].tolist()
        sel_box = st.selectbox(
            "要求元を選択（TOP20表示）",
            org_box_opts,
            key="req_org_box",
            format_func=lambda x: (
                "（選択してください）" if x == ""
                else f"{display_to_label.get(x, x)} （{cnt_by_display.get(x, 0):,}件）"
            ),
        )

        # ドリルダウン検出（ダイアログは main() 末尾で一括 dispatch）
        # selectbox は一度表示した値を _req_box_acked に記録し、再トリガーを防ぐ
        _req_box_acked = st.session_state.get("_req_box_acked", "")
        _box_is_new = bool(sel_box) and sel_box != _req_box_acked
        if not sel_box:
            st.session_state["_req_box_acked"] = ""

        pts_pie = sel_pie.get("selection", {}).get("points", []) if sel_pie else []
        _last_pie_sel = st.session_state.get("_req_org_selected", "")
        if pts_pie:
            clicked_label   = pts_pie[0].get("label", "")
            clicked_display = label_to_display.get(clicked_label, "")
            if clicked_display and clicked_display != _last_pie_sel:
                st.session_state["_req_org_selected"] = clicked_display
                _dlg_type = "requesting_org"
                _dlg_args = {"fys": _req_fys, "org": clicked_display, "label": clicked_label}
        else:
            if _last_pie_sel:
                st.session_state["_req_org_selected"] = ""
        if _box_is_new:
            st.session_state["_req_box_acked"] = sel_box
            _dlg_type = "requesting_org"
            _dlg_args = {
                "fys": _req_fys, "org": sel_box,
                "label": display_to_label.get(sel_box, sel_box),
            }

    total_req = int(req_df["cnt"].sum()) if not req_df.empty else 0
    total_oku = float(req_df["oku"].sum()) if not req_df.empty else 0.0
    _req_fys_label = " / ".join(f"FY{y}" for y in sorted(_req_fys))
    st.caption(
        f"{_req_fys_label} 収録 {total_req:,}件 / {total_oku:,.0f}億円のマッピング結果。"
        f"※ 要求元の分類方法: "
        f"地方調達（陸自・海自・空自・防衛局等）は調達機関から自動判定（confidence=1.0）。"
        f"中央調達（防衛装備庁）は調達予定品目表の品目名と契約名を突合して要求元を特定。"
        f"突合不能分は担当官室・契約月・ベンダー実績・装備品辞書から推定（confidence=0.3〜0.7）。"
    )

    st.divider()

    # ── 受注企業 Top30 ──────────────────────────────────────────────
    st.subheader("🏭 受注企業 Top30")
    df_v = df
    scope_label = " / ".join(f"FY{y}" for y in sorted(_active_fys)) if _is_filtered else "全年度"

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
            on_select="rerun", key="vendor_chart",
        )
        pts = sel.get("selection", {}).get("points", []) if sel else []
        if pts:
            vendor = pts[0].get("y") or (pts[0].get("customdata") or [None])[0]
            if vendor:
                _dlg_type = "vendor"
                _dlg_args = {
                    "sub": df_v[df_v["vendor_norm"] == vendor],
                    "title": f"受注企業: {vendor}（{scope_label}）",
                }
        st.caption("バー（または企業名）をクリックすると、その企業の契約一覧をモーダル表示します。")

    st.divider()

    # ── 大型契約 Top30（金額順）────────────────────────────────────────
    st.subheader("🏆 大型契約 Top30")
    df_big = df

    big_top = (
        df_big.dropna(subset=["contract_amount"])
        .nlargest(30, "contract_amount")
        [["id", "contract_name", "vendor_norm", "amount_oku",
          "agency_name", "fiscal_year", "contract_date"]]
        .reset_index(drop=True)
    )
    eq_map = _load_equipment_map()
    big_top = (
        big_top.merge(eq_map, left_on="id", right_on="contract_id", how="left")
        .drop(columns=["id", "contract_id"])
        .rename(columns={
            "contract_name":  "契約名",
            "vendor_norm":    "受注企業",
            "amount_oku":     "金額(億円)",
            "agency_name":    "機関",
            "fiscal_year":    "年度",
            "contract_date":  "契約日",
            "equipment_name": "装備品",
            "ref_url":        "解説",
        })
    )

    if big_top.empty:
        st.info("大型契約データがありません。")
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
                "装備品":    st.column_config.TextColumn(width="small"),
                "解説":      st.column_config.LinkColumn(width="small", display_text="📖"),
            },
        )
        st.caption("契約金額（円）降順。NULL（単価契約等）は除外。")


    # ── ダイアログ dispatch（1ラン1つ保証） ──────────────────────────────
    if _dlg_type == "sunburst":
        show_sunburst_drilldown(_dlg_args["sub"], _dlg_args["title"])
    elif _dlg_type == "requesting_org":
        show_requesting_org_drilldown(_dlg_args["fys"], _dlg_args["org"], _dlg_args["label"])
    elif _dlg_type == "vendor":
        show_vendor_drilldown(_dlg_args["sub"], _dlg_args["title"])


# ── グローバル年度フィルター（全ページ共通サイドバー）──────────────────────
with st.sidebar:
    st.divider()
    st.markdown("**📅 年度フィルター**")
    st.multiselect(
        "表示年度",
        options=_ALL_FYS,
        default=[2024],
        format_func=lambda y: f"FY{y}",
        key="global_fy",
        label_visibility="collapsed",
    )
    _gfy_state = st.session_state.get("global_fy", _ALL_FYS)
    if not _gfy_state or set(_gfy_state) == set(_ALL_FYS):
        st.caption("全年度（フィルタなし）")
    else:
        st.caption(f"選択中: {' / '.join(f'FY{y}' for y in sorted(_gfy_state))}")

pg = st.navigation(
    {
        "": [
            st.Page(main, title="トップページ", icon="🏠", default=True),
            st.Page("pages/4_search.py", title="検索", icon="🔎"),
        ],
        "分析": [
            st.Page("pages/96_low_price_bid.py", title="低価格入札分析", icon="⚠️"),
        ],
        "その他（参考）": [
            st.Page("pages/3_jigyou_review.py", title="行政事業レビュー", icon="🔍"),
            st.Page("pages/5_requesting_org_methodology.py", title="要求元判定ロジック", icon="🔬"),
            st.Page("pages/6_pillar_breakdown.py", title="7本柱ブレークダウン", icon="🏛️"),
            st.Page("pages/97_equipment_glossary.py", title="装備品解説図鑑", icon="🔭"),
            st.Page("pages/98_coverage.py", title="収録状況・カバレッジ", icon="📊"),
            st.Page("pages/99_url_matrix.py", title="URLマトリクス", icon="🗂️"),
        ],
    }
)
pg.run()
