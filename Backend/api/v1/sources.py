"""`/api/v1/sources` routes (Phase 1).

Transport-only layer: parse query/body, delegate to `SourceService`, shape the
response. Phase 1 never performs a network request on create/update.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response

from services.errors import validation
from services.source_health_service import SourceHealthService
from services.source_service import SourceService

from .models import (
    HealthLogPage,
    SourceCreate,
    SourcePage,
    SourceResponse,
    SourceUpdate,
    health_log_response,
    source_response,
)

SourceTypeLiteral = Literal["rss", "atom", "website", "official_announcement", "api"]

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])
_service = SourceService()
_health_service = SourceHealthService()


@router.get("", response_model=SourcePage)
def list_sources(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    q: str | None = Query(default=None, max_length=100),
    source_type: SourceTypeLiteral | None = None,
    category_id: uuid.UUID | None = None,
    uncategorized: bool = False,
    enabled: bool | None = None,
    language: str | None = Query(default=None, max_length=35),
    order: Literal["priority", "name", "created_at", "updated_at", "last_success_at"] = "priority",
    direction: Literal["asc", "desc"] = "desc",
) -> SourcePage:
    records, total = _service.list(
        limit=limit,
        offset=offset,
        keyword=q,
        source_type=source_type,
        category_id=str(category_id) if category_id is not None else None,
        uncategorized=uncategorized,
        enabled=enabled,
        language=language,
        order=order,
        direction=direction,
    )
    return SourcePage(
        items=[source_response(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{source_id}", response_model=SourceResponse)
def get_source(source_id: uuid.UUID) -> SourceResponse:
    return source_response(_service.get(str(source_id)))


@router.post("", status_code=201, response_model=SourceResponse)
def create_source(payload: SourceCreate) -> SourceResponse:
    record = _service.create(
        name=payload.name,
        source_type=payload.source_type,
        url=payload.url,
        homepage_url=payload.homepage_url,
        category_id=payload.category_id,
        description=payload.description,
        language=payload.language,
        country=payload.country,
        priority=payload.priority,
        credibility_score=payload.credibility_score,
        fetch_interval_minutes=payload.fetch_interval_minutes,
        max_entries_per_fetch=payload.max_entries_per_fetch,
        enabled=payload.enabled,
    )
    return source_response(record)


@router.patch("/{source_id}", response_model=SourceResponse)
def update_source(source_id: uuid.UUID, payload: SourceUpdate) -> SourceResponse:
    fields = {name: getattr(payload, name) for name in payload.model_fields_set}
    if not fields:
        raise validation("request", "empty", "没有可更新的字段")
    for required in (
        "name",
        "source_type",
        "url",
        "priority",
        "fetch_interval_minutes",
        "enabled",
    ):
        if required in fields and fields[required] is None:
            raise validation(required, "null", "不能为空")
    return source_response(_service.update(str(source_id), fields))


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: uuid.UUID) -> Response:
    _service.delete(str(source_id))
    return Response(status_code=204)


@router.get("/{source_id}/health", response_model=HealthLogPage)
def source_health(
    source_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
) -> HealthLogPage:
    records, total = _health_service.list(str(source_id), limit=limit)
    return HealthLogPage(
        items=[health_log_response(record) for record in records],
        total=total,
    )
