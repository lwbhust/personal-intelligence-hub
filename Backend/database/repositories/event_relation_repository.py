"""Parameterised SQL for `event_relations`."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from .models import EventRelationRecord

_COLUMNS = (
    "id",
    "source_event_id",
    "target_event_id",
    "relation_type",
    "confidence",
    "status",
    "rationale",
    "evidence_article_ids_json",
    "actor",
    "algorithm_version",
    "created_at",
    "updated_at",
)


def _from_row(row: sqlite3.Row, *, titles: bool = False) -> EventRelationRecord:
    try:
        evidence = json.loads(str(row["evidence_article_ids_json"]))
    except (TypeError, json.JSONDecodeError):
        evidence = []
    keys = set(row.keys())
    return EventRelationRecord(
        id=str(row["id"]),
        source_event_id=str(row["source_event_id"]),
        target_event_id=str(row["target_event_id"]),
        relation_type=str(row["relation_type"]),
        confidence=float(row["confidence"]),
        status=str(row["status"]),
        rationale=row["rationale"],
        evidence_article_ids=tuple(
            str(item) for item in evidence if isinstance(item, str)
        ),
        actor=str(row["actor"]),
        algorithm_version=str(row["algorithm_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        source_event_title=row["source_event_title"] if titles else None,
        target_event_title=row["target_event_title"] if titles else None,
    )


def upsert_algorithm_candidate(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_COLUMNS)
    placeholders = ", ".join("?" for _ in _COLUMNS)
    conn.execute(
        f"""
        INSERT INTO event_relations ({columns}) VALUES ({placeholders})
        ON CONFLICT(source_event_id, target_event_id, relation_type) DO UPDATE SET
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            evidence_article_ids_json = excluded.evidence_article_ids_json,
            updated_at = excluded.updated_at
        WHERE event_relations.status = 'candidate'
          AND event_relations.actor = 'algorithm'
        """,
        tuple(values[key] for key in _COLUMNS),
    )


def insert_manual(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_COLUMNS)
    placeholders = ", ".join("?" for _ in _COLUMNS)
    conn.execute(
        f"INSERT INTO event_relations ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _COLUMNS),
    )


def get(conn: sqlite3.Connection, relation_id: str) -> EventRelationRecord | None:
    row = conn.execute(
        "SELECT * FROM event_relations WHERE id = ?", (relation_id,)
    ).fetchone()
    return None if row is None else _from_row(row)


def find(
    conn: sqlite3.Connection,
    *,
    source_event_id: str,
    target_event_id: str,
    relation_type: str,
) -> EventRelationRecord | None:
    row = conn.execute(
        "SELECT * FROM event_relations WHERE source_event_id = ? "
        "AND target_event_id = ? AND relation_type = ?",
        (source_event_id, target_event_id, relation_type),
    ).fetchone()
    return None if row is None else _from_row(row)


def list_for_event(conn: sqlite3.Connection, event_id: str) -> list[EventRelationRecord]:
    rows = conn.execute(
        """
        SELECT r.*, s.title AS source_event_title, t.title AS target_event_title
        FROM event_relations AS r
        JOIN events AS s ON s.id = r.source_event_id
        JOIN events AS t ON t.id = r.target_event_id
        WHERE r.source_event_id = ? OR r.target_event_id = ?
        ORDER BY r.confidence DESC, r.created_at DESC
        """,
        (event_id, event_id),
    ).fetchall()
    return [_from_row(row, titles=True) for row in rows]


def update_status(conn: sqlite3.Connection, relation_id: str, *, status: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE event_relations SET status = ?, updated_at = ? WHERE id = ?",
        (status, updated_at, relation_id),
    )


def article_titles(
    conn: sqlite3.Connection, article_ids: list[str]
) -> list[dict[str, str]]:
    if not article_ids:
        return []
    placeholders = ", ".join("?" for _ in article_ids)
    rows = conn.execute(
        f"SELECT id, title FROM articles WHERE id IN ({placeholders})",
        tuple(article_ids),
    ).fetchall()
    by_id = {str(row["id"]): str(row["title"]) for row in rows}
    return [
        {"article_id": article_id, "title": by_id.get(article_id, "")}
        for article_id in article_ids
    ]


def delete_for_merged_event(conn: sqlite3.Connection, source_event_id: str, target_event_id: str) -> None:
    conn.execute(
        "DELETE FROM event_relations WHERE "
        "(source_event_id = ? AND target_event_id = ?) "
        "OR (source_event_id = ? AND target_event_id = ?)",
        (source_event_id, target_event_id, target_event_id, source_event_id),
    )


def merge_event_relations(
    conn: sqlite3.Connection,
    *,
    source_event_id: str,
    target_event_id: str,
    updated_at: str,
) -> None:
    delete_for_merged_event(conn, source_event_id, target_event_id)
    conn.execute(
        "UPDATE OR IGNORE event_relations SET source_event_id = ?, updated_at = ? "
        "WHERE source_event_id = ?",
        (target_event_id, updated_at, source_event_id),
    )
    conn.execute(
        "UPDATE OR IGNORE event_relations SET target_event_id = ?, updated_at = ? "
        "WHERE target_event_id = ?",
        (target_event_id, updated_at, source_event_id),
    )
    conn.execute(
        "DELETE FROM event_relations WHERE source_event_id = ? OR target_event_id = ?",
        (source_event_id, source_event_id),
    )
