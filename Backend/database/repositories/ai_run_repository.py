"""Parameterised SQL for `ai_runs` and `ai_run_items` (Phase 3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import AIRunItemRecord, AIRunRecord

_RUN_COLUMNS = (
    "id",
    "trigger_type",
    "scope",
    "status",
    "requested_count",
    "processed_count",
    "succeeded_count",
    "failed_count",
    "skipped_count",
    "model_name",
    "error_message",
    "cancel_requested",
    "pause_requested",
    "started_at",
    "finished_at",
    "duration_ms",
    "created_at",
    "updated_at",
)

_RUN_UPDATE_ALLOWED = set(_RUN_COLUMNS) - {"id", "trigger_type", "scope", "created_at"}

_ITEM_COLUMNS = (
    "id",
    "run_id",
    "article_id",
    "status",
    "attempts",
    "error_code",
    "error_message",
    "started_at",
    "finished_at",
    "duration_ms",
    "created_at",
    "updated_at",
)

_ITEM_UPDATE_ALLOWED = set(_ITEM_COLUMNS) - {"id", "run_id", "article_id", "created_at"}

_ITEM_SELECT = """
    SELECT i.*, a.title AS article_title
    FROM ai_run_items AS i
    LEFT JOIN articles AS a ON a.id = i.article_id
"""


def _run_from_row(row: sqlite3.Row, items: tuple[AIRunItemRecord, ...] = ()) -> AIRunRecord:
    return AIRunRecord(
        id=str(row["id"]),
        trigger_type=str(row["trigger_type"]),
        scope=str(row["scope"]),
        status=str(row["status"]),
        requested_count=int(row["requested_count"]),
        processed_count=int(row["processed_count"]),
        succeeded_count=int(row["succeeded_count"]),
        failed_count=int(row["failed_count"]),
        skipped_count=int(row["skipped_count"]),
        model_name=row["model_name"],
        error_message=row["error_message"],
        cancel_requested=bool(int(row["cancel_requested"])),
        pause_requested=bool(int(row["pause_requested"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        items=items,
    )


def _item_from_row(row: sqlite3.Row) -> AIRunItemRecord:
    return AIRunItemRecord(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        article_id=str(row["article_id"]),
        article_title=row["article_title"],
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def insert_run(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_RUN_COLUMNS)
    placeholders = ", ".join("?" for _ in _RUN_COLUMNS)
    conn.execute(
        f"INSERT INTO ai_runs ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _RUN_COLUMNS),
    )


def insert_item(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_ITEM_COLUMNS)
    placeholders = ", ".join("?" for _ in _ITEM_COLUMNS)
    conn.execute(
        f"INSERT INTO ai_run_items ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _ITEM_COLUMNS),
    )


def update_run(conn: sqlite3.Connection, run_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _RUN_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE ai_runs SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), run_id),
    )


def update_item(conn: sqlite3.Connection, item_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _ITEM_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE ai_run_items SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), item_id),
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> AIRunRecord | None:
    row = conn.execute("SELECT * FROM ai_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    item_rows = conn.execute(
        f"{_ITEM_SELECT} WHERE i.run_id = ? ORDER BY i.created_at ASC, i.id ASC",
        (run_id,),
    ).fetchall()
    return _run_from_row(row, tuple(_item_from_row(item) for item in item_rows))


def list_runs(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[AIRunRecord], int]:
    where = "" if status is None else "WHERE status = ?"
    params: list[object] = [] if status is None else [status]
    rows = conn.execute(
        f"SELECT * FROM ai_runs {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM ai_runs {where}",
        tuple(params),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_run_from_row(row) for row in rows], total


def next_pending_item(conn: sqlite3.Connection, run_id: str) -> AIRunItemRecord | None:
    row = conn.execute(
        f"{_ITEM_SELECT} WHERE i.run_id = ? AND i.status = 'pending' "
        "ORDER BY i.created_at ASC, i.id ASC LIMIT 1",
        (run_id,),
    ).fetchone()
    return None if row is None else _item_from_row(row)


def pending_items(conn: sqlite3.Connection, run_id: str) -> list[AIRunItemRecord]:
    rows = conn.execute(
        f"{_ITEM_SELECT} WHERE i.run_id = ? AND i.status = 'pending' "
        "ORDER BY i.created_at ASC, i.id ASC",
        (run_id,),
    ).fetchall()
    return [_item_from_row(row) for row in rows]


def claim_item(conn: sqlite3.Connection, item_id: str, started_at: str) -> bool:
    cursor = conn.execute(
        "UPDATE ai_run_items SET status = 'running', started_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (started_at, started_at, item_id),
    )
    return cursor.rowcount == 1


def counts(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
    row = conn.execute(
        "SELECT "
        "SUM(CASE WHEN status IN ('succeeded','failed','skipped','cancelled') THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) "
        "FROM ai_run_items WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    return {
        "processed": int(row[0] or 0),
        "succeeded": int(row[1] or 0),
        "failed": int(row[2] or 0),
        "skipped": int(row[3] or 0),
    }


def fail_pending_items(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    error_code: str,
    error_message: str,
    finished_at: str,
) -> int:
    cursor = conn.execute(
        "UPDATE ai_run_items SET status = ?, error_code = ?, error_message = ?, "
        "finished_at = ?, updated_at = ? WHERE run_id = ? AND status IN ('pending','running')",
        (status, error_code, error_message, finished_at, finished_at, run_id),
    )
    return int(cursor.rowcount)


def start_run(conn: sqlite3.Connection, run_id: str, *, started_at: str, now: str) -> bool:
    """Start a run unless a concurrent pause/cancel arrived first."""

    cursor = conn.execute(
        "UPDATE ai_runs SET status = 'running', started_at = ?, finished_at = NULL, "
        "duration_ms = NULL, pause_requested = 0, updated_at = ? "
        "WHERE id = ? AND status = 'pending' AND pause_requested = 0 "
        "AND cancel_requested = 0",
        (started_at, now, run_id),
    )
    return cursor.rowcount == 1


def mark_stale(conn: sqlite3.Connection, finished_at: str) -> int:
    conn.execute(
        "UPDATE ai_run_items SET status = 'failed', error_code = 'interrupted', "
        "error_message = 'Sidecar 重启，任务被中断', finished_at = ?, updated_at = ? "
        "WHERE status = 'running'",
        (finished_at, finished_at),
    )
    # Paused runs stay paused so the user can resume them after a restart.
    cursor = conn.execute(
        "UPDATE ai_runs SET status = 'failed', "
        "error_message = 'Sidecar 重启，任务被中断', finished_at = ?, updated_at = ? "
        "WHERE status = 'running'",
        (finished_at, finished_at),
    )
    return int(cursor.rowcount)


def find_active_run(conn: sqlite3.Connection, *, scope: str | None = None) -> AIRunRecord | None:
    where = "WHERE status IN ('pending','running','paused')"
    params: list[object] = []
    if scope is not None:
        where += " AND scope = ?"
        params.append(scope)
    row = conn.execute(
        f"SELECT * FROM ai_runs {where} ORDER BY created_at ASC LIMIT 1",
        tuple(params),
    ).fetchone()
    return None if row is None else _run_from_row(row)


def retryable_article_ids(conn: sqlite3.Connection, run_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT article_id FROM ai_run_items WHERE run_id = ? "
        "AND status IN ('failed','cancelled','pending') ORDER BY created_at ASC",
        (run_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def prune_runs(conn: sqlite3.Connection, keep: int) -> None:
    conn.execute(
        "DELETE FROM ai_runs WHERE id IN ("
        "SELECT id FROM ai_runs ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?"
        ")",
        (keep,),
    )


def list_pending_run_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM ai_runs WHERE status = 'pending' ORDER BY created_at ASC"
    ).fetchall()
    return [str(row[0]) for row in rows]


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM ai_runs GROUP BY status"
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}
