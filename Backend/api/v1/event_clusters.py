"""`/api/v1/event-clusters` routes (Phase 4)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, status

from services.event_clustering_service import get_event_clustering_service

from .models import (
    ClusterRunCreate,
    ClusterRunPage,
    ClusterRunResponse,
    ClusterStatusResponse,
    cluster_run_response,
)

router = APIRouter(prefix="/api/v1/event-clusters", tags=["event-clusters"])
_service = get_event_clustering_service()


@router.post(
    "/runs", response_model=ClusterRunResponse, status_code=status.HTTP_202_ACCEPTED
)
def create_run(payload: ClusterRunCreate) -> ClusterRunResponse:
    run = _service.create_run(
        scope=payload.scope,
        article_ids=payload.article_ids,
        limit=payload.limit,
        use_llm=payload.use_llm,
    )
    return cluster_run_response(run)


@router.get("/runs", response_model=ClusterRunPage)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    status_filter: Literal[
        "pending", "running", "succeeded", "partially_succeeded", "failed", "cancelled"
    ]
    | None = Query(default=None, alias="status"),
) -> ClusterRunPage:
    records, total = _service.list_runs(limit=limit, offset=offset, status=status_filter)
    return ClusterRunPage(
        items=[cluster_run_response(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/status", response_model=ClusterStatusResponse)
def cluster_status() -> ClusterStatusResponse:
    return ClusterStatusResponse(**_service.status())


@router.get("/runs/{run_id}", response_model=ClusterRunResponse)
def get_run(run_id: uuid.UUID) -> ClusterRunResponse:
    return cluster_run_response(_service.get_run(str(run_id)))


@router.post("/runs/{run_id}/cancel", response_model=ClusterRunResponse)
def cancel_run(run_id: uuid.UUID) -> ClusterRunResponse:
    return cluster_run_response(_service.cancel(str(run_id)))


@router.post("/runs/{run_id}/retry", response_model=ClusterRunResponse)
def retry_run(run_id: uuid.UUID) -> ClusterRunResponse:
    return cluster_run_response(_service.retry(str(run_id)))
