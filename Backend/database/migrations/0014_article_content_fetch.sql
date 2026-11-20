-- 0014_article_content_fetch.sql
-- Phase 8: on-demand full-text retrieval for articles that only have an RSS
-- summary. Records when the body was last fetched so the reader can show the
-- real coverage state instead of guessing. Forward-only, additive column.

ALTER TABLE articles ADD COLUMN content_fetched_at TEXT;
