"""`/api/v1/today` — the single home-page aggregate for the 今日 screen."""

from __future__ import annotations

from fastapi import APIRouter, Query

from services import today_service

router = APIRouter(prefix="/api/v1/today", tags=["today"])


@router.get("/overview")
def get_today_overview(
    picks: int = Query(default=5, ge=1, le=10),
    todo: int = Query(default=10, ge=1, le=20),
) -> dict:
    return today_service.overview(pick_limit=picks, todo_limit=todo)
