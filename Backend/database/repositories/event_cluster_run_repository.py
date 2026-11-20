"""Parameterised SQL for clustering runs and per-article decisions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from .models import EventClusterRunRecord, EventDecisionRecord

_RUN_COLUMNS = (
    "id",
    "trigger_type",
    "scope",
    "status",
    "requested_count",
    "processed_count",
    "attached_count",
    "created_event_count",
    "updated_event_count",
    "candidate_pair_count",
    "ambiguous_count",
    "llm_called_count",
    "llm_accepted_count",
    "skipped_count",
    "failed_count",
    "use_llm",
    "article_ids_json",
    "model_name",
    "error_message",
    "cancel_requested",
    "started_at",
    "finished_at",
    "duration_ms",
    "created_at",
    "updated_at",
)

_RUN_UPDATE_ALLOWED = set(_RUN_COLUMNS) - {"id", "trigger_type", "scope", "created_at"}

_DECISION_COLUMNS = (
    "id",
    "run_id",
    "article_id",
    "candidate_event_id",
    "decision",
    "score",
    "reasons_json",
    "method",
    "llm_used",
    "status",
    "created_at",
    "resolved_at",
)


def _run_from_row(row: sqlite3.Row) -> EventClusterRunRecord:
    try:
        article_ids = tuple(
            str(item) for item in json.loads(str(row["article_ids_json"])) if isinstance(item, str)
        )
    except (TypeError, json.JSONDecodeError):
        article_ids = ()
    return EventClusterRunRecord(
        id=str(row["id"]),
        trigger_type=str(row["trigger_type"]),
        scope=str(row["scope"]),
        status=str(row["status"]),
        requested_count=int(row["requested_count"]),
        processed_count=int(row["processed_count"]),
        attached_count=int(row["attached_count"]),
        created_event_count=int(row["created_event_count"]),
        updated_event_count=int(row["updated_event_count"]),
        candidate_pair_count=int(row["candidate_pair_count"]),
        ambiguous_count=int(row["ambiguous_count"]),
        llm_called_count=int(row["llm_called_count"]),
        llm_accepted_count=int(row["llm_accepted_count"]),
        skipped_count=int(row["skipped_count"]),
        failed_count=int(row["failed_count"]),
        use_llm=bool(int(row["use_llm"])),
        model_name=row["model_name"],
        error_message=row["error_message"],
        cancel_requested=bool(int(row["cancel_requested"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        article_ids=article_ids,
    )


def _decision_from_row(row: sqlite3.Row) -> EventDecisionRecord:
    try:
        reasons = json.loads(str(row["reasons_json"]))
    except (TypeError, json.JSONDecodeError):
        reasons = []
    keys = set(row.keys())
    return EventDecisionRecord(
        id=str(row["id"]),
        run_id=row["run_id"],
        article_id=str(row["article_id"]),
        candidate_event_id=row["candidate_event_id"],
        decision=str(row["decision"]),
        score=None if row["score"] is None else float(row["score"]),
        reasons=tuple(str(item) for item in reasons if isinstance(item, str)),
        method=str(row["method"]),
        llm_used=bool(int(row["llm_used"])),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        resolved_at=row["resolved_at"],
        article_title=row["article_title"] if "article_title" in keys else None,
        candidate_event_title=(
            row["candidate_event_title"] if "candidate_event_title" in keys else None
        ),
    )


def insert_run(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_RUN_COLUMNS)
    placeholders = ", ".join("?" for _ in _RUN_COLUMNS)
    conn.execute(
        f"INSERT INTO event_cluster_runs ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _RUN_COLUMNS),
    )


def update_run(conn: sqlite3.Connection, run_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _RUN_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE event_cluster_runs SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), run_id),
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> EventClusterRunRecord | None:
    row = conn.execute(
        "SELECT * FROM event_cluster_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return None if row is None else _run_from_row(row)


def list_runs(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[EventClusterRunRecord], int]:
    clause = "WHERE status = ?" if status else ""
    params: list[object] = [status] if status else []
    rows = conn.execute(
        f"SELECT * FROM event_cluster_runs {clause} "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM event_cluster_runs {clause}", tuple(params)
    ).fetchone()
    return (
        [_run_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def find_active_run(conn: sqlite3.Connection, *, scope: str) -> EventClusterRunRecord | None:
    row = conn.execute(
        "SELECT * FROM event_cluster_runs WHERE scope = ? "
        "AND status IN ('pending','running') ORDER BY created_at DESC LIMIT 1",
        (scope,),
    ).fetchone()
    return None if row is None else _run_from_row(row)


def any_active_run(conn: sqlite3.Connection) -> EventClusterRunRecord | None:
    row = conn.execute(
        "SELECT * FROM event_cluster_runs WHERE status IN ('pending','running') "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return None if row is None else _run_from_row(row)


def latest_run(conn: sqlite3.Connection) -> EventClusterRunRecord | None:
    row = conn.execute(
        "SELECT * FROM event_cluster_runs ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return None if row is None else _run_from_row(row)


def list_pending_run_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM event_cluster_runs WHERE status = 'pending' ORDER BY created_at ASC"
    ).fetchall()
    return [str(row[0]) for row in rows]


def mark_stale(conn: sqlite3.Connection, now: str) -> int:
    cursor = conn.execute(
        "UPDATE event_cluster_runs SET status = 'failed', "
        "error_message = '运行被中断（服务重启）', finished_at = ?, updated_at = ? "
        "WHERE status = 'running'",
        (now, now),
    )
    return int(cursor.rowcount or 0)


def prune_runs(conn: sqlite3.Connection, keep: int = 200) -> int:
    row = conn.execute(
        "SELECT id FROM event_cluster_runs ORDER BY created_at DESC, id DESC LIMIT 1 OFFSET ?",
        (max(0, keep - 1),),
    ).fetchone()
    if row is None:
        return 0
    cursor = conn.execute(
        "DELETE FROM event_cluster_runs WHERE (created_at, id) < "
        "(SELECT created_at, id FROM event_cluster_runs WHERE id = ?)",
        (str(row["id"]),),
    )
    return int(cursor.rowcount or 0)


def prune_decisions(conn: sqlite3.Connection, keep_runs: int = 200) -> int:
    """Drop candidate decisions that belong to runs beyond the kept window.

    Decisions of the most recent `keep_runs` runs are preserved so the event
    center can still explain recent clustering choices.
    """

    cursor = conn.execute(
        """
        DELETE FROM event_candidate_decisions
        WHERE run_id IS NOT NULL
          AND run_id NOT IN (
              SELECT id FROM event_cluster_runs
              ORDER BY created_at DESC, id DESC LIMIT ?
          )
        """,
        (max(1, keep_runs),),
    )
    return int(cursor.rowcount or 0)


def insert_decision(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_DECISION_COLUMNS)
    placeholders = ", ".join("?" for _ in _DECISION_COLUMNS)
    conn.execute(
        f"INSERT INTO event_candidate_decisions ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _DECISION_COLUMNS),
    )


def get_decision(conn: sqlite3.Connection, decision_id: str) -> EventDecisionRecord | None:
    row = conn.execute(
        """
        SELECT d.*, a.title AS article_title, e.title AS candidate_event_title
        FROM event_candidate_decisions AS d
        LEFT JOIN articles AS a ON a.id = d.article_id
        LEFT JOIN events AS e ON e.id = d.candidate_event_id
        WHERE d.id = ?
        """,
        (decision_id,),
    ).fetchone()
    return None if row is None else _decision_from_row(row)


def update_decision(
    conn: sqlite3.Connection, decision_id: str, fields: Mapping[str, object]
) -> None:
    allowed = {"candidate_event_id", "decision", "status", "resolved_at", "method", "llm_used"}
    keys = [key for key in fields if key in allowed]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE event_candidate_decisions SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), decision_id),
    )


def list_decisions(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    decision: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
) -> tuple[list[EventDecisionRecord], int]:
    clauses: list[str] = []
    params: list[object] = []
    if decision:
        clauses.append("d.decision = ?")
        params.append(decision)
    if status:
        clauses.append("d.status = ?")
        params.append(status)
    if run_id:
        clauses.append("d.run_id = ?")
        params.append(run_id)
    where = " AND ".join(clauses) if clauses else "1 = 1"
    rows = conn.execute(
        f"""
        SELECT d.*, a.title AS article_title, e.title AS candidate_event_title
        FROM event_candidate_decisions AS d
        LEFT JOIN articles AS a ON a.id = d.article_id
        LEFT JOIN events AS e ON e.id = d.candidate_event_id
        WHERE {where}
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM event_candidate_decisions AS d WHERE {where}",
        tuple(params),
    ).fetchone()
    return (
        [_decision_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def count_ambiguous_for_event(conn: sqlite3.Connection, event_id: str) -> int:
    # Pending ambiguous decisions also represent unresolved boundary risk, so
    # they must lower the confidence boundary component until a human resolves
    # them (resolved decisions become `manual_resolved`).
    row = conn.execute(
        "SELECT COUNT(*) FROM event_candidate_decisions "
        "WHERE candidate_event_id = ? AND decision = 'ambiguous'",
        (event_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def count_decisions_for_event(conn: sqlite3.Connection, event_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM event_candidate_decisions WHERE candidate_event_id = ?",
        (event_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def latest_decision_for_event(
    conn: sqlite3.Connection, event_id: str
) -> EventDecisionRecord | None:
    row = conn.execute(
        """
        SELECT d.*, a.title AS article_title, e.title AS candidate_event_title
        FROM event_candidate_decisions AS d
        LEFT JOIN articles AS a ON a.id = d.article_id
        LEFT JOIN events AS e ON e.id = d.candidate_event_id
        WHERE d.candidate_event_id = ?
        ORDER BY d.created_at DESC, d.id DESC LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    return None if row is None else _decision_from_row(row)
