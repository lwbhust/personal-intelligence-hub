"""`/api/v1/personalization` and `/api/v1/digest` — Phase 7.3.1.

Transport only: every route delegates to `services.personalization_service`.
Request models validate shape; business validation stays in the service so HTTP
and tests share one error contract.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

import database
from database.repositories import personalization_repository as repo
from services import personalization_service as service
from services.errors import validation
from services.personalization_service import result_payload

router = APIRouter(prefix="/api/v1/personalization", tags=["personalization"])
digest_router = APIRouter(prefix="/api/v1/digest", tags=["digest"])

InterestLevel = Literal["core", "extended", "general", "muted"]
InterestType = Literal["domain", "topic", "keyword", "entity", "source", "event"]


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    digest_time: str | None = None
    timezone: str | None = None
    daily_item_limit: int | None = None
    daily_minutes: int | None = None
    exploration_ratio: float | None = None
    auto_adjust_enabled: bool | None = None
    onboarding_done: bool | None = None
    scoring_config: dict | None = None


class InterestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    interest_type: InterestType = "topic"
    level: InterestLevel = "general"
    weight: float | None = Field(default=None, ge=0, le=1)
    domain_key: str | None = None
    enabled: bool = True
    notes: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclusion_keywords: list[str] = Field(default_factory=list, max_length=50)


class InterestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    interest_type: InterestType | None = None
    level: InterestLevel | None = None
    weight: float | None = Field(default=None, ge=0, le=1)
    domain_key: str | None = None
    enabled: bool | None = None
    notes: str | None = None
    keywords: list[str] | None = Field(default=None, max_length=50)
    exclusion_keywords: list[str] | None = Field(default=None, max_length=50)


class KeywordsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclusion_keywords: list[str] = Field(default_factory=list, max_length=50)


class EntityLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str


class SourceLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str


class BlockSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    reason: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["article", "event"]
    target_id: str
    feedback: Literal[
        "interested", "not_interested", "important", "duplicate", "source_disliked", "later"
    ]
    interest_id: str | None = None
    note: str | None = None


class DigestGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str | None = None
    force: bool = False


@router.get("/profile")
def get_profile() -> dict:
    return service.profile_payload()


@router.patch("/profile")
def update_profile(payload: ProfileUpdate) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    service.update_profile(fields)
    return service.profile_payload()


@router.get("/interests")
def list_interests() -> dict:
    return service.interests_payload()


@router.post("/interests", status_code=201)
def create_interest(payload: InterestCreate) -> dict:
    return service.create_interest(payload.model_dump())


@router.patch("/interests/{interest_id}")
def update_interest(interest_id: str, payload: InterestUpdate) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    return service.update_interest(interest_id, fields)


@router.delete("/interests/{interest_id}")
def delete_interest(interest_id: str) -> dict:
    return service.delete_interest(interest_id)


@router.put("/interests/{interest_id}/keywords")
def update_keywords(interest_id: str, payload: KeywordsUpdate) -> dict:
    return service.update_interest(
        interest_id,
        {
            "keywords": payload.keywords,
            "exclusion_keywords": payload.exclusion_keywords,
        },
    )


@router.post("/interests/{interest_id}/entities")
def link_entity(interest_id: str, payload: EntityLinkRequest) -> dict:
    return service.link_interest_entity(interest_id, payload.entity_id)


@router.delete("/interests/{interest_id}/entities/{entity_id}")
def unlink_entity(interest_id: str, entity_id: str) -> dict:
    return service.unlink_interest_entity(interest_id, entity_id)


@router.post("/interests/{interest_id}/sources")
def link_source(interest_id: str, payload: SourceLinkRequest) -> dict:
    return service.link_interest_source(interest_id, payload.source_id)


@router.delete("/interests/{interest_id}/sources/{source_id}")
def unlink_source(interest_id: str, source_id: str) -> dict:
    return service.unlink_interest_source(interest_id, source_id)


@router.get("/blocked-sources")
def blocked_sources() -> dict:
    return service.blocked_sources_payload()


@router.post("/blocked-sources")
def block_source(payload: BlockSourceRequest) -> dict:
    return service.block_source(payload.source_id, payload.reason)


@router.delete("/blocked-sources/{source_id}")
def unblock_source(source_id: str) -> dict:
    return service.unblock_source(source_id)


@router.get("/feed")
def get_feed(
    limit: int | None = Query(default=None, ge=1, le=50),
    include_low: bool = False,
    include_read: bool = False,
) -> dict:
    return service.feed(limit=limit, include_low=include_low, include_read=include_read)


@router.get("/recommendations")
def list_recommendations(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    service.ensure_fresh()
    with database.read_session() as conn:
        records, total = repo.list_results_for_explanation(conn, limit=limit, offset=offset)
        interests = repo.list_interests(conn)
    core_names = {item.name for item in interests if item.enabled and item.level == "core"}
    return {
        "items": [result_payload(record, core_names=core_names) for record in records],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/recommendations/{target_type}/{target_id}")
def get_recommendation(target_type: str, target_id: str) -> dict:
    return service.recommendation_detail(target_type, target_id)


@router.post("/feedback", status_code=201)
def create_feedback(payload: FeedbackRequest) -> dict:
    return service.submit_feedback(**payload.model_dump())


@router.delete("/feedback/{feedback_id}")
def delete_feedback(feedback_id: str) -> dict:
    return service.revoke_feedback(feedback_id)


@router.delete("/feedback/target/{target_type}/{target_id}")
def delete_feedback_for_target(target_type: str, target_id: str) -> dict:
    return service.revoke_feedback_for_target(target_type, target_id)


@router.get("/feedback")
def list_feedback(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    return service.feedback_payloads(limit=limit, offset=offset)


@router.get("/suggestions")
def get_suggestions() -> dict:
    return service.suggestions()


@router.get("/stats")
def get_stats() -> dict:
    return service.stats_payload()


@digest_router.get("/today")
def get_today_digest(
    generate: bool = True,
    force: bool = False,
) -> dict:
    return service.digest_today(generate=generate, force=force)


@digest_router.get("/history")
def get_digest_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    return service.digest_history(limit=limit, offset=offset)


@digest_router.post("/generate", status_code=201)
def generate_digest(payload: DigestGenerateRequest) -> dict:
    if payload.date:
        return service.digest_for_date(payload.date, generate=True, force=payload.force)
    return service.digest_today(generate=True, force=payload.force)


@digest_router.get("/{digest_date}")
def get_digest(
    digest_date: str,
    generate: bool = False,
) -> dict:
    return service.digest_for_date(digest_date, generate=generate)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clear_interests: bool = False
    clear_feedback: bool = False
    clear_digests: bool = False


@router.post("/reset")
def reset_personalization(payload: ResetRequest) -> dict:
    if not (payload.clear_interests or payload.clear_feedback or payload.clear_digests):
        raise validation("clear", "required", "至少选择一项要清除的数据")
    return service.reset_personalization(
        clear_interests=payload.clear_interests,
        clear_feedback=payload.clear_feedback,
        clear_digests=payload.clear_digests,
    )
