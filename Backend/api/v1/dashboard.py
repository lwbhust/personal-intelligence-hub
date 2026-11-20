"""`/api/v1/dashboard` — Phase 6.1 intelligent cockpit."""

from __future__ import annotations

from fastapi import APIRouter, Query

import database
from services import dashboard_service as ds

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/overview")
def get_overview() -> dict:
    with database.read_session() as conn:
        return ds.overview(conn)


@router.get("/articles/trend")
def get_articles_trend(days: int = Query(default=30, ge=1, le=365)) -> dict:
    with database.read_session() as conn:
        return {"days": days, "items": ds.articles_trend(conn, days=days)}


@router.get("/sources")
def get_sources_distribution() -> dict:
    with database.read_session() as conn:
        return {"items": ds.sources_distribution(conn)}


@router.get("/categories")
def get_categories_distribution() -> dict:
    with database.read_session() as conn:
        return {"items": ds.categories_distribution(conn)}


@router.get("/events/hot")
def get_hot_events(limit: int = Query(default=10, ge=1, le=50)) -> dict:
    with database.read_session() as conn:
        return {"items": ds.events_hot(conn, limit=limit)}


@router.get("/entities/top")
def get_top_entities(limit: int = Query(default=15, ge=1, le=50)) -> dict:
    with database.read_session() as conn:
        return {"items": ds.entities_top(conn, limit=limit)}


@router.get("/reading-state")
def get_reading_state_distribution() -> dict:
    with database.read_session() as conn:
        return ds.reading_state_distribution(conn)


@router.get("/source-health")
def get_source_health() -> dict:
    with database.read_session() as conn:
        return {"items": ds.source_health(conn)}
