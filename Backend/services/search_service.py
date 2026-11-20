"""Full-text search service (Phase 5)."""

from __future__ import annotations

import database
from database.repositories import fts_search_repository as fts
from database.repositories.models import FtsSearchResult

from .errors import validation

_SEARCH_ORDERS = {"rank", "published_at", "fetched_at"}


class SearchService:
    def search(
        self,
        *,
        query: str,
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
        if order not in _SEARCH_ORDERS:
            raise validation("order", "enum", "不支持的搜索排序字段")
        if reading_status is not None and reading_status not in {
            "unread",
            "reading",
            "read",
            "later",
        }:
            raise validation("reading_status", "enum", "不支持的阅读状态")
        clean_query = " ".join(query.split()) if query else ""
        if len(clean_query) > 200:
            raise validation("q", "string_too_long", "搜索查询不能超过 200 字符")
        with database.read_session() as conn:
            return fts.search(
                conn,
                clean_query,
                limit=limit,
                offset=offset,
                source_id=source_id,
                category_id=category_id,
                reading_status=reading_status,
                is_favorite=is_favorite,
                start_published_at=start_published_at,
                end_published_at=end_published_at,
                order=order,
            )

    def rebuild_index(self) -> int:
        with database.session() as conn:
            return fts.rebuild_index(conn)
