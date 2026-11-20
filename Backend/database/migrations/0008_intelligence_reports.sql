-- 0008_intelligence_reports.sql
-- Phase 7.1: persisted intelligence reports (daily brief / weekly review) and
-- their citations. Forward-only; the migration runner owns the transaction.
-- No Phase 0-7.0 table is altered.

CREATE TABLE intelligence_reports (
    id                 TEXT    PRIMARY KEY NOT NULL,
    report_type        TEXT    NOT NULL CHECK (report_type IN ('daily','weekly')),
    period_key         TEXT    NOT NULL,
    period_start       TEXT    NOT NULL,
    period_end         TEXT    NOT NULL,
    data_from_at       TEXT,
    data_to_at         TEXT,
    status             TEXT    NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending','running','succeeded','degraded',
                                                 'failed','cancelled','superseded')),
    ai_status          TEXT    NOT NULL DEFAULT 'pending'
                               CHECK (ai_status IN ('pending','used','unavailable','invalid')),
    headline           TEXT,
    overview           TEXT,
    content_json       TEXT    NOT NULL DEFAULT '{}',
    stats_json         TEXT    NOT NULL DEFAULT '{}',
    model_name         TEXT,
    model_digest       TEXT,
    prompt_version     TEXT    NOT NULL,
    stats_version      TEXT    NOT NULL,
    article_count      INTEGER NOT NULL DEFAULT 0 CHECK (article_count >= 0),
    event_count        INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    entity_count       INTEGER NOT NULL DEFAULT 0 CHECK (entity_count >= 0),
    citation_count     INTEGER NOT NULL DEFAULT 0 CHECK (citation_count >= 0),
    trigger_type       TEXT    NOT NULL DEFAULT 'manual'
                               CHECK (trigger_type IN ('manual','retry')),
    cancel_requested   INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    error_code         TEXT,
    error_message      TEXT,
    started_at         TEXT,
    finished_at        TEXT,
    duration_ms        INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL,
    CHECK (length(period_key) = 10),
    CHECK (length(period_start) = 10),
    CHECK (length(period_end) = 10),
    CHECK (period_end >= period_start),
    CHECK (data_from_at IS NULL OR length(data_from_at) = 24),
    CHECK (data_to_at IS NULL OR length(data_to_at) = 24),
    CHECK (headline IS NULL OR length(headline) BETWEEN 1 AND 300),
    CHECK (overview IS NULL OR length(overview) BETWEEN 1 AND 4000),
    CHECK (length(content_json) <= 60000),
    CHECK (length(stats_json) <= 120000),
    CHECK (model_name IS NULL OR length(model_name) BETWEEN 1 AND 200),
    CHECK (model_digest IS NULL OR length(model_digest) <= 128),
    CHECK (length(prompt_version) BETWEEN 1 AND 64),
    CHECK (length(stats_version) BETWEEN 1 AND 64),
    CHECK (error_code IS NULL OR length(error_code) <= 64),
    CHECK (error_message IS NULL OR length(error_message) <= 1000),
    CHECK (started_at IS NULL OR length(started_at) = 24),
    CHECK (finished_at IS NULL OR length(finished_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CHECK (updated_at >= created_at)
);

-- One active report per period: prevents duplicate generations and duplicate
-- running jobs for the same day/week. `period_key` is the dedupe anchor (the
-- day for daily, the ISO week start for the rolling weekly window).
CREATE UNIQUE INDEX ux_intelligence_reports_active
    ON intelligence_reports(report_type, period_key)
    WHERE status IN ('pending','running','succeeded','degraded');

CREATE INDEX ix_intelligence_reports_created
    ON intelligence_reports(created_at DESC, id);

CREATE INDEX ix_intelligence_reports_type_status
    ON intelligence_reports(report_type, status, created_at DESC);

CREATE TABLE intelligence_report_citations (
    id             TEXT    PRIMARY KEY NOT NULL,
    report_id      TEXT    NOT NULL
                           REFERENCES intelligence_reports(id) ON DELETE CASCADE,
    citation_type  TEXT    NOT NULL
                           CHECK (citation_type IN ('article','event','entity')),
    ref_id         TEXT    NOT NULL,
    section_key    TEXT    NOT NULL,
    rank           INTEGER NOT NULL DEFAULT 0 CHECK (rank >= 0),
    title          TEXT,
    source_name    TEXT,
    url            TEXT,
    evidence       TEXT,
    created_at     TEXT    NOT NULL,
    CHECK (length(ref_id) BETWEEN 1 AND 64),
    CHECK (length(section_key) BETWEEN 1 AND 64),
    CHECK (title IS NULL OR length(title) <= 500),
    CHECK (source_name IS NULL OR length(source_name) <= 200),
    CHECK (url IS NULL OR length(url) <= 2048),
    CHECK (evidence IS NULL OR length(evidence) <= 1000),
    CHECK (length(created_at) = 24),
    UNIQUE (report_id, citation_type, ref_id, section_key)
);

CREATE INDEX ix_intelligence_citations_report
    ON intelligence_report_citations(report_id, section_key, rank);

CREATE INDEX ix_intelligence_citations_ref
    ON intelligence_report_citations(citation_type, ref_id);
