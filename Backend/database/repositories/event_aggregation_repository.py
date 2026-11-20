"""Read helpers for Phase 7.6 cross-source event aggregation.

Only SELECT statements live here; every mutation still goes through the Phase 4
repository functions inside a caller-owned transaction.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence


def recent_events(
    conn: sqlite3.Connection, *, cutoff: str, limit: int
) -> list[sqlite3.Row]:
    """Events that can still receive reports (merged/archived are excluded)."""

    return conn.execute(
        """
        SELECT e.id, e.title, e.summary, e.category, e.status, e.is_manual,
               e.first_published_at, e.last_published_at, e.last_seen_at,
               e.created_at, e.article_count, e.source_count
        FROM events AS e
        WHERE e.status NOT IN ('merged','archived')
          AND COALESCE(e.last_published_at, e.last_seen_at) >= ?
          AND EXISTS (SELECT 1 FROM event_articles AS ea WHERE ea.event_id = e.id)
        ORDER BY COALESCE(e.last_published_at, e.last_seen_at) DESC
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()


def event_members(
    conn: sqlite3.Connection, event_ids: Sequence[str]
) -> dict[str, list[sqlite3.Row]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT ea.event_id, a.id AS article_id, a.title, a.summary, a.published_at,
               a.fetched_at, a.source_id, s.name AS source_name,
               s.credibility_score, a.content_state, a.canonical_url,
               a.original_url, a.content_hash,
               c.name AS source_category,
               x.summary AS ai_summary, x.category AS ai_category,
               x.keywords_json AS ai_keywords
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id
        LEFT JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN source_categories AS c ON c.id = s.category_id
        LEFT JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE ea.event_id IN ({placeholders}) AND a.deleted_at IS NULL
        ORDER BY (a.published_at IS NULL) ASC, a.published_at ASC, a.id ASC
        """,
        tuple(event_ids),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["event_id"]), []).append(row)
    return grouped


def unassigned_articles(
    conn: sqlite3.Connection, *, since: str, limit: int
) -> list[sqlite3.Row]:
    """Active articles that are not evidence of any event yet."""

    return conn.execute(
        """
        SELECT a.id, a.title, a.summary, a.published_at, a.fetched_at,
               a.source_id, s.name AS source_name, s.credibility_score,
               a.content_state, a.canonical_url, a.original_url, a.content_hash,
               c.name AS source_category,
               x.summary AS ai_summary, x.category AS ai_category,
               x.keywords_json AS ai_keywords
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id AND s.deleted_at IS NULL
        LEFT JOIN source_categories AS c ON c.id = s.category_id
        LEFT JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE a.deleted_at IS NULL AND a.status = 'active'
          AND a.content_state <> 'unavailable'
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND NOT EXISTS (
              SELECT 1 FROM event_articles AS ea WHERE ea.article_id = a.id
          )
        ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()


def event_rows_by_ids(
    conn: sqlite3.Connection, event_ids: Sequence[str]
) -> dict[str, sqlite3.Row]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT e.id, e.title, e.summary, e.category, e.status, e.is_manual,
               e.first_seen_at, e.first_published_at, e.last_published_at,
               e.last_seen_at, e.created_at, e.article_count, e.source_count
        FROM events AS e WHERE e.id IN ({placeholders})
        """,
        tuple(event_ids),
    ).fetchall()
    return {str(row["id"]): row for row in rows}


def article_row_by_id(
    conn: sqlite3.Connection, article_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT a.id, a.title, a.summary, a.published_at, a.fetched_at,
               a.source_id, s.name AS source_name, s.credibility_score,
               a.content_state, a.canonical_url, a.original_url, a.content_hash,
               c.name AS source_category,
               x.summary AS ai_summary, x.category AS ai_category,
               x.keywords_json AS ai_keywords
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id AND s.deleted_at IS NULL
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


__all__ = [
    "article_row_by_id",
    "event_members",
    "event_rows_by_ids",
    "recent_events",
    "unassigned_articles",
]
