-- 0012_source_adapters.sql
-- Phase 7.6: official web/API adapters for sources without RSS.
-- Forward-only; the migration runner owns the transaction.
-- Only a new table is created; no existing table or row is modified.

CREATE TABLE source_adapter_configs (
    source_id             TEXT    PRIMARY KEY NOT NULL
                                  REFERENCES sources(id) ON DELETE CASCADE,
    adapter_type          TEXT    NOT NULL
                                  CHECK (adapter_type IN ('html_list','json_api','manual_inbox')),
    entry_url             TEXT    NOT NULL,
    config_json           TEXT    NOT NULL,
    config_version        TEXT    NOT NULL DEFAULT 'html-list-v1',
    rate_limit_seconds    INTEGER NOT NULL DEFAULT 5
                                  CHECK (rate_limit_seconds BETWEEN 1 AND 60),
    max_entries_per_run   INTEGER NOT NULL DEFAULT 12
                                  CHECK (max_entries_per_run BETWEEN 1 AND 50),
    fetch_full_text       INTEGER NOT NULL DEFAULT 0
                                  CHECK (fetch_full_text IN (0, 1)),
    last_verified_at      TEXT,
    last_verification     TEXT    NOT NULL DEFAULT 'unknown'
                                  CHECK (last_verification IN
                                         ('unknown','verified','selector_drift','blocked')),
    last_sample_json      TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(entry_url) BETWEEN 1 AND 2048),
    CHECK (length(config_json) BETWEEN 2 AND 20000),
    CHECK (length(config_version) BETWEEN 1 AND 64),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (last_verified_at IS NULL OR length(last_verified_at) = 24),
    CHECK (last_sample_json IS NULL OR length(last_sample_json) <= 20000)
);

CREATE INDEX ix_adapter_verification
    ON source_adapter_configs(last_verification, updated_at DESC);
