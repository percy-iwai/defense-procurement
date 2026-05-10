"""DB接続ヘルパー — procurement.db 単独 / defense_pillar.db を ATTACH した接続を提供。

Streamlit Cloud 対応: procurement.db は Git LFS で管理されているが
Streamlit Community Cloud は LFS オブジェクトを取得しない。
PROC_DB は起動時に自動ダウンロード（GitHub Releases）してローカルキャッシュを返す。

使い方:
    from _db import connect_with_pillar, PROC_DB
    with connect_with_pillar() as conn:
        df = pd.read_sql("SELECT * FROM pillar.defense_pillar_master", conn)
"""
from __future__ import annotations

import sqlite3
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROC_DB_LOCAL = PROJECT_ROOT / "data" / "db" / "procurement.db"
_PROC_DB_CACHE = Path("/tmp/procurement.db")
_PROC_DB_URL = (
    "https://github.com/percy-iwai/defense-procurement"
    "/releases/download/v1.0-db/procurement.db"
)
_MIN_REAL_SIZE = 1_000_000  # 1 MB 以上 = 実ファイル（LFSポインタは ~134 bytes）

PILLAR_DB = PROJECT_ROOT / "data" / "db" / "defense_pillar.db"


def _resolve_proc_db() -> Path:
    """procurement.db の実体パスを返す。必要なら GitHub Releases からダウンロード。"""
    if _PROC_DB_LOCAL.exists() and _PROC_DB_LOCAL.stat().st_size >= _MIN_REAL_SIZE:
        return _PROC_DB_LOCAL
    if _PROC_DB_CACHE.exists() and _PROC_DB_CACHE.stat().st_size >= _MIN_REAL_SIZE:
        return _PROC_DB_CACHE
    # Streamlit Cloud 環境 — GitHub Releases から取得
    _PROC_DB_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print("[cloud-db] Downloading procurement.db from GitHub Releases...", flush=True)
    urllib.request.urlretrieve(_PROC_DB_URL, _PROC_DB_CACHE)
    size_mb = _PROC_DB_CACHE.stat().st_size // 1_000_000
    print(f"[cloud-db] Done ({size_mb} MB)", flush=True)
    return _PROC_DB_CACHE


# モジュールロード時に一度だけ解決（Python モジュールキャッシュにより再ダウンロードなし）
PROC_DB: Path = _resolve_proc_db()


@contextmanager
def connect_with_pillar() -> Iterator[sqlite3.Connection]:
    """procurement.db を main、defense_pillar.db を `pillar` として ATTACH した接続。"""
    conn = sqlite3.connect(PROC_DB)
    try:
        conn.execute(f"ATTACH DATABASE '{PILLAR_DB.as_posix()}' AS pillar")
        yield conn
    finally:
        conn.close()


@contextmanager
def connect_pillar_only() -> Iterator[sqlite3.Connection]:
    """defense_pillar.db を main として開く接続（procurement.db との JOIN が不要な場合）。"""
    conn = sqlite3.connect(PILLAR_DB)
    try:
        yield conn
    finally:
        conn.close()
