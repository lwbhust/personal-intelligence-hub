-- 0013_automation_default.sql
-- Phase 7.9: enable the local pipeline by default for brand-new databases only.
-- Forward-only; the migration runner owns the transaction.
--
-- Guard: only runs when the database has never ingested an article and has never
-- queued a pipeline task. Existing user databases (articles > 0) keep their
-- current automation setting, so nobody's configuration is overwritten.

UPDATE pipeline_settings
SET automation_enabled = 1,
    updated_at = '2026-11-19T00:00:00.000Z'
WHERE id = 1
  AND automation_enabled = 0
  AND NOT EXISTS (SELECT 1 FROM articles)
  AND NOT EXISTS (SELECT 1 FROM pipeline_tasks);
