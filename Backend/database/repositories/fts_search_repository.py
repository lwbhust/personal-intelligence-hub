"""FTS5 full-text search for articles.

Uses SQLite FTS5 with the built-in `trigram` tokenizer, which handles both
English and Chinese (3-character window). When the query is too short for
trigram (< 3 chars) we fall back to a plain LIKE search across title /
summary / content_text so short keyword searches still return results.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .models import FtsSearchResult

# --- Helpers ---

def _sanitize_query(text: str) -> str:
    return " ".join(text.split())


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_filter_sql(
    *,
    source_id: str | None,
    category_id: str | None,
    reading_status: str | None,
    is_favorite: bool | None,
    start_published_at: str | None,
    end_published_at: str | None,
) -> tuple[str, list[object]]:
    clauses: list[str] = ["a.deleted_at IS NULL", "a.status = 'active'"]
    params: list[object] = []
    if source_id is not None:
        clauses.append("a.source_id = ?")
        params.append(source_id)
    if category_id is not None:
        clauses.append("s.category_id = ?")
        params.append(category_id)
    if reading_status is not None:
        clauses.append("a.reading_status = ?")
        params.append(reading_status)
    if is_favorite is True:
        clauses.append("a.is_favorite = 1")
    elif is_favorite is False:
        clauses.append("a.is_favorite = 0")
    if start_published_at is not None:
        clauses.append("(a.published_at IS NULL OR a.published_at >= ?)")
        params.append(start_published_at)
    if end_published_at is not None:
        clauses.append("(a.published_at IS NULL OR a.published_at <= ?)")
        params.append(end_published_at)
    return " AND ".join(clauses), params


def _fts_capable(query: str) -> bool:
    """trigram tokenizer needs ≥3 chars to form a trigram."""
    return len(query.strip()) >= 3


# --- Main entry point ---

def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    offset: int,
    source_id: str | None = None,
    category_id: str | None = None,
    reading_status: str | None = None,
    is_favorite: bool | None = None,
    start_published_at: str | None = None,
    end_published_at: str | None = None,
    order: str = "rank",
) -> tuple[list[FtsSearchResult], int]:
    cleaned = _sanitize_query(query)
    filter_sql, filter_params = _build_filter_sql(
        source_id=source_id,
        category_id=category_id,
        reading_status=reading_status,
        is_favorite=is_favorite,
        start_published_at=start_published_at,
        end_published_at=end_published_at,
    )

    use_fts = bool(cleaned) and _fts_capable(cleaned)

    if use_fts:
        return _fts_path(
            conn, cleaned, filter_sql, filter_params,
            limit=limit, offset=offset, order=order,
        )
    elif cleaned:
        return _like_path(
            conn, cleaned, filter_sql, filter_params,
            limit=limit, offset=offset, order=order,
        )
    else:
        return _listing_path(
            conn, filter_sql, filter_params,
            limit=limit, offset=offset,
        )


# --- FTS trigram path ---

def _fts_path(
    conn: sqlite3.Connection,
    cleaned: str,
    filter_sql: str,
    filter_params: list[object],
    *,
    limit: int,
    offset: int,
    order: str,
) -> tuple[list[FtsSearchResult], int]:
    count_sql = f"""
        SELECT COUNT(*)
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        WHERE {filter_sql}
          AND a.id IN (SELECT article_id FROM articles_fts WHERE articles_fts MATCH ?)
    """
    count_params = (*filter_params, cleaned)
    total_row = conn.execute(count_sql, count_params).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    order_lower = order.lower()
    if order_lower in {"rank", "relevance"}:
        order_expr = "bm25(articles_fts, 1.5, 1.0, 0.5)"
        order_dir = "ASC"
    elif order_lower == "published_at":
        order_expr = "(a.published_at IS NULL) ASC, a.published_at DESC"
        order_dir = ""
    elif order_lower == "fetched_at":
        order_expr = "a.fetched_at DESC"
        order_dir = ""
    else:
        order_expr = "bm25(articles_fts, 1.5, 1.0, 0.5)"
        order_dir = "ASC"

    results_sql = f"""
        SELECT a.id, a.title, a.summary, a.content_text, a.published_at, a.fetched_at,
               a.reading_status, a.is_favorite,
               s.name AS source_name,
               c.name AS category_name,
               bm25(articles_fts, 1.5, 1.0, 0.5) AS rank_val,
               snippet(articles_fts, 1, '<mark>', '</mark>', '...', 64) AS snippet
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        JOIN articles_fts ON articles_fts.article_id = a.id
        WHERE {filter_sql}
          AND articles_fts MATCH ?
        ORDER BY {order_expr} {order_dir}
        LIMIT ? OFFSET ?
    """
    params = (*filter_params, cleaned, limit, offset)
    rows = conn.execute(results_sql, params).fetchall()

    results = [
        FtsSearchResult(
            article_id=str(row["id"]),
            title=str(row["title"]),
            summary=row["summary"],
            source_name=row["source_name"],
            category_name=row["category_name"],
            published_at=row["published_at"],
            fetched_at=str(row["fetched_at"]),
            reading_status=str(row["reading_status"]),
            is_favorite=bool(int(row["is_favorite"])) if row["is_favorite"] is not None else False,
            rank=float(row["rank_val"]),
            snippet=str(row["snippet"] or ""),
        )
        for row in rows
    ]
    return results, total


# --- LIKE path (short queries < 3 chars) ---

def _like_path(
    conn: sqlite3.Connection,
    cleaned: str,
    filter_sql: str,
    filter_params: list[object],
    *,
    limit: int,
    offset: int,
    order: str,
) -> tuple[list[FtsSearchResult], int]:
    pattern = f"%{_escape_like(cleaned)}%"
    keyword_clause = "(a.title LIKE ? ESCAPE '\\' OR COALESCE(a.summary,'') LIKE ? ESCAPE '\\' OR COALESCE(a.content_text,'') LIKE ? ESCAPE '\\')"

    count_sql = f"""
        SELECT COUNT(*)
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        WHERE {filter_sql} AND {keyword_clause}
    """
    count_params = (*filter_params, pattern, pattern, pattern)
    total_row = conn.execute(count_sql, count_params).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    order_lower = order.lower()
    if order_lower in {"rank", "relevance"}:
        order_expr = "(instr(a.title, ?) > 0) DESC, (instr(COALESCE(a.summary,''), ?) > 0) DESC, a.published_at DESC"
        order_params = [cleaned, cleaned]
    elif order_lower == "published_at":
        order_expr = "(a.published_at IS NULL) ASC, a.published_at DESC"
        order_params = []
    elif order_lower == "fetched_at":
        order_expr = "a.fetched_at DESC"
        order_params = []
    else:
        order_expr = "(instr(a.title, ?) > 0) DESC, (instr(COALESCE(a.summary,''), ?) > 0) DESC, a.published_at DESC"
        order_params = [cleaned, cleaned]

    results_sql = f"""
        SELECT a.id, a.title, a.summary, a.content_text, a.published_at, a.fetched_at,
               a.reading_status, a.is_favorite,
               s.name AS source_name,
               c.name AS category_name
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        WHERE {filter_sql} AND {keyword_clause}
        ORDER BY {order_expr}, a.id ASC
        LIMIT ? OFFSET ?
    """
    params = (*filter_params, pattern, pattern, pattern, *order_params, limit, offset)
    rows = conn.execute(results_sql, params).fetchall()

    results = [
        FtsSearchResult(
            article_id=str(row["id"]),
            title=str(row["title"]),
            summary=row["summary"],
            source_name=row["source_name"],
            category_name=row["category_name"],
            published_at=row["published_at"],
            fetched_at=str(row["fetched_at"]),
            reading_status=str(row["reading_status"]),
            is_favorite=bool(int(row["is_favorite"])) if row["is_favorite"] is not None else False,
            rank=0.0,
            snippet=_make_like_snippet(str(row["title"]), row["summary"], str(row["content_text"] or ""), cleaned),
        )
        for row in rows
    ]
    return results, total


def _make_like_snippet(title: str, summary: str | None, content: str, query: str) -> str:
    """Build a simple marked snippet from title/summary/content for LIKE results."""
    pattern_index = -1
    haystack = ""
    for src_name, src in (("title", title), ("summary", summary or ""), ("content", content)):
        idx = src.lower().find(query.lower())
        if idx >= 0:
            haystack = src
            pattern_index = idx
            break
    if pattern_index < 0:
        return ""
    start = max(0, pattern_index - 20)
    end = min(len(haystack), pattern_index + len(query) + 40)
    snippet = haystack[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(haystack):
        snippet = snippet + "..."
    # Mark the matched query substring (case-preserving)
    lower = haystack[start:end].lower()
    idx = 0
    marked = ""
    while True:
        pos = lower.find(query.lower(), idx)
        if pos < 0:
            marked += snippet[idx:]
            break
        marked += snippet[idx:pos] + "<mark>" + snippet[pos:pos + len(query)] + "</mark>"
        idx = pos + len(query)
    return marked


# --- Empty query: listing path ---

def _listing_path(
    conn: sqlite3.Connection,
    filter_sql: str,
    filter_params: list[object],
    *,
    limit: int,
    offset: int,
) -> tuple[list[FtsSearchResult], int]:
    count_sql = f"""
        SELECT COUNT(*) FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id WHERE {filter_sql}
    """
    total_row = conn.execute(count_sql, filter_params).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    results_sql = f"""
        SELECT a.id, a.title, a.summary, a.content_text, a.published_at, a.fetched_at,
               a.reading_status, a.is_favorite,
               s.name AS source_name,
               c.name AS category_name
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id
        LEFT JOIN source_categories AS c
               ON c.id = s.category_id AND c.deleted_at IS NULL
        WHERE {filter_sql}
        ORDER BY (a.published_at IS NULL) ASC, a.published_at DESC, a.id ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(results_sql, (*filter_params, limit, offset)).fetchall()
    results = [
        FtsSearchResult(
            article_id=str(row["id"]),
            title=str(row["title"]),
            summary=row["summary"],
            source_name=row["source_name"],
            category_name=row["category_name"],
            published_at=row["published_at"],
            fetched_at=str(row["fetched_at"]),
            reading_status=str(row["reading_status"]),
            is_favorite=bool(int(row["is_favorite"])) if row["is_favorite"] is not None else False,
            rank=0.0,
            snippet="",
        )
        for row in rows
    ]
    return results, total


# --- Maintenance ---

def rebuild_index(conn: sqlite3.Connection) -> int:
    """Drop and rebuild the FTS index from `articles`. Returns row count."""
    conn.execute("DELETE FROM articles_fts")
    cur = conn.execute(
        """
        INSERT INTO articles_fts(article_id, title, summary, content_text)
        SELECT id, title, COALESCE(summary,''), COALESCE(content_text,'')
        FROM articles WHERE deleted_at IS NULL
        """
    )
    return cur.rowcount or 0
