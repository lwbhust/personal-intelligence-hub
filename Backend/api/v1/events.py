"""`/api/v1/events` routes (Phase 4). Transport-only layer."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from services.event_scoring_service import get_scoring_service
from services.event_service import get_event_service

from .models import (
    CandidateItem,
    CandidatePage,
    DecisionItem,
    DecisionPage,
    DecisionResolveRequest,
    EventArticleAddRequest,
    EventArticleAddResponse,
    EventArticleItem,
    EventArticlePage,
    EventCreateRequest,
    EventDetail,
    EventEntityItem,
    EventEntityPage,
    EventMergeRequest,
    EventMergeResponse,
    EventPage,
    EventPatchRequest,
    EventRelationItem,
    EventRelationPage,
    EventSplitRequest,
    EventSummary,
    RelationCreateRequest,
    RelationUpdateRequest,
    ScorePage,
    TimelineItem,
    TimelineNoteRequest,
    TimelineNoteResponse,
    TimelinePage,
    decision_item,
    event_article_item,
    event_detail,
    event_entity_item,
    event_relation_item,
    event_summary,
    score_snapshot_item,
    timeline_item,
)

router = APIRouter(prefix="/api/v1/events", tags=["events"])
_service = get_event_service()
_scoring = get_scoring_service()


# --------------------------------------------------------------------------
# static paths must precede /{event_id}
# --------------------------------------------------------------------------


@router.get("", response_model=EventPage)
def list_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    status_filter: Literal[
        "candidate", "active", "evolving", "dormant", "closed", "merged", "archived"
    ]
    | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=100),
    order: Literal[
        "importance", "recent", "heat", "freshness", "confidence", "articles"
    ] = "importance",
    window: Literal["24h", "7d", "30d", "all"] = "all",
) -> EventPage:
    records, total = _service.list(
        limit=limit,
        offset=offset,
        status=status_filter,
        category=category,
        keyword=q,
        order=order,
        window=window,
    )
    return EventPage(
        items=[event_summary(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/candidates", response_model=CandidatePage)
def list_candidates(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> CandidatePage:
    items, total = _service.candidates(limit=limit, offset=offset)
    return CandidatePage(
        items=[
            CandidateItem(
                event=event_summary(record),
                latest_decision=(decision_item(decision) if decision else None),
            )
            for record, decision in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/clustering/decisions", response_model=DecisionPage)
def list_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    decision: Literal[
        "attached", "created", "ambiguous", "skipped", "llm_rejected", "llm_accepted",
        "manual_resolved",
    ]
    | None = None,
    status_filter: Literal["pending", "resolved", "ignored"] | None = Query(
        default=None, alias="status"
    ),
) -> DecisionPage:
    records, total = _service.decisions(
        limit=limit, offset=offset, decision=decision, status=status_filter
    )
    return DecisionPage(
        items=[decision_item(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/clustering/decisions/{decision_id}/resolve",
    response_model=DecisionItem,
)
def resolve_decision(
    decision_id: uuid.UUID, payload: DecisionResolveRequest
) -> DecisionItem:
    record = _service.resolve_decision(
        str(decision_id), action=payload.action, event_id=payload.event_id
    )
    return decision_item(record)


@router.post("", response_model=EventDetail, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreateRequest) -> EventDetail:
    return event_detail(
        _service.create_event(
            title=payload.title,
            category=payload.category,
            summary=payload.summary,
            article_ids=payload.article_ids,
        )
    )


# --------------------------------------------------------------------------
# dynamic event paths
# --------------------------------------------------------------------------


@router.get("/{event_id}", response_model=EventDetail)
def get_event(event_id: uuid.UUID) -> EventDetail:
    return event_detail(_service.detail(str(event_id)))


@router.patch("/{event_id}", response_model=EventDetail)
def patch_event(event_id: uuid.UUID, payload: EventPatchRequest) -> EventDetail:
    return event_detail(
        _service.patch(
            str(event_id),
            title=payload.title,
            summary=payload.summary,
            category=payload.category,
            status=payload.status,
            status_reason=payload.status_reason,
        )
    )


@router.post("/{event_id}/confirm", response_model=EventDetail)
def confirm_event(event_id: uuid.UUID) -> EventDetail:
    return event_detail(_service.confirm(str(event_id)))


@router.get("/{event_id}/articles", response_model=EventArticlePage)
def list_event_articles(
    event_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> EventArticlePage:
    records, total = _service.articles(str(event_id), limit=limit, offset=offset)
    return EventArticlePage(
        items=[event_article_item(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{event_id}/articles", response_model=EventArticleAddResponse)
def add_event_article(
    event_id: uuid.UUID, payload: EventArticleAddRequest
) -> EventArticleAddResponse:
    result = _service.add_article(
        str(event_id), payload.article_id, payload.role
    )
    return EventArticleAddResponse(**result)


@router.delete(
    "/{event_id}/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_event_article(event_id: uuid.UUID, article_id: uuid.UUID) -> Response:
    _service.remove_article(str(event_id), str(article_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{event_id}/timeline", response_model=TimelinePage)
def event_timeline(
    event_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    key_only: bool = False,
) -> TimelinePage:
    records, total = _service.timeline(
        str(event_id), limit=limit, offset=offset, key_only=key_only
    )
    return TimelinePage(
        items=[timeline_item(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{event_id}/timeline",
    response_model=TimelineNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_timeline_note(
    event_id: uuid.UUID, payload: TimelineNoteRequest
) -> TimelineNoteResponse:
    item_id = _service.add_note(
        str(event_id),
        title=payload.title,
        description=payload.description,
        occurred_at=payload.occurred_at,
    )
    return TimelineNoteResponse(id=item_id)


@router.get("/{event_id}/entities", response_model=EventEntityPage)
def event_entities(event_id: uuid.UUID) -> EventEntityPage:
    records = _service.entities(str(event_id))
    return EventEntityPage(
        items=[event_entity_item(record) for record in records],
        total=len(records),
    )


@router.get("/{event_id}/relations", response_model=EventRelationPage)
def event_relations(event_id: uuid.UUID) -> EventRelationPage:
    records = _service.relations(str(event_id))
    return EventRelationPage(
        items=[event_relation_item(record) for record in records],
        total=len(records),
    )


@router.post(
    "/{event_id}/relations",
    response_model=EventRelationItem,
    status_code=status.HTTP_201_CREATED,
)
def create_relation(
    event_id: uuid.UUID, payload: RelationCreateRequest
) -> EventRelationItem:
    return event_relation_item(
        _service.add_relation(
            str(event_id),
            target_event_id=payload.target_event_id,
            relation_type=payload.relation_type,
            rationale=payload.rationale,
            evidence_article_ids=payload.evidence_article_ids,
        )
    )


@router.patch("/{event_id}/relations/{relation_id}", response_model=EventRelationItem)
def update_relation(
    event_id: uuid.UUID, relation_id: uuid.UUID, payload: RelationUpdateRequest
) -> EventRelationItem:
    return event_relation_item(
        _service.update_relation(str(event_id), str(relation_id), status=payload.status)
    )


@router.get("/{event_id}/scores", response_model=ScorePage)
def event_scores(
    event_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
) -> ScorePage:
    records, total = _scoring.snapshots(
        str(event_id), limit=limit, offset=offset
    )
    return ScorePage(
        items=[score_snapshot_item(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{event_id}/merge", response_model=EventMergeResponse)
def merge_event(event_id: uuid.UUID, payload: EventMergeRequest) -> EventMergeResponse:
    target, stats = _service.merge(
        str(event_id), payload.target_event_id, payload.reason
    )
    return EventMergeResponse(
        **event_detail(target).model_dump(),
        source_event_id=str(event_id),
        moved_articles=stats["moved_articles"],
        duplicate_articles=stats["duplicate_articles"],
        moved_timeline_items=stats["moved_timeline_items"],
    )


@router.post(
    "/{event_id}/unmerge",
    response_model=EventDetail,
)
def unmerge_event(event_id: uuid.UUID) -> EventDetail:
    return event_detail(_service.unmerge(str(event_id)))


@router.post(
    "/{event_id}/split",
    response_model=EventDetail,
    status_code=status.HTTP_201_CREATED,
)
def split_event(event_id: uuid.UUID, payload: EventSplitRequest) -> EventDetail:
    return event_detail(
        _service.split(
            str(event_id),
            article_ids=payload.article_ids,
            title=payload.title,
            category=payload.category,
        )
    )
