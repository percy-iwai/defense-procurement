"""33機関の site_url を正しい掲載ページ URL に修正する。

Task 1: MSDF bukei インデックスから keiyakukeka_main_{code}.html 取得
Task 2: ATLA ny_*_ichi.html パターンで URL確認（HEAD）
Task 3: GSDF/RDB/ASDF トップページから調達情報リンク探索
"""
from __future__ import annotations
import re, sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
from pathlib import Path

import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL_DB = PROJECT_ROOT / "data" / "db" / "url_matrix.db"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; defense-procurement-research/1.0)"
})
TIMEOUT = 15


def decode_html(content: bytes) -> str:
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return content.decode(enc)
        except Exception:
            pass
    return content.decode("utf-8", errors="replace")


# =========================================================
# Task 1: MSDF bukei index
# =========================================================
MSDF_IDX = "https://www.mod.go.jp/msdf/bukei/keiyakukeka_idx.html"
MSDF_BASE = "https://www.mod.go.jp/msdf/bukei/"

# 一部コードはagency_idと一致しない（zd → msdf_asd）
MSDF_CODE_TO_AGENCY: dict[str, str] = {
    "zd": "msdf_asd",
}

def fetch_msdf_urls() -> dict[str, str]:
    """keiyakukeka_idx.html から {agency_id: url} を返す。"""
    try:
        r = SESSION.get(MSDF_IDX, timeout=TIMEOUT)
        html = decode_html(r.content)
        # 実際のリンク形式: href="d0/keiyakukeka_main_D0.html"
        codes = re.findall(r'href="(\w+)/keiyakukeka_main_\w+\.html"', html, re.IGNORECASE)
        result = {}
        for code in set(codes):
            code_lower = code.lower()
            agency_id = MSDF_CODE_TO_AGENCY.get(code_lower, f"msdf_{code_lower}")
            result[agency_id] = f"{MSDF_BASE}{code_lower}/keiyakukeka_main_{code_lower.upper()}.html"
        logger.info(f"[Task1] MSCDインデックス: {len(result)} コード取得")
        return result
    except Exception as e:
        logger.error(f"[Task1] MSDF index 取得失敗: {e}")
        return {}


# =========================================================
# Task 2: ATLA ny_*_ichi.html
# =========================================================
ATLA_BASE = "https://www.mod.go.jp/atla/data/info/"

# 各 agency_id → 候補 URL リスト（先に 200 が返ったものを採用）
ATLA_CANDIDATES: dict[str, list[str]] = {
    "atla_shimokita": [
        ATLA_BASE + "ny_shimokita/ny_shimokita_ichi.html",
        ATLA_BASE + "ny_shimokita/pdf_ichiran/",
    ],
    "atla_chitose": [
        ATLA_BASE + "ny_chitose/ny_chitose_ichi.html",
        ATLA_BASE + "ny_chitose/pdf_ichiran/",
    ],
    "atla_gifu": [
        ATLA_BASE + "ny_gifu/ny_gifu_ichi.html",
        ATLA_BASE + "ny_gifu/pdf_ichiran/",
    ],
    "atla_koukuu": [
        ATLA_BASE + "ny_koukuu/ny_koukuu_ichi.html",
        ATLA_BASE + "ny_koukuu/pdf_ichiran/",
        ATLA_BASE + "ny_kenkyu_koukuu/ny_koukuu_ichi.html",
        ATLA_BASE + "ny_kenkyu_koukuu/pdf_ichiran/",
    ],
    "atla_riku": [
        ATLA_BASE + "ny_kenkyu_riku/ny_riku_ichi.html",
        ATLA_BASE + "ny_kenkyu_riku/pdf_ichiran/",
        ATLA_BASE + "ny_riku/ny_riku_ichi.html",
        ATLA_BASE + "ny_riku/pdf_ichiran/",
    ],
    "atla_kantei": [
        ATLA_BASE + "ny_kenkyu_kantei/ny_kantei_ichi.html",
        ATLA_BASE + "ny_kenkyu_kantei/pdf_ichiran/",
        ATLA_BASE + "ny_kantei/ny_kantei_ichi.html",
        ATLA_BASE + "ny_kantei/pdf_ichiran/",
    ],
    "atla_shinsedai": [
        ATLA_BASE + "ny_kenkyu_shinsedai/ny_shinsedai_ichi.html",
        ATLA_BASE + "ny_kenkyu_shinsedai/pdf_ichiran/",
        ATLA_BASE + "ny_shinsedai/ny_shinsedai_ichi.html",
        ATLA_BASE + "ny_shinsedai/pdf_ichiran/",
    ],
    "atla_disti": [
        ATLA_BASE + "ny_disti/ny_kenkyu_disti_ichi.html",
        ATLA_BASE + "ny_disti/ny_disti_ichi.html",
    ],
    "atla_kanbo": [
        ATLA_BASE + "ny_honbu/ny_honbu_ichi.html",
        ATLA_BASE + "ny_honbu/pdf_ichiran/",
    ],
}


def check_atla(agency_id: str, urls: list[str]) -> tuple[str, str | None]:
    for url in urls:
        try:
            r = SESSION.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                logger.info(f"[Task2] {agency_id}: OK  {url}")
                return agency_id, url
        except Exception:
            pass
    logger.warning(f"[Task2] {agency_id}: 全候補NG")
    return agency_id, None


# =========================================================
# Task 3: GSDF / RDB / ASDF top-page crawl
# =========================================================
PROC_PATTERNS = re.compile(
    r"(調達|契約|入札|落札|適正化|tekisei|nyusatu|nyusatsu|"
    r"keiyaku|kouhyou|kekka|chotatsu|rakusatu|fin/|zaisei|"
    r"jouhou|07_fin|document|disclosure|procurement)",
    re.IGNORECASE,
)

# 正しいURLが既知の機関はここに直接記載（crawlせずそのまま採用）
KNOWN_CORRECT: dict[str, str] = {
    "gsdf_cfin":       "https://www.mod.go.jp/gsdf/dc/cfin/html/concept.html",
    "gsdf_eisei":      "https://www.mod.go.jp/gsdf/mss/document/fin/",
    "gsdf_gmcc":       "https://www.mod.go.jp/gsdf/gmcc/raising/hoto/hzyo/",
    "rdb_n_kanto":     "https://www.mod.go.jp/rdb/n-kanto/nyusatsu-keiyaku/nyusatukekkasonota/nyusatukekkasonota.html",
    "rdb_s_kanto":     "https://www.mod.go.jp/rdb/s_kanto/",
    "asdf_shizuhama":  "https://www.mod.go.jp/asdf/shizuhama/",
    # ATLA研究所: ny_kenkyu_* ディレクトリ（ny_koukuu_ichi.htmlではなくny_kenkyu_koukuu_ichi.html）
    "atla_koukuu":     "https://www.mod.go.jp/atla/data/info/ny_kenkyu_koukuu/ny_kenkyu_koukuu_ichi.html",
    "atla_riku":       "https://www.mod.go.jp/atla/data/info/ny_kenkyu_riku/ny_kenkyu_riku_ichi.html",
    "atla_kantei":     "https://www.mod.go.jp/atla/data/info/ny_kenkyu_kantei/ny_kenkyu_kantei_ichi.html",
    "atla_shinsedai":  "https://www.mod.go.jp/atla/data/info/ny_kenkyu_shinsedai/ny_kenkyu_shinsedai_ichi.html",
}

# agency_id → 探索起点 URL（トップページ）
TASK3_TOP: dict[str, str] = {
    "gsdf_buki":   "https://www.mod.go.jp/gsdf/ord_sch/",
    "gsdf_ctrans": "https://www.mod.go.jp/gsdf/yokohama/",
    "gsdf_eisei":  "https://www.mod.go.jp/gsdf/mss/",
    "rdb_kinchu":  "https://www.mod.go.jp/rdb/kinchu/",
}


def crawl_top(agency_id: str, top_url: str) -> tuple[str, str | None]:
    """トップページの href を探して調達情報ページを返す。"""
    try:
        r = SESSION.get(top_url, timeout=TIMEOUT)
        html = decode_html(r.content)
        hrefs = re.findall(r'href="([^"#][^"]*)"', html, re.IGNORECASE)
        candidates: list[tuple[int, str]] = []
        for href in hrefs:
            full = urljoin(top_url, href)
            if "mod.go.jp" not in full:
                continue
            if href.lower().endswith('.pdf'):
                continue
            if not PROC_PATTERNS.search(href):
                continue
            # 深さスコア（パス深さが深いほど良い）
            depth = href.count("/")
            candidates.append((depth, full))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            best = candidates[0][1]
            logger.info(f"[Task3] {agency_id}: {best}")
            return agency_id, best
        logger.warning(f"[Task3] {agency_id}: 調達リンク見つからず (top={top_url})")
        return agency_id, None
    except Exception as e:
        logger.error(f"[Task3] {agency_id}: {e}")
        return agency_id, None


# =========================================================
# メイン
# =========================================================
def run() -> None:
    updates: dict[str, str] = {}

    # Task 1: MSDF
    logger.info("=== Task 1: MSDF ===")
    msdf_map = fetch_msdf_urls()
    # url_matrix に存在する agency_id のみ採用
    with sqlite3.connect(URL_DB) as conn:
        existing = {r[0] for r in conn.execute("SELECT DISTINCT agency_id FROM url_matrix")}
    for agency_id, url in msdf_map.items():
        if agency_id in existing:
            updates[agency_id] = url
            logger.info(f"  {agency_id}: {url}")

    # Task 2 + Task 3: 並行実行
    tasks2 = list(ATLA_CANDIDATES.items())
    tasks3 = list(TASK3_TOP.items())

    logger.info("=== Task 2+3: 並行実行 ===")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures: dict = {}
        for aid, urls in tasks2:
            futures[pool.submit(check_atla, aid, urls)] = aid
        for aid, top in tasks3:
            futures[pool.submit(crawl_top, aid, top)] = aid

        for fut in as_completed(futures):
            aid, url = fut.result()
            if url:
                updates[aid] = url

    # 既知正解URLを上書き
    for agency_id, url in KNOWN_CORRECT.items():
        updates[agency_id] = url
        logger.info(f"[Known] {agency_id}: {url}")

    # DB更新
    logger.info(f"=== DB更新: {len(updates)} 機関 ===")
    with sqlite3.connect(URL_DB) as conn:
        for agency_id, url in sorted(updates.items()):
            conn.execute(
                "UPDATE url_matrix SET site_url = ? WHERE agency_id = ?",
                (url, agency_id),
            )
            logger.info(f"  UPDATE {agency_id}: {url}")
        conn.commit()

    # 変更なし機関を報告
    all_targets = (list(msdf_map.keys()) + list(ATLA_CANDIDATES.keys())
                   + list(TASK3_TOP.keys()) + list(KNOWN_CORRECT.keys()))
    no_update = [a for a in all_targets if a not in updates and a in existing]
    if no_update:
        logger.warning(f"URL未更新: {no_update}")


if __name__ == "__main__":
    run()
