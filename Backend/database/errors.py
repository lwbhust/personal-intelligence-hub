"""Stable database error codes shared with the frozen API contract.

`Docs/API_CONTRACT.md` §6.5 defines the only values allowed in
`database.code`; `Docs/DATABASE_BASELINE.md` §9 defines when each is used.
"""

from __future__ import annotations

import sqlite3

DATABASE_UNAVAILABLE = "database_unavailable"
DATABASE_LOCKED = "database_locked"
DATABASE_MIGRATION_FAILED = "database_migration_failed"
DATABASE_SCHEMA_ERROR = "database_schema_error"

ALLOWED_CODES: frozenset[str] = frozenset(
    {
        DATABASE_UNAVAILABLE,
        DATABASE_LOCKED,
        DATABASE_MIGRATION_FAILED,
        DATABASE_SCHEMA_ERROR,
    }
)


class DatabaseError(Exception):
    """Database failure carrying a stable, contract-approved error code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


def classify_error(exc: BaseException) -> str:
    """Map an exception to one of the contract error codes.

    Never returns a free-form string: callers expose this value through
    `/health`, so unknown failures collapse to `database_unavailable`.
    """

    if isinstance(exc, DatabaseError):
        return exc.code
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            return DATABASE_LOCKED
        if "no such table" in message or "no such column" in message:
            return DATABASE_SCHEMA_ERROR
        if "malformed" in message or "not a database" in message:
            return DATABASE_SCHEMA_ERROR
        return DATABASE_UNAVAILABLE
    if isinstance(exc, sqlite3.DatabaseError):
        # Corruption or a non-SQLite file: the schema cannot be trusted.
        return DATABASE_SCHEMA_ERROR
    if isinstance(exc, OSError):
        return DATABASE_UNAVAILABLE
    return DATABASE_UNAVAILABLE
