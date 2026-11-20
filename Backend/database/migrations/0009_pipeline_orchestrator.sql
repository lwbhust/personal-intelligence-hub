-- 0009_pipeline_orchestrator.sql
-- Phase 7.2: persistent pipeline tasks, settings, backfill runs and the audit
-- columns needed to keep event categories consistent.
-- Forward-only; the migration runner owns the transaction. No existing table is
-- rebuilt and no user row is deleted.

-- ---------------------------------------------------------------------------
-- Event classification provenance (additive columns only).
-- `events.category` is still constrained to the Phase 4 ten-domain set; these
-- columns record where the value came from so automation never overwrites a
-- manual correction.
-- ---------------------------------------------------------------------------
ALTER TABLE events ADD COLUMN category_source TEXT NOT NULL DEFAULT 'legacy'
    CHECK (category_source IN ('legacy','auto','manual','unresolved'));
ALTER TABLE events ADD COLUMN category_reason TEXT;
ALTER TABLE events ADD COLUMN category_updated_at TEXT;

CREATE INDEX ix_events_category_source
    ON events(category_source, category);

-- ---------------------------------------------------------------------------
-- Pipeline settings: a single row. Automation is off by default so an update
-- never starts analysing the existing history without an explicit opt-in.
-- ---------------------------------------------------------------------------
CREATE TABLE pipeline_settings (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    automation_enabled    INTEGER NOT NULL DEFAULT 0 CHECK (automation_enabled IN (0,1)),
    paused                INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0,1)),
    ai_enabled            INTEGER NOT NULL DEFAULT 1 CHECK (ai_enabled IN (0,1)),
    entity_enabled        INTEGER NOT NULL DEFAULT 1 CHECK (entity_enabled IN (0,1)),
    event_enabled         INTEGER NOT NULL DEFAULT 1 CHECK (event_enabled IN (0,1)),
    scoring_enabled       INTEGER NOT NULL DEFAULT 1 CHECK (scoring_enabled IN (0,1)),
    batch_size            INTEGER NOT NULL DEFAULT 3 CHECK (batch_size BETWEEN 1 AND 50),
    max_attempts          INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    ai_interval_seconds   INTEGER NOT NULL DEFAULT 30 CHECK (ai_interval_seconds BETWEEN 0 AND 3600),
    updated_at            TEXT    NOT NULL,
    CHECK (length(updated_at) = 24)
);

INSERT INTO pipeline_settings (
    id, automation_enabled, paused, ai_enabled, entity_enabled, event_enabled,
    scoring_enabled, batch_size, max_attempts, ai_interval_seconds, updated_at
) VALUES (1, 0, 0, 1, 1, 1, 1, 3, 3, 30, '2026-11-18T00:00:00.000Z');

-- ---------------------------------------------------------------------------
-- Backfill batches created explicitly by the user (bounded, resumable).
-- ---------------------------------------------------------------------------
CREATE TABLE pipeline_runs (
    id                    TEXT    PRIMARY KEY NOT NULL,
    trigger_type          TEXT    NOT NULL DEFAULT 'backfill'
                                  CHECK (trigger_type IN ('manual','backfill')),
    status                TEXT    NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','running','paused','succeeded',
                                                    'partially_succeeded','failed','cancelled')),
    requested_tasks       INTEGER NOT NULL DEFAULT 0 CHECK (requested_tasks >= 0),
    created_tasks         INTEGER NOT NULL DEFAULT 0 CHECK (created_tasks >= 0),
    processed_tasks       INTEGER NOT NULL DEFAULT 0 CHECK (processed_tasks >= 0),
    succeeded_tasks       INTEGER NOT NULL DEFAULT 0 CHECK (succeeded_tasks >= 0),
    failed_tasks          INTEGER NOT NULL DEFAULT 0 CHECK (failed_tasks >= 0),
    skipped_tasks         INTEGER NOT NULL DEFAULT 0 CHECK (skipped_tasks >= 0),
    cancel_requested      INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    error_message         TEXT,
    started_at            TEXT,
    finished_at           TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24)
);

CREATE INDEX ix_pipeline_runs_created
    ON pipeline_runs(created_at DESC, id);

-- ---------------------------------------------------------------------------
-- One persistent task per article. Stages are executed in order; the task row
-- is the single source of truth for progress across restarts.
-- ---------------------------------------------------------------------------
CREATE TABLE pipeline_tasks (
    id                    TEXT    PRIMARY KEY NOT NULL,
    task_type             TEXT    NOT NULL DEFAULT 'article_pipeline'
                                  CHECK (task_type IN ('article_pipeline')),
    article_id            TEXT    REFERENCES articles(id) ON DELETE CASCADE,
    event_id              TEXT    REFERENCES events(id) ON DELETE SET NULL,
    stage                 TEXT    NOT NULL DEFAULT 'quality_check'
                                  CHECK (stage IN ('quality_check','ai_analysis','entity_sync',
                                                   'event_match','event_score','refresh','done')),
    status                TEXT    NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','ready','running','retry_wait',
                                                    'succeeded','failed','skipped','cancelled')),
    priority              INTEGER NOT NULL DEFAULT 100,
    idempotency_key       TEXT    NOT NULL,
    attempts              INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts          INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    next_retry_at         TEXT,
    lease_owner           TEXT,
    lease_expires_at      TEXT,
    last_heartbeat_at     TEXT,
    error_code            TEXT,
    error_message         TEXT,
    input_summary         TEXT,
    output_summary        TEXT,
    trigger_type          TEXT    NOT NULL DEFAULT 'auto'
                                  CHECK (trigger_type IN ('auto','manual','backfill')),
    batch_id              TEXT    REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    created_at            TEXT    NOT NULL,
    started_at            TEXT,
    completed_at          TEXT,
    updated_at            TEXT    NOT NULL,
    CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (completed_at IS NULL OR length(completed_at) = 24),
    CHECK (next_retry_at IS NULL OR length(next_retry_at) = 24),
    CHECK (lease_expires_at IS NULL OR length(lease_expires_at) = 24),
    CHECK (status <> 'succeeded' OR completed_at IS NOT NULL)
);

-- Idempotency: an article can only have one pipeline task, regardless of how
-- many times ingestion or a backfill request is repeated.
CREATE UNIQUE INDEX ux_pipeline_tasks_idempotency
    ON pipeline_tasks(idempotency_key);

CREATE INDEX ix_pipeline_tasks_ready
    ON pipeline_tasks(status, stage, priority, created_at);

CREATE INDEX ix_pipeline_tasks_article
    ON pipeline_tasks(article_id, created_at DESC);

CREATE INDEX ix_pipeline_tasks_batch
    ON pipeline_tasks(batch_id, status);

CREATE TABLE pipeline_task_logs (
    id                    TEXT    PRIMARY KEY NOT NULL,
    task_id               TEXT    NOT NULL
                                  REFERENCES pipeline_tasks(id) ON DELETE CASCADE,
    stage                 TEXT,
    level                 TEXT    NOT NULL DEFAULT 'info'
                                  CHECK (level IN ('info','warn','error')),
    message               TEXT    NOT NULL,
    detail_json           TEXT    NOT NULL DEFAULT '{}',
    created_at            TEXT    NOT NULL,
    CHECK (length(message) BETWEEN 1 AND 2000),
    CHECK (length(detail_json) <= 12000),
    CHECK (length(created_at) = 24)
);

CREATE INDEX ix_pipeline_task_logs_task
    ON pipeline_task_logs(task_id, created_at DESC);
