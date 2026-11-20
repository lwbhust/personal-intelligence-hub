"""PIH SQLite data layer (Phase 0 infrastructure only).

Public surface consumed by backend-developer (names and signatures frozen):

    DatabaseStatus, DatabaseError,
    resolve_data_dir, database_path, path_kind,
    initialize, health_check, session,
    get_meta, set_meta

No business tables, no ORM, no FTS5 in Phase 0.
Contract sources: Docs/API_CONTRACT.md §6, Docs/DATABASE_BASELINE.md.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .connection import (
    DEFAULT_BUSY_TIMEOUT_MS,
    HEALTH_BUSY_TIMEOUT_MS,
    connect,
    enable_wal,
)
from .errors import (
    ALLOWED_CODES,
    DATABASE_MIGRATION_FAILED,
    DATABASE_SCHEMA_ERROR,
    DATABASE_UNAVAILABLE,
    DatabaseError,
    classify_error,
)
from .migrator import MIGRATIONS_DIR, apply_migrations, discover_migrations
from .paths import (
    DB_FILENAME,
    ENV_DATA_DIR,
    PATH_KIND_APPLICATION_SUPPORT,
    PATH_KIND_CUSTOM,
    database_path,
    path_kind,
    resolve_data_dir,
)
from .status import DatabaseStatus
from .timeutil import utc_now

__all__ = [
    "ALLOWED_CODES",
    "DATABASE_MIGRATION_FAILED",
    "DATABASE_SCHEMA_ERROR",
    "DATABASE_UNAVAILABLE",
    "DB_FILENAME",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DatabaseError",
    "DatabaseStatus",
    "ENV_DATA_DIR",
    "MIGRATIONS_DIR",
    "apply_migrations",
    "connect",
    "database_path",
    "discover_migrations",
    "get_meta",
    "health_check",
    "initialize",
    "path_kind",
    "read_session",
    "resolve_data_dir",
    "session",
    "set_meta",
]


def _ensure_directory(directory: Path) -> None:
    """Create the data directory with mode 0700 when it does not exist.

    Existing directories keep their current mode on purpose
    (DATABASE_BASELINE.md §2.3).
    """

    if directory.is_dir():
        return
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        # mkdir mode is filtered by umask; chmod makes 0700 deterministic.
        os.chmod(directory, 0o700)
    except OSError:
        pass


def _restrict_file_mode(database_file: Path) -> None:
    try:
        os.chmod(database_file, 0o600)
    except OSError:
        pass


def _failure_status(code: str, kind: str) -> DatabaseStatus:
    return DatabaseStatus(
        status="error",
        schema_version=None,
        path_kind=kind,
        code=code,
    )


def initialize(database_path_override: Path | str | None = None) -> DatabaseStatus:
    """Create/open the database, apply migrations, and report real state.

    Never raises: failures are reported as `status="error"` plus a stable
    contract code, so Sidecar startup is not blocked (API_CONTRACT.md §2.4).
    """

    kind = path_kind()
    conn: sqlite3.Connection | None = None
    try:
        if database_path_override is None:
            database_file = database_path()
        else:
            database_file = Path(database_path_override).resolve()

        _ensure_directory(database_file.parent)
        existed_before = database_file.exists()

        conn = connect(database_file)
        if not existed_before:
            _restrict_file_mode(database_file)

        enable_wal(conn)
        schema_version = apply_migrations(conn)
        return DatabaseStatus(
            status="ok",
            schema_version=schema_version,
            path_kind=kind,
            code=None,
        )
    except Exception as exc:  # noqa: BLE001 - initialize must never raise
        return _failure_status(classify_error(exc), kind)
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def health_check() -> DatabaseStatus:
    """Lightweight probe for `/health`; never raises.

    Phase 1 (DB-01) keeps this cheap: a short-lived connection with a 500 ms
    busy timeout, `SELECT 1` and `MAX(version)`. No `quick_check`/`integrity_check`
    here — those belong to backup verification, not a 5-second health poll.
    """

    kind = path_kind()
    conn: sqlite3.Connection | None = None
    schema_version: int | None = None
    try:
        database_file = database_path()
        if not database_file.is_file():
            return _failure_status(DATABASE_UNAVAILABLE, kind)

        conn = connect(database_file, busy_timeout_ms=HEALTH_BUSY_TIMEOUT_MS)
        conn.execute("SELECT 1").fetchone()

        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        schema_version = int(row[0]) if row is not None and row[0] is not None else 0

        return DatabaseStatus(
            status="ok",
            schema_version=schema_version,
            path_kind=kind,
            code=None,
        )
    except Exception as exc:  # noqa: BLE001 - health must never raise
        return DatabaseStatus(
            status="error",
            schema_version=schema_version,
            path_kind=kind,
            code=classify_error(exc),
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


@contextmanager
def read_session() -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection inside one deferred transaction.

    `BEGIN DEFERRED` + `query_only` gives a single snapshot for the whole
    request, so paginated `items` and `total` always agree. Callers must not
    write; the connection is closed on exit.
    """

    database_file = database_path()
    if not database_file.is_file():
        raise DatabaseError(
            DATABASE_UNAVAILABLE,
            "database file is missing; call initialize() first",
        )

    conn = connect(database_file)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN DEFERRED")
        yield conn
    finally:
        if conn.in_transaction:
            try:
                conn.execute("COMMIT")
            except sqlite3.Error:
                pass
        try:
            conn.close()
        except sqlite3.Error:
            pass


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """Yield a connection inside one explicit `BEGIN IMMEDIATE` transaction.

    Commits on normal exit, rolls back and re-raises on any exception, and
    always closes the connection. Not re-entrant; do not nest sessions.
    """

    database_file = database_path()
    if not database_file.is_file():
        raise DatabaseError(
            DATABASE_UNAVAILABLE,
            "database file is missing; call initialize() first",
        )

    conn = connect(database_file)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        if conn.in_transaction:
            conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def get_meta(key: str) -> str | None:
    """Read a value from the Phase 0 `app_meta` infrastructure table."""

    with session() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = ?",
            (key,),
        ).fetchone()
    return None if row is None else str(row["value"])


def set_meta(key: str, value: str) -> None:
    """Upsert a value into `app_meta` with a UTC `updated_at` timestamp."""

    with session() as conn:
        conn.execute(
            "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at",
            (key, value, utc_now()),
        )
