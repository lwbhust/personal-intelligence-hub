-- 0005_ai_analysis.sql
-- Phase 3: local AI model registry, analysis runs, per-article results and
-- embedding storage (embeddings stay empty until AI-01 is approved).
-- Forward-only; the migration runner owns the transaction.

CREATE TABLE ai_model_registry (
    model_name       TEXT    PRIMARY KEY NOT NULL,
    provider_kind    TEXT    NOT NULL DEFAULT 'ollama-local'
                             CHECK (provider_kind = 'ollama-local'),
    digest           TEXT,
    size_bytes       INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    parameter_size   TEXT,
    quantization     TEXT,
    max_context      INTEGER CHECK (max_context IS NULL OR max_context > 0),
    num_ctx          INTEGER NOT NULL CHECK (num_ctx BETWEEN 1024 AND 32768),
    roles            TEXT    NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    last_checked_at  TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    CHECK (length(model_name) BETWEEN 1 AND 200),
    CHECK (lower(model_name) NOT LIKE '%-cloud%'),
    CHECK (length(roles) BETWEEN 1 AND 200),
    CHECK (digest IS NULL OR length(digest) <= 128),
    CHECK (parameter_size IS NULL OR length(parameter_size) <= 32),
    CHECK (quantization IS NULL OR length(quantization) <= 32),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (last_checked_at IS NULL OR length(last_checked_at) = 24),
    CHECK (updated_at >= created_at)
);

CREATE INDEX ix_ai_model_registry_enabled
    ON ai_model_registry(enabled);

CREATE TABLE ai_runs (
    id                TEXT    PRIMARY KEY NOT NULL,
    trigger_type      TEXT    NOT NULL CHECK (trigger_type IN ('manual','retry')),
    scope             TEXT    NOT NULL CHECK (scope IN ('selected','unanalyzed')),
    status            TEXT    NOT NULL
                              CHECK (status IN ('pending','running','paused','succeeded',
                                                'partially_succeeded','failed','cancelled')),
    requested_count   INTEGER NOT NULL DEFAULT 0 CHECK (requested_count >= 0),
    processed_count   INTEGER NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
    succeeded_count   INTEGER NOT NULL DEFAULT 0 CHECK (succeeded_count >= 0),
    failed_count      INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    skipped_count     INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    model_name        TEXT,
    error_message     TEXT,
    cancel_requested  INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    pause_requested   INTEGER NOT NULL DEFAULT 0 CHECK (pause_requested IN (0,1)),
    started_at        TEXT,
    finished_at       TEXT,
    duration_ms       INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    CHECK (error_message IS NULL OR length(error_message) <= 1000),
    CHECK (model_name IS NULL OR length(model_name) BETWEEN 1 AND 200),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (started_at IS NULL OR length(started_at) = 24),
    CHECK (finished_at IS NULL OR length(finished_at) = 24),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CHECK (updated_at >= created_at)
);

CREATE INDEX ix_ai_runs_created
    ON ai_runs(created_at DESC, id);

CREATE INDEX ix_ai_runs_status
    ON ai_runs(status, created_at DESC);

CREATE TABLE ai_run_items (
    id             TEXT    PRIMARY KEY NOT NULL,
    run_id         TEXT    NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
    article_id     TEXT    NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    status         TEXT    NOT NULL
                           CHECK (status IN ('pending','running','succeeded','failed',
                                             'skipped','cancelled')),
    attempts       INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error_code     TEXT,
    error_message  TEXT,
    started_at     TEXT,
    finished_at    TEXT,
    duration_ms    INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    CHECK (error_code IS NULL OR length(error_code) <= 64),
    CHECK (error_message IS NULL OR length(error_message) <= 1000),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (started_at IS NULL OR length(started_at) = 24),
    CHECK (finished_at IS NULL OR length(finished_at) = 24),
    CHECK (updated_at >= created_at),
    UNIQUE (run_id, article_id)
);

CREATE UNIQUE INDEX ux_ai_run_items_running
    ON ai_run_items(article_id)
    WHERE status = 'running';

CREATE INDEX ix_ai_run_items_run
    ON ai_run_items(run_id, created_at);

CREATE INDEX ix_ai_run_items_article
    ON ai_run_items(article_id, created_at DESC);

CREATE TABLE article_ai_analysis (
    id              TEXT    PRIMARY KEY NOT NULL,
    article_id      TEXT    NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    analysis_type   TEXT    NOT NULL CHECK (analysis_type = 'article_analysis'),
    provider_kind   TEXT    NOT NULL CHECK (provider_kind = 'ollama-local'),
    model_name      TEXT    NOT NULL,
    model_digest    TEXT,
    prompt_version  TEXT    NOT NULL,
    params_json     TEXT    NOT NULL,
    content_hash    TEXT    NOT NULL,
    category        TEXT    NOT NULL
                            CHECK (category IN ('科技','财经','政治','国际','社会',
                                                '健康','教育','文化','体育','其他')),
    summary         TEXT    NOT NULL,
    keywords_json   TEXT    NOT NULL,
    entities_json   TEXT    NOT NULL,
    confidence      REAL    NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    input_chars     INTEGER NOT NULL CHECK (input_chars >= 0),
    duration_ms     INTEGER NOT NULL CHECK (duration_ms >= 0),
    created_at      TEXT    NOT NULL,
    CHECK (length(model_name) BETWEEN 1 AND 200),
    CHECK (model_digest IS NULL OR length(model_digest) <= 128),
    CHECK (length(prompt_version) BETWEEN 1 AND 64),
    CHECK (length(params_json) <= 1000),
    CHECK (length(content_hash) = 64),
    CHECK (length(summary) BETWEEN 1 AND 300),
    CHECK (length(keywords_json) <= 4000),
    CHECK (length(entities_json) <= 8000),
    CHECK (length(created_at) = 24),
    UNIQUE (article_id, analysis_type, prompt_version, content_hash, model_name)
);

CREATE INDEX ix_article_ai_analysis_article
    ON article_ai_analysis(article_id, created_at DESC);

CREATE INDEX ix_article_ai_analysis_category
    ON article_ai_analysis(category, created_at DESC);

CREATE TABLE article_embeddings (
    id            TEXT    PRIMARY KEY NOT NULL,
    article_id    TEXT    NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    model_name    TEXT    NOT NULL,
    model_digest  TEXT,
    dimensions    INTEGER NOT NULL CHECK (dimensions > 0 AND dimensions <= 8192),
    vector        BLOB    NOT NULL,
    content_hash  TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    CHECK (length(model_name) BETWEEN 1 AND 200),
    CHECK (model_digest IS NULL OR length(model_digest) <= 128),
    CHECK (length(content_hash) = 64),
    CHECK (length(created_at) = 24),
    UNIQUE (article_id, model_name, content_hash)
);

CREATE INDEX ix_article_embeddings_model
    ON article_embeddings(model_name, created_at DESC);

-- Seeded candidates. Only the currently installed local model is enabled;
-- qwen3:1.7b / gemma3:4b are kept as disabled candidates (not installed as of
-- the Phase 3 audit). -cloud models are rejected by the CHECK constraint.
INSERT INTO ai_model_registry (
    model_name, provider_kind, num_ctx, roles, enabled,
    created_at, updated_at
) VALUES
    ('qwen3.5:4b-mlx', 'ollama-local', 4096,
     'classify,summary,keywords,entities', 1,
     '2026-11-16T00:00:00.000Z', '2026-11-16T00:00:00.000Z'),
    ('qwen3:1.7b', 'ollama-local', 4096,
     'classify,summary,keywords,entities', 0,
     '2026-11-16T00:00:00.000Z', '2026-11-16T00:00:00.000Z'),
    ('gemma3:4b', 'ollama-local', 4096,
     'classify,summary,keywords,entities', 0,
     '2026-11-16T00:00:00.000Z', '2026-11-16T00:00:00.000Z');
