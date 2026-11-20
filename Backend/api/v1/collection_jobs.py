"""`/api/v1/collection-jobs` and manual collection routes (Phase 2).

Job creation returns immediately (202). Execution happens on a bounded
background worker so `/health` and article browsing never block.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query

from services.collection_service import get_collection_service

from .models import (
    CollectResponse,
    CollectionStatus,
    JobCreate,
    JobPage,
    JobResponse,
    job_item_response,
    job_response,
)

router = APIRouter(prefix="/api/v1", tags=["collection"])
_service = get_collection_service()


@router.post("/collection-jobs", status_code=202, response_model=JobResponse)
def create_job(payload: JobCreate) -> JobResponse:
    source_ids = (
        None
        if payload.source_ids is None
        else [str(source_id) for source_id in payload.source_ids]
    )
    job = _service.create_job(trigger_type="manual", source_ids=source_ids)
    return job_response(job)


@router.get("/collection-jobs", response_model=JobPage)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    status: Literal[
        "pending",
        "running",
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancelled",
    ]
    | None = None,
) -> JobPage:
    records, total = _service.list_jobs(limit=limit, offset=offset, status=status)
    return JobPage(
        items=[job_response(record, include_items=False) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/collection/status", response_model=CollectionStatus)
def collection_status() -> CollectionStatus:
    return CollectionStatus(**_service.status())


@router.get("/collection-jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID) -> JobResponse:
    return job_response(_service.get_job(str(job_id)))


@router.post("/collection-jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: uuid.UUID) -> JobResponse:
    return job_response(_service.cancel_job(str(job_id)))


@router.post(
    "/collection-jobs/{job_id}/retry", status_code=202, response_model=JobResponse
)
def retry_job(job_id: uuid.UUID) -> JobResponse:
    return job_response(_service.retry_job(str(job_id)))


@router.post(
    "/sources/{source_id}/collect", status_code=202, response_model=CollectResponse
)
def collect_source(source_id: uuid.UUID) -> CollectResponse:
    job = _service.create_job(trigger_type="manual", source_ids=[str(source_id)])
    item = job.items[0] if job.items else None
    return CollectResponse(
        job=job_response(job),
        item=job_item_response(item) if item is not None else None,
    )
