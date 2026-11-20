-- 0003_sources.sql
-- Phase 1: information sources. Forward-only; the runner owns the transaction.

CREATE TABLE sources (
    id                     TEXT    PRIMARY KEY NOT NULL,
    category_id            TEXT    REFERENCES source_categories(id) ON DELETE SET NULL,
    name                   TEXT    NOT NULL,
    source_type            TEXT    NOT NULL
                                   CHECK (source_type IN ('rss','atom','website','official_announcement','api')),
    url                    TEXT    NOT NULL,
    homepage_url           TEXT,
    description            TEXT,
    language               TEXT,
    country                TEXT,
    priority               INTEGER NOT NULL DEFAULT 0
                                   CHECK (priority BETWEEN 0 AND 100),
    credibility_score      INTEGER
                                   CHECK (credibility_score IS NULL
                                          OR credibility_score BETWEEN 0 AND 100),
    fetch_interval_minutes INTEGER NOT NULL DEFAULT 60
                                   CHECK (fetch_interval_minutes BETWEEN 5 AND 1440),
    enabled                INTEGER NOT NULL DEFAULT 1
                                   CHECK (enabled IN (0, 1)),
    health_status          TEXT    NOT NULL DEFAULT 'unknown'
                                   CHECK (health_status IN ('unknown','healthy','degraded','failing')),
    last_fetch_at          TEXT,
    last_success_at        TEXT,
    last_error_at          TEXT,
    last_error_code        TEXT,
    last_error_message     TEXT,
    created_at             TEXT    NOT NULL,
    updated_at             TEXT    NOT NULL,
    deleted_at             TEXT,
    CHECK (length(trim(name)) BETWEEN 1 AND 120),
    CHECK (length(url) BETWEEN 1 AND 2048),
    CHECK (homepage_url IS NULL OR length(homepage_url) BETWEEN 1 AND 2048),
    CHECK (description IS NULL OR length(description) <= 500),
    CHECK (country IS NULL OR (length(country) = 2 AND country = upper(country))),
    CHECK (last_error_code IS NULL OR length(last_error_code) <= 64),
    CHECK (last_error_message IS NULL OR length(last_error_message) <= 500),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (deleted_at IS NULL OR length(deleted_at) = 24),
    CHECK (enabled = 1 OR health_status <> 'healthy'),
    CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX ux_sources_url_active
    ON sources(url)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_sources_list
    ON sources(deleted_at, enabled, source_type, category_id);

CREATE INDEX ix_sources_category_active
    ON sources(category_id)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_sources_priority_active
    ON sources(priority DESC, created_at DESC)
    WHERE deleted_at IS NULL;
