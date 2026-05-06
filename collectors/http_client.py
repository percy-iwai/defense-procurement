"""HTTP取得クライアント（User-Agent付与・ローカルキャッシュ・リトライ）。"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 2.0
WARP_RATE_LIMIT_SEC = 2.5

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def _cache_path(url: str, ext: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return RAW_DIR / "_cache" / f"{h}{ext}"


def fetch(
    url: str,
    *,
    save_to: Optional[Path] = None,
    use_cache: bool = True,
    is_warp: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> Optional[bytes]:
    """URLを取得しbytesで返す。404時は None。

    save_to を指定するとそのパスに保存（既存があれば再利用）。
    use_cache=True なら data/raw/_cache/{hash}{ext} に共有キャッシュ。
    """
    if save_to and save_to.exists() and save_to.stat().st_size > 0:
        return save_to.read_bytes()

    ext = Path(url.split("?", 1)[0]).suffix or ""
    cache = _cache_path(url, ext) if use_cache else None
    if cache and cache.exists() and cache.stat().st_size > 0:
        data = cache.read_bytes()
        if save_to:
            save_to.parent.mkdir(parents=True, exist_ok=True)
            save_to.write_bytes(data)
        return data

    # WARP/Wayback URL は自動的に rate-limit を適用
    if not is_warp and (
        url.startswith("https://warp.ndl.go.jp/")
        or url.startswith("https://web.archive.org/")
    ):
        is_warp = True

    headers = {"User-Agent": UA}
    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        try:
            if is_warp:
                time.sleep(WARP_RATE_LIMIT_SEC)
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                data = r.content
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(data)
                if save_to:
                    save_to.parent.mkdir(parents=True, exist_ok=True)
                    save_to.write_bytes(data)
                return data
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        if attempt < retries:
            time.sleep(DEFAULT_BACKOFF * attempt)
    logger.warning(f"fetch失敗: {url} ({last_err})")
    return None
