"""`/api/v1/entities` routes (Phase 4). Transport-only layer."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from services.entity_service import get_entity_service, sync_entities

from .models import (
    EntityAliasCreate,
    EntityAliasItem,
    EntityDetail,
    EntityMergeCandidatesPage,
    EntityMergePair,
    EntityMergeRequest,
    EntityPage,
    EntitySyncRequest,
    EntitySyncResponse,
    entity_detail,
    entity_summary,
)

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])
_service = get_entity_service()


@router.get("", response_model=EntityPage)
def list_entities(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    type: Literal[
        "person", "organization", "company", "location", "product", "event", "other"
    ]
    | None = None,
    q: str | None = Query(default=None, max_length=100),
    order: Literal["last_seen", "first_seen", "article_count"] = "last_seen",
    direction: Literal["asc", "desc"] = "desc",
) -> EntityPage:
    records, total = _service.list(
        limit=limit,
        offset=offset,
        entity_type=type,
        keyword=q,
        order=order,
        direction=direction,
    )
    return EntityPage(
        items=[entity_summary(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/merge-candidates", response_model=EntityMergeCandidatesPage)
def merge_candidates(
    limit: int = Query(default=50, ge=1, le=200),
) -> EntityMergeCandidatesPage:
    pairs = _service.merge_candidates(limit=limit)
    return EntityMergeCandidatesPage(
        items=[
            EntityMergePair(
                source=entity_summary(source),
                target=entity_summary(target),
                shared_alias=shared_alias,
                reason="shared_alias_key",
            )
            for source, target, shared_alias in pairs
        ],
        total=len(pairs),
    )


@router.post("/merge", response_model=EntityDetail)
def merge_entities(payload: EntityMergeRequest) -> EntityDetail:
    record = _service.merge(
        payload.source_entity_id, payload.target_entity_id, payload.reason
    )
    detail = _service.detail(record.id)
    return entity_detail(detail)


@router.post("/sync", response_model=EntitySyncResponse)
def sync(payload: EntitySyncRequest) -> EntitySyncResponse:
    stats = sync_entities(limit=payload.limit)
    return EntitySyncResponse(
        processed_articles=int(stats["processed_articles"]),
        created_entities=int(stats["created_entities"]),
        linked_mentions=int(stats["linked_mentions"]),
        ambiguous_mentions=int(stats["ambiguous_mentions"]),
        updated_entities=int(stats["updated_entities"]),
        duration_ms=int(stats["duration_ms"]),
    )


@router.get("/{entity_id}", response_model=EntityDetail)
def get_entity(entity_id: uuid.UUID) -> EntityDetail:
    return entity_detail(_service.detail(str(entity_id)))


@router.post("/{entity_id}/unmerge", response_model=EntityDetail)
def unmerge_entity(entity_id: uuid.UUID) -> EntityDetail:
    record = _service.unmerge(str(entity_id))
    return entity_detail(_service.detail(record.id))


@router.post("/{entity_id}/aliases", response_model=EntityDetail)
def add_alias(entity_id: uuid.UUID, payload: EntityAliasCreate) -> EntityDetail:
    _service.add_alias(str(entity_id), payload.alias, payload.language)
    return entity_detail(_service.detail(str(entity_id)))


@router.delete("/{entity_id}/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alias(entity_id: uuid.UUID, alias_id: uuid.UUID) -> Response:
    _service.delete_alias(str(entity_id), str(alias_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
