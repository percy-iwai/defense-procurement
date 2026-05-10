"""DB接続ヘルパー — procurement.db 単独 / defense_pillar.db を ATTACH した接続を提供。

使い方:
    from _db import connect_with_pillar
    with connect_with_pillar() as conn:
        df = pd.read_sql("SELECT * FROM pillar.defense_pillar_master", conn)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROC_DB = PROJECT_ROOT / "data" / "db" / "procurement.db"
PILLAR_DB = PROJECT_ROOT / "data" / "db" / "defense_pillar.db"


@contextmanager
def connect_with_pillar() -> Iterator[sqlite3.Connection]:
    """procurement.db を main、defense_pillar.db を `pillar` として ATTACH した接続。

    SQLite の ATTACH では絶対パスを使う必要があるため as_posix() で渡す。
    `with ... as conn:` で使うと終了時に自動 close される。
    """
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
