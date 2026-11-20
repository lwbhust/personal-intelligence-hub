"""Parameterised SQL for `source_categories`.

No connection lifecycle and no transactions here: callers own both
(`database.session()` for writes, `database.read_session()` for reads).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import SourceCategoryRecord

_ACTIVE = "deleted_at IS NULL"

_ORDER_COLUMNS = {"sort_order": "c.sort_order", "name": "c.name"}


def _row_to_record(row: sqlite3.Row) -> SourceCategoryRecord:
    keys = set(row.keys())
    return SourceCategoryRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        description=row["description"],
        sort_order=int(row["sort_order"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        source_count=int(row["source_count"]) if "source_count" in keys else 0,
    )


def list_categories(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    order: str = "sort_order",
    direction: str = "asc",
) -> tuple[list[SourceCategoryRecord], int]:
    column = _ORDER_COLUMNS.get(order, _ORDER_COLUMNS["sort_order"])
    dir_sql = "ASC" if direction.lower() == "asc" else "DESC"
    rows = conn.execute(
        f"""
        SELECT c.id, c.name, c.description, c.sort_order, c.created_at,
               c.updated_at, COUNT(s.id) AS source_count
        FROM source_categories AS c
        LEFT JOIN sources AS s
               ON s.category_id = c.id AND s.deleted_at IS NULL
        WHERE c.{_ACTIVE}
        GROUP BY c.id
        ORDER BY {column} {dir_sql}, c.name ASC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM source_categories WHERE {_ACTIVE}"
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_row_to_record(row) for row in rows], total


def list_active_categories(conn: sqlite3.Connection) -> list[SourceCategoryRecord]:
    rows = conn.execute(
        f"""
        SELECT c.id, c.name, c.description, c.sort_order, c.created_at,
               c.updated_at,
               (SELECT COUNT(*) FROM sources AS s
                 WHERE s.category_id = c.id AND s.deleted_at IS NULL) AS source_count
        FROM source_categories AS c
        WHERE c.{_ACTIVE}
        ORDER BY c.sort_order ASC, c.name ASC
        """
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def get_active(
    conn: sqlite3.Connection, category_id: str
) -> SourceCategoryRecord | None:
    row = conn.execute(
        f"""
        SELECT c.id, c.name, c.description, c.sort_order, c.created_at,
               c.updated_at,
               (SELECT COUNT(*) FROM sources AS s
                 WHERE s.category_id = c.id AND s.deleted_at IS NULL) AS source_count
        FROM source_categories AS c
        WHERE c.id = ? AND c.{_ACTIVE}
        """,
        (category_id,),
    ).fetchone()
    return None if row is None else _row_to_record(row)


def name_exists(
    conn: sqlite3.Connection, name: str, *, exclude_id: str | None = None
) -> bool:
    if exclude_id is None:
        row = conn.execute(
            f"SELECT 1 FROM source_categories WHERE name = ? AND {_ACTIVE} LIMIT 1",
            (name,),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT 1 FROM source_categories WHERE name = ? AND id <> ? AND {_ACTIVE} LIMIT 1",
            (name, exclude_id),
        ).fetchone()
    return row is not None


def insert(
    conn: sqlite3.Connection,
    *,
    category_id: str,
    name: str,
    description: str | None,
    sort_order: int,
    created_at: str,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO source_categories
            (id, name, description, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (category_id, name, description, sort_order, created_at, updated_at),
    )


def update(
    conn: sqlite3.Connection,
    category_id: str,
    fields: Mapping[str, object],
) -> None:
    allowed = {"name", "description", "sort_order", "updated_at"}
    assignments = [f"{key} = ?" for key in fields if key in allowed]
    if not assignments:
        return
    values = [fields[key] for key in fields if key in allowed]
    conn.execute(
        f"UPDATE source_categories SET {', '.join(assignments)} WHERE id = ?",
        (*values, category_id),
    )


def soft_delete(conn: sqlite3.Connection, category_id: str, deleted_at: str) -> None:
    conn.execute(
        "UPDATE source_categories SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (deleted_at, deleted_at, category_id),
    )


def count_active_sources(conn: sqlite3.Connection, category_id: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM sources WHERE category_id = ? AND {_ACTIVE}",
        (category_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def clear_category_on_sources(
    conn: sqlite3.Connection, category_id: str, updated_at: str
) -> None:
    """Detach every source (including soft-deleted ones) before a category
    delete, so a later restore cannot point at a deleted category."""

    conn.execute(
        "UPDATE sources SET category_id = NULL, updated_at = ? WHERE category_id = ?",
        (updated_at, category_id),
    )
