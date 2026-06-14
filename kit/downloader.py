"""WARP / mod.go.jp 特化ダウンローダー（新環境でのデータ再取得用・完全自走）。

urls_replay.csv（kit/export_kit_data.py が出力）の全URLをダウンロードし、
collectors/http_client.py と**同一のハッシュ規則**で data/raw/_cache/ に保存する。
キャッシュが温まれば、既存の pipeline/load_*.py は一切の改修なしで
オフライン再生（HTTP なしで再パース）できる。

機能:
  - レジューム: kit/exports/download_manifest.jsonl に結果を追記。再実行時は
    成功済み/404確定済みをスキップ（中断・再開自由、Coworkセッション切断にも耐える）
  - レート制限: warp.ndl.go.jp / web.archive.org 2.5秒、mod.go.jp等 1.0秒
  - リトライ: 429/5xx/接続エラーは指数バックオフで3回
  - 404フォールバック: ライブURLが消えていたら Wayback Machine CDX API で
    スナップショットを探して取得し、**元URLのキーで**キャッシュに保存

実行:
  python kit/downloader.py --dry-run            # キャッシュヒット率の確認のみ（通信なし）
  python kit/downloader.py                      # urls_replay.csv 全件
  python kit/downloader.py --urls retry.txt     # URLリストファイル（1行1URL）
  python kit/downloader.py --retry-failed       # manifest上 fail のURLだけ再試行
  python kit/downloader.py --discover index.txt # インデックスページからリンク発見→DL

終了コード: 0=エラーなし（404確定は成功扱い） / 1=エラー残あり
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collectors.http_client import UA, _cache_path  # noqa: E402  同一ハッシュ規則を共有

EXPORTS_DIR = PROJECT_ROOT / "kit" / "exports"
DEFAULT_CSV = EXPORTS_DIR / "urls_replay.csv"
MANIFEST = EXPORTS_DIR / "download_manifest.jsonl"

RATE_LIMITS = {  # ドメイン → 最小リクエスト間隔（秒）
    "warp.ndl.go.jp": 2.5,
    "web.archive.org": 2.5,
}
DEFAULT_RATE = 1.0
RETRIES = 3
BACKOFF = 3.0
TIMEOUT = 60


# ── ユーティリティ ───────────────────────────────────────────────────────────

def _ext_of(url: str) -> str:
    return Path(url.split("?", 1)[0]).suffix or ""


def cache_path_for(url: str) -> Path:
    """http_client.fetch() がキャッシュ照合に使うのと同一のパス。"""
    return _cache_path(url, _ext_of(url))


def _domain(url: str) -> str:
    return urlparse(url).netloc


def _is_archive(url: str) -> bool:
    return "warp.ndl.go.jp" in url or "web.archive.org" in url


def _unwrap_archive(url: str) -> str:
    """WARP/Wayback ラッパーから元URLを取り出す（非ラップURLはそのまま）。"""
    for marker in ("/https://", "/http://"):
        if "warp.ndl.go.jp" in url or "web.archive.org" in url:
            idx = url.find(marker)
            if idx > 0:
                return url[idx + 1:]
    return url


# ── manifest（レジューム）────────────────────────────────────────────────────

def load_manifest() -> dict[str, dict]:
    state: dict[str, dict] = {}
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    state[rec["url"]] = rec  # 後勝ち
                except (json.JSONDecodeError, KeyError):
                    continue
    return state


def append_manifest(rec: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── レート制限つきHTTP ────────────────────────────────────────────────────────

class Throttle:
    def __init__(self, rate_scale: float = 1.0) -> None:
        self.last: dict[str, float] = {}
        self.scale = rate_scale

    def wait(self, url: str) -> None:
        dom = _domain(url)
        interval = RATE_LIMITS.get(dom, DEFAULT_RATE) * self.scale
        elapsed = time.monotonic() - self.last.get(dom, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self.last[dom] = time.monotonic()


def http_get(session: requests.Session, throttle: Throttle,
             url: str) -> tuple[str, bytes | None]:
    """('ok'|'gone'|'fail', data)。429/5xx/接続断はバックオフ付きリトライ。"""
    last_err = ""
    for attempt in range(1, RETRIES + 1):
        throttle.wait(url)
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200 and r.content:
                return "ok", r.content
            if r.status_code == 404:
                return "gone", None
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            last_err = type(exc).__name__
        if attempt < RETRIES:
            time.sleep(BACKOFF * attempt)
    return f"fail:{last_err}", None


# ── Wayback フォールバック（pipeline/search_warp_snapshots.py の方式を流用）──

def wayback_lookup(session: requests.Session, throttle: Throttle,
                   url: str) -> str | None:
    """Wayback CDX API で最初の200スナップショットURLを返す。"""
    cdx = ("https://web.archive.org/cdx/search/cdx"
           f"?url={quote(url, safe='')}"
           "&output=json&limit=1&fl=timestamp&filter=statuscode:200")
    throttle.wait("https://web.archive.org/")
    try:
        r = session.get(cdx, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
        if len(data) < 2:
            return None
        ts = data[1][0]
        return f"https://web.archive.org/web/{ts}id_/{url}"
    except (requests.RequestException, ValueError):
        return None


# ── 1件処理 ──────────────────────────────────────────────────────────────────

def process_url(session: requests.Session, throttle: Throttle, url: str) -> dict:
    """URLを取得して元URLキーでキャッシュ保存。manifest用レコードを返す。"""
    rec: dict = {"url": url, "ts": datetime.now().isoformat()}
    cache = cache_path_for(url)
    if cache.exists() and cache.stat().st_size > 0:
        rec.update(status="cached", bytes=cache.stat().st_size)
        return rec

    status, data = http_get(session, throttle, url)

    # フォールバック: 404なら Wayback でスナップショットを探す
    if status == "gone":
        target = _unwrap_archive(url)
        snap = wayback_lookup(session, throttle, target)
        if snap:
            s2, data = http_get(session, throttle, snap)
            if s2 == "ok" and data:
                status = "ok"
                rec["fallback"] = snap

    if status == "ok" and data:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        rec.update(status="ok", bytes=len(data),
                   sha256=hashlib.sha256(data).hexdigest()[:16])
    else:
        rec.update(status=status, bytes=0)
    return rec


# ── URLリスト読み込み ─────────────────────────────────────────────────────────

def urls_from_csv(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig") as f:
        return [row["url"] for row in csv.DictReader(f) if row.get("url")]


def urls_from_txt(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def urls_from_discover(path: Path) -> list[str]:
    """インデックスページURLのリストから PDF/Excel リンクを発見する。"""
    from collectors.index_scraper import scrape_file_links
    index_urls = urls_from_txt(path)
    found: list[str] = []
    for iu in index_urls:
        try:
            links = scrape_file_links(iu)
            print(f"discover: {len(links):3d} links <- {iu[:90]}")
            found.extend(links)
        except Exception as exc:  # noqa: BLE001
            print(f"discover FAIL: {iu[:90]} ({exc})")
    seen: set[str] = set()
    return [u for u in found if not (u in seen or seen.add(u))]


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="WARP/mod.go.jp 特化ダウンローダー")
    parser.add_argument("--replay", default=str(DEFAULT_CSV),
                        help=f"urls_replay.csv のパス（既定: {DEFAULT_CSV}）")
    parser.add_argument("--urls", help="URLリストファイル（1行1URL、#コメント可）")
    parser.add_argument("--discover",
                        help="インデックスページURLのリストファイル→リンク発見してDL")
    parser.add_argument("--retry-failed", action="store_true",
                        help="manifest上 fail のURLのみ再試行")
    parser.add_argument("--rate", type=float, default=1.0,
                        help="レート制限の倍率（2.0で2倍待つ。既定1.0）")
    parser.add_argument("--limit", type=int, help="処理URL数上限（デバッグ用）")
    parser.add_argument("--dry-run", action="store_true",
                        help="通信せずキャッシュ/manifestヒット状況のみ表示")
    args = parser.parse_args()

    manifest = load_manifest()

    if args.retry_failed:
        urls = [u for u, r in manifest.items()
                if str(r.get("status", "")).startswith("fail")]
    elif args.discover:
        urls = urls_from_discover(Path(args.discover))
    elif args.urls:
        urls = urls_from_txt(Path(args.urls))
    else:
        urls = urls_from_csv(Path(args.replay))

    if args.limit:
        urls = urls[: args.limit]
    total = len(urls)
    print(f"対象URL: {total:,}件")

    # dry-run: キャッシュヒット棚卸し
    if args.dry_run:
        hit = sum(1 for u in urls
                  if cache_path_for(u).exists() and cache_path_for(u).stat().st_size > 0)
        man_ok = sum(1 for u in urls
                     if manifest.get(u, {}).get("status") in ("ok", "cached", "gone"))
        print(f"[DRY-RUN] cache hit: {hit:,}/{total:,} ({hit / max(total, 1):.1%})  "
              f"manifest resolved: {man_ok:,}")
        print(f"SUMMARY ok=0 cached={hit} gone404=0 fail=0 remaining={total - hit}")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    throttle = Throttle(args.rate)

    stats = {"ok": 0, "cached": 0, "gone": 0, "fail": 0, "skipped": 0}
    t0 = time.monotonic()
    for i, url in enumerate(urls, 1):
        prev = manifest.get(url, {}).get("status")
        if not args.retry_failed and prev in ("ok", "cached", "gone"):
            # 過去に解決済み（キャッシュ実体が消えていたら再取得）
            if prev == "gone" or cache_path_for(url).exists():
                stats["skipped"] += 1
                continue
        rec = process_url(session, throttle, url)
        append_manifest(rec)
        manifest[url] = rec
        st = rec["status"]
        if st in ("ok", "cached"):
            stats["ok" if st == "ok" else "cached"] += 1
        elif st == "gone":
            stats["gone"] += 1
            print(f"  GONE(404): {url[:100]}")
        else:
            stats["fail"] += 1
            print(f"  FAIL({st}): {url[:100]}")
        if i % 100 == 0:
            el = time.monotonic() - t0
            eta = el / i * (total - i)
            print(f"進捗 {i:,}/{total:,}  ok={stats['ok']} cached={stats['cached']} "
                  f"skip={stats['skipped']} gone={stats['gone']} fail={stats['fail']}  "
                  f"経過{el / 60:.0f}分 残り目安{eta / 60:.0f}分")

    print(f"SUMMARY ok={stats['ok']} cached={stats['cached']} skipped={stats['skipped']} "
          f"gone404={stats['gone']} fail={stats['fail']}")
    if stats["gone"]:
        print("※ gone404 はライブ・アーカイブとも消失したURL。verify_rebuild.py の"
              "欠損レポートと突き合わせて影響を確認してください。")
    sys.exit(1 if stats["fail"] else 0)


if __name__ == "__main__":
    main()
