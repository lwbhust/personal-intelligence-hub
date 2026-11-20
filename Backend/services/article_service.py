"""Article browsing: list/detail with whitelist filters (no full-text search)."""

from __future__ import annotations

import database
from database.repositories import article_repository as repo
from database.repositories.models import ArticleRecord

from .errors import not_found, validation

_ORDERS = {"published_at", "fetched_at", "created_at"}
_STATUSES = {"active", "archived", "deleted"}
_READING_STATUSES = {"unread", "reading", "read", "later"}


class ArticleService:
    def list(
        self,
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
        if order not in _ORDERS:
            raise validation("order", "enum", "不支持的排序字段")
        if direction.lower() not in ("asc", "desc"):
            raise validation("direction", "enum", "排序方向只能是 asc 或 desc")
        if status not in _STATUSES:
            raise validation("status", "enum", "不支持的文章状态")
        if reading_status is not None and reading_status not in _READING_STATUSES:
            raise validation("reading_status", "enum", "不支持的阅读状态")
        clean_keyword = None
        if keyword is not None:
            clean_keyword = " ".join(keyword.split())
            if len(clean_keyword) > 100:
                raise validation("q", "string_too_long", "关键词不能超过 100 个字符")
            if not clean_keyword:
                clean_keyword = None
        with database.read_session() as conn:
            return repo.list_articles(
                conn,
                limit=limit,
                offset=offset,
                keyword=clean_keyword,
                source_id=source_id,
                category_id=category_id,
                status=status,
                reading_status=reading_status,
                is_favorite=is_favorite,
                order=order,
                direction=direction,
            )

    def get(self, article_id: str) -> ArticleRecord:
        with database.read_session() as conn:
            record = repo.get_active(conn, article_id)
        if record is None:
            raise not_found("article_not_found", "文章不存在")
        return record

    # --- Phase 5: reading state & favorites ---

    def update_reading_state(
        self,
        article_id: str,
        *,
        reading_status: str | None = None,
        is_favorite: bool | None = None,
        mark_read: bool = False,
    ) -> ArticleRecord:
        if reading_status is not None and reading_status not in _READING_STATUSES:
            raise validation("reading_status", "enum", "不支持的阅读状态")
        with database.session() as conn:
            record = repo.get_active(conn, article_id)
            if record is None:
                raise not_found("article_not_found", "文章不存在")
            repo.set_reading_state(
                conn,
                article_id,
                reading_status=reading_status,
                is_favorite=is_favorite,
                mark_read_now=mark_read,
            )
            conn.commit()
            refreshed = repo.get_active(conn, article_id)
        assert refreshed is not None
        return refreshed

    def set_favorite(self, article_id: str, *, is_favorite: bool) -> ArticleRecord:
        return self.update_reading_state(article_id, is_favorite=is_favorite)

    def mark_read(self, article_id: str) -> ArticleRecord:
        return self.update_reading_state(
            article_id, reading_status="read", mark_read=True
        )

    def mark_later(self, article_id: str) -> ArticleRecord:
        return self.update_reading_state(article_id, reading_status="later")

    def mark_unread(self, article_id: str) -> ArticleRecord:
        return self.update_reading_state(article_id, reading_status="unread")
