"""SQLite connection factory (Phase 0: short-lived connections, no pool).

Contract source: `Docs/DATABASE_BASELINE.md` §3 and §4.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .errors import DATABASE_UNAVAILABLE, DatabaseError

DEFAULT_BUSY_TIMEOUT_MS = 5000
# Deliberate exception for `/health`: the client must answer within 2 s.
HEALTH_BUSY_TIMEOUT_MS = 500


def connect(
    db_path: str | Path,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """Open a connection with the baseline PRAGMAs applied.

    `isolation_level=None` disables Python's implicit transaction handling;
    transactions are always explicit (`BEGIN IMMEDIATE` / `COMMIT`).
    `journal_mode=WAL` is persistent and is set once during initialization.
    """

    timeout_seconds = max(int(busy_timeout_ms), 0) / 1000
    conn = sqlite3.connect(
        str(db_path),
        timeout=timeout_seconds,
        isolation_level=None,
        check_same_thread=True,
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        conn.execute("PRAGMA synchronous = NORMAL")
    except BaseException:
        conn.close()
        raise
    return conn


def enable_wal(conn: sqlite3.Connection) -> None:
    """Persistently enable WAL and verify it actually took effect."""

    row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
    actual = str(row[0]).lower() if row is not None else ""
    if actual != "wal":
        raise DatabaseError(
            DATABASE_UNAVAILABLE,
            "WAL journal mode could not be enabled",
        )
