"""Parameterised SQL for `sources`.

No connection lifecycle and no transactions here: callers own both.
All filters are bound parameters; ordering is restricted to a whitelist.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import SourceRecord

_ACTIVE = "s.deleted_at IS NULL"

_ORDER_COLUMNS = {
    "priority": "s.priority",
    "name": "s.name",
    "created_at": "s.created_at",
    "updated_at": "s.updated_at",
    "last_success_at": "s.last_success_at",
}


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_record(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        id=str(row["id"]),
        category_id=row["category_id"],
        category_name=row["category_name"],
        name=str(row["name"]),
        source_type=str(row["source_type"]),
        url=str(row["url"]),
        homepage_url=row["homepage_url"],
        description=row["description"],
        language=row["language"],
        country=row["country"],
        priority=int(row["priority"]),
        credibility_score=row["credibility_score"],
        fetch_interval_minutes=int(row["fetch_interval_minutes"]),
        max_entries_per_fetch=row["max_entries_per_fetch"],
        enabled=bool(int(row["enabled"])),
        health_status=str(row["health_status"]),
        last_fetch_at=row["last_fetch_at"],
        last_success_at=row["last_success_at"],
        last_error_at=row["last_error_at"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        article_count=int(row["article_count"]),
        adapter_verification=row["adapter_verification"],
    )


def _where(
    *,
    keyword: str | None,
    source_type: str | None,
    category_id: str | None,
    uncategorized: bool,
    enabled: bool | None,
    language: str | None,
) -> tuple[str, list[object]]:
    clauses = [_ACTIVE]
    params: list[object] = []
    if keyword:
        clauses.append("s.name LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(keyword)}%")
    if source_type is not None:
        clauses.append("s.source_type = ?")
        params.append(source_type)
    if uncategorized:
        clauses.append("s.category_id IS NULL")
    elif category_id is not None:
        clauses.append("s.category_id = ?")
        params.append(category_id)
    if enabled is not None:
        clauses.append("s.enabled = ?")
        params.append(1 if enabled else 0)
    if language:
        clauses.append("s.language = ?")
        params.append(language)
    return " AND ".join(clauses), params


def list_sources(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    keyword: str | None = None,
    source_type: str | None = None,
    category_id: str | None = None,
    uncategorized: bool = False,
    enabled: bool | None = None,
    language: str | None = None,
    order: str = "priority",
    direction: str = "desc",
) -> tuple[list[SourceRecord], int]:
    where_sql, params = _where(
        keyword=keyword,
        source_type=source_type,
        category_id=category_id,
        uncategorized=uncategorized,
        enabled=enabled,
        language=language,
    )
    column = _ORDER_COLUMNS.get(order, _ORDER_COLUMNS["priority"])
    dir_sql = "ASC" if direction.lower() == "asc" else "DESC"

    rows = conn.execute(
        f"""
        SELECT s.*, c.name AS category_name,
               ac.last_verification AS adapter_verification,
               (SELECT COUNT(*) FROM articles AS a
                 WHERE a.source_id = s.id AND a.deleted_at IS NULL) AS article_count
        FROM sources AS s
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        LEFT JOIN source_adapter_configs AS ac
               ON ac.source_id = s.id
        WHERE {where_sql}
        ORDER BY {column} {dir_sql}, s.created_at DESC, s.id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM sources AS s WHERE {where_sql}",
        tuple(params),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_row_to_record(row) for row in rows], total


def get_active(conn: sqlite3.Connection, source_id: str) -> SourceRecord | None:
    row = conn.execute(
        f"""
        SELECT s.*, c.name AS category_name,
               ac.last_verification AS adapter_verification,
               (SELECT COUNT(*) FROM articles AS a
                 WHERE a.source_id = s.id AND a.deleted_at IS NULL) AS article_count
        FROM sources AS s
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        LEFT JOIN source_adapter_configs AS ac
               ON ac.source_id = s.id
        WHERE s.id = ? AND {_ACTIVE}
        """,
        (source_id,),
    ).fetchone()
    return None if row is None else _row_to_record(row)


def url_exists(
    conn: sqlite3.Connection, url: str, *, exclude_id: str | None = None
) -> bool:
    if exclude_id is None:
        row = conn.execute(
            f"SELECT 1 FROM sources AS s WHERE s.url = ? AND {_ACTIVE} LIMIT 1",
            (url,),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT 1 FROM sources AS s WHERE s.url = ? AND s.id <> ? AND {_ACTIVE} LIMIT 1",
            (url, exclude_id),
        ).fetchone()
    return row is not None


def insert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    allowed = [
        "id",
        "category_id",
        "name",
        "source_type",
        "url",
        "homepage_url",
        "description",
        "language",
        "country",
        "priority",
        "credibility_score",
        "fetch_interval_minutes",
        "max_entries_per_fetch",
        "enabled",
        "health_status",
        "created_at",
        "updated_at",
    ]
    columns = ", ".join(allowed)
    placeholders = ", ".join("?" for _ in allowed)
    conn.execute(
        f"INSERT INTO sources ({columns}) VALUES ({placeholders})",
        tuple(values.get(key) for key in allowed),
    )


def update(
    conn: sqlite3.Connection, source_id: str, fields: Mapping[str, object]
) -> None:
    allowed = {
        "category_id",
        "name",
        "source_type",
        "url",
        "homepage_url",
        "description",
        "language",
        "country",
        "priority",
        "credibility_score",
        "fetch_interval_minutes",
        "max_entries_per_fetch",
        "enabled",
        "health_status",
        "updated_at",
    }
    keys = [key for key in fields if key in allowed]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE sources SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), source_id),
    )


def soft_delete(conn: sqlite3.Connection, source_id: str, deleted_at: str) -> None:
    conn.execute(
        "UPDATE sources SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (deleted_at, deleted_at, source_id),
    )


# --------------------------------------------------------------------------
# Phase 2: collection-facing queries and status summary
# --------------------------------------------------------------------------

_COLLECTABLE = (
    "s.deleted_at IS NULL AND s.enabled = 1 AND ("
    "s.source_type IN ('rss','atom') OR EXISTS ("
    "SELECT 1 FROM source_adapter_configs AS ac WHERE ac.source_id = s.id))"
)


def list_collectable(conn: sqlite3.Connection) -> list[SourceRecord]:
    rows = conn.execute(
        f"""
        SELECT s.*, c.name AS category_name,
               ac.last_verification AS adapter_verification,
               (SELECT COUNT(*) FROM articles AS a
                 WHERE a.source_id = s.id AND a.deleted_at IS NULL) AS article_count
        FROM sources AS s
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        LEFT JOIN source_adapter_configs AS ac
               ON ac.source_id = s.id
        WHERE {_COLLECTABLE}
        ORDER BY s.priority DESC, s.created_at ASC, s.id ASC
        """,
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def get_collectable(conn: sqlite3.Connection, source_id: str) -> SourceRecord | None:
    row = conn.execute(
        f"""
        SELECT s.*, c.name AS category_name,
               ac.last_verification AS adapter_verification,
               (SELECT COUNT(*) FROM articles AS a
                 WHERE a.source_id = s.id AND a.deleted_at IS NULL) AS article_count
        FROM sources AS s
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        LEFT JOIN source_adapter_configs AS ac
               ON ac.source_id = s.id
        WHERE s.id = ? AND {_COLLECTABLE}
        """,
        (source_id,),
    ).fetchone()
    return None if row is None else _row_to_record(row)


def update_collection_summary(
    conn: sqlite3.Connection, source_id: str, fields: Mapping[str, object]
) -> None:
    allowed = {
        "health_status",
        "last_fetch_at",
        "last_success_at",
        "last_error_at",
        "last_error_code",
        "last_error_message",
        "updated_at",
    }
    keys = [key for key in fields if key in allowed]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE sources SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), source_id),
    )
