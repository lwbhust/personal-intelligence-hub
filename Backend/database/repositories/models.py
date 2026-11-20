"""Read models for the Phase 1 repositories.

These dataclasses are the only rows that leave the data layer; API models are
built from them. Keep them free of SQLite types so the boundary stays clean.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceCategoryRecord:
    id: str
    name: str
    description: str | None
    sort_order: int
    created_at: str
    updated_at: str
    source_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: str
    category_id: str | None
    category_name: str | None
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
    created_at: str
    updated_at: str
    article_count: int = 0
    adapter_verification: str | None = None


@dataclass(frozen=True, slots=True)
class SourceAdapterRecord:
    source_id: str
    adapter_type: str
    entry_url: str
    config_json: str
    config_version: str
    rate_limit_seconds: int
    max_entries_per_run: int
    fetch_full_text: bool
    last_verified_at: str | None
    last_verification: str
    last_sample_json: str | None
    created_at: str
    updated_at: str


def _to_bool(value: object) -> bool:
    return bool(int(value)) if value is not None else False


@dataclass(frozen=True, slots=True)
class ArticleRecord:
    id: str
    source_id: str
    source_name: str | None
    category_id: str | None
    category_name: str | None
    external_id: str | None
    canonical_url: str | None
    original_url: str | None
    title: str
    author: str | None
    summary: str | None
    content_text: str | None
    content_state: str
    published_at: str | None
    source_updated_at: str | None
    fetched_at: str
    content_hash: str
    status: str
    created_at: str
    updated_at: str
    reading_status: str = "unread"
    is_favorite: bool = False
    last_read_at: str | None = None
    read_count: int = 0
    content_fetched_at: str | None = None


@dataclass(frozen=True, slots=True)
class FtsSearchResult:
    article_id: str
    title: str
    summary: str | None
    source_name: str | None
    category_name: str | None
    published_at: str | None
    fetched_at: str
    reading_status: str
    is_favorite: bool
    rank: float
    snippet: str


@dataclass(frozen=True, slots=True)
class CollectionJobItemRecord:
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
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CollectionJobRecord:
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
    items: tuple[CollectionJobItemRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceHealthRecord:
    id: str
    source_id: str
    checked_at: str
    status: str
    http_status: int | None
    latency_ms: int | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class SourceFetchStateRecord:
    source_id: str
    etag: str | None
    last_modified: str | None
    last_fetch_at: str | None
    last_success_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    consecutive_failures: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class AIModelRecord:
    model_name: str
    provider_kind: str
    digest: str | None
    size_bytes: int | None
    parameter_size: str | None
    quantization: str | None
    max_context: int | None
    num_ctx: int
    roles: tuple[str, ...]
    enabled: bool
    last_checked_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AIRunItemRecord:
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
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AIRunRecord:
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
    items: tuple[AIRunItemRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityAliasRecord:
    id: str
    entity_id: str
    alias: str
    alias_key: str
    language: str
    source: str
    confidence: float
    merged_from_entity_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class EntityRecord:
    id: str
    canonical_name: str
    entity_type: str
    type_group: str
    normalized_key: str
    status: str
    confidence: float
    normalization_basis: str
    merged_into_entity_id: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    created_at: str
    updated_at: str
    article_count: int = 0
    alias_count: int = 0
    aliases: tuple[EntityAliasRecord, ...] = ()
    articles: tuple[ArticleEntityRecord, ...] = ()
    merged_from: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ArticleEntityRecord:
    id: str
    article_id: str
    entity_id: str | None
    analysis_id: str | None
    raw_name: str
    raw_type: str
    match_method: str
    status: str
    confidence: float
    created_at: str
    updated_at: str
    article_title: str | None = None
    source_name: str | None = None
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class EventScoreRecord:
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
    inputs: dict[str, object]
    explanation: dict[str, object]
    is_current: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class EventEntityRecord:
    id: str
    event_id: str
    entity_id: str
    role: str
    article_count: int
    confidence: float
    evidence_article_id: str | None
    created_at: str
    updated_at: str
    canonical_name: str = ""
    entity_type: str = "other"
    evidence_article_title: str | None = None


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: str
    title: str
    summary: str | None
    category: str
    status: str
    status_reason: str | None
    first_seen_at: str
    last_seen_at: str
    first_published_at: str | None
    last_published_at: str | None
    occurred_at: str | None
    article_count: int
    source_count: int
    is_manual: bool
    merged_into_event_id: str | None
    algorithm_version: str
    title_source: str
    summary_source: str
    created_at: str
    updated_at: str
    category_source: str = "legacy"
    category_reason: str | None = None
    category_updated_at: str | None = None
    current_scores: EventScoreRecord | None = None
    top_entities: tuple[EventEntityRecord, ...] = ()
    entities: tuple[EventEntityRecord, ...] = ()
    relations: tuple["EventRelationRecord", ...] = ()


@dataclass(frozen=True, slots=True)
class EventArticleRecord:
    id: str
    event_id: str
    article_id: str
    role: str
    similarity: float | None
    match_reasons: tuple[str, ...]
    is_manual: bool
    added_at: str
    created_at: str
    title: str
    source_id: str
    source_name: str | None
    published_at: str | None
    fetched_at: str
    summary: str | None
    ai_summary: str | None
    category: str | None
    canonical_url: str | None = None
    original_url: str | None = None


@dataclass(frozen=True, slots=True)
class EventTimelineRecord:
    id: str
    event_id: str
    article_id: str | None
    kind: str
    title: str
    description: str | None
    occurred_at: str | None
    published_at: str | None
    recognized_at: str
    confidence: float | None
    is_key: bool
    evidence: dict[str, object]
    created_at: str
    article_title: str | None = None


@dataclass(frozen=True, slots=True)
class EventRelationRecord:
    id: str
    source_event_id: str
    target_event_id: str
    relation_type: str
    confidence: float
    status: str
    rationale: str | None
    evidence_article_ids: tuple[str, ...]
    actor: str
    algorithm_version: str
    created_at: str
    updated_at: str
    source_event_title: str | None = None
    target_event_title: str | None = None
    evidence_articles: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EventClusterRunRecord:
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
    article_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EventDecisionRecord:
    id: str
    run_id: str | None
    article_id: str
    candidate_event_id: str | None
    decision: str
    score: float | None
    reasons: tuple[str, ...]
    method: str
    llm_used: bool
    status: str
    created_at: str
    resolved_at: str | None
    article_title: str | None = None
    candidate_event_title: str | None = None


@dataclass(frozen=True, slots=True)
class AIAnalysisRecord:
    id: str
    article_id: str
    analysis_type: str
    provider_kind: str
    model_name: str
    model_digest: str | None
    prompt_version: str
    params: dict[str, object]
    content_hash: str
    category: str
    summary: str
    keywords: tuple[str, ...]
    entities: tuple[dict[str, str], ...]
    confidence: float
    input_chars: int
    duration_ms: int
    created_at: str


@dataclass(frozen=True, slots=True)
class IntelligenceReportRecord:
    id: str
    report_type: str
    period_key: str
    period_start: str
    period_end: str
    data_from_at: str | None
    data_to_at: str | None
    status: str
    ai_status: str
    headline: str | None
    overview: str | None
    content: dict[str, object]
    stats: dict[str, object]
    model_name: str | None
    model_digest: str | None
    prompt_version: str
    stats_version: str
    article_count: int
    event_count: int
    entity_count: int
    citation_count: int
    trigger_type: str
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class IntelligenceCitationRecord:
    id: str
    report_id: str
    citation_type: str
    ref_id: str
    section_key: str
    rank: int
    title: str | None
    source_name: str | None
    url: str | None
    evidence: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Phase 7.3.1 — personalization records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InterestProfileRecord:
    display_name: str
    digest_time: str
    timezone: str
    daily_item_limit: int | None
    daily_minutes: int | None
    exploration_ratio: float
    auto_adjust_enabled: bool
    onboarding_done: bool
    scoring_config: dict[str, object]
    updated_at: str


@dataclass(frozen=True, slots=True)
class InterestRecord:
    id: str
    name: str
    interest_type: str
    level: str
    weight: float
    domain_key: str | None
    enabled: bool
    notes: str | None
    created_at: str
    updated_at: str
    keywords: tuple[str, ...] = ()
    exclusion_keywords: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    entity_names: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    source_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    id: str
    target_type: str
    target_id: str
    feedback: str
    interest_id: str | None
    note: str | None
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    id: str
    target_type: str
    target_id: str
    score: float
    level: str
    interest_score: float
    importance_score: float
    novelty_score: float
    source_quality_score: float
    recency_score: float
    matched_interests: tuple[str, ...]
    matched_entities: tuple[str, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    explanation: dict[str, object]
    algorithm_version: str
    inputs_version: str
    is_fallback: bool
    computed_at: str
    title: str | None = None
    summary: str | None = None
    source_name: str | None = None
    category: str | None = None
    published_at: str | None = None
    event_id: str | None = None
    article_count: int = 0
    source_count: int = 0
    is_read: bool = False
    is_favorite: bool = False


@dataclass(frozen=True, slots=True)
class DigestRecord:
    id: str
    digest_date: str
    timezone: str
    status: str
    ai_status: str
    headline: str | None
    overview: str | None
    stats: dict[str, object]
    model_name: str | None
    model_digest: str | None
    prompt_version: str | None
    digest_version: str
    generated_at: str | None
    superseded_at: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    items: tuple["DigestItemRecord", ...] = ()


@dataclass(frozen=True, slots=True)
class DigestItemRecord:
    id: str
    digest_id: str
    section: str
    rank: int
    target_type: str
    target_id: str | None
    title: str
    reason: str | None
    matched_interests: tuple[str, ...]
    score: float | None
    created_at: str
