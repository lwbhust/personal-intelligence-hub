-- 0004_articles_and_collection.sql
-- Phase 2: articles, collection jobs, source health and fetch cursors.
-- Forward-only; the migration runner owns the transaction.

CREATE TABLE articles (
    id                TEXT    PRIMARY KEY NOT NULL,
    source_id         TEXT    NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id       TEXT,
    canonical_url     TEXT,
    original_url      TEXT,
    title             TEXT    NOT NULL,
    author            TEXT,
    summary           TEXT,
    content_text      TEXT,
    content_state     TEXT    NOT NULL DEFAULT 'unavailable'
                              CHECK (content_state IN ('full','summary_only','unavailable')),
    published_at      TEXT,
    source_updated_at TEXT,
    fetched_at        TEXT    NOT NULL,
    content_hash      TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'active'
                              CHECK (status IN ('active','archived','deleted')),
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    deleted_at        TEXT,
    CHECK (length(trim(title)) BETWEEN 1 AND 500),
    CHECK (length(content_hash) = 64),
    CHECK (external_id IS NULL OR length(external_id) BETWEEN 1 AND 512),
    CHECK (canonical_url IS NULL OR length(canonical_url) BETWEEN 1 AND 2048),
    CHECK (original_url IS NULL OR length(original_url) BETWEEN 1 AND 2048),
    CHECK (author IS NULL OR length(author) <= 200),
    CHECK (summary IS NULL OR length(summary) <= 8000),
    CHECK (content_text IS NULL OR length(content_text) <= 200000),
    CHECK (length(fetched_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (published_at IS NULL OR length(published_at) = 24),
    CHECK (source_updated_at IS NULL OR length(source_updated_at) = 24),
    CHECK (deleted_at IS NULL OR length(deleted_at) = 24),
    CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX ux_articles_source_external
    ON articles(source_id, external_id)
    WHERE deleted_at IS NULL AND external_id IS NOT NULL;

CREATE UNIQUE INDEX ux_articles_source_canonical
    ON articles(source_id, canonical_url)
    WHERE deleted_at IS NULL AND canonical_url IS NOT NULL;

CREATE INDEX ix_articles_list
    ON articles(status, published_at DESC, id)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_articles_source
    ON articles(source_id, published_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_articles_fetched
    ON articles(fetched_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_articles_hash
    ON articles(source_id, content_hash)
    WHERE deleted_at IS NULL;

CREATE TABLE source_fetch_state (
    source_id             TEXT    PRIMARY KEY NOT NULL
                                  REFERENCES sources(id) ON DELETE CASCADE,
    etag                  TEXT,
    last_modified         TEXT,
    last_fetch_at         TEXT,
    last_success_at       TEXT,
    last_error_code       TEXT,
    last_error_message    TEXT,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0
                                  CHECK (consecutive_failures >= 0),
    updated_at            TEXT    NOT NULL,
    CHECK (length(updated_at) = 24),
    CHECK (last_fetch_at IS NULL OR length(last_fetch_at) = 24),
    CHECK (last_success_at IS NULL OR length(last_success_at) = 24),
    CHECK (etag IS NULL OR length(etag) <= 512),
    CHECK (last_modified IS NULL OR length(last_modified) <= 128),
    CHECK (last_error_code IS NULL OR length(last_error_code) <= 64),
    CHECK (last_error_message IS NULL OR length(last_error_message) <= 500)
);

CREATE TABLE collection_jobs (
    id                       TEXT    PRIMARY KEY NOT NULL,
    trigger_type             TEXT    NOT NULL
                                     CHECK (trigger_type IN ('manual','scheduled')),
    scope                    TEXT    NOT NULL
                                     CHECK (scope IN ('single_source','all_enabled')),
    status                   TEXT    NOT NULL
                                     CHECK (status IN ('pending','running','succeeded',
                                                       'partially_succeeded','failed','cancelled')),
    requested_source_count   INTEGER NOT NULL DEFAULT 0 CHECK (requested_source_count >= 0),
    processed_source_count   INTEGER NOT NULL DEFAULT 0 CHECK (processed_source_count >= 0),
    succeeded_source_count   INTEGER NOT NULL DEFAULT 0 CHECK (succeeded_source_count >= 0),
    failed_source_count      INTEGER NOT NULL DEFAULT 0 CHECK (failed_source_count >= 0),
    discovered_count         INTEGER NOT NULL DEFAULT 0 CHECK (discovered_count >= 0),
    inserted_count           INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    updated_count            INTEGER NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
    duplicate_count          INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    error_count              INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    error_message            TEXT,
    cancel_requested         INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    started_at               TEXT,
    finished_at              TEXT,
    duration_ms              INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at               TEXT    NOT NULL,
    updated_at               TEXT    NOT NULL,
    CHECK (error_message IS NULL OR length(error_message) <= 1000),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (started_at IS NULL OR length(started_at) = 24),
    CHECK (finished_at IS NULL OR length(finished_at) = 24),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CHECK (updated_at >= created_at)
);

CREATE INDEX ix_collection_jobs_created
    ON collection_jobs(created_at DESC, id);

CREATE INDEX ix_collection_jobs_status
    ON collection_jobs(status, created_at DESC);

CREATE TABLE collection_job_items (
    id                TEXT    PRIMARY KEY NOT NULL,
    job_id            TEXT    NOT NULL REFERENCES collection_jobs(id) ON DELETE CASCADE,
    source_id         TEXT    NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    status            TEXT    NOT NULL
                              CHECK (status IN ('pending','running','succeeded',
                                                'failed','skipped','cancelled')),
    http_status       INTEGER CHECK (http_status IS NULL
                                     OR http_status BETWEEN 100 AND 599),
    discovered_count  INTEGER NOT NULL DEFAULT 0 CHECK (discovered_count >= 0),
    inserted_count    INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    updated_count     INTEGER NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
    duplicate_count   INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    error_count       INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    error_code        TEXT,
    error_message     TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    duration_ms       INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    CHECK (error_code IS NULL OR length(error_code) <= 64),
    CHECK (error_message IS NULL OR length(error_message) <= 1000),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (started_at IS NULL OR length(started_at) = 24),
    CHECK (finished_at IS NULL OR length(finished_at) = 24),
    CHECK (updated_at >= created_at),
    UNIQUE (job_id, source_id)
);

CREATE UNIQUE INDEX ux_collection_job_items_running
    ON collection_job_items(source_id)
    WHERE status = 'running';

CREATE INDEX ix_collection_job_items_job
    ON collection_job_items(job_id, created_at);

CREATE INDEX ix_collection_job_items_source
    ON collection_job_items(source_id, created_at DESC);

CREATE TABLE source_health_logs (
    id             TEXT    PRIMARY KEY NOT NULL,
    source_id      TEXT    NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    checked_at     TEXT    NOT NULL,
    status         TEXT    NOT NULL CHECK (status IN ('healthy','degraded','failing')),
    http_status    INTEGER CHECK (http_status IS NULL
                                  OR http_status BETWEEN 100 AND 599),
    latency_ms     INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error_code     TEXT,
    error_message  TEXT,
    created_at     TEXT    NOT NULL,
    CHECK (length(checked_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (error_code IS NULL OR length(error_code) <= 64),
    CHECK (error_message IS NULL OR length(error_message) <= 500)
);

CREATE INDEX ix_source_health_logs_source
    ON source_health_logs(source_id, checked_at DESC);
