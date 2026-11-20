"""`/api/v1/ai` and article-analysis routes (Phase 3). Transport only."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query

from database.repositories.models import AIAnalysisRecord, AIRunRecord
from services.ai_analysis_service import get_ai_service

from .models import (
    AIModelItem,
    AIModelPage,
    AIRunCreate,
    AIRunItemResponse,
    AIRunPage,
    AIRunResponse,
    AIStatus,
    AnalysisItem,
    ArticleAnalysisResponse,
)

router = APIRouter(prefix="/api/v1", tags=["ai"])
_service = get_ai_service()


def _run_item_response(item) -> AIRunItemResponse:
    return AIRunItemResponse(
        id=item.id,
        run_id=item.run_id,
        article_id=item.article_id,
        article_title=item.article_title,
        status=item.status,
        attempts=item.attempts,
        error_code=item.error_code,
        error_message=item.error_message,
        started_at=item.started_at,
        finished_at=item.finished_at,
        duration_ms=item.duration_ms,
    )


def _run_response(record: AIRunRecord, *, include_items: bool = True) -> AIRunResponse:
    return AIRunResponse(
        id=record.id,
        trigger_type=record.trigger_type,
        scope=record.scope,
        status=record.status,
        requested_count=record.requested_count,
        processed_count=record.processed_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        skipped_count=record.skipped_count,
        model_name=record.model_name,
        error_message=record.error_message,
        cancel_requested=record.cancel_requested,
        pause_requested=record.pause_requested,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
        created_at=record.created_at,
        updated_at=record.updated_at,
        items=[_run_item_response(item) for item in record.items] if include_items else [],
    )


def _analysis_response(record: AIAnalysisRecord) -> AnalysisItem:
    return AnalysisItem(
        id=record.id,
        analysis_type=record.analysis_type,
        category=record.category,
        summary=record.summary,
        keywords=list(record.keywords),
        entities=[dict(item) for item in record.entities],
        confidence=record.confidence,
        model_name=record.model_name,
        model_digest=record.model_digest,
        prompt_version=record.prompt_version,
        params=dict(record.params),
        input_chars=record.input_chars,
        duration_ms=record.duration_ms,
        content_hash=record.content_hash,
        created_at=record.created_at,
    )


@router.get("/ai/status", response_model=AIStatus)
def ai_status() -> AIStatus:
    return AIStatus(**_service.status())


@router.get("/ai/models", response_model=AIModelPage)
def ai_models() -> AIModelPage:
    items = [
        AIModelItem(
            model_name=view.record.model_name,
            enabled=view.record.enabled,
            roles=list(view.record.roles),
            num_ctx=view.record.num_ctx,
            digest=view.live_digest or view.record.digest,
            size_bytes=view.live_size_bytes or view.record.size_bytes,
            parameter_size=view.live_parameter_size or view.record.parameter_size,
            quantization=view.live_quantization or view.record.quantization,
            max_context=view.record.max_context,
            installed=view.installed,
            remote=view.remote,
            last_checked_at=view.record.last_checked_at,
        )
        for view in _service.model_views()
    ]
    return AIModelPage(items=items, total=len(items))


@router.post("/ai/runs", status_code=202, response_model=AIRunResponse)
def create_run(payload: AIRunCreate) -> AIRunResponse:
    record = _service.create_run(
        scope=payload.scope,
        article_ids=payload.article_ids,
        limit=payload.limit,
    )
    return _run_response(record)


@router.get("/ai/runs", response_model=AIRunPage)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    status: Literal[
        "pending",
        "running",
        "paused",
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancelled",
    ]
    | None = None,
) -> AIRunPage:
    records, total = _service.list_runs(limit=limit, offset=offset, status=status)
    return AIRunPage(
        items=[_run_response(record, include_items=False) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/ai/runs/{run_id}", response_model=AIRunResponse)
def get_run(run_id: uuid.UUID) -> AIRunResponse:
    return _run_response(_service.get_run(str(run_id)))


@router.post("/ai/runs/{run_id}/pause", response_model=AIRunResponse)
def pause_run(run_id: uuid.UUID) -> AIRunResponse:
    return _run_response(_service.pause_run(str(run_id)))


@router.post("/ai/runs/{run_id}/resume", status_code=202, response_model=AIRunResponse)
def resume_run(run_id: uuid.UUID) -> AIRunResponse:
    return _run_response(_service.resume_run(str(run_id)))


@router.post("/ai/runs/{run_id}/cancel", response_model=AIRunResponse)
def cancel_run(run_id: uuid.UUID) -> AIRunResponse:
    return _run_response(_service.cancel_run(str(run_id)))


@router.post("/ai/runs/{run_id}/retry", status_code=202, response_model=AIRunResponse)
def retry_run(run_id: uuid.UUID) -> AIRunResponse:
    return _run_response(_service.retry_run(str(run_id)))


@router.get(
    "/articles/{article_id}/analysis", response_model=ArticleAnalysisResponse
)
def article_analysis(article_id: uuid.UUID) -> ArticleAnalysisResponse:
    records = _service.article_analysis(str(article_id))
    return ArticleAnalysisResponse(
        article_id=str(article_id),
        items=[_analysis_response(record) for record in records],
    )


@router.post(
    "/articles/{article_id}/analyze",
    status_code=202,
    response_model=AIRunResponse,
)
def analyze_article(article_id: uuid.UUID) -> AIRunResponse:
    return _run_response(_service.analyze_article(str(article_id)))
