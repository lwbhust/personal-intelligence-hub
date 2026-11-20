"""Parameterised SQL for `event_score_snapshots`."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from .models import EventScoreRecord

_COLUMNS = (
    "id",
    "event_id",
    "algorithm_version",
    "scored_at",
    "importance_score",
    "heat_score",
    "freshness_score",
    "coverage_score",
    "confidence_score",
    "total_score",
    "inputs_json",
    "explanation_json",
    "is_current",
    "created_at",
)


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _from_row(row: sqlite3.Row) -> EventScoreRecord:
    return EventScoreRecord(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        algorithm_version=str(row["algorithm_version"]),
        scored_at=str(row["scored_at"]),
        importance_score=float(row["importance_score"]),
        heat_score=float(row["heat_score"]),
        freshness_score=float(row["freshness_score"]),
        coverage_score=float(row["coverage_score"]),
        confidence_score=float(row["confidence_score"]),
        total_score=float(row["total_score"]),
        inputs=_json_object(row["inputs_json"]),
        explanation=_json_object(row["explanation_json"]),
        is_current=bool(int(row["is_current"])),
        created_at=str(row["created_at"]),
    )


def clear_current(conn: sqlite3.Connection, event_id: str) -> None:
    conn.execute(
        "UPDATE event_score_snapshots SET is_current = 0 WHERE event_id = ? AND is_current = 1",
        (event_id,),
    )


def insert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_COLUMNS)
    placeholders = ", ".join("?" for _ in _COLUMNS)
    conn.execute(
        f"INSERT INTO event_score_snapshots ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _COLUMNS),
    )


def current(conn: sqlite3.Connection, event_id: str) -> EventScoreRecord | None:
    row = conn.execute(
        "SELECT * FROM event_score_snapshots WHERE event_id = ? AND is_current = 1",
        (event_id,),
    ).fetchone()
    return None if row is None else _from_row(row)


def previous(conn: sqlite3.Connection, event_id: str, current_id: str) -> EventScoreRecord | None:
    row = conn.execute(
        "SELECT * FROM event_score_snapshots WHERE event_id = ? AND id <> ? "
        "ORDER BY scored_at DESC, id DESC LIMIT 1",
        (event_id, current_id),
    ).fetchone()
    return None if row is None else _from_row(row)


def list_snapshots(
    conn: sqlite3.Connection, event_id: str, *, limit: int = 10, offset: int = 0
) -> tuple[list[EventScoreRecord], int]:
    rows = conn.execute(
        "SELECT * FROM event_score_snapshots WHERE event_id = ? "
        "ORDER BY is_current DESC, scored_at DESC, id DESC LIMIT ? OFFSET ?",
        (event_id, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) FROM event_score_snapshots WHERE event_id = ?", (event_id,)
    ).fetchone()
    return (
        [_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def touch(conn: sqlite3.Connection, snapshot_id: str, scored_at: str) -> None:
    conn.execute(
        "UPDATE event_score_snapshots SET scored_at = ? WHERE id = ?",
        (scored_at, snapshot_id),
    )


def prune(conn: sqlite3.Connection, event_id: str, keep: int = 50) -> int:
    row = conn.execute(
        "SELECT id FROM event_score_snapshots WHERE event_id = ? "
        "AND is_current = 0 ORDER BY scored_at DESC, id DESC LIMIT 1 OFFSET ?",
        (event_id, max(0, keep - 1)),
    ).fetchone()
    if row is None:
        return 0
    cursor = conn.execute(
        "DELETE FROM event_score_snapshots WHERE event_id = ? AND is_current = 0 "
        "AND (scored_at, id) < (SELECT scored_at, id FROM event_score_snapshots WHERE id = ?)",
        (event_id, str(row["id"])),
    )
    return int(cursor.rowcount or 0)


def list_event_ids_needing_score(
    conn: sqlite3.Connection,
    *,
    limit: int,
    algorithm_version: str,
    stale_before: str | None = None,
) -> list[str]:
    """Events without a current snapshot, on another algorithm version, or
    whose current snapshot is older than `stale_before` (time-decaying scores)."""

    rows = conn.execute(
        """
        SELECT e.id
        FROM events AS e
        LEFT JOIN event_score_snapshots AS s
               ON s.event_id = e.id AND s.is_current = 1
        WHERE e.status NOT IN ('merged','archived')
          AND (
                s.id IS NULL
             OR s.algorithm_version <> ?
             OR (? IS NOT NULL AND s.scored_at < ?)
          )
        ORDER BY e.last_seen_at DESC
        LIMIT ?
        """,
        (algorithm_version, stale_before, stale_before, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def list_scored_event_ids(conn: sqlite3.Connection, *, limit: int) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM events WHERE status NOT IN ('merged','archived') "
        "ORDER BY last_seen_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]
