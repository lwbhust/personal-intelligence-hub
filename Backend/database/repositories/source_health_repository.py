"""Parameterised SQL for `source_health_logs`."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import SourceHealthRecord


def _row_to_record(row: sqlite3.Row) -> SourceHealthRecord:
    return SourceHealthRecord(
        id=str(row["id"]),
        source_id=str(row["source_id"]),
        checked_at=str(row["checked_at"]),
        status=str(row["status"]),
        http_status=row["http_status"],
        latency_ms=row["latency_ms"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def insert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = (
        "id",
        "source_id",
        "checked_at",
        "status",
        "http_status",
        "latency_ms",
        "error_code",
        "error_message",
        "created_at",
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO source_health_logs ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values[key] for key in columns),
    )


def list_recent(
    conn: sqlite3.Connection, source_id: str, *, limit: int
) -> tuple[list[SourceHealthRecord], int]:
    rows = conn.execute(
        """
        SELECT * FROM source_health_logs
        WHERE source_id = ?
        ORDER BY checked_at DESC, id ASC
        LIMIT ?
        """,
        (source_id, limit),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) FROM source_health_logs WHERE source_id = ?", (source_id,)
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_row_to_record(row) for row in rows], total


def prune(conn: sqlite3.Connection, source_id: str, keep: int) -> int:
    cursor = conn.execute(
        """
        DELETE FROM source_health_logs
        WHERE source_id = ? AND id NOT IN (
            SELECT id FROM source_health_logs
            WHERE source_id = ?
            ORDER BY checked_at DESC, id ASC
            LIMIT ?
        )
        """,
        (source_id, source_id, keep),
    )
    return cursor.rowcount
