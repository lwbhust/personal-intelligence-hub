"""Parameterised SQL for events, memberships, timeline, entities and audits."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from .models import (
    EventArticleRecord,
    EventEntityRecord,
    EventRecord,
    EventScoreRecord,
    EventTimelineRecord,
)
from .source_repository import escape_like

_EVENT_COLUMNS = (
    "id",
    "title",
    "summary",
    "category",
    "status",
    "status_reason",
    "first_seen_at",
    "last_seen_at",
    "first_published_at",
    "last_published_at",
    "occurred_at",
    "article_count",
    "source_count",
    "is_manual",
    "merged_into_event_id",
    "algorithm_version",
    "title_source",
    "summary_source",
    "created_at",
    "updated_at",
)

_EVENT_UPDATE_ALLOWED = {
    "title",
    "summary",
    "category",
    "status",
    "status_reason",
    "first_seen_at",
    "last_seen_at",
    "first_published_at",
    "last_published_at",
    "occurred_at",
    "article_count",
    "source_count",
    "is_manual",
    "merged_into_event_id",
    "algorithm_version",
    "title_source",
    "summary_source",
    "category_source",
    "category_reason",
    "category_updated_at",
    "updated_at",
}

_EVENT_SELECT = """
    SELECT e.*, s.id AS score_id, s.algorithm_version AS score_algorithm_version,
           s.scored_at AS score_scored_at, s.importance_score AS score_importance,
           s.heat_score AS score_heat, s.freshness_score AS score_freshness,
           s.coverage_score AS score_coverage, s.confidence_score AS score_confidence,
           s.total_score AS score_total, s.inputs_json AS score_inputs,
           s.explanation_json AS score_explanation, s.created_at AS score_created_at
    FROM events AS e
    LEFT JOIN event_score_snapshots AS s
           ON s.event_id = e.id AND s.is_current = 1
"""

_ORDER_COLUMNS = {
    "importance": "COALESCE(s.importance_score, 0)",
    "heat": "COALESCE(s.heat_score, 0)",
    "freshness": "COALESCE(s.freshness_score, 0)",
    "confidence": "COALESCE(s.confidence_score, 0)",
    "recent": "COALESCE(e.last_published_at, e.last_seen_at)",
    "articles": "e.article_count",
    "emerging": "(0.6 * COALESCE(s.heat_score, 0) + 0.4 * COALESCE(s.freshness_score, 0))",
    "new": "e.first_seen_at",
}


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: object) -> list[object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _event_from_row(row: sqlite3.Row) -> EventRecord:
    scores = None
    if row["score_id"] is not None:
        scores = EventScoreRecord(
            id=str(row["score_id"]),
            event_id=str(row["id"]),
            algorithm_version=str(row["score_algorithm_version"]),
            scored_at=str(row["score_scored_at"]),
            importance_score=float(row["score_importance"]),
            heat_score=float(row["score_heat"]),
            freshness_score=float(row["score_freshness"]),
            coverage_score=float(row["score_coverage"]),
            confidence_score=float(row["score_confidence"]),
            total_score=float(row["score_total"]),
            inputs=_json_object(row["score_inputs"]),
            explanation=_json_object(row["score_explanation"]),
            is_current=True,
            created_at=str(row["score_created_at"]),
        )
    return EventRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        summary=row["summary"],
        category=str(row["category"]),
        status=str(row["status"]),
        status_reason=row["status_reason"],
        first_seen_at=str(row["first_seen_at"]),
        last_seen_at=str(row["last_seen_at"]),
        first_published_at=row["first_published_at"],
        last_published_at=row["last_published_at"],
        occurred_at=row["occurred_at"],
        article_count=int(row["article_count"]),
        source_count=int(row["source_count"]),
        is_manual=bool(int(row["is_manual"])),
        merged_into_event_id=row["merged_into_event_id"],
        algorithm_version=str(row["algorithm_version"]),
        title_source=str(row["title_source"]),
        summary_source=str(row["summary_source"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        category_source=(
            str(row["category_source"]) if "category_source" in row.keys() else "legacy"
        ),
        category_reason=(
            row["category_reason"] if "category_reason" in row.keys() else None
        ),
        category_updated_at=(
            row["category_updated_at"] if "category_updated_at" in row.keys() else None
        ),
        current_scores=scores,
    )


def insert_event(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_EVENT_COLUMNS)
    placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
    conn.execute(
        f"INSERT INTO events ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _EVENT_COLUMNS),
    )


def update_event(conn: sqlite3.Connection, event_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _EVENT_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE events SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), event_id),
    )


def set_category_provenance(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    source: str,
    reason: str | None,
    updated_at: str,
) -> None:
    """Record who owns an event category (manual edits are never overwritten)."""

    conn.execute(
        "UPDATE events SET category_source = ?, category_reason = ?, "
        "category_updated_at = ? WHERE id = ?",
        (source, reason, updated_at, event_id),
    )


def get(conn: sqlite3.Connection, event_id: str) -> EventRecord | None:
    row = conn.execute(f"{_EVENT_SELECT} WHERE e.id = ?", (event_id,)).fetchone()
    return None if row is None else _event_from_row(row)


def list_events(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    order: str = "importance",
    direction: str = "desc",
    cutoff: str | None = None,
    exclude_terminal: bool = True,
) -> tuple[list[EventRecord], int]:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("e.status = ?")
        params.append(status)
    elif exclude_terminal:
        clauses.append("e.status NOT IN ('merged','archived')")
    if category:
        clauses.append("e.category = ?")
        params.append(category)
    if keyword:
        pattern = f"%{escape_like(keyword)}%"
        clauses.append(
            "(e.title LIKE ? ESCAPE '\\' OR e.summary LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    if cutoff:
        clauses.append(
            "COALESCE(e.last_published_at, e.last_seen_at) >= ?"
        )
        params.append(cutoff)
    where = " AND ".join(clauses) if clauses else "1 = 1"
    column = _ORDER_COLUMNS.get(order, _ORDER_COLUMNS["importance"])
    direction_sql = "ASC" if direction.lower() == "asc" else "DESC"
    rows = conn.execute(
        f"""
        {_EVENT_SELECT}
        WHERE {where}
        ORDER BY ({column} IS NULL) ASC, {column} {direction_sql}, e.id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM events AS e WHERE {where}", tuple(params)
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_event_from_row(row) for row in rows], total


def list_ranked_events(
    conn: sqlite3.Connection,
    *,
    kind: str,
    limit: int,
    offset: int,
    category: str | None = None,
    cutoff: str | None = None,
) -> tuple[list[EventRecord], int]:
    """SQL-paginated ranking over current score snapshots.

    `total` counts every matching event (not a truncation of an in-memory
    window), so deep pages and offsets stay accurate.
    """

    clauses = ["e.status NOT IN ('merged','archived')"]
    params: list[object] = []
    if kind != "recent":
        clauses.append("s.id IS NOT NULL")
    if category:
        clauses.append("e.category = ?")
        params.append(category)
    if cutoff:
        clauses.append("COALESCE(e.last_published_at, e.last_seen_at) >= ?")
        params.append(cutoff)
    where = " AND ".join(clauses)
    column = _ORDER_COLUMNS.get(kind, _ORDER_COLUMNS["importance"])
    rows = conn.execute(
        f"""
        {_EVENT_SELECT}
        WHERE {where}
        ORDER BY ({column} IS NULL) ASC, {column} DESC, e.id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"""
        SELECT COUNT(*) FROM events AS e
        LEFT JOIN event_score_snapshots AS s
               ON s.event_id = e.id AND s.is_current = 1
        WHERE {where}
        """,
        tuple(params),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_event_from_row(row) for row in rows], total


# --------------------------------------------------------------------------
# memberships
# --------------------------------------------------------------------------


def insert_event_article(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = (
        "id",
        "event_id",
        "article_id",
        "role",
        "similarity",
        "match_reasons_json",
        "is_manual",
        "added_at",
        "created_at",
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO event_articles ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values[key] for key in columns),
    )


def update_event_article(
    conn: sqlite3.Connection, event_id: str, article_id: str, fields: Mapping[str, object]
) -> None:
    allowed = {"role", "similarity", "match_reasons_json", "is_manual"}
    keys = [key for key in fields if key in allowed]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE event_articles SET {assignments} WHERE event_id = ? AND article_id = ?",
        (*(fields[key] for key in keys), event_id, article_id),
    )


def get_event_article(
    conn: sqlite3.Connection, event_id: str, article_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM event_articles WHERE event_id = ? AND article_id = ?",
        (event_id, article_id),
    ).fetchone()


def get_article_membership(conn: sqlite3.Connection, article_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM event_articles WHERE article_id = ?", (article_id,)
    ).fetchone()


def delete_event_article(conn: sqlite3.Connection, event_id: str, article_id: str) -> None:
    conn.execute(
        "DELETE FROM event_articles WHERE event_id = ? AND article_id = ?",
        (event_id, article_id),
    )


def move_articles(
    conn: sqlite3.Connection,
    *,
    source_event_id: str,
    target_event_id: str,
    article_ids: list[str] | None = None,
) -> tuple[int, int]:
    """Move memberships; return ``(moved, duplicates)``.

    A duplicate is an article the target already contains (global unique
    article_id); those source rows are removed after the move.
    """

    before = count_event_articles(conn, source_event_id)
    if article_ids is None:
        conn.execute(
            "UPDATE OR IGNORE event_articles SET event_id = ? WHERE event_id = ?",
            (target_event_id, source_event_id),
        )
        conn.execute("DELETE FROM event_articles WHERE event_id = ?", (source_event_id,))
    else:
        if not article_ids:
            return 0, 0
        placeholders = ", ".join("?" for _ in article_ids)
        conn.execute(
            f"UPDATE OR IGNORE event_articles SET event_id = ? "
            f"WHERE event_id = ? AND article_id IN ({placeholders})",
            (target_event_id, source_event_id, *article_ids),
        )
        conn.execute(
            f"DELETE FROM event_articles WHERE event_id = ? AND article_id IN ({placeholders})",
            (source_event_id, *article_ids),
        )
    after = count_event_articles(conn, source_event_id)
    moved = max(0, before - after)
    duplicates = max(0, len(article_ids) - moved) if article_ids is not None else 0
    return moved, duplicates


def move_timeline_all(
    conn: sqlite3.Connection, *, source_event_id: str, target_event_id: str
) -> int:
    before = conn.execute(
        "SELECT COUNT(*) FROM event_timeline_items WHERE event_id = ?", (source_event_id,)
    ).fetchone()
    conn.execute(
        "UPDATE OR IGNORE event_timeline_items SET event_id = ? WHERE event_id = ?",
        (target_event_id, source_event_id),
    )
    conn.execute("DELETE FROM event_timeline_items WHERE event_id = ?", (source_event_id,))
    return int(before[0]) if before is not None else 0


def list_timeline_ids(conn: sqlite3.Connection, event_id: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM event_timeline_items WHERE event_id = ?", (event_id,)
        )
    ]


def move_timeline_by_ids(
    conn: sqlite3.Connection,
    *,
    source_event_id: str,
    target_event_id: str,
    item_ids: list[str],
) -> int:
    if not item_ids:
        return 0
    placeholders = ", ".join("?" for _ in item_ids)
    cursor = conn.execute(
        f"UPDATE OR IGNORE event_timeline_items SET event_id = ? "
        f"WHERE event_id = ? AND id IN ({placeholders})",
        (source_event_id, target_event_id, *item_ids),
    )
    return int(cursor.rowcount)


def move_timeline_articles(
    conn: sqlite3.Connection,
    *,
    source_event_id: str,
    target_event_id: str,
    article_ids: list[str],
) -> int:
    if not article_ids:
        return 0
    placeholders = ", ".join("?" for _ in article_ids)
    before = conn.execute(
        f"SELECT COUNT(*) FROM event_timeline_items WHERE event_id = ? "
        f"AND article_id IN ({placeholders})",
        (source_event_id, *article_ids),
    ).fetchone()
    conn.execute(
        f"UPDATE OR IGNORE event_timeline_items SET event_id = ? "
        f"WHERE event_id = ? AND article_id IN ({placeholders})",
        (target_event_id, source_event_id, *article_ids),
    )
    conn.execute(
        f"DELETE FROM event_timeline_items WHERE event_id = ? AND article_id IN ({placeholders})",
        (source_event_id, *article_ids),
    )
    return int(before[0]) if before is not None else 0


def list_event_article_ids(conn: sqlite3.Connection, event_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT article_id FROM event_articles WHERE event_id = ? ORDER BY added_at ASC",
        (event_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def count_event_articles(conn: sqlite3.Connection, event_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM event_articles WHERE event_id = ?", (event_id,)
    ).fetchone()
    return int(row[0]) if row is not None else 0


_EVENT_ARTICLE_SELECT = """
    SELECT ea.*, a.title, a.source_id, s.name AS source_name,
           a.published_at, a.fetched_at, a.summary,
           a.canonical_url, a.original_url,
           x.summary AS ai_summary, x.category AS ai_category
    FROM event_articles AS ea
    JOIN articles AS a ON a.id = ea.article_id
    JOIN sources AS s ON s.id = a.source_id
    LEFT JOIN article_ai_analysis AS x ON x.id = (
        SELECT x2.id FROM article_ai_analysis AS x2
        WHERE x2.article_id = a.id
        ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
    )
"""


def _event_article_from_row(row: sqlite3.Row) -> EventArticleRecord:
    reasons = tuple(
        str(item) for item in _json_list(row["match_reasons_json"]) if isinstance(item, str)
    )
    return EventArticleRecord(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        article_id=str(row["article_id"]),
        role=str(row["role"]),
        similarity=None if row["similarity"] is None else float(row["similarity"]),
        match_reasons=reasons,
        is_manual=bool(int(row["is_manual"])),
        added_at=str(row["added_at"]),
        created_at=str(row["created_at"]),
        title=str(row["title"]),
        source_id=str(row["source_id"]),
        source_name=row["source_name"],
        published_at=row["published_at"],
        fetched_at=str(row["fetched_at"]),
        summary=row["summary"],
        ai_summary=row["ai_summary"],
        category=row["ai_category"],
        canonical_url=row["canonical_url"],
        original_url=row["original_url"],
    )


def list_event_articles(
    conn: sqlite3.Connection, event_id: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[EventArticleRecord], int]:
    rows = conn.execute(
        f"""
        {_EVENT_ARTICLE_SELECT}
        WHERE ea.event_id = ?
        ORDER BY (a.published_at IS NULL) ASC, a.published_at ASC, ea.added_at ASC
        LIMIT ? OFFSET ?
        """,
        (event_id, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) FROM event_articles WHERE event_id = ?", (event_id,)
    ).fetchone()
    return (
        [_event_article_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def list_member_rows(conn: sqlite3.Connection, event_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.id, a.title, a.summary, a.published_at, a.source_id, a.content_hash,
               x.summary AS ai_summary, x.category AS ai_category,
               x.keywords_json AS ai_keywords
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id
        LEFT JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE ea.event_id = ? AND a.deleted_at IS NULL
        ORDER BY (a.published_at IS NULL) ASC, a.published_at ASC, ea.added_at ASC
        """,
        (event_id,),
    ).fetchall()


def event_stats(conn: sqlite3.Connection, event_id: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS article_count,
               COUNT(DISTINCT a.source_id) AS source_count,
               COUNT(DISTINCT a.content_hash) AS content_count,
               MIN(a.published_at) AS first_published_at,
               MAX(a.published_at) AS last_published_at
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id
        WHERE ea.event_id = ? AND a.deleted_at IS NULL
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        return {
            "article_count": 0,
            "source_count": 0,
            "content_count": 0,
            "first_published_at": None,
            "last_published_at": None,
        }
    return {
        "article_count": int(row["article_count"]),
        "source_count": int(row["source_count"]),
        "content_count": int(row["content_count"]),
        "first_published_at": row["first_published_at"],
        "last_published_at": row["last_published_at"],
    }


# --------------------------------------------------------------------------
# exclusions
# --------------------------------------------------------------------------


def add_exclusion(
    conn: sqlite3.Connection, *, article_id: str, event_id: str, reason: str | None, created_at: str
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO event_article_exclusions "
        "(article_id, event_id, reason, created_at) VALUES (?, ?, ?, ?)",
        (article_id, event_id, reason, created_at),
    )


def delete_exclusion(conn: sqlite3.Connection, *, article_id: str, event_id: str) -> None:
    conn.execute(
        "DELETE FROM event_article_exclusions WHERE article_id = ? AND event_id = ?",
        (article_id, event_id),
    )


def excluded_event_ids(conn: sqlite3.Connection, article_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT event_id FROM event_article_exclusions WHERE article_id = ?",
        (article_id,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def is_excluded(conn: sqlite3.Connection, *, article_id: str, event_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM event_article_exclusions WHERE article_id = ? AND event_id = ?",
        (article_id, event_id),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------
# event entities
# --------------------------------------------------------------------------


def delete_event_entities(conn: sqlite3.Connection, event_id: str) -> None:
    conn.execute("DELETE FROM event_entities WHERE event_id = ?", (event_id,))


def insert_event_entity(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = (
        "id",
        "event_id",
        "entity_id",
        "role",
        "article_count",
        "confidence",
        "evidence_article_id",
        "created_at",
        "updated_at",
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO event_entities ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values[key] for key in columns),
    )


def list_event_entities(conn: sqlite3.Connection, event_id: str) -> list[EventEntityRecord]:
    rows = conn.execute(
        """
        SELECT ee.*, e.canonical_name, e.entity_type, a.title AS evidence_article_title
        FROM event_entities AS ee
        JOIN entities AS e ON e.id = ee.entity_id
        LEFT JOIN articles AS a ON a.id = ee.evidence_article_id
        WHERE ee.event_id = ?
        ORDER BY ee.article_count DESC, ee.confidence DESC, e.canonical_name ASC
        """,
        (event_id,),
    ).fetchall()
    return [
        EventEntityRecord(
            id=str(row["id"]),
            event_id=str(row["event_id"]),
            entity_id=str(row["entity_id"]),
            role=str(row["role"]),
            article_count=int(row["article_count"]),
            confidence=float(row["confidence"]),
            evidence_article_id=row["evidence_article_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            canonical_name=str(row["canonical_name"]),
            entity_type=str(row["entity_type"]),
            evidence_article_title=row["evidence_article_title"],
        )
        for row in rows
    ]


def event_entity_union(
    conn: sqlite3.Connection, event_id: str
) -> tuple[list[str], list[str], list[str], list[str]]:
    rows = conn.execute(
        """
        SELECT DISTINCT ae.entity_id, e.normalized_key, e.type_group
        FROM event_articles AS ea
        JOIN article_entities AS ae ON ae.article_id = ea.article_id
        JOIN entities AS e ON e.id = ae.entity_id
        WHERE ea.event_id = ? AND ae.status = 'resolved'
        """,
        (event_id,),
    ).fetchall()
    ids = [str(row[0]) for row in rows]
    keys = [str(row[1]) for row in rows]
    event_ids = [str(row[0]) for row in rows if str(row[2]) == "event"]
    event_keys = [str(row[1]) for row in rows if str(row[2]) == "event"]
    return ids, keys, event_ids, event_keys


def event_entity_mentions(
    conn: sqlite3.Connection, event_id: str
) -> dict[str, tuple[str, ...]]:
    rows = conn.execute(
        """
        SELECT ae.entity_id, ae.article_id
        FROM event_articles AS ea
        JOIN article_entities AS ae ON ae.article_id = ea.article_id
        WHERE ea.event_id = ? AND ae.entity_id IS NOT NULL
        ORDER BY ae.article_id
        """,
        (event_id,),
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(str(row["entity_id"]), []).append(str(row["article_id"]))
    return {key: tuple(value) for key, value in result.items()}


def content_publish_times(conn: sqlite3.Connection, event_id: str) -> list[str | None]:
    """One row per unique content hash, with the earliest publication time."""

    rows = conn.execute(
        """
        SELECT a.content_hash, MIN(a.published_at) AS published_at
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id
        WHERE ea.event_id = ? AND a.deleted_at IS NULL
        GROUP BY a.content_hash
        """,
        (event_id,),
    ).fetchall()
    return [row["published_at"] for row in rows]


def content_source_times(
    conn: sqlite3.Connection, event_id: str
) -> list[tuple[str | None, str]]:
    """`(earliest published_at, source_id)` per unique content hash.

    Reposts with the same content hash collapse to one row (the earliest
    publication), so heat/coverage never count syndication twice. When several
    sources carry the same content, SQLite's bare-column-with-MIN semantics
    keep the source of the earliest publication.
    """

    rows = conn.execute(
        """
        SELECT a.content_hash, MIN(a.published_at) AS published_at, a.source_id
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id
        WHERE ea.event_id = ? AND a.deleted_at IS NULL
        GROUP BY a.content_hash
        """,
        (event_id,),
    ).fetchall()
    return [(row["published_at"], str(row["source_id"])) for row in rows]


def event_entity_stats(conn: sqlite3.Connection, event_id: str) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT e.type_group, COUNT(*) AS entity_count,
               AVG(ee.confidence) AS avg_confidence
        FROM event_entities AS ee
        JOIN entities AS e ON e.id = ee.entity_id
        WHERE ee.event_id = ?
        GROUP BY e.type_group
        """,
        (event_id,),
    ).fetchall()
    counts = {"organization": 0, "person": 0, "location": 0}
    weighted = 0.0
    total = 0
    for row in rows:
        group = str(row["type_group"])
        count = int(row["entity_count"])
        if group in counts:
            counts[group] = count
        total += count
        weighted += float(row["avg_confidence"] or 0.0) * count
    return {
        "org_count": counts["organization"],
        "person_count": counts["person"],
        "location_count": counts["location"],
        "avg_confidence": (weighted / total) if total else 0.0,
    }


def event_ambiguous_keys(conn: sqlite3.Connection, event_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT ae.raw_name
        FROM event_articles AS ea
        JOIN article_entities AS ae ON ae.article_id = ea.article_id
        WHERE ea.event_id = ? AND ae.entity_id IS NULL
        """,
        (event_id,),
    ).fetchall()
    return {str(row["raw_name"]).strip().lower() for row in rows if row["raw_name"]}


def article_ids_belonging_to_events(
    conn: sqlite3.Connection, *, article_ids: list[str], event_ids: list[str]
) -> set[str]:
    if not article_ids or not event_ids:
        return set()
    article_ph = ", ".join("?" for _ in article_ids)
    event_ph = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT article_id FROM event_articles
        WHERE article_id IN ({article_ph}) AND event_id IN ({event_ph})
        """,
        (*article_ids, *event_ids),
    ).fetchall()
    return {str(row[0]) for row in rows}


def article_publish_bounds(
    conn: sqlite3.Connection, article_ids: list[str]
) -> tuple[str | None, str | None]:
    if not article_ids:
        return None, None
    placeholders = ", ".join("?" for _ in article_ids)
    row = conn.execute(
        f"SELECT MIN(published_at) AS first, MAX(published_at) AS last "
        f"FROM articles WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        tuple(article_ids),
    ).fetchone()
    if row is None:
        return None, None
    return row["first"], row["last"]


def event_keywords(conn: sqlite3.Connection, event_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT x.keywords_json
        FROM event_articles AS ea
        JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = ea.article_id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE ea.event_id = ?
        """,
        (event_id,),
    ).fetchall()
    result: set[str] = set()
    for row in rows:
        for item in _json_list(row["keywords_json"]):
            if isinstance(item, str) and item.strip():
                result.add(item.strip().lower())
    return result


# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------


def insert_timeline_item(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = (
        "id",
        "event_id",
        "article_id",
        "kind",
        "title",
        "description",
        "occurred_at",
        "published_at",
        "recognized_at",
        "confidence",
        "is_key",
        "evidence_json",
        "created_at",
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO event_timeline_items ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values[key] for key in columns),
    )


def timeline_exists_for_article(
    conn: sqlite3.Connection, event_id: str, article_id: str
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM event_timeline_items WHERE event_id = ? AND article_id = ? LIMIT 1",
        (event_id, article_id),
    ).fetchone()
    return row is not None


def timeline_is_empty(conn: sqlite3.Connection, event_id: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM event_timeline_items WHERE event_id = ?", (event_id,)
    ).fetchone()
    return int(row[0]) == 0 if row is not None else True


def delete_timeline_for_article(
    conn: sqlite3.Connection, event_id: str, article_id: str
) -> int:
    """Remove report-derived timeline nodes when an article leaves the event."""

    cursor = conn.execute(
        "DELETE FROM event_timeline_items WHERE event_id = ? AND article_id = ?",
        (event_id, article_id),
    )
    return int(cursor.rowcount or 0)


def list_timeline(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    key_only: bool = False,
) -> tuple[list[EventTimelineRecord], int]:
    clauses = ["t.event_id = ?"]
    params: list[object] = [event_id]
    if key_only:
        clauses.append("t.is_key = 1")
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT t.*, a.title AS article_title
        FROM event_timeline_items AS t
        LEFT JOIN articles AS a ON a.id = t.article_id
        WHERE {where}
        ORDER BY t.recognized_at DESC, t.id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM event_timeline_items AS t WHERE {where}", tuple(params)
    ).fetchone()
    records = [
        EventTimelineRecord(
            id=str(row["id"]),
            event_id=str(row["event_id"]),
            article_id=row["article_id"],
            kind=str(row["kind"]),
            title=str(row["title"]),
            description=row["description"],
            occurred_at=row["occurred_at"],
            published_at=row["published_at"],
            recognized_at=str(row["recognized_at"]),
            confidence=None if row["confidence"] is None else float(row["confidence"]),
            is_key=bool(int(row["is_key"])),
            evidence=_json_object(row["evidence_json"]),
            created_at=str(row["created_at"]),
            article_title=row["article_title"],
        )
        for row in rows
    ]
    return records, int(total_row[0]) if total_row is not None else 0


# --------------------------------------------------------------------------
# clustering helpers
# --------------------------------------------------------------------------


def article_feature_row(conn: sqlite3.Connection, article_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT a.id, a.title, a.summary, a.content_text, a.published_at,
               a.source_id, a.content_hash,
               c.name AS source_category,
               x.id AS analysis_id, x.summary AS ai_summary,
               x.category AS ai_category, x.keywords_json AS ai_keywords
        FROM articles AS a
        LEFT JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN source_categories AS c ON c.id = s.category_id
        LEFT JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE a.id = ? AND a.deleted_at IS NULL AND a.status = 'active'
        """,
        (article_id,),
    ).fetchone()


def article_entity_keys(
    conn: sqlite3.Connection, article_id: str
) -> tuple[set[str], set[str], set[str], set[str]]:
    rows = conn.execute(
        """
        SELECT ae.entity_id, e.normalized_key, e.type_group, ae.raw_name, ae.status
        FROM article_entities AS ae
        LEFT JOIN entities AS e ON e.id = ae.entity_id
        WHERE ae.article_id = ?
        """,
        (article_id,),
    ).fetchall()
    ids: set[str] = set()
    keys: set[str] = set()
    event_ids: set[str] = set()
    event_keys: set[str] = set()
    for row in rows:
        if row["entity_id"]:
            ids.add(str(row["entity_id"]))
        if row["normalized_key"]:
            keys.add(str(row["normalized_key"]))
        if row["entity_id"] and str(row["type_group"]) == "event":
            event_ids.add(str(row["entity_id"]))
        if row["normalized_key"] and str(row["type_group"]) == "event":
            event_keys.add(str(row["normalized_key"]))
        if not row["entity_id"] and row["raw_name"]:
            keys.add(str(row["raw_name"]).strip().lower())
    return ids, keys, event_ids, event_keys


def eligible_article_ids(
    conn: sqlite3.Connection, *, limit: int, include_assigned: bool = False
) -> list[str]:
    clause = "" if include_assigned else (
        "AND NOT EXISTS (SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id)"
    )
    rows = conn.execute(
        f"""
        SELECT a.id
        FROM articles AS a
        WHERE a.deleted_at IS NULL AND a.status = 'active'
          {clause}
        ORDER BY (a.published_at IS NULL) ASC, a.published_at ASC, a.id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def events_for_clustering(
    conn: sqlite3.Connection, *, cutoff: str, limit: int = 200
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT e.* FROM events AS e
        WHERE e.status NOT IN ('merged','archived')
          AND COALESCE(e.last_published_at, e.last_seen_at) >= ?
        ORDER BY COALESCE(e.last_published_at, e.last_seen_at) DESC
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()
