"""gsdf_eadep / gsdf_nadep の FY2024 データを WARP 経由で収集。

ユーザー提供の WARP URL:
  - eadep: warp.ndl.go.jp/20240703/20240703084030 ... tyokai/honsyo/zuikeiitiran.html
  - nadep: warp.ndl.go.jp/20250702/20250702012911 ... nyuusatujouhou.html
            → 071kouhyou06/kouhyou06.htm (FY2024 結果ページ)
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urljoin

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import fetch  # noqa: E402
from parsers.pdf_table import (  # noqa: E402
    fy_from_date,
    parse_pdf_records,
)

DB_PATH = PROJECT_ROOT / "data" / "db" / "procurement.db"

INSERT_SQL = """
INSERT OR IGNORE INTO contracts (
    agency_id, agency_name, agency_category,
    fiscal_year, contract_type,
    contract_name, vendor_name, vendor_address, corporate_number,
    contract_amount, estimated_price, award_rate,
    bid_method, zuii_reason, contract_date, contract_officer,
    quantity, unit_measure,
    source_url, source_type
) VALUES (
    :agency_id, :agency_name, :agency_category,
    :fiscal_year, :contract_type,
    :contract_name, :vendor_name, :vendor_address, :corporate_number,
    :contract_amount, :estimated_price, :award_rate,
    :bid_method, :zuii_reason, :contract_date, :contract_officer,
    :quantity, :unit_measure,
    :source_url, :source_type
)
"""

REQUIRED_KEYS = [
    "contract_name", "vendor_name", "vendor_address", "corporate_number",
    "contract_amount", "estimated_price", "award_rate",
    "bid_method", "zuii_reason", "contract_date", "contract_officer",
    "quantity", "unit_measure", "contract_type",
]

TARGET_FYS = {2022, 2023, 2024, 2025}


# ── WARP プレフィックス（id_形式） ──────────────────────
def _warp_id(coll: str, ts: str, real_url: str) -> str:
    return f"https://warp.ndl.go.jp/{coll}/{ts}id_/{real_url}"


def _warp_index(coll: str, ts: str, page_url: str) -> list[str]:
    """WARP'd HTML を取得し、その中の PDF 相対 URL を WARP 化して返す。"""
    warp_url = _warp_id(coll, ts, page_url)
    data = fetch(warp_url, is_warp=True, use_cache=True, timeout=30)
    if not data:
        logger.warning(f"index取得失敗: {warp_url}")
        return []
    text = data.decode("cp932", errors="replace")
    if text.count("�") > 50:
        text = data.decode("utf-8", errors="replace")
    hrefs = re.findall(r'href=["\']([^"\'\s]+)["\']', text)

    out: list[str] = []
    for h in hrefs:
        if not h.lower().endswith(".pdf"):
            continue
        # 既に WARP の絶対 URL になっている (例: 様式 PDF)
        if h.startswith("/20") or h.startswith("https://warp.ndl.go.jp/"):
            full = h if h.startswith("http") else "https://warp.ndl.go.jp" + h
        else:
            # 相対 → real_url に urljoin → WARP 化
            real_pdf = urljoin(page_url, h)
            full = _warp_id(coll, ts, real_pdf)
        out.append(full)
    return out


# ── 収集対象定義 ──────────────────────────────────────
EADEP_AGENCY = {
    "agency_id": "gsdf_eadep",
    "agency_name": "関東補給処",
    "agency_category": "陸上自衛隊",
}
NADEP_AGENCY = {
    "agency_id": "gsdf_nadep",
    "agency_name": "北海道補給処",
    "agency_category": "陸上自衛隊",
}

EADEP_INDEXES = [
    ("20240703", "20240703084030",
     "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/honsyo/zuikeiitiran.html"),
]

# eadep live site URL patterns (FY2024/FY2025 月別 + 年度まとめ)
# R{ry}{kind}{mm}.pdf と R{ry:02d}{kind}456789101112123.pdf の2パターンを試行
_EADEP_HONSYO = "https://www.mod.go.jp/gsdf/eae/eadep/tyokai/honsyo/"
EADEP_LIVE_PATTERNS: list[str] = [
    f"{_EADEP_HONSYO}R{ry}{kind}{mm}.pdf"
    for ry in (6, 7) for mm in range(1, 13)
    for kind in ("zuikei", "ippan")
] + [
    f"{_EADEP_HONSYO}R{ry:02d}{kind}456789101112123.pdf"
    for ry in (6, 7) for kind in ("zuikei", "ippan")
]

NADEP_INDEXES = [
    # top-level index (FY2022/2023 など他年度リンクを探す)
    ("20250702", "20250702012911",
     "https://www.mod.go.jp/gsdf/nae/nadep/nyuusatujouhou/nyuusatujouhou.html"),
    # FY2024 結果ページ
    ("20250702", "20250702012911",
     "https://www.mod.go.jp/gsdf/nae/nadep/nyuusatujouhou/071kouhyou06/kouhyou06.htm"),
]


def _classify_url(url: str) -> tuple[str, str | None]:
    """URL から (contract_type, bid_method 既定) を推定。"""
    u = url.lower()
    fn = u.rsplit("/", 1)[-1]
    if "zuikei" in u or "zuii" in fn or "/zui" in u:
        return ("随意契約", "随意契約")
    if "ippan" in u or "kouhyou" in u or "kyousou" in u:
        return ("一般競争", "一般競争入札")
    return ("一般競争", "一般競争入札")


def _enrich(rec: dict, *, agency: dict, source_url: str) -> dict:
    rec.update({
        "agency_id": agency["agency_id"],
        "agency_name": agency["agency_name"],
        "agency_category": agency["agency_category"],
        "source_url": source_url,
        "source_type": "pdf_warp",
    })
    ctype, bid_default = _classify_url(source_url)
    if not rec.get("contract_type"):
        rec["contract_type"] = ctype
    if not rec.get("bid_method"):
        rec["bid_method"] = bid_default
    for k in REQUIRED_KEYS:
        rec.setdefault(k, None)
    return rec


def collect_target(agency: dict, indexes: list[tuple[str, str, str]]) -> list[dict]:
    all_records: list[dict] = []
    for coll, ts, page_url in indexes:
        logger.info(f"  index: {page_url}")
        pdf_urls = _warp_index(coll, ts, page_url)
        # 重複除去
        pdf_urls = list(dict.fromkeys(pdf_urls))
        # 様式系（フォーム）を除外: kakusyuyosiki, mitumorisho, nyusatusho, nilyuusatu,
        #                           nennkann, kyososankato, sagyo, zyuryo, seikyu, ginko
        # 規則系（ルール）を除外: kisoku, kokoroe, hyoujunnkeiyaku, ouinn, ocjit
        skip_kw = (
            "kakusyuyosiki", "mitumori", "nyusatusho", "nilyuusatu",
            "nennkann", "kyososankato", "sagyo", "zyuryo", "seikyusyo",
            "ginkohurikomi", "kakusyu", "hyoujunnkeiyaku", "kokoroe",
            "ouinn", "ocjit", "ouin-osirase", "kisoku/", "/080kisoku/",
            "yoteikouji", "/050yoteikouji/", "open0", "oc0", "OC02", "OC03",
            "/oc/", "yousiki",
        )
        filtered = [u for u in pdf_urls if not any(kw.lower() in u.lower() for kw in skip_kw)]
        logger.info(f"    PDFs: {len(pdf_urls)} → 除外後 {len(filtered)}")

        for pdf_url in filtered:
            data = fetch(pdf_url, is_warp=True, use_cache=True, timeout=30)
            if not data:
                logger.debug(f"      miss: {pdf_url}")
                continue
            try:
                recs = list(parse_pdf_records(data, target_fys=TARGET_FYS))
            except Exception as e:
                logger.warning(f"      parse err: {pdf_url} - {e}")
                continue
            kept = []
            for rec in recs:
                cd_fy = fy_from_date(rec.get("contract_date"))
                if cd_fy is None or cd_fy not in TARGET_FYS:
                    continue
                rec["fiscal_year"] = cd_fy
                kept.append(_enrich(rec, agency=agency, source_url=pdf_url))
            if kept:
                fname = pdf_url.rsplit("/", 1)[-1][:40]
                logger.info(f"      [{fname}] {len(kept)}件")
            all_records.extend(kept)
    return all_records


def _collect_eadep_live() -> list[dict]:
    """eadep live site の月別/年度まとめ PDF を試行収集（404 スキップ）。"""
    recs_all: list[dict] = []
    for url in EADEP_LIVE_PATTERNS:
        data = fetch(url, is_warp=False, use_cache=True, timeout=20)
        if not data:
            continue
        try:
            recs = list(parse_pdf_records(data, target_fys=TARGET_FYS))
        except Exception as e:
            logger.warning(f"      live parse err: {url} - {e}")
            continue
        kept = []
        for rec in recs:
            cd_fy = fy_from_date(rec.get("contract_date"))
            if cd_fy is None or cd_fy not in TARGET_FYS:
                continue
            rec["fiscal_year"] = cd_fy
            kept.append(_enrich(rec, agency=EADEP_AGENCY, source_url=url))
        if kept:
            fname = url.rsplit("/", 1)[-1]
            logger.info(f"      [live:{fname}] {len(kept)}件")
        recs_all.extend(kept)
    return recs_all


def main(dry_run: bool = False) -> None:
    logger.info("=== gsdf_eadep WARP 収集 ===")
    eadep_recs = collect_target(EADEP_AGENCY, EADEP_INDEXES)
    logger.info("=== gsdf_eadep live site 補完 ===")
    eadep_live = _collect_eadep_live()
    eadep_recs = eadep_recs + eadep_live
    logger.info(f"  → eadep: {len(eadep_recs)}件 (WARP+live)")

    logger.info("=== gsdf_nadep WARP 収集 ===")
    nadep_recs = collect_target(NADEP_AGENCY, NADEP_INDEXES)
    logger.info(f"  → nadep: {len(nadep_recs)}件")

    all_recs = eadep_recs + nadep_recs
    logger.info(f"\n合計レコード: {len(all_recs)}件")

    if dry_run:
        from collections import Counter
        for label, recs in (("eadep", eadep_recs), ("nadep", nadep_recs)):
            fy_cnt: Counter = Counter(r.get("fiscal_year") for r in recs)
            print(f"  {label} FY内訳: {dict(fy_cnt)}")
        return

    inserted = 0
    duplicates = 0
    skipped = 0
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for rec in all_recs:
            if not rec.get("fiscal_year"):
                skipped += 1
                continue
            try:
                cur.execute(INSERT_SQL, rec)
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.commit()
    logger.info(
        f"\nDB投入: 新規 {inserted}件 / 重複 {duplicates}件 / スキップ {skipped}件"
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    main(dry_run=args.dry_run)
