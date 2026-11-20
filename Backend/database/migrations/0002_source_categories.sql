-- 0002_source_categories.sql
-- Phase 1: source categories. Forward-only; the runner owns the transaction.

CREATE TABLE source_categories (
    id          TEXT    PRIMARY KEY NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
                        CHECK (sort_order BETWEEN -1000 AND 1000),
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    deleted_at  TEXT,
    CHECK (length(trim(name)) BETWEEN 1 AND 40),
    CHECK (description IS NULL OR length(description) <= 200),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (deleted_at IS NULL OR length(deleted_at) = 24),
    CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX ux_source_categories_name_active
    ON source_categories(name)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_source_categories_sort
    ON source_categories(sort_order, name)
    WHERE deleted_at IS NULL;
