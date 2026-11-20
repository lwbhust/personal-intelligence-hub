"""Phase 6.1 Dashboard stats service.

All queries are single-pass, real SQLite data, no mock.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping


def _coerce_rows(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for r in rows:
        if isinstance(r, sqlite3.Row):
            out.append(dict(r))
        else:
            out.append(dict(r))
    return out


def overview(conn: sqlite3.Connection) -> dict[str, object]:
    """Top-line counters for the dashboard hero."""

    now = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    total_articles = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL"
    ).fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL "
        "AND date(COALESCE(published_at, fetched_at)) = date('now')"
    ).fetchone()[0]
    week = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL "
        "AND date(COALESCE(published_at, fetched_at)) >= date('now','-6 days')"
    ).fetchone()[0]
    sources_active = conn.execute(
        "SELECT COUNT(*) FROM sources WHERE enabled = 1 AND deleted_at IS NULL"
    ).fetchone()[0]
    sources_total = conn.execute(
        "SELECT COUNT(*) FROM sources WHERE deleted_at IS NULL"
    ).fetchone()[0]
    events_active = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status IN ('active','evolving','dormant')"
    ).fetchone()[0]
    events_total = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    unread = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL AND reading_status = 'unread'"
    ).fetchone()[0]
    favorites = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL AND is_favorite = 1"
    ).fetchone()[0]

    return {
        "generated_at": now,
        "articles": {
            "total": int(total_articles),
            "today": int(today),
            "last_7_days": int(week),
            "unread": int(unread),
            "favorites": int(favorites),
        },
        "sources": {
            "total": int(sources_total),
            "active": int(sources_active),
        },
        "events": {
            "total": int(events_total),
            "active": int(events_active),
        },
    }


def articles_trend(
    conn: sqlite3.Connection,
    *,
    days: int = 30,
) -> list[dict[str, object]]:
    """Daily article count for the last `days` UTC days.

    Counts use the publication date and fall back to `fetched_at` when a feed
    item has no published timestamp. Every day in the window is returned,
    including zero-count days, so the chart always has a real daily axis.
    """

    start_offset = f"-{max(days - 1, 0)} days"
    rows = conn.execute(
        """
        WITH RECURSIVE window(day) AS (
            SELECT date('now', ?)
            UNION ALL
            SELECT date(day, '+1 day') FROM window WHERE day < date('now')
        )
        SELECT window.day AS day, COUNT(a.id) AS count
        FROM window
        LEFT JOIN articles AS a
               ON date(COALESCE(a.published_at, a.fetched_at)) = window.day
              AND a.deleted_at IS NULL
        GROUP BY window.day
        ORDER BY window.day ASC
        """,
        (start_offset,),
    ).fetchall()
    return [{"day": r["day"], "count": int(r["count"])} for r in rows]


def sources_distribution(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Article count per source, top 20."""

    rows = conn.execute(
        """
        SELECT s.name AS name, s.language AS language,
               c.name AS category,
               COUNT(a.id) AS articles_count,
               MAX(a.fetched_at) AS last_fetched
        FROM sources AS s
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        LEFT JOIN articles AS a ON a.source_id = s.id AND a.deleted_at IS NULL
        WHERE s.deleted_at IS NULL
        GROUP BY s.id
        ORDER BY articles_count DESC
        LIMIT 20
        """
    ).fetchall()
    return _coerce_rows(rows)


def categories_distribution(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Article count per category."""

    rows = conn.execute(
        """
        SELECT COALESCE(c.name, '(uncategorized)') AS name,
               COUNT(a.id) AS articles_count
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        WHERE a.deleted_at IS NULL
        GROUP BY c.id
        ORDER BY articles_count DESC
        """
    ).fetchall()
    return _coerce_rows(rows)


def events_hot(
    conn: sqlite3.Connection,
    *,
    limit: int = 10,
) -> list[dict[str, object]]:
    """Top events by heat score (from latest snapshot)."""

    rows = conn.execute(
        """
        SELECT e.id, e.title, e.summary, e.status, e.category,
               e.first_seen_at, e.last_seen_at, e.article_count,
               s.heat_score, s.importance_score
        FROM events AS e
        LEFT JOIN event_score_snapshots AS s
               ON s.event_id = e.id AND s.is_current = 1
        ORDER BY COALESCE(s.heat_score, 0) DESC,
                 COALESCE(s.importance_score, 0) DESC,
                 e.article_count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            **dict(r),
            "article_count": int(r["article_count"]),
            "heat_score": float(r["heat_score"] or 0),
            "importance_score": float(r["importance_score"] or 0),
        }
        for r in rows
    ]


def entities_top(
    conn: sqlite3.Connection,
    *,
    limit: int = 15,
) -> list[dict[str, object]]:
    """Most mentioned entities (via Phase 4 article_entities)."""

    rows = conn.execute(
        """
        SELECT e.canonical_name AS name, e.entity_type,
               COUNT(ae.article_id) AS mentions
        FROM entities AS e
        JOIN article_entities AS ae ON ae.entity_id = e.id
        GROUP BY e.id
        ORDER BY mentions DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {**dict(r), "mentions": int(r["mentions"])}
        for r in rows
    ]


def reading_state_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT reading_status, COUNT(*) AS n
        FROM articles WHERE deleted_at IS NULL
        GROUP BY reading_status
        """
    ).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out[str(r["reading_status"])] = int(r["n"])
    return out


def source_health(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Source health: status, last collected, error counts."""

    rows = conn.execute(
        """
        SELECT s.id, s.name, s.health_status, s.enabled,
               s.last_fetch_at, s.last_success_at, s.last_error_at,
               s.last_error_code, s.last_error_message,
               h.status AS log_status, h.http_status, h.latency_ms,
               h.error_code AS log_error_code, h.checked_at AS last_checked
        FROM sources AS s
        LEFT JOIN source_health_logs AS h
               ON h.id = (SELECT id FROM source_health_logs
                          WHERE source_id = s.id
                          ORDER BY checked_at DESC LIMIT 1)
        WHERE s.deleted_at IS NULL
        ORDER BY s.name ASC
        """
    ).fetchall()
    return _coerce_rows(rows)
