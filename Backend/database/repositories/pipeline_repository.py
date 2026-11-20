"""Parameterised SQL for the Phase 7.2 pipeline orchestrator.

Every write goes through a caller-owned `database.session()` transaction. The
repository never starts its own transaction and never touches business tables
directly other than the read-only joins needed for backfill previews.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

TASK_COLUMNS = (
    "id",
    "task_type",
    "article_id",
    "event_id",
    "stage",
    "status",
    "priority",
    "idempotency_key",
    "attempts",
    "max_attempts",
    "next_retry_at",
    "lease_owner",
    "lease_expires_at",
    "last_heartbeat_at",
    "error_code",
    "error_message",
    "input_summary",
    "output_summary",
    "trigger_type",
    "batch_id",
    "created_at",
    "started_at",
    "completed_at",
    "updated_at",
)

_TASK_UPDATE_ALLOWED = set(TASK_COLUMNS) - {"id", "task_type", "idempotency_key", "created_at"}

RUN_COLUMNS = (
    "id",
    "trigger_type",
    "status",
    "requested_tasks",
    "created_tasks",
    "processed_tasks",
    "succeeded_tasks",
    "failed_tasks",
    "skipped_tasks",
    "cancel_requested",
    "error_message",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
)

_RUN_UPDATE_ALLOWED = set(RUN_COLUMNS) - {"id", "trigger_type", "created_at"}

SETTINGS_COLUMNS = (
    "id",
    "automation_enabled",
    "paused",
    "ai_enabled",
    "entity_enabled",
    "event_enabled",
    "scoring_enabled",
    "batch_size",
    "max_attempts",
    "ai_interval_seconds",
    "updated_at",
)

ACTIVE_STATUSES = ("pending", "ready", "running", "retry_wait")
TERMINAL_STATUSES = ("succeeded", "failed", "skipped", "cancelled")


@dataclass(frozen=True, slots=True)
class PipelineTaskRecord:
    id: str
    task_type: str
    article_id: str | None
    event_id: str | None
    stage: str
    status: str
    priority: int
    idempotency_key: str
    attempts: int
    max_attempts: int
    next_retry_at: str | None
    lease_owner: str | None
    lease_expires_at: str | None
    last_heartbeat_at: str | None
    error_code: str | None
    error_message: str | None
    input_summary: str | None
    output_summary: str | None
    trigger_type: str
    batch_id: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str
    article_title: str | None = None
    source_name: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineTaskLogRecord:
    id: str
    task_id: str
    stage: str | None
    level: str
    message: str
    detail: dict[str, object]
    created_at: str


@dataclass(frozen=True, slots=True)
class PipelineSettingsRecord:
    automation_enabled: bool
    paused: bool
    ai_enabled: bool
    entity_enabled: bool
    event_enabled: bool
    scoring_enabled: bool
    batch_size: int
    max_attempts: int
    ai_interval_seconds: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class PipelineRunRecord:
    id: str
    trigger_type: str
    status: str
    requested_tasks: int
    created_tasks: int
    processed_tasks: int
    succeeded_tasks: int
    failed_tasks: int
    skipped_tasks: int
    cancel_requested: bool
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    updated_at: str


def _task_from_row(row: sqlite3.Row) -> PipelineTaskRecord:
    keys = set(row.keys())
    return PipelineTaskRecord(
        id=str(row["id"]),
        task_type=str(row["task_type"]),
        article_id=row["article_id"],
        event_id=row["event_id"],
        stage=str(row["stage"]),
        status=str(row["status"]),
        priority=int(row["priority"]),
        idempotency_key=str(row["idempotency_key"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        next_retry_at=row["next_retry_at"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        last_heartbeat_at=row["last_heartbeat_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        input_summary=row["input_summary"],
        output_summary=row["output_summary"],
        trigger_type=str(row["trigger_type"]),
        batch_id=row["batch_id"],
        created_at=str(row["created_at"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        updated_at=str(row["updated_at"]),
        article_title=row["article_title"] if "article_title" in keys else None,
        source_name=row["source_name"] if "source_name" in keys else None,
    )


def _log_from_row(row: sqlite3.Row) -> PipelineTaskLogRecord:
    try:
        detail = json.loads(str(row["detail_json"]))
    except (TypeError, json.JSONDecodeError):
        detail = {}
    return PipelineTaskLogRecord(
        id=str(row["id"]),
        task_id=str(row["task_id"]),
        stage=row["stage"],
        level=str(row["level"]),
        message=str(row["message"]),
        detail=detail if isinstance(detail, dict) else {},
        created_at=str(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def insert_task(conn: sqlite3.Connection, values: Mapping[str, object]) -> bool:
    """Insert one task; a duplicate idempotency key is a no-op.

    Returns True when a new row was written.
    """

    columns = ", ".join(TASK_COLUMNS)
    placeholders = ", ".join("?" for _ in TASK_COLUMNS)
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO pipeline_tasks ({columns}) VALUES ({placeholders})",
        tuple(values[column] for column in TASK_COLUMNS),
    )
    return cursor.rowcount == 1


_TASK_JOIN = (
    "SELECT t.*, a.title AS article_title, s.name AS source_name "
    "FROM pipeline_tasks AS t "
    "LEFT JOIN articles AS a ON a.id = t.article_id "
    "LEFT JOIN sources AS s ON s.id = a.source_id "
)


def get_task(conn: sqlite3.Connection, task_id: str) -> PipelineTaskRecord | None:
    row = conn.execute(_TASK_JOIN + "WHERE t.id = ?", (task_id,)).fetchone()
    return None if row is None else _task_from_row(row)


def get_task_by_idempotency(
    conn: sqlite3.Connection, idempotency_key: str
) -> PipelineTaskRecord | None:
    row = conn.execute(
        _TASK_JOIN + "WHERE t.idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return None if row is None else _task_from_row(row)


def get_task_for_article(
    conn: sqlite3.Connection, article_id: str
) -> PipelineTaskRecord | None:
    row = conn.execute(
        _TASK_JOIN + "WHERE t.article_id = ? ORDER BY t.created_at DESC LIMIT 1",
        (article_id,),
    ).fetchone()
    return None if row is None else _task_from_row(row)


def list_tasks(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    stage: str | None = None,
    trigger_type: str | None = None,
) -> tuple[list[PipelineTaskRecord], int]:
    clauses: list[str] = []
    params: list[object] = []
    if status is not None:
        values = [item.strip() for item in status.split(",") if item.strip()]
        if len(values) == 1:
            clauses.append("t.status = ?")
            params.append(values[0])
        elif values:
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"t.status IN ({placeholders})")
            params.extend(values)
    if stage is not None:
        clauses.append("t.stage = ?")
        params.append(stage)
    if trigger_type is not None:
        clauses.append("t.trigger_type = ?")
        params.append(trigger_type)
    where = "" if not clauses else "WHERE " + " AND ".join(clauses)
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM pipeline_tasks AS t {where}", tuple(params)
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    rows = conn.execute(
        _TASK_JOIN
        + where
        + " ORDER BY t.updated_at DESC, t.created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    ).fetchall()
    return [_task_from_row(row) for row in rows], total


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM pipeline_tasks GROUP BY status"
    ).fetchall()
    return {str(row["status"]): int(row["n"]) for row in rows}


def count_by_stage(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT stage, COUNT(*) AS n FROM pipeline_tasks "
        "WHERE status IN ('pending','ready','running','retry_wait') GROUP BY stage"
    ).fetchall()
    return {str(row["stage"]): int(row["n"]) for row in rows}


def _claim(
    conn: sqlite3.Connection,
    *,
    where: str,
    params: tuple[object, ...],
    owner: str,
    now: str,
    lease_until: str,
    limit: int,
) -> list[PipelineTaskRecord]:
    rows = conn.execute(
        "SELECT id FROM pipeline_tasks t "
        f"WHERE {where} ORDER BY t.priority ASC, t.created_at ASC LIMIT ?",
        params + (limit,),
    ).fetchall()
    ids = [str(row[0]) for row in rows]
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    conn.execute(
        f"UPDATE pipeline_tasks SET status = 'running', lease_owner = ?, "
        f"lease_expires_at = ?, last_heartbeat_at = ?, "
        f"started_at = COALESCE(started_at, ?), updated_at = ? "
        f"WHERE id IN ({placeholders})",
        (owner, lease_until, now, now, now, *ids),
    )
    claimed = conn.execute(
        _TASK_JOIN + f"WHERE t.id IN ({placeholders}) "
        "ORDER BY t.priority ASC, t.created_at ASC",
        tuple(ids),
    ).fetchall()
    return [_task_from_row(row) for row in claimed]


def claim_ready(
    conn: sqlite3.Connection,
    *,
    owner: str,
    now: str,
    lease_until: str,
    limit: int,
) -> list[PipelineTaskRecord]:
    """Claim pending/ready tasks and retry_wait tasks whose backoff elapsed.

    Phase 7.2.1: `retry_wait` rows used to be a terminal resting state — nothing
    ever promoted them back into the queue, so an expired lease or a transient
    model failure parked the task forever. Tasks parked at `event_match` are
    excluded because that stage is claimed by the batch phase.
    """

    return _claim(
        conn,
        where=(
            "t.status IN ('pending','ready','retry_wait') "
            "AND t.stage <> 'event_match' "
            "AND (t.next_retry_at IS NULL OR t.next_retry_at <= ?)"
        ),
        params=(now,),
        owner=owner,
        now=now,
        lease_until=lease_until,
        limit=limit,
    )


def claim_stage(
    conn: sqlite3.Connection,
    *,
    stage: str,
    owner: str,
    now: str,
    lease_until: str,
    limit: int,
) -> list[PipelineTaskRecord]:
    """Claim tasks already parked at a specific stage (batch event matching)."""

    return _claim(
        conn,
        where=(
            "t.stage = ? AND t.status IN ('pending','ready','retry_wait') "
            "AND (t.next_retry_at IS NULL OR t.next_retry_at <= ?)"
        ),
        params=(stage, now),
        owner=owner,
        now=now,
        lease_until=lease_until,
        limit=limit,
    )


def update_task(
    conn: sqlite3.Connection, task_id: str, fields: Mapping[str, object]
) -> None:
    unknown = set(fields) - _TASK_UPDATE_ALLOWED
    if unknown:
        raise ValueError(f"unknown pipeline task fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn.execute(
        f"UPDATE pipeline_tasks SET {assignments} WHERE id = ?",
        tuple(fields.values()) + (task_id,),
    )


def release_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    now: str,
    status: str = "ready",
) -> None:
    update_task(
        conn,
        task_id,
        {
            "status": status,
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": now,
        },
    )


def recover_expired_leases(
    conn: sqlite3.Connection, *, now: str
) -> list[str]:
    """Return running tasks whose lease expired and park them for retry."""

    rows = conn.execute(
        "SELECT id, attempts, max_attempts FROM pipeline_tasks "
        "WHERE status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at < ?)",
        (now,),
    ).fetchall()
    recovered: list[str] = []
    for row in rows:
        task_id = str(row["id"])
        attempts = int(row["attempts"]) + 1
        if attempts >= int(row["max_attempts"]):
            update_task(
                conn,
                task_id,
                {
                    "status": "failed",
                    "attempts": attempts,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": now,
                    "error_code": "lease_expired",
                    "error_message": "任务租约过期且已达最大尝试次数",
                    "updated_at": now,
                },
            )
        else:
            update_task(
                conn,
                task_id,
                {
                    "status": "retry_wait",
                    "attempts": attempts,
                    "next_retry_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "error_code": "lease_expired",
                    "error_message": "任务执行中断，租约过期后重新排队",
                    "updated_at": now,
                },
            )
        recovered.append(task_id)
    return recovered


def touch_lease(
    conn: sqlite3.Connection, task_id: str, *, owner: str, now: str, lease_until: str
) -> None:
    update_task(
        conn,
        task_id,
        {
            "lease_owner": owner,
            "lease_expires_at": lease_until,
            "last_heartbeat_at": now,
            "updated_at": now,
        },
    )


def has_ready_backfill(conn: sqlite3.Connection, *, now: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pipeline_tasks WHERE trigger_type = 'backfill' "
        "AND status IN ('pending','ready','retry_wait') "
        "AND (next_retry_at IS NULL OR next_retry_at <= ?) LIMIT 1",
        (now,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def add_log(
    conn: sqlite3.Connection,
    *,
    log_id: str,
    task_id: str,
    stage: str | None,
    level: str,
    message: str,
    detail: Mapping[str, object] | None,
    created_at: str,
) -> None:
    payload = json.dumps(dict(detail or {}), ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 12000:
        payload = json.dumps({"truncated": True}, separators=(",", ":"))
    conn.execute(
        "INSERT INTO pipeline_task_logs "
        "(id, task_id, stage, level, message, detail_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (log_id, task_id, stage, level, message[:2000], payload, created_at),
    )


def list_logs(
    conn: sqlite3.Connection, task_id: str, *, limit: int, offset: int
) -> tuple[list[PipelineTaskLogRecord], int]:
    total_row = conn.execute(
        "SELECT COUNT(*) FROM pipeline_task_logs WHERE task_id = ?", (task_id,)
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    rows = conn.execute(
        "SELECT * FROM pipeline_task_logs WHERE task_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (task_id, limit, offset),
    ).fetchall()
    return [_log_from_row(row) for row in rows], total


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings(conn: sqlite3.Connection) -> PipelineSettingsRecord:
    row = conn.execute("SELECT * FROM pipeline_settings WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("pipeline_settings row is missing")
    return PipelineSettingsRecord(
        automation_enabled=bool(int(row["automation_enabled"])),
        paused=bool(int(row["paused"])),
        ai_enabled=bool(int(row["ai_enabled"])),
        entity_enabled=bool(int(row["entity_enabled"])),
        event_enabled=bool(int(row["event_enabled"])),
        scoring_enabled=bool(int(row["scoring_enabled"])),
        batch_size=int(row["batch_size"]),
        max_attempts=int(row["max_attempts"]),
        ai_interval_seconds=int(row["ai_interval_seconds"]),
        updated_at=str(row["updated_at"]),
    )


def update_settings(
    conn: sqlite3.Connection, fields: Mapping[str, object], *, updated_at: str
) -> PipelineSettingsRecord:
    allowed = set(SETTINGS_COLUMNS) - {"id", "updated_at"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown pipeline settings: {sorted(unknown)}")
    values = dict(fields)
    values["updated_at"] = updated_at
    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(
        f"UPDATE pipeline_settings SET {assignments} WHERE id = 1",
        tuple(values.values()),
    )
    return get_settings(conn)


# ---------------------------------------------------------------------------
# Backfill runs
# ---------------------------------------------------------------------------


def insert_run(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(RUN_COLUMNS)
    placeholders = ", ".join("?" for _ in RUN_COLUMNS)
    conn.execute(
        f"INSERT INTO pipeline_runs ({columns}) VALUES ({placeholders})",
        tuple(values[column] for column in RUN_COLUMNS),
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> PipelineRunRecord | None:
    row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return PipelineRunRecord(
        id=str(row["id"]),
        trigger_type=str(row["trigger_type"]),
        status=str(row["status"]),
        requested_tasks=int(row["requested_tasks"]),
        created_tasks=int(row["created_tasks"]),
        processed_tasks=int(row["processed_tasks"]),
        succeeded_tasks=int(row["succeeded_tasks"]),
        failed_tasks=int(row["failed_tasks"]),
        skipped_tasks=int(row["skipped_tasks"]),
        cancel_requested=bool(int(row["cancel_requested"])),
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def list_runs(
    conn: sqlite3.Connection, *, limit: int, offset: int
) -> tuple[list[PipelineRunRecord], int]:
    total_row = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    ids = conn.execute(
        "SELECT id FROM pipeline_runs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    records = [get_run(conn, str(row[0])) for row in ids]
    return [record for record in records if record is not None], total


def update_run(
    conn: sqlite3.Connection, run_id: str, fields: Mapping[str, object]
) -> None:
    unknown = set(fields) - _RUN_UPDATE_ALLOWED
    if unknown:
        raise ValueError(f"unknown pipeline run fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn.execute(
        f"UPDATE pipeline_runs SET {assignments} WHERE id = ?",
        tuple(fields.values()) + (run_id,),
    )


def cancel_pending_tasks_for_run(
    conn: sqlite3.Connection, run_id: str, *, now: str
) -> int:
    """Cancel queued tasks of a backfill batch; running tasks are left alone."""

    cursor = conn.execute(
        "UPDATE pipeline_tasks SET status = 'cancelled', completed_at = ?, "
        "lease_owner = NULL, lease_expires_at = NULL, updated_at = ? "
        "WHERE batch_id = ? AND status IN ('pending','ready','retry_wait')",
        (now, now, run_id),
    )
    return cursor.rowcount


def refresh_run_counters(conn: sqlite3.Connection, run_id: str, *, now: str) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded, "
        "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
        "SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped, "
        "SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled, "
        "SUM(CASE WHEN status IN ('succeeded','failed','skipped','cancelled') THEN 1 ELSE 0 END) "
        "AS processed FROM pipeline_tasks WHERE batch_id = ?",
        (run_id,),
    ).fetchone()
    total = int(row["total"] or 0) if row is not None else 0
    processed = int(row["processed"] or 0) if row is not None else 0
    succeeded = int(row["succeeded"] or 0) if row is not None else 0
    failed = int(row["failed"] or 0) if row is not None else 0
    skipped = int(row["skipped"] or 0) if row is not None else 0
    cancelled = int(row["cancelled"] or 0) if row is not None else 0

    run = get_run(conn, run_id)
    if run is None:
        return
    fields: dict[str, object] = {
        "processed_tasks": processed,
        "succeeded_tasks": succeeded,
        "failed_tasks": failed,
        "skipped_tasks": skipped,
        "updated_at": now,
    }
    if processed >= total and total > 0:
        if run.cancel_requested or cancelled:
            fields["status"] = "cancelled"
        elif failed == 0:
            fields["status"] = "succeeded"
        elif succeeded + skipped > 0:
            fields["status"] = "partially_succeeded"
        else:
            fields["status"] = "failed"
        fields["finished_at"] = now
    elif processed > 0:
        fields["status"] = "running"
    update_run(conn, run_id, fields)


# ---------------------------------------------------------------------------
# Backfill preview helpers (read-only aggregates)
# ---------------------------------------------------------------------------


def backfill_preview(conn: sqlite3.Connection) -> dict[str, int]:
    """Count articles that still need the pipeline, without creating tasks."""

    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN NOT EXISTS (
                    SELECT 1 FROM article_ai_analysis AS x
                    WHERE x.article_id = a.id AND x.content_hash = a.content_hash
                ) THEN 1 ELSE 0 END) AS ai_needed,
            SUM(CASE WHEN NOT EXISTS (
                    SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id
                ) THEN 1 ELSE 0 END) AS event_needed
        FROM articles AS a
        WHERE a.deleted_at IS NULL AND a.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM pipeline_tasks AS t WHERE t.article_id = a.id)
          AND (
              NOT EXISTS (
                  SELECT 1 FROM article_ai_analysis AS x
                  WHERE x.article_id = a.id AND x.content_hash = a.content_hash
              )
              OR NOT EXISTS (SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id)
          )
        """
    ).fetchone()
    total = int(row["total"] or 0) if row is not None else 0
    ai_needed = int(row["ai_needed"] or 0) if row is not None else 0
    event_needed = int(row["event_needed"] or 0) if row is not None else 0
    return {
        "pending_articles": total,
        "ai_needed": ai_needed,
        "event_needed": event_needed,
    }


def next_backfill_article_ids(conn: sqlite3.Connection, *, limit: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT a.id FROM articles AS a
        WHERE a.deleted_at IS NULL AND a.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM pipeline_tasks AS t WHERE t.article_id = a.id)
          AND (
              NOT EXISTS (
                  SELECT 1 FROM article_ai_analysis AS x
                  WHERE x.article_id = a.id AND x.content_hash = a.content_hash
              )
              OR NOT EXISTS (SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id)
          )
        ORDER BY a.created_at ASC, a.id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def recent_activity(conn: sqlite3.Connection) -> dict[str, object]:
    """Last completion/failure timestamps and the most recent error."""

    row = conn.execute(
        "SELECT MAX(completed_at) AS last_completed FROM pipeline_tasks "
        "WHERE status IN ('succeeded','failed','skipped','cancelled')"
    ).fetchone()
    last_succeeded = conn.execute(
        "SELECT MAX(completed_at) FROM pipeline_tasks WHERE status = 'succeeded'"
    ).fetchone()
    error_row = conn.execute(
        "SELECT error_code, error_message, completed_at FROM pipeline_tasks "
        "WHERE status = 'failed' ORDER BY COALESCE(completed_at, updated_at) DESC LIMIT 1"
    ).fetchone()
    return {
        "last_completed_at": None if row is None else row["last_completed"],
        "last_succeeded_at": None if last_succeeded is None else last_succeeded[0],
        "last_error": None
        if error_row is None
        else {
            "error_code": error_row["error_code"],
            "error_message": error_row["error_message"],
            "at": error_row["completed_at"],
        },
    }


def today_counts(conn: sqlite3.Connection, *, since: str) -> dict[str, int]:
    row = conn.execute(
        "SELECT "
        "SUM(CASE WHEN status = 'succeeded' AND completed_at >= ? THEN 1 ELSE 0 END) AS ok, "
        "SUM(CASE WHEN status = 'failed' AND completed_at >= ? THEN 1 ELSE 0 END) AS bad, "
        "SUM(CASE WHEN status = 'skipped' AND completed_at >= ? THEN 1 ELSE 0 END) AS skipped "
        "FROM pipeline_tasks",
        (since, since, since),
    ).fetchone()
    if row is None:
        return {"succeeded": 0, "failed": 0, "skipped": 0}
    return {
        "succeeded": int(row["ok"] or 0),
        "failed": int(row["bad"] or 0),
        "skipped": int(row["skipped"] or 0),
    }


__all__ = [
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "PipelineRunRecord",
    "PipelineSettingsRecord",
    "PipelineTaskLogRecord",
    "PipelineTaskRecord",
    "add_log",
    "backfill_preview",
    "cancel_pending_tasks_for_run",
    "claim_ready",
    "claim_stage",
    "count_by_stage",
    "count_by_status",
    "get_run",
    "get_settings",
    "get_task",
    "get_task_by_idempotency",
    "get_task_for_article",
    "has_ready_backfill",
    "insert_run",
    "insert_task",
    "list_logs",
    "list_runs",
    "list_tasks",
    "next_backfill_article_ids",
    "recent_activity",
    "recover_expired_leases",
    "refresh_run_counters",
    "release_task",
    "today_counts",
    "touch_lease",
    "update_run",
    "update_settings",
    "update_task",
]
