-- 0007_reading_and_search.sql
-- Phase 5: full-text search via FTS5 + trigram tokenizer, reading state,
-- favorites and later-read markers. Forward-only; the migration runner owns
-- the transaction. No Phase 0-4 table is altered beyond new columns on
-- `articles` (ADD COLUMN only, no existing data rewritten).

-- --- 1. Articles: reading state + favorite/later-read fields ---

ALTER TABLE articles ADD COLUMN reading_status TEXT NOT NULL DEFAULT 'unread'
    CHECK (reading_status IN ('unread','reading','read','later'));

ALTER TABLE articles ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0
    CHECK (is_favorite IN (0,1));

ALTER TABLE articles ADD COLUMN last_read_at TEXT
    CHECK (last_read_at IS NULL OR length(last_read_at) = 24);

ALTER TABLE articles ADD COLUMN read_count INTEGER NOT NULL DEFAULT 0
    CHECK (read_count >= 0);

CREATE INDEX ix_articles_reading_status
    ON articles(reading_status, published_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_articles_favorite
    ON articles(is_favorite, published_at DESC)
    WHERE deleted_at IS NULL AND is_favorite = 1;

CREATE INDEX ix_articles_last_read
    ON articles(last_read_at DESC)
    WHERE deleted_at IS NULL AND last_read_at IS NOT NULL;

-- --- 2. FTS5 virtual table (trigram tokenizer for 中英文混合搜索) ---
-- Standalone (not content-mode): we own sync via triggers because the
-- articles PK is TEXT and trigram ranks/snippets require direct control.

CREATE VIRTUAL TABLE articles_fts USING fts5(
    article_id,
    title,
    summary,
    content_text,
    tokenize='trigram'
);

-- Initial population from existing non-deleted articles.
INSERT INTO articles_fts(article_id, title, summary, content_text)
    SELECT id, title,
           COALESCE(summary, ''),
           COALESCE(content_text, '')
    FROM articles
    WHERE deleted_at IS NULL;

-- --- 3. Triggers: keep FTS in sync with articles lifecycle ---

CREATE TRIGGER articles_fts_insert AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(article_id, title, summary, content_text)
        VALUES (new.id, new.title,
                COALESCE(new.summary, ''),
                COALESCE(new.content_text, ''));
END;

CREATE TRIGGER articles_fts_update AFTER UPDATE ON articles BEGIN
    DELETE FROM articles_fts WHERE article_id = new.id;
    INSERT INTO articles_fts(article_id, title, summary, content_text)
        VALUES (new.id, new.title,
                COALESCE(new.summary, ''),
                COALESCE(new.content_text, ''));
END;

CREATE TRIGGER articles_fts_delete AFTER DELETE ON articles BEGIN
    DELETE FROM articles_fts WHERE article_id = old.id;
END;
