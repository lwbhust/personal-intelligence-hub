"""`/api/v1/search` routes — FTS5 full-text search (Phase 5)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query

from api.v1.models import FtsSearchItem, FtsSearchResponse
from services.search_service import SearchService

router = APIRouter(prefix="/api/v1/search", tags=["search"])
_service = SearchService()


@router.get("", response_model=FtsSearchResponse)
def full_text_search(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    order: Literal["rank", "published_at", "fetched_at"] = "rank",
    source_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    reading_status: Literal["unread", "reading", "read", "later"] | None = None,
    is_favorite: bool | None = None,
    start_published_at: str | None = Query(default=None, max_length=24),
    end_published_at: str | None = Query(default=None, max_length=24),
) -> FtsSearchResponse:
    results, total = _service.search(
        query=q,
        limit=limit,
        offset=offset,
        order=order,
        source_id=str(source_id) if source_id is not None else None,
        category_id=str(category_id) if category_id is not None else None,
        reading_status=reading_status,
        is_favorite=is_favorite,
        start_published_at=start_published_at,
        end_published_at=end_published_at,
    )
    return FtsSearchResponse(
        items=[
            FtsSearchItem(
                article_id=r.article_id,
                title=r.title,
                summary=r.summary,
                snippet=r.snippet,
                rank=r.rank,
                source_name=r.source_name,
                category_name=r.category_name,
                published_at=r.published_at,
                fetched_at=r.fetched_at,
                reading_status=r.reading_status,
                is_favorite=r.is_favorite,
            )
            for r in results
        ],
        total=total,
        limit=limit,
        offset=offset,
        query=q,
    )
