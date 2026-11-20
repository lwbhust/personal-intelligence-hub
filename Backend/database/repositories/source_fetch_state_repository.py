"""Parameterised SQL for `source_fetch_state` (ETag / Last-Modified cursors)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import SourceFetchStateRecord

_COLUMNS = (
    "source_id",
    "etag",
    "last_modified",
    "last_fetch_at",
    "last_success_at",
    "last_error_code",
    "last_error_message",
    "consecutive_failures",
    "updated_at",
)


def get(conn: sqlite3.Connection, source_id: str) -> SourceFetchStateRecord | None:
    row = conn.execute(
        "SELECT * FROM source_fetch_state WHERE source_id = ?", (source_id,)
    ).fetchone()
    if row is None:
        return None
    return SourceFetchStateRecord(
        source_id=str(row["source_id"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        last_fetch_at=row["last_fetch_at"],
        last_success_at=row["last_success_at"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        consecutive_failures=int(row["consecutive_failures"]),
        updated_at=str(row["updated_at"]),
    )


def upsert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    """Insert or replace a cursor row.

    Every column is written, so callers must pass the full row; omitted keys
    become NULL/default instead of preserving the previous value.
    """

    params = tuple(values.get(key) for key in _COLUMNS)
    assignments = ", ".join(
        f"{key} = excluded.{key}" for key in _COLUMNS if key != "source_id"
    )
    conn.execute(
        f"""
        INSERT INTO source_fetch_state ({', '.join(_COLUMNS)})
        VALUES ({', '.join('?' for _ in _COLUMNS)})
        ON CONFLICT(source_id) DO UPDATE SET {assignments}
        """,
        params,
    )
