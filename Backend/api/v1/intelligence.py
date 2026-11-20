"""`/api/v1/intelligence` — Phase 7.1 intelligence center.

Transport-only: every route delegates to `IntelligenceService` or the
deterministic statistics builder. No SQL and no model calls live here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

import database
from core.timeutil import utc_timestamp
from services.event_scoring_service import get_scoring_service
from services.intelligence_service import get_intelligence_service
from services.intelligence_stats import build_stats, today_utc

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])
_service = get_intelligence_service()
_scoring = get_scoring_service()


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: Literal["daily", "weekly"] = "daily"
    force: bool = False


def _report_payload(record) -> dict:
    return {
        "id": record.id,
        "report_type": record.report_type,
        "period_key": record.period_key,
        "period_start": record.period_start,
        "period_end": record.period_end,
        "data_from_at": record.data_from_at,
        "data_to_at": record.data_to_at,
        "status": record.status,
        "ai_status": record.ai_status,
        "headline": record.headline,
        "overview": record.overview,
        "content": record.content,
        "stats": record.stats,
        "model_name": record.model_name,
        "model_digest": record.model_digest,
        "prompt_version": record.prompt_version,
        "stats_version": record.stats_version,
        "article_count": record.article_count,
        "event_count": record.event_count,
        "entity_count": record.entity_count,
        "citation_count": record.citation_count,
        "trigger_type": record.trigger_type,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_ms": record.duration_ms,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _citation_payload(record) -> dict:
    return {
        "id": record.id,
        "citation_type": record.citation_type,
        "ref_id": record.ref_id,
        "section_key": record.section_key,
        "rank": record.rank,
        "title": record.title,
        "source_name": record.source_name,
        "url": record.url,
        "evidence": record.evidence,
        "created_at": record.created_at,
    }


@router.get("/status")
def get_status() -> dict:
    return _service.status()


@router.get("/reports")
def list_reports(
    report_type: Literal["daily", "weekly"] | None = None,
    status: Literal["pending", "running", "succeeded", "degraded", "failed", "cancelled", "superseded"]
    | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    records, total = _service.list_reports(
        report_type=report_type, status=status, limit=limit, offset=offset
    )
    return {
        "items": [_report_payload(record) for record in records],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    record, citations = _service.report_detail(report_id)
    return {
        "report": _report_payload(record),
        "citations": [_citation_payload(item) for item in citations],
    }


@router.post("/reports/generate", status_code=202)
def generate_report(payload: GenerateRequest) -> dict:
    record, reused = _service.create_report(
        report_type=payload.report_type, force=payload.force
    )
    return {"reused": reused, "report": _report_payload(record)}


@router.post("/reports/{report_id}/cancel")
def cancel_report(report_id: str) -> dict:
    record = _service.cancel_report(report_id)
    return {"report": _report_payload(record)}


@router.get("/emerging")
def get_emerging(
    window_days: int = Query(default=7, ge=1, le=30),
) -> dict:
    """Deterministic emerging-topic statistics (no model, no persisted report)."""

    today = today_utc()
    start = today - timedelta(days=window_days - 1)
    with database.read_session() as conn:
        stats = build_stats(
            conn, report_type="weekly", period_start=start, period_end=today
        )
    return {
        "generated_at": utc_timestamp(),
        "window_days": window_days,
        "period": stats["period"],
        "totals": stats["totals"],
        "categories": stats["categories"],
        "rising_keywords": stats["rising_keywords"],
        "cross_source_topics": stats["cross_source_topics"],
        "new_entities": stats["new_entities"],
        "top_entities": stats["top_entities"],
        "unclustered_samples": stats["unclustered_samples"],
        "notes": stats["notes"],
    }


@router.get("/rankings")
def get_rankings(
    kind: Literal["importance", "heat", "emerging", "new"] = "importance",
    window: Literal["24h", "7d", "30d"] = "7d",
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=1000),
) -> dict:
    result = _scoring.rankings(
        kind=kind, window=window, category=None, limit=limit, offset=offset
    )
    return {
        "kind": result["kind"],
        "window": result["window"],
        "algorithm_version": result["algorithm_version"],
        "generated_at": result["generated_at"],
        "total": result["total"],
        "items": [
            {
                "rank": item["rank"],
                "score": item["score"],
                "previous_total_score": item["previous_total_score"],
                "score_change": item["score_change"],
                "event": {
                    "id": item["event"].id,
                    "title": item["event"].title,
                    "summary": item["event"].summary,
                    "category": item["event"].category,
                    "status": item["event"].status,
                    "article_count": item["event"].article_count,
                    "source_count": item["event"].source_count,
                    "first_seen_at": item["event"].first_seen_at,
                    "last_seen_at": item["event"].last_seen_at,
                    "current_scores": None
                    if item["event"].current_scores is None
                    else {
                        "importance_score": item["event"].current_scores.importance_score,
                        "heat_score": item["event"].current_scores.heat_score,
                        "freshness_score": item["event"].current_scores.freshness_score,
                        "coverage_score": item["event"].current_scores.coverage_score,
                        "confidence_score": item["event"].current_scores.confidence_score,
                        "total_score": item["event"].current_scores.total_score,
                        "algorithm_version": item["event"].current_scores.algorithm_version,
                        "scored_at": item["event"].current_scores.scored_at,
                    },
                },
            }
            for item in result["items"]
        ],
    }
