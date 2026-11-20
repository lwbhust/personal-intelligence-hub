-- 0010_personalization.sql
-- Phase 7.3.1: personal interest profile, explainable recommendations, feedback
-- and daily digests. Forward-only; the migration runner owns the transaction.
-- No existing table is rebuilt and no user row is deleted.

-- ---------------------------------------------------------------------------
-- Profile settings (single row). Digest time/timezone and reading budget are
-- user-controlled; scoring_config_json keeps threshold overrides without new
-- columns per knob.
-- ---------------------------------------------------------------------------
CREATE TABLE interest_profiles (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    display_name          TEXT    NOT NULL DEFAULT '我的兴趣',
    digest_time           TEXT    NOT NULL DEFAULT '08:00'
                                  CHECK (digest_time GLOB '[0-2][0-9]:[0-5][0-9]'),
    timezone              TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
    daily_item_limit      INTEGER CHECK (daily_item_limit IS NULL OR daily_item_limit BETWEEN 1 AND 100),
    daily_minutes         INTEGER CHECK (daily_minutes IS NULL OR daily_minutes BETWEEN 1 AND 600),
    exploration_ratio     REAL    NOT NULL DEFAULT 0.1
                                  CHECK (exploration_ratio >= 0 AND exploration_ratio <= 0.5),
    auto_adjust_enabled   INTEGER NOT NULL DEFAULT 1 CHECK (auto_adjust_enabled IN (0,1)),
    onboarding_done       INTEGER NOT NULL DEFAULT 0 CHECK (onboarding_done IN (0,1)),
    scoring_config_json   TEXT    NOT NULL DEFAULT '{}' CHECK (length(scoring_config_json) <= 4000),
    updated_at            TEXT    NOT NULL,
    CHECK (length(updated_at) = 24)
);

INSERT INTO interest_profiles (id, updated_at)
VALUES (1, '2026-11-18T00:00:00.000Z');

-- ---------------------------------------------------------------------------
-- Interests. `domain_key` refers to taxonomy-v1 keys (technology, finance, …)
-- and is only used by domain/topic interests. Keywords, entities and sources
-- are linked through dedicated tables so the existing entity/source libraries
-- stay the single source of truth.
-- ---------------------------------------------------------------------------
CREATE TABLE interests (
    id                    TEXT    PRIMARY KEY NOT NULL,
    name                  TEXT    NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    interest_type         TEXT    NOT NULL
                                  CHECK (interest_type IN ('domain','topic','keyword','entity','source','event')),
    level                 TEXT    NOT NULL
                                  CHECK (level IN ('core','extended','general','muted')),
    weight                REAL    NOT NULL CHECK (weight >= 0 AND weight <= 1),
    domain_key            TEXT,
    enabled               INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    notes                 TEXT    CHECK (notes IS NULL OR length(notes) <= 500),
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24)
);

CREATE UNIQUE INDEX ux_interests_name ON interests(name);
CREATE INDEX ix_interests_level ON interests(level, enabled, updated_at DESC);

CREATE TABLE interest_keywords (
    id                    TEXT    PRIMARY KEY NOT NULL,
    interest_id           TEXT    NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    keyword               TEXT    NOT NULL CHECK (length(keyword) BETWEEN 1 AND 80),
    is_exclusion          INTEGER NOT NULL DEFAULT 0 CHECK (is_exclusion IN (0,1)),
    created_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24)
);

CREATE UNIQUE INDEX ux_interest_keywords
    ON interest_keywords(interest_id, keyword, is_exclusion);

CREATE TABLE interest_entity_links (
    id                    TEXT    PRIMARY KEY NOT NULL,
    interest_id           TEXT    NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    entity_id             TEXT    NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    created_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24)
);

CREATE UNIQUE INDEX ux_interest_entity ON interest_entity_links(interest_id, entity_id);
CREATE INDEX ix_interest_entity_entity ON interest_entity_links(entity_id);

CREATE TABLE interest_source_links (
    id                    TEXT    PRIMARY KEY NOT NULL,
    interest_id           TEXT    NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    source_id             TEXT    NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    created_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24)
);

CREATE UNIQUE INDEX ux_interest_source ON interest_source_links(interest_id, source_id);
CREATE INDEX ix_interest_source_source ON interest_source_links(source_id);

-- Blocked sources are global: articles from them never enter the feed, but
-- remain fully queryable in the article list.
CREATE TABLE blocked_sources (
    source_id             TEXT    PRIMARY KEY NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    reason                TEXT    CHECK (reason IS NULL OR length(reason) <= 200),
    created_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24)
);

-- ---------------------------------------------------------------------------
-- User feedback. Append-only with soft revoke; the partial unique index keeps
-- exactly one active feedback per target while preserving history.
-- ---------------------------------------------------------------------------
CREATE TABLE recommendation_feedback (
    id                    TEXT    PRIMARY KEY NOT NULL,
    target_type           TEXT    NOT NULL CHECK (target_type IN ('article','event')),
    target_id             TEXT    NOT NULL,
    feedback              TEXT    NOT NULL
                                  CHECK (feedback IN ('interested','not_interested','important',
                                                      'duplicate','source_disliked','later')),
    interest_id           TEXT    REFERENCES interests(id) ON DELETE SET NULL,
    note                  TEXT    CHECK (note IS NULL OR length(note) <= 500),
    created_at            TEXT    NOT NULL,
    revoked_at            TEXT,
    CHECK (length(created_at) = 24),
    CHECK (revoked_at IS NULL OR length(revoked_at) = 24)
);

CREATE UNIQUE INDEX ux_feedback_active
    ON recommendation_feedback(target_type, target_id)
    WHERE revoked_at IS NULL;
CREATE INDEX ix_feedback_created ON recommendation_feedback(created_at DESC);
CREATE INDEX ix_feedback_interest ON recommendation_feedback(interest_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Current recommendation per target. Exactly one current row per target; the
-- full explanation is stored so the API never has to re-derive it.
-- ---------------------------------------------------------------------------
CREATE TABLE recommendation_results (
    id                    TEXT    PRIMARY KEY NOT NULL,
    target_type           TEXT    NOT NULL CHECK (target_type IN ('article','event')),
    target_id             TEXT    NOT NULL,
    score                 REAL    NOT NULL CHECK (score >= 0 AND score <= 100),
    level                 TEXT    NOT NULL
                                  CHECK (level IN ('must_read','recommended','watch','low','not_recommended')),
    interest_score        REAL    NOT NULL,
    importance_score      REAL    NOT NULL,
    novelty_score         REAL    NOT NULL,
    source_quality_score  REAL    NOT NULL,
    recency_score         REAL    NOT NULL,
    matched_interests_json TEXT   NOT NULL DEFAULT '[]',
    matched_entities_json  TEXT   NOT NULL DEFAULT '[]',
    reason_codes_json     TEXT    NOT NULL DEFAULT '[]',
    warnings_json         TEXT    NOT NULL DEFAULT '[]',
    explanation_json      TEXT    NOT NULL DEFAULT '{}' CHECK (length(explanation_json) <= 12000),
    algorithm_version     TEXT    NOT NULL,
    inputs_version        TEXT    NOT NULL,
    is_fallback           INTEGER NOT NULL DEFAULT 0 CHECK (is_fallback IN (0,1)),
    is_current            INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    computed_at           TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(computed_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24)
);

CREATE UNIQUE INDEX ux_reco_current
    ON recommendation_results(target_type, target_id)
    WHERE is_current = 1;
CREATE INDEX ix_reco_rank ON recommendation_results(is_current, score DESC);

-- ---------------------------------------------------------------------------
-- Daily digest. One current succeeded version per local date; regenerating a
-- date supersedes the previous version instead of deleting history.
-- ---------------------------------------------------------------------------
CREATE TABLE daily_digests (
    id                    TEXT    PRIMARY KEY NOT NULL,
    digest_date           TEXT    NOT NULL CHECK (digest_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    timezone              TEXT    NOT NULL,
    status                TEXT    NOT NULL DEFAULT 'generating'
                                  CHECK (status IN ('generating','succeeded','failed','superseded')),
    ai_status             TEXT    NOT NULL DEFAULT 'skipped'
                                  CHECK (ai_status IN ('used','skipped','invalid')),
    headline              TEXT,
    overview              TEXT,
    stats_json            TEXT    NOT NULL DEFAULT '{}' CHECK (length(stats_json) <= 20000),
    model_name            TEXT,
    model_digest          TEXT,
    prompt_version        TEXT,
    digest_version        TEXT    NOT NULL,
    generated_at          TEXT,
    superseded_at         TEXT,
    error_code            TEXT,
    error_message         TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24)
);

CREATE UNIQUE INDEX ux_digest_current
    ON daily_digests(digest_date, timezone)
    WHERE status = 'succeeded';
CREATE INDEX ix_digest_date ON daily_digests(digest_date DESC, created_at DESC);

CREATE TABLE daily_digest_items (
    id                    TEXT    PRIMARY KEY NOT NULL,
    digest_id             TEXT    NOT NULL REFERENCES daily_digests(id) ON DELETE CASCADE,
    section               TEXT    NOT NULL
                                  CHECK (section IN ('must_not_miss','highlights','core_interest',
                                                     'event_changes','emerging','leads')),
    rank                  INTEGER NOT NULL DEFAULT 0,
    target_type           TEXT    NOT NULL CHECK (target_type IN ('article','event','topic')),
    target_id             TEXT,
    title                 TEXT    NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    reason                TEXT,
    matched_interests_json TEXT   NOT NULL DEFAULT '[]',
    score                 REAL,
    created_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24)
);

CREATE INDEX ix_digest_items_digest ON daily_digest_items(digest_id, section, rank);
