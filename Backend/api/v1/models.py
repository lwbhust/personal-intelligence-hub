"""Pydantic request/response models for `/api/v1`.

Extra fields are rejected (`extra="forbid"`) so client typos fail loudly.
Response models never expose soft-delete or storage internals.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["rss", "atom", "website", "official_announcement", "api"]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)
    sort_order: int = Field(default=0, ge=-1000, le=1000)


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=-1000, le=1000)


class CategorySummary(BaseModel):
    id: str
    name: str


class CategoryResponse(BaseModel):
    id: str
    name: str
    description: str | None
    sort_order: int
    source_count: int
    created_at: str
    updated_at: str


class CategoryPage(BaseModel):
    items: list[CategoryResponse]
    total: int
    limit: int
    offset: int


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    source_type: SourceType
    url: str = Field(min_length=1, max_length=2048)
    homepage_url: str | None = Field(default=None, max_length=2048)
    category_id: str | None = None
    description: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=35)
    country: str | None = Field(default=None, max_length=2)
    priority: int = Field(default=0, ge=0, le=100)
    credibility_score: int | None = Field(default=None, ge=0, le=100)
    fetch_interval_minutes: int = Field(default=60, ge=5, le=1440)
    max_entries_per_fetch: int | None = Field(default=None, ge=1, le=100)
    enabled: bool = True


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    source_type: SourceType | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    homepage_url: str | None = Field(default=None, max_length=2048)
    category_id: str | None = None
    description: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=35)
    country: str | None = Field(default=None, max_length=2)
    priority: int | None = Field(default=None, ge=0, le=100)
    credibility_score: int | None = Field(default=None, ge=0, le=100)
    fetch_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    max_entries_per_fetch: int | None = Field(default=None, ge=1, le=100)
    enabled: bool | None = None


class SourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    url: str
    homepage_url: str | None
    description: str | None
    language: str | None
    country: str | None
    priority: int
    credibility_score: int | None
    fetch_interval_minutes: int
    max_entries_per_fetch: int | None
    enabled: bool
    health_status: str
    last_fetch_at: str | None
    last_success_at: str | None
    last_error_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    category: CategorySummary | None
    article_count: int
    adapter_verification: str | None
    created_at: str
    updated_at: str


class SourcePage(BaseModel):
    items: list[SourceResponse]
    total: int
    limit: int
    offset: int


class AdapterConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_type: Literal["html_list"] = "html_list"
    list_urls: list[str] = Field(min_length=1, max_length=10)
    link_pattern: str = Field(min_length=1, max_length=500)
    max_pages: int = Field(default=1, ge=1, le=3)
    rate_limit_seconds: int = Field(default=5, ge=1, le=60)
    max_entries_per_run: int = Field(default=12, ge=1, le=50)
    fetch_full_text: bool = False


class AdapterConfigResponse(BaseModel):
    source_id: str
    adapter_type: str
    entry_url: str
    list_urls: list[str]
    link_pattern: str | None
    max_pages: int
    rate_limit_seconds: int
    max_entries_per_run: int
    fetch_full_text: bool
    config_version: str
    last_verified_at: str | None
    last_verification: str
    created_at: str
    updated_at: str


class AdapterDryRunEntry(BaseModel):
    title: str
    link: str | None
    published_at: str | None
    summary_chars: int
    content_chars: int
    content_state: str


class AdapterDryRunResponse(BaseModel):
    source_id: str
    adapter_type: str
    http_status: int | None
    duration_ms: int
    suggestion: str
    entries: list[AdapterDryRunEntry]
    errors: list[str]


# --------------------------------------------------------------------------
# Phase 2: articles, collection jobs, source health
# --------------------------------------------------------------------------


class ArticleSummary(BaseModel):
    id: str
    source_id: str
    source_name: str | None
    category_id: str | None
    category_name: str | None
    title: str
    author: str | None
    summary: str | None
    canonical_url: str | None
    content_state: str
    published_at: str | None
    fetched_at: str
    status: str
    created_at: str
    updated_at: str
    reading_status: str = "unread"
    is_favorite: bool = False
    last_read_at: str | None = None
    read_count: int = 0


class ArticleDetail(ArticleSummary):
    external_id: str | None
    original_url: str | None
    content_text: str | None
    source_updated_at: str | None
    content_hash: str
    content_fetched_at: str | None = None


class ArticlePage(BaseModel):
    items: list[ArticleSummary]
    total: int
    limit: int
    offset: int


class ArticleContentFetchResult(BaseModel):
    status: str
    chars: int = 0
    url: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ArticleContentFetchResponse(BaseModel):
    article: ArticleDetail
    fetch: ArticleContentFetchResult


# --------------------------------------------------------------------------
# Phase 5: full-text search + reading state
# --------------------------------------------------------------------------


class FtsSearchItem(BaseModel):
    article_id: str
    title: str
    summary: str | None
    snippet: str
    rank: float
    source_name: str | None
    category_name: str | None
    published_at: str | None
    fetched_at: str
    reading_status: str
    is_favorite: bool


class FtsSearchResponse(BaseModel):
    items: list[FtsSearchItem]
    total: int
    limit: int
    offset: int
    query: str


class ReadingStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading_status: Literal["unread", "reading", "read", "later"] | None = None
    is_favorite: bool | None = None
    mark_read: bool = False


# --------------------------------------------------------------------------
# Phase 3: local AI analysis
# --------------------------------------------------------------------------


class EmbeddingStatus(BaseModel):
    enabled: bool
    reason: str | None


class AIStatus(BaseModel):
    enabled: bool
    provider_kind: str
    base_url: str
    available: bool
    version: str | None
    error_code: str | None
    default_model: str | None
    enabled_models: list[str]
    installed_models: list[str]
    cloud_models_blocked: int
    concurrency: int
    queue_depth: int
    running_run_id: str | None
    embedding: EmbeddingStatus
    checked_at: str


class AIModelItem(BaseModel):
    model_name: str
    enabled: bool
    roles: list[str]
    num_ctx: int
    digest: str | None
    size_bytes: int | None
    parameter_size: str | None
    quantization: str | None
    max_context: int | None
    installed: bool
    remote: bool
    last_checked_at: str | None


class AIModelPage(BaseModel):
    items: list[AIModelItem]
    total: int


class AIRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["selected", "unanalyzed"]
    article_ids: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=200)


class AIRunItemResponse(BaseModel):
    id: str
    run_id: str
    article_id: str
    article_title: str | None
    status: str
    attempts: int
    error_code: str | None
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None


class AIRunResponse(BaseModel):
    id: str
    trigger_type: str
    scope: str
    status: str
    requested_count: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    model_name: str | None
    error_message: str | None
    cancel_requested: bool
    pause_requested: bool
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    created_at: str
    updated_at: str
    items: list[AIRunItemResponse] = []


class AIRunPage(BaseModel):
    items: list[AIRunResponse]
    total: int
    limit: int
    offset: int


class AnalysisItem(BaseModel):
    id: str
    analysis_type: str
    category: str
    summary: str
    keywords: list[str]
    entities: list[dict[str, str]]
    confidence: float
    model_name: str
    model_digest: str | None
    prompt_version: str
    params: dict[str, object]
    input_chars: int
    duration_ms: int
    content_hash: str
    created_at: str


class ArticleAnalysisResponse(BaseModel):
    article_id: str
    items: list[AnalysisItem]


class JobItemResponse(BaseModel):
    id: str
    job_id: str
    source_id: str
    source_name: str | None
    status: str
    http_status: int | None
    discovered_count: int
    inserted_count: int
    updated_count: int
    duplicate_count: int
    error_count: int
    error_code: str | None
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None


class JobResponse(BaseModel):
    id: str
    trigger_type: str
    scope: str
    status: str
    requested_source_count: int
    processed_source_count: int
    succeeded_source_count: int
    failed_source_count: int
    discovered_count: int
    inserted_count: int
    updated_count: int
    duplicate_count: int
    error_count: int
    error_message: str | None
    cancel_requested: bool
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    created_at: str
    updated_at: str
    items: list[JobItemResponse]


class JobPage(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_type: Literal["manual"] = "manual"
    # Length is validated in CollectionService so >50 returns the documented
    # 409 collection_batch_too_large instead of a generic 422.
    source_ids: list[uuid.UUID] | None = None


class CollectResponse(BaseModel):
    job: JobResponse
    item: JobItemResponse | None


class CollectionStatus(BaseModel):
    scheduler_enabled: bool
    running_job_id: str | None
    max_concurrency: int
    queue_depth: int


class HealthLogResponse(BaseModel):
    checked_at: str
    status: str
    http_status: int | None
    latency_ms: int | None
    error_code: str | None
    error_message: str | None


class HealthLogPage(BaseModel):
    items: list[HealthLogResponse]
    total: int


def article_summary(record: object) -> ArticleSummary:
    return ArticleSummary(
        id=record.id,
        source_id=record.source_id,
        source_name=record.source_name,
        category_id=record.category_id,
        category_name=record.category_name,
        title=record.title,
        author=record.author,
        summary=record.summary,
        canonical_url=record.canonical_url,
        content_state=record.content_state,
        published_at=record.published_at,
        fetched_at=record.fetched_at,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reading_status=getattr(record, "reading_status", "unread"),
        is_favorite=getattr(record, "is_favorite", False),
        last_read_at=getattr(record, "last_read_at", None),
        read_count=getattr(record, "read_count", 0),
    )


def article_detail(record: object) -> ArticleDetail:
    return ArticleDetail(
        **article_summary(record).model_dump(),
        external_id=record.external_id,
        original_url=record.original_url,
        content_text=record.content_text,
        source_updated_at=record.source_updated_at,
        content_hash=record.content_hash,
        content_fetched_at=getattr(record, "content_fetched_at", None),
    )


def job_item_response(record: object) -> JobItemResponse:
    return JobItemResponse(
        id=record.id,
        job_id=record.job_id,
        source_id=record.source_id,
        source_name=record.source_name,
        status=record.status,
        http_status=record.http_status,
        discovered_count=record.discovered_count,
        inserted_count=record.inserted_count,
        updated_count=record.updated_count,
        duplicate_count=record.duplicate_count,
        error_count=record.error_count,
        error_code=record.error_code,
        error_message=record.error_message,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
    )


def job_response(record: object, *, include_items: bool = True) -> JobResponse:
    return JobResponse(
        id=record.id,
        trigger_type=record.trigger_type,
        scope=record.scope,
        status=record.status,
        requested_source_count=record.requested_source_count,
        processed_source_count=record.processed_source_count,
        succeeded_source_count=record.succeeded_source_count,
        failed_source_count=record.failed_source_count,
        discovered_count=record.discovered_count,
        inserted_count=record.inserted_count,
        updated_count=record.updated_count,
        duplicate_count=record.duplicate_count,
        error_count=record.error_count,
        error_message=record.error_message,
        cancel_requested=record.cancel_requested,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
        created_at=record.created_at,
        updated_at=record.updated_at,
        items=(
            [job_item_response(item) for item in record.items]
            if include_items
            else []
        ),
    )


def health_log_response(record: object) -> HealthLogResponse:
    return HealthLogResponse(
        checked_at=record.checked_at,
        status=record.status,
        http_status=record.http_status,
        latency_ms=record.latency_ms,
        error_code=record.error_code,
        error_message=record.error_message,
    )


def category_response(record: object) -> CategoryResponse:
    return CategoryResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        sort_order=record.sort_order,
        source_count=record.source_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def source_response(record: object) -> SourceResponse:
    category = (
        CategorySummary(id=record.category_id, name=record.category_name or "")
        if record.category_id is not None
        else None
    )
    return SourceResponse(
        id=record.id,
        name=record.name,
        source_type=record.source_type,
        url=record.url,
        homepage_url=record.homepage_url,
        description=record.description,
        language=record.language,
        country=record.country,
        priority=record.priority,
        credibility_score=record.credibility_score,
        fetch_interval_minutes=record.fetch_interval_minutes,
        max_entries_per_fetch=record.max_entries_per_fetch,
        enabled=record.enabled,
        health_status=record.health_status,
        last_fetch_at=record.last_fetch_at,
        last_success_at=record.last_success_at,
        last_error_at=record.last_error_at,
        last_error_code=record.last_error_code,
        last_error_message=record.last_error_message,
        category=category,
        article_count=record.article_count,
        adapter_verification=record.adapter_verification,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# --------------------------------------------------------------------------
# Phase 4: entities, events, clustering and rankings
# --------------------------------------------------------------------------


class EntitySummary(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    type_group: str
    status: str
    confidence: float
    article_count: int
    alias_count: int
    first_seen_at: str | None
    last_seen_at: str | None
    merged_into_entity_id: str | None


class EntityAliasItem(BaseModel):
    id: str
    alias: str
    language: str
    source: str
    confidence: float


class EntityArticleItem(BaseModel):
    article_id: str
    title: str | None
    source_name: str | None
    published_at: str | None
    raw_name: str
    raw_type: str
    match_method: str
    confidence: float


class EntityDetail(EntitySummary):
    normalization_basis: str
    aliases: list[EntityAliasItem]
    articles: list[EntityArticleItem]
    merged_from: list[dict[str, str]]


class EntityPage(BaseModel):
    items: list[EntitySummary]
    total: int
    limit: int
    offset: int


class EntityMergePair(BaseModel):
    source: EntitySummary
    target: EntitySummary
    shared_alias: str
    reason: str


class EntityMergeCandidatesPage(BaseModel):
    items: list[EntityMergePair]
    total: int


class EntityMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entity_id: str
    target_entity_id: str
    reason: str | None = Field(default=None, max_length=500)


class EntityAliasCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, pattern="^(zh|en|mixed|unknown)$")


class EntitySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=200, ge=1, le=500)


class EntitySyncResponse(BaseModel):
    processed_articles: int
    created_entities: int
    linked_mentions: int
    ambiguous_mentions: int
    updated_entities: int
    duration_ms: int


class EventScoreSummary(BaseModel):
    importance_score: float
    heat_score: float
    freshness_score: float
    coverage_score: float
    confidence_score: float
    total_score: float
    algorithm_version: str
    scored_at: str


class EventEntityItem(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str
    role: str
    article_count: int
    confidence: float
    evidence_article_id: str | None
    evidence_article_title: str | None


class EventRelationEvidence(BaseModel):
    article_id: str
    title: str


class EventRelationItem(BaseModel):
    id: str
    source_event_id: str
    target_event_id: str
    source_event_title: str | None
    target_event_title: str | None
    relation_type: str
    confidence: float
    status: str
    rationale: str | None
    evidence_articles: list[EventRelationEvidence]
    actor: str
    algorithm_version: str
    created_at: str
    updated_at: str


class EventSummary(BaseModel):
    id: str
    title: str
    summary: str | None
    category: str
    status: str
    first_seen_at: str
    last_seen_at: str
    first_published_at: str | None
    last_published_at: str | None
    article_count: int
    source_count: int
    is_manual: bool
    merged_into_event_id: str | None
    algorithm_version: str
    current_scores: EventScoreSummary | None
    top_entities: list[EventEntityItem]


class EventDetail(EventSummary):
    status_reason: str | None
    occurred_at: str | None
    created_at: str
    updated_at: str
    entities: list[EventEntityItem]
    relations: list[EventRelationItem]


class EventPage(BaseModel):
    items: list[EventSummary]
    total: int
    limit: int
    offset: int


class EventArticleItem(BaseModel):
    id: str
    article_id: str
    title: str
    source_id: str
    source_name: str | None
    published_at: str | None
    fetched_at: str
    summary: str | None
    ai_summary: str | None
    category: str | None
    canonical_url: str | None
    original_url: str | None
    role: str
    similarity: float | None
    match_reasons: list[str]
    is_manual: bool
    added_at: str


class EventArticlePage(BaseModel):
    items: list[EventArticleItem]
    total: int
    limit: int
    offset: int


class TimelineItem(BaseModel):
    id: str
    kind: str
    title: str
    description: str | None
    occurred_at: str | None
    published_at: str | None
    recognized_at: str
    article_id: str | None
    article_title: str | None
    confidence: float | None
    is_key: bool
    evidence: dict[str, object]
    created_at: str


class TimelinePage(BaseModel):
    items: list[TimelineItem]
    total: int
    limit: int
    offset: int


class EventEntityPage(BaseModel):
    items: list[EventEntityItem]
    total: int


class EventRelationPage(BaseModel):
    items: list[EventRelationItem]
    total: int


class ScoreComponentItem(BaseModel):
    name: str
    weight: float
    value: float
    contribution: float
    reason: str


class ScoreExplanation(BaseModel):
    formula: str
    weights: dict[str, float] | None = None
    components: list[ScoreComponentItem]


class ScoreSnapshotItem(BaseModel):
    id: str
    event_id: str
    algorithm_version: str
    scored_at: str
    importance_score: float
    heat_score: float
    freshness_score: float
    coverage_score: float
    confidence_score: float
    total_score: float
    is_current: bool
    inputs: dict[str, object]
    explanation: ScoreExplanation


class ScorePage(BaseModel):
    items: list[ScoreSnapshotItem]
    total: int
    limit: int
    offset: int


class EventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    category: str | None = None
    summary: str | None = Field(default=None, max_length=2000)
    article_ids: list[str] | None = None


class EventPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=2000)
    category: str | None = None
    status: Literal["active", "dormant", "closed", "archived"] | None = None
    status_reason: str | None = Field(default=None, max_length=500)


class EventArticleAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: str
    role: Literal["report", "follow_up", "commentary", "duplicate", "primary"] = "follow_up"


class EventArticleAddResponse(BaseModel):
    event_id: str
    article_id: str
    role: str
    moved_from_event_id: str | None
    article_count: int


class EventMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_event_id: str
    reason: str | None = Field(default=None, max_length=500)


class EventMergeResponse(EventDetail):
    source_event_id: str
    moved_articles: int
    duplicate_articles: int
    moved_timeline_items: int


class EventSplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_ids: list[str] = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=300)
    category: str | None = None


class TimelineNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    occurred_at: str | None = Field(default=None, pattern="^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$")


class TimelineNoteResponse(BaseModel):
    id: str


class RelationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_event_id: str
    relation_type: Literal[
        "related_to", "follows", "caused_by", "part_of", "same_topic", "contradicts"
    ]
    rationale: str | None = Field(default=None, max_length=1000)
    evidence_article_ids: list[str] = []


class RelationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["confirmed", "rejected"]


class DecisionItem(BaseModel):
    id: str
    run_id: str | None
    article_id: str
    article_title: str | None
    candidate_event_id: str | None
    candidate_event_title: str | None
    decision: str
    score: float | None
    reasons: list[str]
    method: str
    llm_used: bool
    status: str
    created_at: str
    resolved_at: str | None


class DecisionPage(BaseModel):
    items: list[DecisionItem]
    total: int
    limit: int
    offset: int


class DecisionResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["attach", "create_event", "ignore"]
    event_id: str | None = None


class CandidateItem(BaseModel):
    event: EventSummary
    latest_decision: DecisionItem | None


class CandidatePage(BaseModel):
    items: list[CandidateItem]
    total: int
    limit: int
    offset: int


class ClusterRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["incremental", "full", "selected"]
    article_ids: list[str] | None = None
    limit: int = Field(default=200, ge=1, le=500)
    use_llm: bool = False


class ClusterRunResponse(BaseModel):
    id: str
    trigger_type: str
    scope: str
    status: str
    requested_count: int
    processed_count: int
    attached_count: int
    created_event_count: int
    updated_event_count: int
    candidate_pair_count: int
    ambiguous_count: int
    llm_called_count: int
    llm_accepted_count: int
    skipped_count: int
    failed_count: int
    use_llm: bool
    model_name: str | None
    error_message: str | None
    cancel_requested: bool
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    created_at: str
    updated_at: str


class ClusterRunPage(BaseModel):
    items: list[ClusterRunResponse]
    total: int
    limit: int
    offset: int


class ClusterStatusResponse(BaseModel):
    enabled: bool
    running_run_id: str | None
    queue_depth: int
    llm_enabled: bool
    last_run_id: str | None
    last_run_status: str | None
    last_run_at: str | None
    algorithm_version: str


class ScoreRecomputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["stale", "all", "selected"]
    event_ids: list[str] | None = None
    limit: int = Field(default=200, ge=1, le=200)


class ScoreRecomputeResponse(BaseModel):
    scored_events: int
    created_snapshots: int
    skipped_unchanged: int
    failed_events: int
    algorithm_version: str
    duration_ms: int


class RankingItem(BaseModel):
    rank: int
    event: EventSummary
    score: float
    previous_total_score: float | None
    score_change: float | None


class RankingPage(BaseModel):
    kind: str
    window: str
    algorithm_version: str
    generated_at: str
    items: list[RankingItem]
    total: int
    limit: int
    offset: int


def entity_summary(record: object) -> EntitySummary:
    return EntitySummary(
        id=record.id,
        canonical_name=record.canonical_name,
        entity_type=record.entity_type,
        type_group=record.type_group,
        status=record.status,
        confidence=record.confidence,
        article_count=record.article_count,
        alias_count=record.alias_count,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        merged_into_entity_id=record.merged_into_entity_id,
    )


def entity_detail(record: object) -> EntityDetail:
    return EntityDetail(
        **entity_summary(record).model_dump(),
        normalization_basis=record.normalization_basis,
        aliases=[
            EntityAliasItem(
                id=item.id,
                alias=item.alias,
                language=item.language,
                source=item.source,
                confidence=item.confidence,
            )
            for item in record.aliases
        ],
        articles=[
            EntityArticleItem(
                article_id=item.article_id,
                title=item.article_title,
                source_name=item.source_name,
                published_at=item.published_at,
                raw_name=item.raw_name,
                raw_type=item.raw_type,
                match_method=item.match_method,
                confidence=item.confidence,
            )
            for item in record.articles
        ],
        merged_from=[
            {"id": item[0], "canonical_name": item[1]} for item in record.merged_from
        ],
    )


def event_score_summary(record: object) -> EventScoreSummary:
    return EventScoreSummary(
        importance_score=record.importance_score,
        heat_score=record.heat_score,
        freshness_score=record.freshness_score,
        coverage_score=record.coverage_score,
        confidence_score=record.confidence_score,
        total_score=record.total_score,
        algorithm_version=record.algorithm_version,
        scored_at=record.scored_at,
    )


def event_entity_item(record: object) -> EventEntityItem:
    return EventEntityItem(
        entity_id=record.entity_id,
        canonical_name=record.canonical_name,
        entity_type=record.entity_type,
        role=record.role,
        article_count=record.article_count,
        confidence=record.confidence,
        evidence_article_id=record.evidence_article_id,
        evidence_article_title=record.evidence_article_title,
    )


def event_relation_item(record: object) -> EventRelationItem:
    return EventRelationItem(
        id=record.id,
        source_event_id=record.source_event_id,
        target_event_id=record.target_event_id,
        source_event_title=record.source_event_title,
        target_event_title=record.target_event_title,
        relation_type=record.relation_type,
        confidence=record.confidence,
        status=record.status,
        rationale=record.rationale,
        evidence_articles=[
            EventRelationEvidence(
                article_id=item.get("article_id", ""), title=item.get("title", "")
            )
            for item in record.evidence_articles
        ],
        actor=record.actor,
        algorithm_version=record.algorithm_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def event_summary(record: object) -> EventSummary:
    return EventSummary(
        id=record.id,
        title=record.title,
        summary=record.summary,
        category=record.category,
        status=record.status,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        first_published_at=record.first_published_at,
        last_published_at=record.last_published_at,
        article_count=record.article_count,
        source_count=record.source_count,
        is_manual=record.is_manual,
        merged_into_event_id=record.merged_into_event_id,
        algorithm_version=record.algorithm_version,
        current_scores=(
            event_score_summary(record.current_scores) if record.current_scores else None
        ),
        top_entities=[event_entity_item(item) for item in record.top_entities],
    )


def event_detail(record: object) -> EventDetail:
    return EventDetail(
        **event_summary(record).model_dump(),
        status_reason=record.status_reason,
        occurred_at=record.occurred_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        entities=[event_entity_item(item) for item in record.entities],
        relations=[event_relation_item(item) for item in record.relations],
    )


def event_article_item(record: object) -> EventArticleItem:
    return EventArticleItem(
        id=record.id,
        article_id=record.article_id,
        title=record.title,
        source_id=record.source_id,
        source_name=record.source_name,
        published_at=record.published_at,
        fetched_at=record.fetched_at,
        summary=record.summary,
        ai_summary=record.ai_summary,
        category=record.category,
        canonical_url=record.canonical_url,
        original_url=record.original_url,
        role=record.role,
        similarity=record.similarity,
        match_reasons=list(record.match_reasons),
        is_manual=record.is_manual,
        added_at=record.added_at,
    )


def timeline_item(record: object) -> TimelineItem:
    return TimelineItem(
        id=record.id,
        kind=record.kind,
        title=record.title,
        description=record.description,
        occurred_at=record.occurred_at,
        published_at=record.published_at,
        recognized_at=record.recognized_at,
        article_id=record.article_id,
        article_title=record.article_title,
        confidence=record.confidence,
        is_key=record.is_key,
        evidence=dict(record.evidence),
        created_at=record.created_at,
    )


def score_snapshot_item(record: object) -> ScoreSnapshotItem:
    explanation = record.explanation or {}
    return ScoreSnapshotItem(
        id=record.id,
        event_id=record.event_id,
        algorithm_version=record.algorithm_version,
        scored_at=record.scored_at,
        importance_score=record.importance_score,
        heat_score=record.heat_score,
        freshness_score=record.freshness_score,
        coverage_score=record.coverage_score,
        confidence_score=record.confidence_score,
        total_score=record.total_score,
        is_current=record.is_current,
        inputs=dict(record.inputs),
        explanation=ScoreExplanation(
            formula=str(explanation.get("formula", "")),
            weights=explanation.get("weights") if isinstance(explanation.get("weights"), dict) else None,
            components=[
                ScoreComponentItem(**item)
                for item in explanation.get("components", [])
                if isinstance(item, dict)
            ],
        ),
    )


def cluster_run_response(record: object) -> ClusterRunResponse:
    return ClusterRunResponse(
        id=record.id,
        trigger_type=record.trigger_type,
        scope=record.scope,
        status=record.status,
        requested_count=record.requested_count,
        processed_count=record.processed_count,
        attached_count=record.attached_count,
        created_event_count=record.created_event_count,
        updated_event_count=record.updated_event_count,
        candidate_pair_count=record.candidate_pair_count,
        ambiguous_count=record.ambiguous_count,
        llm_called_count=record.llm_called_count,
        llm_accepted_count=record.llm_accepted_count,
        skipped_count=record.skipped_count,
        failed_count=record.failed_count,
        use_llm=record.use_llm,
        model_name=record.model_name,
        error_message=record.error_message,
        cancel_requested=record.cancel_requested,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def decision_item(record: object) -> DecisionItem:
    return DecisionItem(
        id=record.id,
        run_id=record.run_id,
        article_id=record.article_id,
        article_title=record.article_title,
        candidate_event_id=record.candidate_event_id,
        candidate_event_title=record.candidate_event_title,
        decision=record.decision,
        score=record.score,
        reasons=list(record.reasons),
        method=record.method,
        llm_used=record.llm_used,
        status=record.status,
        created_at=record.created_at,
        resolved_at=record.resolved_at,
    )


class AggregationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["event_merge", "article_attach", "article_group"]
    source_event_id: str | None = Field(default=None, max_length=64)
    target_event_id: str | None = Field(default=None, max_length=64)
    article_id: str | None = Field(default=None, max_length=64)
    event_id: str | None = Field(default=None, max_length=64)
    article_ids: list[str] | None = Field(default=None, max_length=20)


class AggregationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairs: list[AggregationPair] = Field(min_length=1, max_length=50)
    confirm: bool
    create_backup: bool = True
