"""Parameterised SQL for Phase 7.1 intelligence reports.

Two groups live here:

* report persistence (`intelligence_reports`, `intelligence_report_citations`);
* deterministic read models used to build a report's evidence (articles,
  events, entities, keywords). Every number a report shows comes from these
  queries — the model never supplies statistics.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence

from .models import IntelligenceCitationRecord, IntelligenceReportRecord

_REPORT_COLUMNS = (
    "id",
    "report_type",
    "period_key",
    "period_start",
    "period_end",
    "data_from_at",
    "data_to_at",
    "status",
    "ai_status",
    "headline",
    "overview",
    "content_json",
    "stats_json",
    "model_name",
    "model_digest",
    "prompt_version",
    "stats_version",
    "article_count",
    "event_count",
    "entity_count",
    "citation_count",
    "trigger_type",
    "cancel_requested",
    "error_code",
    "error_message",
    "started_at",
    "finished_at",
    "duration_ms",
    "created_at",
    "updated_at",
)

_REPORT_UPDATE_ALLOWED = {
    "status",
    "ai_status",
    "headline",
    "overview",
    "content_json",
    "stats_json",
    "model_name",
    "model_digest",
    "article_count",
    "event_count",
    "entity_count",
    "citation_count",
    "cancel_requested",
    "error_code",
    "error_message",
    "started_at",
    "finished_at",
    "duration_ms",
    "data_from_at",
    "data_to_at",
    "updated_at",
}

_CITATION_COLUMNS = (
    "id",
    "report_id",
    "citation_type",
    "ref_id",
    "section_key",
    "rank",
    "title",
    "source_name",
    "url",
    "evidence",
    "created_at",
)

ACTIVE_STATUSES = ("pending", "running", "succeeded", "degraded")


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _report_from_row(row: sqlite3.Row) -> IntelligenceReportRecord:
    return IntelligenceReportRecord(
        id=str(row["id"]),
        report_type=str(row["report_type"]),
        period_key=str(row["period_key"]),
        period_start=str(row["period_start"]),
        period_end=str(row["period_end"]),
        data_from_at=row["data_from_at"],
        data_to_at=row["data_to_at"],
        status=str(row["status"]),
        ai_status=str(row["ai_status"]),
        headline=row["headline"],
        overview=row["overview"],
        content=_json_object(row["content_json"]),
        stats=_json_object(row["stats_json"]),
        model_name=row["model_name"],
        model_digest=row["model_digest"],
        prompt_version=str(row["prompt_version"]),
        stats_version=str(row["stats_version"]),
        article_count=int(row["article_count"]),
        event_count=int(row["event_count"]),
        entity_count=int(row["entity_count"]),
        citation_count=int(row["citation_count"]),
        trigger_type=str(row["trigger_type"]),
        cancel_requested=bool(int(row["cancel_requested"])),
        error_code=row["error_code"],
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _citation_from_row(row: sqlite3.Row) -> IntelligenceCitationRecord:
    return IntelligenceCitationRecord(
        id=str(row["id"]),
        report_id=str(row["report_id"]),
        citation_type=str(row["citation_type"]),
        ref_id=str(row["ref_id"]),
        section_key=str(row["section_key"]),
        rank=int(row["rank"]),
        title=row["title"],
        source_name=row["source_name"],
        url=row["url"],
        evidence=row["evidence"],
        created_at=str(row["created_at"]),
    )


# --------------------------------------------------------------------------
# report persistence
# --------------------------------------------------------------------------


def insert_report(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_REPORT_COLUMNS)
    placeholders = ", ".join("?" for _ in _REPORT_COLUMNS)
    conn.execute(
        f"INSERT INTO intelligence_reports ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _REPORT_COLUMNS),
    )


def update_report(
    conn: sqlite3.Connection, report_id: str, fields: Mapping[str, object]
) -> None:
    assignments = []
    params: list[object] = []
    for key, value in fields.items():
        if key not in _REPORT_UPDATE_ALLOWED:
            raise KeyError(f"field {key} is not updatable")
        assignments.append(f"{key} = ?")
        params.append(value)
    if not assignments:
        return
    params.append(report_id)
    conn.execute(
        f"UPDATE intelligence_reports SET {', '.join(assignments)} WHERE id = ?",
        tuple(params),
    )


def insert_citations(
    conn: sqlite3.Connection, rows: Sequence[Mapping[str, object]]
) -> None:
    if not rows:
        return
    columns = ", ".join(_CITATION_COLUMNS)
    placeholders = ", ".join("?" for _ in _CITATION_COLUMNS)
    conn.executemany(
        f"INSERT OR IGNORE INTO intelligence_report_citations ({columns}) "
        f"VALUES ({placeholders})",
        [tuple(row[key] for key in _CITATION_COLUMNS) for row in rows],
    )


def get(conn: sqlite3.Connection, report_id: str) -> IntelligenceReportRecord | None:
    row = conn.execute(
        "SELECT * FROM intelligence_reports WHERE id = ?", (report_id,)
    ).fetchone()
    return None if row is None else _report_from_row(row)


def find_active(
    conn: sqlite3.Connection, *, report_type: str, period_key: str
) -> IntelligenceReportRecord | None:
    placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
    row = conn.execute(
        f"SELECT * FROM intelligence_reports WHERE report_type = ? AND period_key = ? "
        f"AND status IN ({placeholders}) "
        "ORDER BY created_at DESC LIMIT 1",
        (report_type, period_key, *ACTIVE_STATUSES),
    ).fetchone()
    return None if row is None else _report_from_row(row)


def supersede_active(
    conn: sqlite3.Connection, *, report_type: str, period_key: str, now: str
) -> int:
    placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
    cursor = conn.execute(
        f"UPDATE intelligence_reports SET status = 'superseded', updated_at = ? "
        f"WHERE report_type = ? AND period_key = ? AND status IN ({placeholders})",
        (now, report_type, period_key, *ACTIVE_STATUSES),
    )
    return int(cursor.rowcount or 0)


def list_reports(
    conn: sqlite3.Connection,
    *,
    report_type: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[IntelligenceReportRecord], int]:
    clauses = ["1 = 1"]
    params: list[object] = []
    if report_type:
        clauses.append("report_type = ?")
        params.append(report_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM intelligence_reports WHERE {where} "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM intelligence_reports WHERE {where}", tuple(params)
    ).fetchone()
    return (
        [_report_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def list_citations(
    conn: sqlite3.Connection, report_id: str
) -> list[IntelligenceCitationRecord]:
    rows = conn.execute(
        "SELECT * FROM intelligence_report_citations WHERE report_id = ? "
        "ORDER BY section_key ASC, rank ASC, created_at ASC",
        (report_id,),
    ).fetchall()
    return [_citation_from_row(row) for row in rows]


def current_running(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT id FROM intelligence_reports WHERE status = 'running' "
        "ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    return None if row is None else str(row[0])


def queued_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM intelligence_reports WHERE status = 'pending'"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def latest_succeeded(conn: sqlite3.Connection) -> IntelligenceReportRecord | None:
    row = conn.execute(
        "SELECT * FROM intelligence_reports WHERE status IN ('succeeded','degraded') "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return None if row is None else _report_from_row(row)


def mark_stale_running(conn: sqlite3.Connection, now: str, *, error_code: str) -> int:
    """A Sidecar restart must never leave a report stuck in `running`."""

    cursor = conn.execute(
        "UPDATE intelligence_reports SET status = 'failed', error_code = ?, "
        "error_message = 'Sidecar 重启导致生成中断，可重新生成', finished_at = ?, "
        "updated_at = ? WHERE status IN ('pending','running')",
        (error_code, now, now),
    )
    return int(cursor.rowcount or 0)


def prune(conn: sqlite3.Connection, keep: int = 200) -> int:
    row = conn.execute(
        "SELECT created_at, id FROM intelligence_reports "
        "ORDER BY created_at DESC, id DESC LIMIT 1 OFFSET ?",
        (max(0, keep - 1),),
    ).fetchone()
    if row is None:
        return 0
    cursor = conn.execute(
        "DELETE FROM intelligence_reports WHERE status NOT IN ('pending','running') "
        "AND (created_at, id) < (?, ?)",
        (str(row["created_at"]), str(row["id"])),
    )
    return int(cursor.rowcount or 0)


# --------------------------------------------------------------------------
# deterministic evidence queries
# --------------------------------------------------------------------------


def article_window_stats(
    conn: sqlite3.Connection, start_ts: str, end_ts: str
) -> dict[str, object]:
    """Counts for articles whose effective publication time falls in range."""

    row = conn.execute(
        """
        SELECT COUNT(*) AS articles,
               COUNT(DISTINCT a.source_id) AS sources,
               MIN(COALESCE(a.published_at, a.fetched_at)) AS first_at,
               MAX(COALESCE(a.published_at, a.fetched_at)) AS last_at
        FROM articles AS a
        WHERE a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
        """,
        (start_ts, end_ts),
    ).fetchone()
    if row is None:
        return {"articles": 0, "sources": 0, "first_at": None, "last_at": None}
    return {
        "articles": int(row["articles"]),
        "sources": int(row["sources"]),
        "first_at": row["first_at"],
        "last_at": row["last_at"],
    }


def category_window_counts(
    conn: sqlite3.Connection, start_ts: str, end_ts: str
) -> dict[str, int]:
    """Article count per AI category using each article's latest analysis."""

    rows = conn.execute(
        """
        SELECT COALESCE(analysis.category, '未分析') AS category, COUNT(*) AS n
        FROM articles AS a
        LEFT JOIN article_ai_analysis AS analysis
               ON analysis.id = (
                    SELECT id FROM article_ai_analysis
                    WHERE article_id = a.id
                    ORDER BY created_at DESC, id DESC LIMIT 1)
        WHERE a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
        GROUP BY COALESCE(analysis.category, '未分析')
        """,
        (start_ts, end_ts),
    ).fetchall()
    return {str(row["category"]): int(row["n"]) for row in rows}


def keyword_rows(
    conn: sqlite3.Connection, start_ts: str, end_ts: str, *, limit: int = 800
) -> list[sqlite3.Row]:
    """Latest AI keywords per article in range (raw JSON, parsed by caller)."""

    return conn.execute(
        """
        SELECT analysis.keywords_json AS keywords_json,
               a.id AS article_id,
               a.source_id AS source_id,
               s.name AS source_name,
               a.title AS title
        FROM articles AS a
        JOIN article_ai_analysis AS analysis
          ON analysis.id = (
               SELECT id FROM article_ai_analysis
               WHERE article_id = a.id
               ORDER BY created_at DESC, id DESC LIMIT 1)
        JOIN sources AS s ON s.id = a.source_id
        WHERE a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
        ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
        LIMIT ?
        """,
        (start_ts, end_ts, limit),
    ).fetchall()


def unclustered_articles(
    conn: sqlite3.Connection, start_ts: str, end_ts: str, *, limit: int = 10
) -> tuple[int, list[dict[str, object]]]:
    """Articles in range that no event contains yet (real gap indicator)."""

    total_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM articles AS a
        WHERE a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
          AND NOT EXISTS (SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id)
        """,
        (start_ts, end_ts),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT a.id, a.title, s.name AS source_name,
               COALESCE(a.published_at, a.fetched_at) AS at
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        WHERE a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
          AND NOT EXISTS (SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id)
        ORDER BY at DESC
        LIMIT ?
        """,
        (start_ts, end_ts, limit),
    ).fetchall()
    return int(total_row[0]) if total_row else 0, [dict(row) for row in rows]


def events_in_window(
    conn: sqlite3.Connection,
    start_ts: str,
    end_ts: str,
    *,
    limit: int = 8,
    new_only: bool = False,
) -> list[dict[str, object]]:
    """Events with activity in range, ordered by their current total score."""

    new_clause = "AND e.first_seen_at >= ? AND e.first_seen_at < ?" if new_only else ""
    params: list[object] = [start_ts, end_ts]
    if new_only:
        params.extend([start_ts, end_ts])
    rows = conn.execute(
        f"""
        SELECT e.id, e.title, e.summary, e.category, e.status,
               e.first_seen_at, e.last_seen_at,
               e.first_published_at, e.last_published_at,
               e.article_count, e.source_count,
               s.importance_score, s.heat_score, s.freshness_score,
               s.coverage_score, s.confidence_score, s.total_score,
               s.algorithm_version
        FROM events AS e
        LEFT JOIN event_score_snapshots AS s
               ON s.event_id = e.id AND s.is_current = 1
        WHERE e.status NOT IN ('merged','archived')
          AND COALESCE(e.last_published_at, e.last_seen_at) >= ?
          AND COALESCE(e.last_published_at, e.last_seen_at) < ?
          {new_clause}
        ORDER BY COALESCE(s.total_score, 0) DESC, e.article_count DESC, e.id ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def count_events_in_window(
    conn: sqlite3.Connection, start_ts: str, end_ts: str, *, new_only: bool = False
) -> int:
    new_clause = "AND e.first_seen_at >= ? AND e.first_seen_at < ?" if new_only else ""
    params: list[object] = [start_ts, end_ts]
    if new_only:
        params.extend([start_ts, end_ts])
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM events AS e
        WHERE e.status NOT IN ('merged','archived')
          AND COALESCE(e.last_published_at, e.last_seen_at) >= ?
          AND COALESCE(e.last_published_at, e.last_seen_at) < ?
          {new_clause}
        """,
        tuple(params),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def event_entities_for(
    conn: sqlite3.Connection, event_ids: Sequence[str]
) -> dict[str, list[dict[str, object]]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT ee.event_id, ee.role, ee.article_count, ee.confidence,
               ent.canonical_name, ent.entity_type
        FROM event_entities AS ee
        JOIN entities AS ent ON ent.id = ee.entity_id
        WHERE ee.event_id IN ({placeholders})
        ORDER BY ee.event_id ASC, ee.article_count DESC, ent.canonical_name ASC
        """,
        tuple(event_ids),
    ).fetchall()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["event_id"]), []).append(dict(row))
    return grouped


def event_evidence_articles(
    conn: sqlite3.Connection, event_ids: Sequence[str], *, per_event: int = 4
) -> dict[str, list[dict[str, object]]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT ea.event_id, a.id AS article_id, a.title, a.summary,
               a.canonical_url, a.original_url,
               COALESCE(a.published_at, a.fetched_at) AS at,
               s.name AS source_name,
               analysis.summary AS ai_summary,
               analysis.category AS category
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id
        JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN article_ai_analysis AS analysis
               ON analysis.id = (
                    SELECT id FROM article_ai_analysis
                    WHERE article_id = a.id
                    ORDER BY created_at DESC, id DESC LIMIT 1)
        WHERE ea.event_id IN ({placeholders})
          AND a.deleted_at IS NULL
        ORDER BY ea.event_id ASC, at DESC
        """,
        tuple(event_ids),
    ).fetchall()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        bucket = grouped.setdefault(str(row["event_id"]), [])
        if len(bucket) < per_event:
            bucket.append(dict(row))
    return grouped


def new_entities(
    conn: sqlite3.Connection, start_ts: str, end_ts: str, *, limit: int = 10
) -> list[dict[str, object]]:
    """Entities first seen in range, ranked by mentions inside the range."""

    rows = conn.execute(
        """
        SELECT ent.id, ent.canonical_name, ent.entity_type, ent.first_seen_at,
               COUNT(DISTINCT ae.article_id) AS mentions
        FROM entities AS ent
        JOIN article_entities AS ae ON ae.entity_id = ent.id
        JOIN articles AS a ON a.id = ae.article_id
        WHERE ent.status = 'active'
          AND ent.first_seen_at >= ? AND ent.first_seen_at < ?
          AND a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
        GROUP BY ent.id
        HAVING mentions >= 2
        ORDER BY mentions DESC, ent.canonical_name ASC
        LIMIT ?
        """,
        (start_ts, end_ts, start_ts, end_ts, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def entity_mentions_in_window(
    conn: sqlite3.Connection, start_ts: str, end_ts: str, *, limit: int = 10
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT ent.canonical_name AS name, ent.entity_type,
               COUNT(DISTINCT ae.article_id) AS mentions
        FROM entities AS ent
        JOIN article_entities AS ae ON ae.entity_id = ent.id
        JOIN articles AS a ON a.id = ae.article_id
        WHERE ent.status = 'active'
          AND a.deleted_at IS NULL
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND COALESCE(a.published_at, a.fetched_at) < ?
        GROUP BY ent.id
        ORDER BY mentions DESC, ent.canonical_name ASC
        LIMIT ?
        """,
        (start_ts, end_ts, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def relations_between(
    conn: sqlite3.Connection, event_ids: Sequence[str]
) -> list[dict[str, object]]:
    if len(event_ids) < 2:
        return []
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT r.source_event_id, r.target_event_id, r.relation_type,
               r.confidence, r.status, r.rationale,
               src.title AS source_title, dst.title AS target_title
        FROM event_relations AS r
        JOIN events AS src ON src.id = r.source_event_id
        JOIN events AS dst ON dst.id = r.target_event_id
        WHERE r.source_event_id IN ({placeholders})
          AND r.target_event_id IN ({placeholders})
          AND r.status <> 'rejected'
        ORDER BY r.confidence DESC
        LIMIT 20
        """,
        (*event_ids, *event_ids),
    ).fetchall()
    return [dict(row) for row in rows]
