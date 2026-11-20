"""Parameterised SQL for `entities`, `entity_aliases`, `article_entities`."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import ArticleEntityRecord, EntityAliasRecord, EntityRecord

_ENTITY_COLUMNS = (
    "id",
    "canonical_name",
    "entity_type",
    "type_group",
    "normalized_key",
    "status",
    "confidence",
    "normalization_basis",
    "merged_into_entity_id",
    "first_seen_at",
    "last_seen_at",
    "created_at",
    "updated_at",
)

_ENTITY_UPDATE_ALLOWED = {
    "canonical_name",
    "entity_type",
    "type_group",
    "normalized_key",
    "status",
    "confidence",
    "normalization_basis",
    "merged_into_entity_id",
    "first_seen_at",
    "last_seen_at",
    "updated_at",
}

_ALIAS_COLUMNS = (
    "id",
    "entity_id",
    "alias",
    "alias_key",
    "language",
    "source",
    "confidence",
    "merged_from_entity_id",
    "created_at",
)

_ARTICLE_ENTITY_COLUMNS = (
    "id",
    "article_id",
    "entity_id",
    "analysis_id",
    "raw_name",
    "raw_type",
    "match_method",
    "status",
    "confidence",
    "merged_from_entity_id",
    "created_at",
    "updated_at",
)

_ENTITY_SELECT = """
    SELECT e.*,
           (SELECT COUNT(*) FROM article_entities AS ae
             WHERE ae.entity_id = e.id AND ae.status = 'resolved') AS article_count,
           (SELECT COUNT(*) FROM entity_aliases AS al
             WHERE al.entity_id = e.id) AS alias_count
    FROM entities AS e
"""


def _entity_from_row(row: sqlite3.Row) -> EntityRecord:
    return EntityRecord(
        id=str(row["id"]),
        canonical_name=str(row["canonical_name"]),
        entity_type=str(row["entity_type"]),
        type_group=str(row["type_group"]),
        normalized_key=str(row["normalized_key"]),
        status=str(row["status"]),
        confidence=float(row["confidence"]),
        normalization_basis=str(row["normalization_basis"]),
        merged_into_entity_id=row["merged_into_entity_id"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        article_count=int(row["article_count"]),
        alias_count=int(row["alias_count"]),
    )


def _alias_from_row(row: sqlite3.Row) -> EntityAliasRecord:
    return EntityAliasRecord(
        id=str(row["id"]),
        entity_id=str(row["entity_id"]),
        alias=str(row["alias"]),
        alias_key=str(row["alias_key"]),
        language=str(row["language"]),
        source=str(row["source"]),
        confidence=float(row["confidence"]),
        merged_from_entity_id=row["merged_from_entity_id"],
        created_at=str(row["created_at"]),
    )


def _article_entity_from_row(row: sqlite3.Row) -> ArticleEntityRecord:
    keys = set(row.keys())
    return ArticleEntityRecord(
        id=str(row["id"]),
        article_id=str(row["article_id"]),
        entity_id=row["entity_id"],
        analysis_id=row["analysis_id"],
        raw_name=str(row["raw_name"]),
        raw_type=str(row["raw_type"]),
        match_method=str(row["match_method"]),
        status=str(row["status"]),
        confidence=float(row["confidence"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        article_title=row["article_title"] if "article_title" in keys else None,
        source_name=row["source_name"] if "source_name" in keys else None,
        published_at=row["published_at"] if "published_at" in keys else None,
    )


def insert_entity(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_ENTITY_COLUMNS)
    placeholders = ", ".join("?" for _ in _ENTITY_COLUMNS)
    conn.execute(
        f"INSERT INTO entities ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _ENTITY_COLUMNS),
    )


def update_entity(conn: sqlite3.Connection, entity_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _ENTITY_UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE entities SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), entity_id),
    )


def get(conn: sqlite3.Connection, entity_id: str) -> EntityRecord | None:
    row = conn.execute(f"{_ENTITY_SELECT} WHERE e.id = ?", (entity_id,)).fetchone()
    return None if row is None else _entity_from_row(row)


def find_active_by_key(
    conn: sqlite3.Connection, *, normalized_key: str, type_group: str
) -> EntityRecord | None:
    row = conn.execute(
        f"{_ENTITY_SELECT} WHERE e.normalized_key = ? AND e.type_group = ? "
        "AND e.merged_into_entity_id IS NULL AND e.status = 'active' LIMIT 1",
        (normalized_key, type_group),
    ).fetchone()
    return None if row is None else _entity_from_row(row)


def find_active_by_alias(
    conn: sqlite3.Connection, *, alias_key: str, type_group: str
) -> list[EntityRecord]:
    rows = conn.execute(
        f"""
        {_ENTITY_SELECT}
        WHERE e.type_group = ?
          AND e.merged_into_entity_id IS NULL
          AND e.status = 'active'
          AND (
              e.normalized_key = ?
              OR EXISTS (
                  SELECT 1 FROM entity_aliases AS al
                  WHERE al.entity_id = e.id AND al.alias_key = ?
              )
          )
        """,
        (type_group, alias_key, alias_key),
    ).fetchall()
    return [_entity_from_row(row) for row in rows]


def list_entities(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    entity_type: str | None = None,
    keyword: str | None = None,
    order: str = "last_seen",
    direction: str = "desc",
) -> tuple[list[EntityRecord], int]:
    clauses = ["e.merged_into_entity_id IS NULL", "e.status = 'active'"]
    params: list[object] = []
    if entity_type:
        clauses.append("e.entity_type = ?")
        params.append(entity_type)
    if keyword:
        pattern = f"%{keyword}%"
        clauses.append(
            "(e.canonical_name LIKE ? ESCAPE '\\' OR EXISTS ("
            "SELECT 1 FROM entity_aliases AS al WHERE al.entity_id = e.id "
            "AND al.alias LIKE ? ESCAPE '\\'))"
        )
        params.extend([pattern, pattern])
    where = " AND ".join(clauses)
    order_column = {
        "last_seen": "e.last_seen_at",
        "first_seen": "e.first_seen_at",
        "article_count": "article_count",
    }.get(order, "e.last_seen_at")
    direction_sql = "ASC" if direction.lower() == "asc" else "DESC"
    rows = conn.execute(
        f"""
        {_ENTITY_SELECT}
        WHERE {where}
        ORDER BY ({order_column} IS NULL) ASC, {order_column} {direction_sql}, e.id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM entities AS e WHERE {where}", tuple(params)
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_entity_from_row(row) for row in rows], total


def list_aliases(conn: sqlite3.Connection, entity_id: str) -> list[EntityAliasRecord]:
    rows = conn.execute(
        "SELECT * FROM entity_aliases WHERE entity_id = ? ORDER BY source = 'canonical' DESC, alias ASC",
        (entity_id,),
    ).fetchall()
    return [_alias_from_row(row) for row in rows]


def get_alias(conn: sqlite3.Connection, alias_id: str) -> EntityAliasRecord | None:
    row = conn.execute(
        "SELECT * FROM entity_aliases WHERE id = ?", (alias_id,)
    ).fetchone()
    return None if row is None else _alias_from_row(row)


def insert_alias(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_ALIAS_COLUMNS)
    placeholders = ", ".join("?" for _ in _ALIAS_COLUMNS)
    conn.execute(
        f"INSERT OR IGNORE INTO entity_aliases ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _ALIAS_COLUMNS),
    )


def delete_alias(conn: sqlite3.Connection, alias_id: str) -> None:
    conn.execute("DELETE FROM entity_aliases WHERE id = ?", (alias_id,))


def alias_owned_by_other(
    conn: sqlite3.Connection, *, alias_key: str, type_group: str, entity_id: str
) -> EntityRecord | None:
    row = conn.execute(
        f"""
        {_ENTITY_SELECT}
        WHERE e.id <> ? AND e.type_group = ?
          AND e.merged_into_entity_id IS NULL AND e.status = 'active'
          AND (
              e.normalized_key = ?
              OR EXISTS (SELECT 1 FROM entity_aliases AS al
                         WHERE al.entity_id = e.id AND al.alias_key = ?)
          )
        LIMIT 1
        """,
        (entity_id, type_group, alias_key, alias_key),
    ).fetchone()
    return None if row is None else _entity_from_row(row)


def insert_article_entity(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_ARTICLE_ENTITY_COLUMNS)
    placeholders = ", ".join("?" for _ in _ARTICLE_ENTITY_COLUMNS)
    conn.execute(
        f"INSERT OR IGNORE INTO article_entities ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _ARTICLE_ENTITY_COLUMNS),
    )


def article_entity_exists(
    conn: sqlite3.Connection, *, article_id: str, entity_id: str
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM article_entities WHERE article_id = ? AND entity_id = ? LIMIT 1",
        (article_id, entity_id),
    ).fetchone()
    return row is not None


def ambiguous_exists(conn: sqlite3.Connection, *, article_id: str, raw_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM article_entities WHERE article_id = ? AND entity_id IS NULL "
        "AND lower(raw_name) = lower(?) LIMIT 1",
        (article_id, raw_name),
    ).fetchone()
    return row is not None


def list_article_entities(
    conn: sqlite3.Connection, entity_id: str, *, limit: int = 100, offset: int = 0
) -> list[ArticleEntityRecord]:
    rows = conn.execute(
        """
        SELECT ae.*, a.title AS article_title, s.name AS source_name,
               a.published_at AS published_at
        FROM article_entities AS ae
        JOIN articles AS a ON a.id = ae.article_id
        JOIN sources AS s ON s.id = a.source_id
        WHERE ae.entity_id = ? AND a.deleted_at IS NULL
        ORDER BY (a.published_at IS NULL) ASC, a.published_at DESC, ae.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (entity_id, limit, offset),
    ).fetchall()
    return [_article_entity_from_row(row) for row in rows]


def list_entities_for_article(conn: sqlite3.Connection, article_id: str) -> list[ArticleEntityRecord]:
    rows = conn.execute(
        """
        SELECT ae.* FROM article_entities AS ae
        WHERE ae.article_id = ? AND ae.status = 'resolved'
        ORDER BY ae.confidence DESC, ae.created_at ASC
        """,
        (article_id,),
    ).fetchall()
    return [_article_entity_from_row(row) for row in rows]


def list_merged_from(conn: sqlite3.Connection, target_id: str) -> list[EntityRecord]:
    rows = conn.execute(
        f"{_ENTITY_SELECT} WHERE e.merged_into_entity_id = ? ORDER BY e.updated_at DESC",
        (target_id,),
    ).fetchall()
    return [_entity_from_row(row) for row in rows]


def list_merge_candidates(
    conn: sqlite3.Connection, limit: int = 50
) -> list[tuple[EntityRecord, EntityRecord, str]]:
    rows = conn.execute(
        """
        SELECT a.entity_id AS left_id, b.entity_id AS right_id, a.alias_key AS shared_key
        FROM entity_aliases AS a
        JOIN entity_aliases AS b
          ON b.alias_key = a.alias_key AND b.entity_id > a.entity_id
        JOIN entities AS ea ON ea.id = a.entity_id
        JOIN entities AS eb ON eb.id = b.entity_id
        WHERE ea.merged_into_entity_id IS NULL AND eb.merged_into_entity_id IS NULL
          AND ea.status = 'active' AND eb.status = 'active'
          AND ea.type_group = eb.type_group
        GROUP BY a.entity_id, b.entity_id, a.alias_key
        ORDER BY a.alias_key
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    results: list[tuple[EntityRecord, EntityRecord, str]] = []
    for row in rows:
        left = get(conn, str(row["left_id"]))
        right = get(conn, str(row["right_id"]))
        if left is not None and right is not None:
            results.append((left, right, str(row["shared_key"])))
    return results


def move_aliases(
    conn: sqlite3.Connection, *, source_id: str, target_id: str
) -> None:
    conn.execute(
        "UPDATE OR IGNORE entity_aliases SET entity_id = ?, merged_from_entity_id = ? "
        "WHERE entity_id = ?",
        (target_id, source_id, source_id),
    )


def move_article_links(
    conn: sqlite3.Connection, *, source_id: str, target_id: str
) -> None:
    conn.execute(
        "UPDATE OR IGNORE article_entities SET entity_id = ?, merged_from_entity_id = ? "
        "WHERE entity_id = ?",
        (target_id, source_id, source_id),
    )


def restore_article_links(conn: sqlite3.Connection, source_id: str) -> int:
    cursor = conn.execute(
        "UPDATE OR IGNORE article_entities SET entity_id = ?, merged_from_entity_id = NULL "
        "WHERE merged_from_entity_id = ? AND entity_id IS NOT NULL",
        (source_id, source_id),
    )
    return int(cursor.rowcount or 0)


def restore_aliases(conn: sqlite3.Connection, source_id: str) -> int:
    cursor = conn.execute(
        "UPDATE OR IGNORE entity_aliases SET entity_id = ?, merged_from_entity_id = NULL "
        "WHERE merged_from_entity_id = ?",
        (source_id, source_id),
    )
    return int(cursor.rowcount or 0)


def count_ambiguous(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM article_entities WHERE status = 'ambiguous'"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def articles_with_analysis(
    conn: sqlite3.Connection, *, limit: int, offset: int = 0
) -> list[tuple[str, str, str, str, str | None, str | None, str | None]]:
    """Return `(article_id, analysis_id, published_at, fetched_at, source_id, title, content_hash)`."""

    rows = conn.execute(
        """
        SELECT a.id AS article_id, x.id AS analysis_id, a.published_at,
               a.fetched_at, a.source_id, a.title, a.content_hash
        FROM articles AS a
        JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE a.deleted_at IS NULL AND a.status = 'active'
        ORDER BY (a.published_at IS NULL) ASC, a.published_at ASC, a.id ASC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [
        (
            str(row["article_id"]),
            str(row["analysis_id"]),
            row["published_at"],
            str(row["fetched_at"]),
            str(row["source_id"]),
            str(row["title"]),
            str(row["content_hash"]),
        )
        for row in rows
    ]


def get_analysis(conn: sqlite3.Connection, analysis_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM article_ai_analysis WHERE id = ?", (analysis_id,)
    ).fetchone()
