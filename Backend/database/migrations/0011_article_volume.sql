-- 0011_article_volume.sql
-- Phase 7.3.3: per-source ingestion cap. Forward-only; the migration runner
-- owns the transaction. Only ADD COLUMN; no table rebuild, no row rewrite.
--
-- NULL keeps the historical behaviour (global parser cap of 100 entries).

ALTER TABLE sources ADD COLUMN max_entries_per_fetch INTEGER
    CHECK (max_entries_per_fetch IS NULL
           OR max_entries_per_fetch BETWEEN 1 AND 100);
