"""Versioned SQL migration runner.

Contract source: `Docs/DATABASE_BASELINE.md` §5 and §6.

Guarantees:
- `schema_migrations` is bootstrapped by the runner, before any versioned file.
- one transaction per migration file; failure rolls the whole file back.
- checksums are SHA-256 of the raw file bytes and are never auto-repaired.
- `executescript()` is intentionally not used: it commits implicitly.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    DATABASE_MIGRATION_FAILED,
    DATABASE_SCHEMA_ERROR,
    DatabaseError,
)
from .timeutil import utc_now

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Baseline §5.1: NNNN_snake_case.sql
_MIGRATION_FILE_RE = re.compile(r"^([0-9]{4})_[a-z0-9_]+\.sql$")

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    checksum   TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    path: Path
    checksum: str


def _file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    """Return migrations sorted by ascending version, validating the tree."""

    base = MIGRATIONS_DIR if directory is None else Path(directory)
    if not base.is_dir():
        raise DatabaseError(DATABASE_SCHEMA_ERROR, "migration directory is missing")

    by_version: dict[int, Migration] = {}
    for path in sorted(base.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.suffix != ".sql":
            continue
        match = _MIGRATION_FILE_RE.match(path.name)
        if match is None:
            raise DatabaseError(
                DATABASE_SCHEMA_ERROR,
                f"invalid migration filename: {path.name}",
            )
        version = int(match.group(1))
        if version in by_version:
            raise DatabaseError(
                DATABASE_SCHEMA_ERROR,
                f"duplicate migration version: {version}",
            )
        by_version[version] = Migration(
            version=version,
            path=path,
            checksum=_file_checksum(path),
        )

    if not by_version:
        raise DatabaseError(DATABASE_SCHEMA_ERROR, "no migration files found")
    return [by_version[version] for version in sorted(by_version)]


def _split_statements(sql: str) -> list[str]:
    """Split a script into complete SQL statements.

    Uses `sqlite3.complete_statement`, which understands trigger bodies and
    string literals, so a `;` inside `BEGIN ... END` or a literal is safe.
    """

    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    if buffer.strip():
        statements.append(buffer)
    return statements


def _rollback_quietly(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass


def bootstrap(conn: sqlite3.Connection) -> None:
    """Idempotently create `schema_migrations` in its own transaction."""

    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in _split_statements(BOOTSTRAP_SQL):
            conn.execute(statement)
        conn.execute("COMMIT")
    except sqlite3.Error:
        _rollback_quietly(conn)
        raise


def _apply_one(conn: sqlite3.Connection, migration: Migration) -> None:
    try:
        sql = migration.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DatabaseError(
            DATABASE_MIGRATION_FAILED,
            f"cannot read migration {migration.version}",
        ) from exc

    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in _split_statements(sql):
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, checksum) "
            "VALUES (?, ?, ?)",
            (migration.version, utc_now(), migration.checksum),
        )
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        _rollback_quietly(conn)
        raise DatabaseError(
            DATABASE_MIGRATION_FAILED,
            f"migration {migration.version} failed: {type(exc).__name__}",
        ) from exc


def apply_migrations(
    conn: sqlite3.Connection,
    directory: Path | None = None,
) -> int:
    """Apply pending migrations and return the resulting schema version."""

    migrations = discover_migrations(directory)
    bootstrap(conn)

    try:
        applied_rows = conn.execute(
            "SELECT version, checksum FROM schema_migrations"
        ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(
            DATABASE_SCHEMA_ERROR,
            "cannot read schema_migrations",
        ) from exc

    applied = {int(row[0]): str(row[1]) for row in applied_rows}
    by_version = {migration.version: migration for migration in migrations}

    # Baseline §5.3 step 7: applied files must still exist and match.
    for version, stored_checksum in sorted(applied.items()):
        migration = by_version.get(version)
        if migration is None:
            raise DatabaseError(
                DATABASE_SCHEMA_ERROR,
                f"applied migration {version} has no file",
            )
        if migration.checksum != stored_checksum:
            raise DatabaseError(
                DATABASE_SCHEMA_ERROR,
                f"checksum mismatch for migration {version}",
            )

    # Baseline §5.3 step 8: never downgrade a newer database.
    highest_known = max(by_version)
    if applied and max(applied) > highest_known:
        raise DatabaseError(
            DATABASE_SCHEMA_ERROR,
            "database schema is newer than this build",
        )

    for migration in migrations:
        if migration.version in applied:
            continue
        _apply_one(conn, migration)

    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0
