"""`/api/v1/pipeline` — Phase 7.2 persistent pipeline and classification APIs.

Transport-only: every route delegates to `PipelineOrchestrator` or the
classification service. No SQL, no model calls and no business logic live here.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

import database
from database.repositories.pipeline_repository import (
    PipelineRunRecord,
    PipelineSettingsRecord,
    PipelineTaskLogRecord,
    PipelineTaskRecord,
)
from services.classification_service import (
    article_category_mapping,
    classification_distribution,
    suggest_for_events,
    taxonomy_snapshot,
)
from services.pipeline_orchestrator import PipelineOrchestrator, get_orchestrator

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

_orchestrator = get_orchestrator()


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automation_enabled: bool | None = None
    paused: bool | None = None
    ai_enabled: bool | None = None
    entity_enabled: bool | None = None
    event_enabled: bool | None = None
    scoring_enabled: bool | None = None
    batch_size: int | None = None
    max_attempts: int | None = None
    ai_interval_seconds: int | None = None


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["enable", "disable", "pause", "resume"]


class BackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = 20


class ClassificationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    limit: int = 200


def _task_payload(task: PipelineTaskRecord) -> dict[str, object]:
    return {
        "id": task.id,
        "task_type": task.task_type,
        "article_id": task.article_id,
        "event_id": task.event_id,
        "stage": task.stage,
        "status": task.status,
        "priority": task.priority,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "next_retry_at": task.next_retry_at,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "input_summary": task.input_summary,
        "output_summary": task.output_summary,
        "trigger_type": task.trigger_type,
        "batch_id": task.batch_id,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "updated_at": task.updated_at,
        "article_title": task.article_title,
        "source_name": task.source_name,
    }


def _log_payload(record: PipelineTaskLogRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "stage": record.stage,
        "level": record.level,
        "message": record.message,
        "detail": record.detail,
        "created_at": record.created_at,
    }


def _settings_payload(record: PipelineSettingsRecord) -> dict[str, object]:
    return {
        "automation_enabled": record.automation_enabled,
        "paused": record.paused,
        "ai_enabled": record.ai_enabled,
        "entity_enabled": record.entity_enabled,
        "event_enabled": record.event_enabled,
        "scoring_enabled": record.scoring_enabled,
        "batch_size": record.batch_size,
        "max_attempts": record.max_attempts,
        "ai_interval_seconds": record.ai_interval_seconds,
        "updated_at": record.updated_at,
    }


def _run_payload(run: PipelineRunRecord) -> dict[str, object]:
    return PipelineOrchestrator._run_payload(run)


@router.get("/overview")
def get_overview() -> dict:
    return _orchestrator.overview()


@router.get("/status")
def get_status() -> dict:
    return {
        "settings": _orchestrator.settings_payload(),
        "runtime": _orchestrator.runtime(),
    }


@router.get("/settings")
def get_settings() -> dict:
    return _orchestrator.settings_payload()


@router.patch("/settings")
def update_settings(payload: SettingsUpdate) -> dict:
    fields = {
        key: value
        for key, value in payload.model_dump().items()
        if value is not None
    }
    return _orchestrator.update_settings(fields)


@router.post("/control")
def control(payload: ControlRequest) -> dict:
    if payload.action == "enable":
        return _orchestrator.set_automation(True)
    if payload.action == "disable":
        return _orchestrator.set_automation(False)
    if payload.action == "pause":
        return _orchestrator.pause()
    return _orchestrator.resume()


@router.get("/tasks")
def list_tasks(
    status: str | None = Query(default=None, max_length=120),
    stage: Literal[
        "quality_check", "ai_analysis", "entity_sync", "event_match", "event_score", "refresh", "done"
    ]
    | None = None,
    trigger_type: Literal["auto", "manual", "backfill"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
) -> dict:
    allowed = {
        "pending",
        "ready",
        "running",
        "retry_wait",
        "succeeded",
        "failed",
        "skipped",
        "cancelled",
    }
    if status is not None:
        requested = {item.strip() for item in status.split(",") if item.strip()}
        if not requested or not requested.issubset(allowed):
            from services.errors import validation

            raise validation("status", "invalid", "不支持的任务状态过滤")
        status = ",".join(sorted(requested))
    records, total = _orchestrator.list_tasks(
        limit=limit,
        offset=offset,
        status=status,
        stage=stage,
        trigger_type=trigger_type,
    )
    return {
        "items": [_task_payload(item) for item in records],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    return {"task": _task_payload(_orchestrator.get_task(task_id))}


@router.get("/tasks/{task_id}/logs")
def get_task_logs(
    task_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    records, total = _orchestrator.task_logs(task_id, limit=limit, offset=offset)
    return {
        "items": [_log_payload(item) for item in records],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str) -> dict:
    return {"task": _task_payload(_orchestrator.retry_task(task_id))}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    return {"task": _task_payload(_orchestrator.cancel_task(task_id))}


@router.get("/backfill/preview")
def backfill_preview() -> dict:
    return _orchestrator.backfill_preview()


@router.post("/backfill", status_code=202)
def create_backfill(payload: BackfillRequest) -> dict:
    result = _orchestrator.create_backfill(limit=payload.limit)
    return {
        "run": result["run"],
        "created_tasks": result["created_tasks"],
    }


@router.get("/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    records, total = _orchestrator.list_runs(limit=limit, offset=offset)
    return {
        "items": [_run_payload(item) for item in records],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return {"run": _run_payload(_orchestrator.get_run(run_id))}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    return {"run": _run_payload(_orchestrator.cancel_run(run_id))}


@router.get("/classification/taxonomy")
def get_taxonomy() -> dict:
    return taxonomy_snapshot()


@router.get("/classification/report")
def classification_report(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100000),
    only_unresolved: bool = False,
) -> dict:
    with database.read_session() as conn:
        suggestions, total = suggest_for_events(
            conn, limit=limit, offset=offset, only_unresolved=only_unresolved
        )
        distribution = classification_distribution(conn)
        mapping = article_category_mapping(conn)
    return {
        "taxonomy_version": taxonomy_snapshot()["version"],
        "events": {
            "items": [item.as_dict() for item in suggestions],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "event_distribution": distribution,
        "article_mapping": mapping,
    }


@router.post("/classification/apply")
def apply_classification(payload: ClassificationApplyRequest) -> dict:
    if not payload.confirm:
        return {
            "applied": False,
            "reason": "需要显式 confirm=true 才会写入真实数据",
        }
    if not 1 <= payload.limit <= 500:
        return {
            "applied": False,
            "reason": "limit 必须在 1–500 之间",
        }
    from services.classification_service import apply_classification as _apply

    return {"applied": True, **_apply(limit=payload.limit)}
