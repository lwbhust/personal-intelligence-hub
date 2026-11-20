"""`/api/v1/articles` routes (Phase 2 + Phase 5 reading state)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Body, Query

from services.article_service import ArticleService
from services.content_fetch_service import get_content_fetch_service

from .models import (
    ArticleContentFetchResponse,
    ArticleContentFetchResult,
    ArticleDetail,
    ArticlePage,
    ReadingStateUpdate,
    article_detail,
    article_summary,
)

router = APIRouter(prefix="/api/v1/articles", tags=["articles"])
_service = ArticleService()


@router.get("", response_model=ArticlePage)
def list_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    q: str | None = Query(default=None, max_length=100),
    source_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    status: Literal["active", "archived"] = "active",
    reading_status: Literal["unread", "reading", "read", "later"] | None = None,
    is_favorite: bool | None = None,
    order: Literal["published_at", "fetched_at", "created_at"] = "published_at",
    direction: Literal["asc", "desc"] = "desc",
) -> ArticlePage:
    records, total = _service.list(
        limit=limit,
        offset=offset,
        keyword=q,
        source_id=str(source_id) if source_id is not None else None,
        category_id=str(category_id) if category_id is not None else None,
        status=status,
        reading_status=reading_status,
        is_favorite=is_favorite,
        order=order,
        direction=direction,
    )
    return ArticlePage(
        items=[article_summary(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{article_id}", response_model=ArticleDetail)
def get_article(article_id: uuid.UUID) -> ArticleDetail:
    return article_detail(_service.get(str(article_id)))


# --- Phase 5: reading state + favorites ---


@router.patch("/{article_id}/reading-state", response_model=ArticleDetail)
def update_reading_state(
    article_id: uuid.UUID,
    body: ReadingStateUpdate = Body(...),
) -> ArticleDetail:
    record = _service.update_reading_state(
        str(article_id),
        reading_status=body.reading_status,
        is_favorite=body.is_favorite,
        mark_read=body.mark_read,
    )
    return article_detail(record)


@router.post("/{article_id}/mark-read", response_model=ArticleDetail)
def mark_article_read(article_id: uuid.UUID) -> ArticleDetail:
    return article_detail(_service.mark_read(str(article_id)))


@router.post("/{article_id}/mark-later", response_model=ArticleDetail)
def mark_article_later(article_id: uuid.UUID) -> ArticleDetail:
    return article_detail(_service.mark_later(str(article_id)))


@router.post("/{article_id}/mark-unread", response_model=ArticleDetail)
def mark_article_unread(article_id: uuid.UUID) -> ArticleDetail:
    return article_detail(_service.mark_unread(str(article_id)))


@router.put("/{article_id}/favorite", response_model=ArticleDetail)
def set_article_favorite(
    article_id: uuid.UUID,
    is_favorite: bool = Body(..., embed=True),
) -> ArticleDetail:
    return article_detail(_service.set_favorite(str(article_id), is_favorite=is_favorite))


# --- Phase 8: on-demand body retrieval ---


@router.post("/{article_id}/fetch-content", response_model=ArticleContentFetchResponse)
def fetch_article_content(article_id: uuid.UUID) -> ArticleContentFetchResponse:
    record, result = get_content_fetch_service().fetch(str(article_id))
    return ArticleContentFetchResponse(
        article=article_detail(record),
        fetch=ArticleContentFetchResult(**result),
    )
