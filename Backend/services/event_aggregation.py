"""Shared event aggregate maintenance (used by clustering, manual edits, merges)."""

from __future__ import annotations

import sqlite3
import uuid

from database.repositories import event_repository as event_repo
from event_intelligence.summary import build_event_summary


def rebuild_event_entities(conn: sqlite3.Connection, event_id: str, now: str) -> int:
    rows = conn.execute(
        """
        SELECT ae.entity_id, COUNT(DISTINCT ae.article_id) AS article_count,
               AVG(ae.confidence) AS avg_confidence, MIN(ae.article_id) AS evidence_article_id,
               e.entity_type, e.type_group
        FROM event_articles AS ea
        JOIN article_entities AS ae ON ae.article_id = ea.article_id
        JOIN entities AS e ON e.id = ae.entity_id
        WHERE ea.event_id = ? AND ae.status = 'resolved'
          AND e.status = 'active' AND e.merged_into_entity_id IS NULL
        GROUP BY ae.entity_id, e.entity_type, e.type_group
        ORDER BY article_count DESC, ae.entity_id ASC
        """,
        (event_id,),
    ).fetchall()
    event_repo.delete_event_entities(conn, event_id)
    if not rows:
        return 0

    top_id = str(rows[0]["entity_id"])
    for row in rows:
        entity_id = str(row["entity_id"])
        type_group = str(row["type_group"])
        if entity_id == top_id and len(rows) > 1:
            role = "subject"
        elif type_group == "organization":
            role = "organization"
        elif type_group == "person":
            role = "actor"
        elif type_group == "location":
            role = "location"
        else:
            role = "mentioned"
        event_repo.insert_event_entity(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "entity_id": entity_id,
                "role": role,
                "article_count": int(row["article_count"]),
                "confidence": round(float(row["avg_confidence"] or 0.0), 4),
                "evidence_article_id": row["evidence_article_id"],
                "created_at": now,
                "updated_at": now,
            },
        )
    return len(rows)


def recompute_event_aggregates(conn: sqlite3.Connection, event_id: str, now: str) -> dict[str, object]:
    stats = event_repo.event_stats(conn, event_id)
    event_repo.update_event(
        conn,
        event_id,
        {
            "article_count": stats["article_count"],
            "source_count": stats["source_count"],
            "first_published_at": stats["first_published_at"],
            "last_published_at": stats["last_published_at"],
            "last_seen_at": now,
            "updated_at": now,
        },
    )
    return stats


def refresh_event_summary(conn: sqlite3.Connection, event_id: str) -> None:
    event = event_repo.get(conn, event_id)
    if event is None or event.summary_source == "manual":
        return
    # `list_member_rows` does not join sources; build an id→name map once.
    names = {
        str(row["source_id"]): str(row["source_name"])
        for row in conn.execute(
            "SELECT s.id AS source_id, s.name AS source_name FROM sources AS s"
        ).fetchall()
    }
    articles = [
        (names.get(str(row["source_id"])), row["ai_summary"] or row["summary"], row["title"])
        for row in event_repo.list_member_rows(conn, event_id)
    ]
    summary = build_event_summary(event.title, articles)
    event_repo.update_event(
        conn,
        event_id,
        {"summary": summary, "summary_source": "auto"},
    )
