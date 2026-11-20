"""Parameterised SQL for `collection_jobs` and `collection_job_items`."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import CollectionJobItemRecord, CollectionJobRecord

_JOB_COLUMNS = (
    "id",
    "trigger_type",
    "scope",
    "status",
    "requested_source_count",
    "processed_source_count",
    "succeeded_source_count",
    "failed_source_count",
    "discovered_count",
    "inserted_count",
    "updated_count",
    "duplicate_count",
    "error_count",
    "error_message",
    "cancel_requested",
    "started_at",
    "finished_at",
    "duration_ms",
    "created_at",
    "updated_at",
)

_JOB_UPDATE_ALLOWED = set(_JOB_COLUMNS) - {"id", "trigger_type", "scope", "created_at"}

_ITEM_COLUMNS = (
    "id",
    "job_id",
    "source_id",
    "status",
    "http_status",
    "discovered_count",
    "inserted_count",
    "updated_count",
    "duplicate_count",
    "error_count",
    "error_code",
    "error_message",
    "started_at",
    "finished_at",
    "duration_ms",
    "created_at",
    "updated_at",
)

_ITEM_UPDATE_ALLOWED = set(_ITEM_COLUMNS) - {"id", "job_id", "source_id", "created_at"}


def _job_from_row(row: sqlite3.Row, items: tuple[CollectionJobItemRecord, ...] = ()) -> CollectionJobRecord:
    return CollectionJobRecord(
        id=str(row["id"]),
        trigger_type=str(row["trigger_type"]),
        scope=str(row["scope"]),
        status=str(row["status"]),
        requested_source_count=int(row["requested_source_count"]),
        processed_source_count=int(row["processed_source_count"]),
        succeeded_source_count=int(row["succeeded_source_count"]),
        failed_source_count=int(row["failed_source_count"]),
        discovered_count=int(row["discovered_count"]),
        inserted_count=int(row["inserted_count"]),
        updated_count=int(row["updated_count"]),
        duplicate_count=int(row["duplicate_count"]),
        error_count=int(row["error_count"]),
        error_message=row["error_message"],
        cancel_requested=bool(int(row["cancel_requested"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        items=items,
    )


def _item_from_row(row: sqlite3.Row) -> CollectionJobItemRecord:
    return CollectionJobItemRecord(
        id=str(row["id"]),
        job_id=str(row["job_id"]),
        source_id=str(row["source_id"]),
        source_name=row["source_name"],
        status=str(row["status"]),
        http_status=row["http_status"],
        discovered_count=int(row["discovered_count"]),
        inserted_count=int(row["inserted_count"]),
        updated_count=int(row["updated_count"]),
        duplicate_count=int(row["duplicate_count"]),
        error_count=int(row["error_count"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def insert_job(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_JOB_COLUMNS)
    placeholders = ", ".join("?" for _ in _JOB_COLUMNS)
    conn.execute(
        f"INSERT INTO collection_jobs ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _JOB_COLUMNS),
    )


def insert_item(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_ITEM_COLUMNS)
    placeholders = ", ".join("?" for _ in _ITEM_COLUMNS)
    conn.execute(
        f"INSERT INTO collection_job_items ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _ITEM_COLUMNS),
    )


def update_job(conn: sqlite3.Connection, job_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _JOB_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE collection_jobs SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), job_id),
    )


def update_item(conn: sqlite3.Connection, item_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _ITEM_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE collection_job_items SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), item_id),
    )


def get_job(
    conn: sqlite3.Connection, job_id: str, *, with_items: bool = True
) -> CollectionJobRecord | None:
    row = conn.execute(
        "SELECT * FROM collection_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        return None
    items = tuple(list_items(conn, job_id)) if with_items else ()
    return _job_from_row(row, items)


def list_jobs(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[CollectionJobRecord], int]:
    if status is None:
        where_sql, params = "", []
    else:
        where_sql, params = "WHERE status = ?", [status]
    rows = conn.execute(
        f"""
        SELECT * FROM collection_jobs
        {where_sql}
        ORDER BY created_at DESC, id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM collection_jobs {where_sql}", tuple(params)
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_job_from_row(row) for row in rows], total


def list_items(conn: sqlite3.Connection, job_id: str) -> list[CollectionJobItemRecord]:
    rows = conn.execute(
        """
        SELECT i.*, s.name AS source_name
        FROM collection_job_items AS i
        LEFT JOIN sources AS s ON s.id = i.source_id
        WHERE i.job_id = ?
        ORDER BY i.created_at ASC, i.id ASC
        """,
        (job_id,),
    ).fetchall()
    return [_item_from_row(row) for row in rows]


def get_item(conn: sqlite3.Connection, item_id: str) -> CollectionJobItemRecord | None:
    row = conn.execute(
        """
        SELECT i.*, s.name AS source_name
        FROM collection_job_items AS i
        LEFT JOIN sources AS s ON s.id = i.source_id
        WHERE i.id = ?
        """,
        (item_id,),
    ).fetchone()
    return None if row is None else _item_from_row(row)


def claim_item(conn: sqlite3.Connection, item_id: str, now: str) -> bool:
    """Atomically move one item from pending to running.

    The partial unique index on running items makes a concurrent claim for the
    same source fail with IntegrityError; callers treat that as "skipped".
    """

    cursor = conn.execute(
        """
        UPDATE collection_job_items
        SET status = 'running', started_at = ?, updated_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (now, now, item_id),
    )
    return cursor.rowcount == 1


def source_is_running(conn: sqlite3.Connection, source_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM collection_job_items WHERE source_id = ? AND status = 'running' LIMIT 1",
        (source_id,),
    ).fetchone()
    return row is not None


def source_has_active_item(conn: sqlite3.Connection, source_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM collection_job_items
        WHERE source_id = ? AND status IN ('pending','running')
        LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    return row is not None


def cancel_pending_items(conn: sqlite3.Connection, job_id: str, now: str) -> None:
    conn.execute(
        """
        UPDATE collection_job_items
        SET status = 'cancelled', finished_at = ?, updated_at = ?
        WHERE job_id = ? AND status = 'pending'
        """,
        (now, now, job_id),
    )


def retryable_source_ids(conn: sqlite3.Connection, job_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT source_id FROM collection_job_items
        WHERE job_id = ? AND status IN ('failed','cancelled')
        ORDER BY source_id
        """,
        (job_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def recompute_job_totals(conn: sqlite3.Connection, job_id: str) -> None:
    """Recompute counters from items so summaries always match real work."""

    conn.execute(
        """
        UPDATE collection_jobs SET
            processed_source_count = (
                SELECT COUNT(*) FROM collection_job_items
                WHERE job_id = ? AND status IN
                      ('succeeded','failed','skipped','cancelled')
            ),
            succeeded_source_count = (
                SELECT COUNT(*) FROM collection_job_items
                WHERE job_id = ? AND status = 'succeeded'
            ),
            failed_source_count = (
                SELECT COUNT(*) FROM collection_job_items
                WHERE job_id = ? AND status = 'failed'
            ),
            discovered_count = (
                SELECT COALESCE(SUM(discovered_count), 0) FROM collection_job_items
                WHERE job_id = ?
            ),
            inserted_count = (
                SELECT COALESCE(SUM(inserted_count), 0) FROM collection_job_items
                WHERE job_id = ?
            ),
            updated_count = (
                SELECT COALESCE(SUM(updated_count), 0) FROM collection_job_items
                WHERE job_id = ?
            ),
            duplicate_count = (
                SELECT COALESCE(SUM(duplicate_count), 0) FROM collection_job_items
                WHERE job_id = ?
            ),
            error_count = (
                SELECT COALESCE(SUM(error_count), 0) FROM collection_job_items
                WHERE job_id = ?
            )
        WHERE id = ?
        """,
        (job_id,) * 8 + (job_id,),
    )


def mark_stale_jobs(conn: sqlite3.Connection, now: str) -> int:
    """Startup recovery: running work cannot survive a process restart."""

    stale_job_ids = [
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM collection_jobs WHERE status IN ('pending','running')"
        ).fetchall()
    ]
    conn.execute(
        """
        UPDATE collection_job_items
        SET status = 'failed', error_code = 'interrupted',
            error_message = '服务重启导致采集中断', finished_at = ?,
            updated_at = ?, error_count = error_count + 1
        WHERE status IN ('pending','running')
        """,
        (now, now),
    )
    cursor = conn.execute(
        """
        UPDATE collection_jobs
        SET status = 'failed', error_message = '服务重启导致采集中断',
            finished_at = ?, updated_at = ?
        WHERE status IN ('pending','running')
        """,
        (now, now),
    )
    for job_id in stale_job_ids:
        recompute_job_totals(conn, job_id)
    return cursor.rowcount


def prune_jobs(conn: sqlite3.Connection, keep: int) -> int:
    row = conn.execute("SELECT COUNT(*) FROM collection_jobs").fetchone()
    total = int(row[0]) if row is not None else 0
    if total <= keep:
        return 0
    cursor = conn.execute(
        """
        DELETE FROM collection_jobs
        WHERE id IN (
            SELECT id FROM collection_jobs
            ORDER BY created_at DESC, id ASC
            LIMIT -1 OFFSET ?
        )
        """,
        (keep,),
    )
    return cursor.rowcount
