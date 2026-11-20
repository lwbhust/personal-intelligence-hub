"""ASGI application factory.

Contract: `Docs/API_CONTRACT.md` §1, §7, §13 and `Docs/PHASE2_CONTRACT.md`.
- `/docs`, `/redoc`, `/openapi.json` are disabled.
- No CORS middleware is added.
- The bearer token is supplied by `main.py`; the app never reads env itself.
- The collection worker starts/stops with the ASGI lifespan so scheduled work
  never outlives the Sidecar process.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from api.body_limit import BodyLimitMiddleware
from api.errors import register_exception_handlers
from api.health import router as health_router
from api.middleware import RequestMiddleware
from api.v1 import (
    ai,
    articles,
    collection_jobs,
    dashboard,
    entities,
    event_aggregation,
    event_clusters,
    events,
    intelligence,
    personalization,
    pipeline,
    rankings,
    search,
    source_categories,
    source_adapters,
    sources,
    today,
)
from core.version import VERSION
from services.ai_analysis_service import get_ai_service
from services.collection_service import get_collection_service
from services.event_clustering_service import get_event_clustering_service
from services.intelligence_service import get_intelligence_service
from services.pipeline_orchestrator import get_orchestrator


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The orchestrator starts first so ingestion events are never dropped.
    orchestrator = get_orchestrator()
    orchestrator.start()
    collection = get_collection_service()
    collection.start()
    ai_service = get_ai_service()
    ai_service.start()
    clustering = get_event_clustering_service()
    clustering.start()
    intelligence_service = get_intelligence_service()
    intelligence_service.start()
    try:
        yield
    finally:
        intelligence_service.stop()
        clustering.stop()
        ai_service.stop()
        collection.stop()
        orchestrator.stop()


def create_app(token: str) -> FastAPI:
    app = FastAPI(
        title="PIH Sidecar",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )
    # Added first so RequestMiddleware stays outermost: authentication must
    # still run before the body-size check.
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestMiddleware, token=token)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(sources.router)
    app.include_router(source_adapters.router)
    app.include_router(source_categories.router)
    app.include_router(articles.router)
    app.include_router(collection_jobs.router)
    app.include_router(ai.router)
    app.include_router(search.router)
    app.include_router(dashboard.router)
    app.include_router(entities.router)
    app.include_router(events.router)
    app.include_router(event_aggregation.router)
    app.include_router(event_clusters.router)
    app.include_router(rankings.router)
    app.include_router(intelligence.router)
    app.include_router(pipeline.router)
    app.include_router(personalization.router)
    app.include_router(personalization.digest_router)
    app.include_router(today.router)
    return app
