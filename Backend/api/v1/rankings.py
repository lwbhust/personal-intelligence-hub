"""`/api/v1/rankings` and score recomputation (Phase 4)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from services.event_scoring_service import get_scoring_service

from .models import (
    RankingItem,
    RankingPage,
    ScoreRecomputeRequest,
    ScoreRecomputeResponse,
    event_summary,
)

router = APIRouter(tags=["rankings"])
_service = get_scoring_service()


@router.get("/api/v1/rankings", response_model=RankingPage)
def rankings(
    kind: Literal["importance", "recent", "heat", "emerging", "confidence", "new"] = "importance",
    window: Literal["24h", "7d", "30d", "all"] = "7d",
    category: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> RankingPage:
    result = _service.rankings(
        kind=kind,
        window=window,
        category=category,
        limit=limit,
        offset=offset,
    )
    return RankingPage(
        kind=str(result["kind"]),
        window=str(result["window"]),
        algorithm_version=str(result["algorithm_version"]),
        generated_at=str(result["generated_at"]),
        items=[
            RankingItem(
                rank=int(item["rank"]),
                event=event_summary(item["event"]),
                score=float(item["score"]),
                previous_total_score=item["previous_total_score"],
                score_change=item["score_change"],
            )
            for item in result["items"]
        ],
        total=int(result["total"]),
        limit=limit,
        offset=offset,
    )


@router.post("/api/v1/event-scores/recompute", response_model=ScoreRecomputeResponse)
def recompute_scores(payload: ScoreRecomputeRequest) -> ScoreRecomputeResponse:
    result = _service.recompute(
        scope=payload.scope,
        event_ids=payload.event_ids,
        limit=payload.limit,
    )
    return ScoreRecomputeResponse(**result)
