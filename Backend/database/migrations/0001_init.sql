-- 0001_init.sql
-- Phase 0 infrastructure only. Business tables are forbidden in Phase 0.
-- Transaction control is owned by the migration runner: do not add
-- BEGIN / COMMIT / ROLLBACK to this file.

CREATE TABLE IF NOT EXISTS app_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
