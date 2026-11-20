"""Parameterised SQL for `articles`.

No connection lifecycle and no transactions here: callers own both.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping

from .models import ArticleRecord
from .source_repository import escape_like

_ACTIVE_SOURCE = "s.deleted_at IS NULL"
_ORDER_COLUMNS = {
    "published_at": "a.published_at",
    "fetched_at": "a.fetched_at",
    "created_at": "a.created_at",
}

_SELECT = """
    SELECT a.*, s.name AS source_name, s.category_id AS category_id,
           c.name AS category_name
    FROM articles AS a
    JOIN sources AS s ON s.id = a.source_id
    LEFT JOIN source_categories AS c
           ON c.id = s.category_id AND c.deleted_at IS NULL
"""


def _row_to_record(row: sqlite3.Row) -> ArticleRecord:
    try:
        reading_status = str(row["reading_status"])
    except (sqlite3.OperationalError, IndexError, KeyError):
        reading_status = "unread"
    try:
        is_favorite = bool(int(row["is_favorite"]))
    except (sqlite3.OperationalError, IndexError, KeyError):
        is_favorite = False
    try:
        last_read_at = row["last_read_at"]
    except (sqlite3.OperationalError, IndexError, KeyError):
        last_read_at = None
    try:
        read_count = int(row["read_count"])
    except (sqlite3.OperationalError, IndexError, KeyError):
        read_count = 0
    try:
        content_fetched_at = row["content_fetched_at"]
    except (sqlite3.OperationalError, IndexError, KeyError):
        content_fetched_at = None
    return ArticleRecord(
        id=str(row["id"]),
        source_id=str(row["source_id"]),
        source_name=row["source_name"],
        category_id=row["category_id"],
        category_name=row["category_name"],
        external_id=row["external_id"],
        canonical_url=row["canonical_url"],
        original_url=row["original_url"],
        title=str(row["title"]),
        author=row["author"],
        summary=row["summary"],
        content_text=row["content_text"],
        content_state=str(row["content_state"]),
        published_at=row["published_at"],
        source_updated_at=row["source_updated_at"],
        fetched_at=str(row["fetched_at"]),
        content_hash=str(row["content_hash"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        reading_status=reading_status,
        is_favorite=is_favorite,
        last_read_at=last_read_at,
        read_count=read_count,
        content_fetched_at=content_fetched_at,
    )


def _where(
    *,
    keyword: str | None,
    source_id: str | None,
    category_id: str | None,
    status: str,
    reading_status: str | None = None,
    is_favorite: bool | None = None,
) -> tuple[str, list[object]]:
    clauses = ["a.deleted_at IS NULL", _ACTIVE_SOURCE, "a.status = ?"]
    params: list[object] = [status]
    if keyword:
        clauses.append("(a.title LIKE ? ESCAPE '\\' OR a.summary LIKE ? ESCAPE '\\')")
        pattern = f"%{escape_like(keyword)}%"
        params.extend([pattern, pattern])
    if source_id is not None:
        clauses.append("a.source_id = ?")
        params.append(source_id)
    if category_id is not None:
        clauses.append("s.category_id = ?")
        params.append(category_id)
    if reading_status is not None:
        clauses.append("a.reading_status = ?")
        params.append(reading_status)
    if is_favorite is not None:
        clauses.append("a.is_favorite = ?")
        params.append(1 if is_favorite else 0)
    return " AND ".join(clauses), params


def list_articles(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    keyword: str | None = None,
    source_id: str | None = None,
    category_id: str | None = None,
    status: str = "active",
    reading_status: str | None = None,
    is_favorite: bool | None = None,
    order: str = "published_at",
    direction: str = "desc",
) -> tuple[list[ArticleRecord], int]:
    where_sql, params = _where(
        keyword=keyword,
        source_id=source_id,
        category_id=category_id,
        status=status,
        reading_status=reading_status,
        is_favorite=is_favorite,
    )
    column = _ORDER_COLUMNS.get(order, _ORDER_COLUMNS["published_at"])
    dir_sql = "ASC" if direction.lower() == "asc" else "DESC"
    rows = conn.execute(
        f"""
        {_SELECT}
        WHERE {where_sql}
        ORDER BY ({column} IS NULL) ASC, {column} {dir_sql}, a.id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    return [_row_to_record(row) for row in rows], total


def get_active(conn: sqlite3.Connection, article_id: str) -> ArticleRecord | None:
    row = conn.execute(
        f"""
        {_SELECT}
        WHERE a.id = ? AND a.deleted_at IS NULL AND {_ACTIVE_SOURCE}
        """,
        (article_id,),
    ).fetchone()
    return None if row is None else _row_to_record(row)


def list_by_source_window(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    start: str,
    end: str,
) -> list[ArticleRecord]:
    """Articles from one source published inside a closed time window.

    Used for same-source title dedup: feed platforms occasionally publish the
    same story twice with different GUIDs and URLs minutes apart.
    """

    rows = conn.execute(
        f"""
        {_SELECT}
        WHERE a.source_id = ? AND a.deleted_at IS NULL
          AND a.published_at IS NOT NULL
          AND a.published_at BETWEEN ? AND ?
        """,
        (source_id, start, end),
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def find_existing(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    external_id: str | None,
    canonical_url: str | None,
    content_hash: str,
) -> tuple[ArticleRecord, str] | None:
    """Return the matching article and which rule matched.

    Precedence is fixed by contract §5: external_id, canonical_url, hash.
    Different sources are never cross-matched. Soft-deleted rows still match:
    retention must not cause the same old entry to be re-inserted on the next
    feed/web run.
    """

    if external_id:
        row = conn.execute(
            f"""
            {_SELECT}
            WHERE a.source_id = ? AND a.external_id = ?
            LIMIT 1
            """,
            (source_id, external_id),
        ).fetchone()
        if row is not None:
            return _row_to_record(row), "external_id"
    if canonical_url:
        row = conn.execute(
            f"""
            {_SELECT}
            WHERE a.source_id = ? AND a.canonical_url = ?
            LIMIT 1
            """,
            (source_id, canonical_url),
        ).fetchone()
        if row is not None:
            return _row_to_record(row), "canonical_url"
    row = conn.execute(
        f"""
        {_SELECT}
        WHERE a.source_id = ? AND a.content_hash = ?
        LIMIT 1
        """,
        (source_id, content_hash),
    ).fetchone()
    if row is not None:
        return _row_to_record(row), "content_hash"
    return None


_INSERT_COLUMNS = (
    "id",
    "source_id",
    "external_id",
    "canonical_url",
    "original_url",
    "title",
    "author",
    "summary",
    "content_text",
    "content_state",
    "published_at",
    "source_updated_at",
    "fetched_at",
    "content_hash",
    "status",
    "created_at",
    "updated_at",
)


def insert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_INSERT_COLUMNS)
    placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
    conn.execute(
        f"INSERT INTO articles ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _INSERT_COLUMNS),
    )


_UPDATE_ALLOWED = {
    "external_id",
    "canonical_url",
    "original_url",
    "title",
    "author",
    "summary",
    "content_text",
    "content_state",
    "content_fetched_at",
    "published_at",
    "source_updated_at",
    "fetched_at",
    "content_hash",
    "status",
    "updated_at",
    "deleted_at",
    "reading_status",
    "is_favorite",
    "last_read_at",
    "read_count",
}


def update(conn: sqlite3.Connection, article_id: str, fields: Mapping[str, object]) -> None:
    keys = [key for key in fields if key in _UPDATE_ALLOWED]
    if not keys:
        return
    assignments = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(
        f"UPDATE articles SET {assignments} WHERE id = ?",
        (*(fields[key] for key in keys), article_id),
    )


def count_active(conn: sqlite3.Connection, *, source_id: str | None = None) -> int:
    if source_id is None:
        row = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL AND source_id = ?",
            (source_id,),
        ).fetchone()
    return int(row[0]) if row is not None else 0


# --- Phase 5: reading state & favorite management ---

def set_reading_state(
    conn: sqlite3.Connection,
    article_id: str,
    *,
    reading_status: str | None = None,
    is_favorite: bool | None = None,
    mark_read_now: bool = False,
) -> None:
    """Update reading_state and/or favorite flag on one article.

    When `mark_read_now` is True, also bump `last_read_at` and `read_count`.
    """

    allowed = {"reading_status", "is_favorite", "last_read_at", "read_count", "updated_at"}
    fields: dict[str, object] = {}
    if reading_status is not None:
        if reading_status not in {"unread", "reading", "read", "later"}:
            raise ValueError(f"invalid reading_status: {reading_status}")
        fields["reading_status"] = reading_status
    if is_favorite is not None:
        fields["is_favorite"] = 1 if is_favorite else 0
    if mark_read_now:
        from core.timeutil import utc_timestamp  # noqa: PLC0415 — local relative import

        fields["last_read_at"] = utc_timestamp()
        conn.execute(
            "UPDATE articles SET read_count = read_count + 1 WHERE id = ?",
            (article_id,),
        )
    fields["updated_at"] = _current_utc(conn)
    update(conn, article_id, fields)


def set_favorite(conn: sqlite3.Connection, article_id: str, *, is_favorite: bool) -> None:
    set_reading_state(conn, article_id, is_favorite=is_favorite)


def mark_read(conn: sqlite3.Connection, article_id: str) -> None:
    """Convenience: set reading_status to 'read' and record the read time."""

    set_reading_state(
        conn, article_id, reading_status="read", mark_read_now=True
    )


def mark_later(conn: sqlite3.Connection, article_id: str) -> None:
    set_reading_state(conn, article_id, reading_status="later")


def mark_unread(conn: sqlite3.Connection, article_id: str) -> None:
    set_reading_state(conn, article_id, reading_status="unread")


def update_content(
    conn: sqlite3.Connection,
    article_id: str,
    *,
    content_text: str,
    content_state: str,
    fetched_at: str,
) -> None:
    """Store an extracted body and record when it was fetched.

    The FTS5 triggers on `articles` keep the search index in sync, so no
    separate indexing call is required.
    """

    if content_state not in {"full", "summary_only", "unavailable"}:
        raise ValueError(f"invalid content_state: {content_state}")
    update(
        conn,
        article_id,
        {
            "content_text": content_text,
            "content_state": content_state,
            "content_fetched_at": fetched_at,
            "updated_at": fetched_at,
        },
    )


def mark_content_fetch(conn: sqlite3.Connection, article_id: str, *, fetched_at: str) -> None:
    """Record a fetch attempt that did not produce a usable body."""

    update(
        conn,
        article_id,
        {"content_fetched_at": fetched_at, "updated_at": fetched_at},
    )


def batch_set_reading_state(
    conn: sqlite3.Connection,
    article_ids: Iterable[str],
    *,
    reading_status: str | None = None,
    is_favorite: bool | None = None,
) -> int:
    """Apply reading_state / favorite change to many articles. Returns count."""

    ids = list(article_ids)
    if not ids:
        return 0
    if reading_status is not None and reading_status not in {"unread", "reading", "read", "later"}:
        raise ValueError(f"invalid reading_status: {reading_status}")

    clauses: list[str] = []
    params: list[object] = []
    if reading_status is not None:
        clauses.append("reading_status = ?")
        params.append(reading_status)
    if is_favorite is not None:
        clauses.append("is_favorite = ?")
        params.append(1 if is_favorite else 0)
    if not clauses:
        return 0
    clauses.append("updated_at = ?")
    params.append(_current_utc(conn))

    placeholders = ",".join("?" for _ in ids)
    sql = f"UPDATE articles SET {', '.join(clauses)} WHERE id IN ({placeholders})"
    cur = conn.execute(sql, (*params, *ids))
    return cur.rowcount or 0


def _current_utc(conn: sqlite3.Connection) -> str:
    from core.timeutil import utc_timestamp  # noqa: PLC0415

    return utc_timestamp()
