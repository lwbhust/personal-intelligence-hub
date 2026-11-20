"""`/api/v1/event-aggregation` routes (Phase 7.6)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.event_aggregation_service import get_event_aggregation_service

from .models import AggregationApplyRequest

router = APIRouter(prefix="/api/v1/event-aggregation", tags=["event-aggregation"])
_service = get_event_aggregation_service()


@router.get("/status")
def aggregation_status() -> dict:
    return _service.status()


@router.get("/dry-run")
def aggregation_dry_run(
    days: int = Query(default=30, ge=1, le=90),
    event_limit: int = Query(default=200, ge=1, le=200),
    article_limit: int = Query(default=500, ge=0, le=800),
) -> dict:
    """Read-only candidate generation. Never writes or merges anything."""

    return _service.dry_run(
        days=days, event_limit=event_limit, article_limit=article_limit
    )


@router.post("/apply")
def aggregation_apply(payload: AggregationApplyRequest) -> dict:
    """Explicit merge of verified candidates; creates a backup first."""

    pairs = [
        {
            "kind": item.kind,
            "source_event_id": item.source_event_id,
            "target_event_id": item.target_event_id,
            "article_id": item.article_id,
            "event_id": item.event_id,
            "article_ids": item.article_ids,
        }
        for item in payload.pairs
    ]
    return _service.apply(
        pairs, confirm=payload.confirm, create_backup=payload.create_backup
    )
