-- 0006_event_intelligence.sql
-- Phase 4: entity normalization, event clustering, timelines, relations and
-- explainable score history. Forward-only; the migration runner owns the
-- transaction. No Phase 0-3 table is altered.

CREATE TABLE entities (
    id                    TEXT    PRIMARY KEY NOT NULL,
    canonical_name        TEXT    NOT NULL,
    entity_type           TEXT    NOT NULL
                                  CHECK (entity_type IN ('person','organization','location',
                                                         'company','product','event','other')),
    type_group            TEXT    NOT NULL
                                  CHECK (type_group IN ('person','organization','location',
                                                        'product','event','other')),
    normalized_key        TEXT    NOT NULL,
    status                TEXT    NOT NULL DEFAULT 'active'
                                  CHECK (status IN ('active','merged','archived')),
    confidence            REAL    NOT NULL DEFAULT 0.5
                                  CHECK (confidence >= 0.0 AND confidence <= 1.0),
    normalization_basis   TEXT    NOT NULL DEFAULT 'ai_extraction'
                                  CHECK (normalization_basis IN ('ai_extraction','exact_match',
                                                                 'alias_match','manual','merge')),
    merged_into_entity_id TEXT    REFERENCES entities(id) ON DELETE SET NULL,
    first_seen_at         TEXT,
    last_seen_at          TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(canonical_name) BETWEEN 1 AND 200),
    CHECK (length(normalized_key) BETWEEN 1 AND 200),
    CHECK (status <> 'merged' OR merged_into_entity_id IS NOT NULL),
    CHECK (merged_into_entity_id IS NULL OR merged_into_entity_id <> id),
    CHECK (first_seen_at IS NULL OR length(first_seen_at) = 24),
    CHECK (last_seen_at IS NULL OR length(last_seen_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX ux_entities_active_key
    ON entities(normalized_key, type_group)
    WHERE merged_into_entity_id IS NULL;

CREATE INDEX ix_entities_type_seen
    ON entities(entity_type, last_seen_at DESC);

CREATE INDEX ix_entities_last_seen
    ON entities(last_seen_at DESC, id);

CREATE TABLE entity_aliases (
    id                    TEXT    PRIMARY KEY NOT NULL,
    entity_id             TEXT    NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias                 TEXT    NOT NULL,
    alias_key             TEXT    NOT NULL,
    language              TEXT    NOT NULL DEFAULT 'unknown'
                                  CHECK (language IN ('zh','en','mixed','unknown')),
    source                TEXT    NOT NULL DEFAULT 'ai_extraction'
                                  CHECK (source IN ('canonical','ai_extraction','manual','merge')),
    confidence            REAL    NOT NULL DEFAULT 0.5
                                  CHECK (confidence >= 0.0 AND confidence <= 1.0),
    merged_from_entity_id TEXT    REFERENCES entities(id) ON DELETE SET NULL,
    created_at            TEXT    NOT NULL,
    CHECK (length(alias) BETWEEN 1 AND 200),
    CHECK (length(alias_key) BETWEEN 1 AND 200),
    CHECK (length(created_at) = 24),
    UNIQUE (entity_id, alias_key)
);

CREATE INDEX ix_entity_aliases_key
    ON entity_aliases(alias_key);

CREATE INDEX ix_entity_aliases_entity
    ON entity_aliases(entity_id);

CREATE TABLE article_entities (
    id                    TEXT    PRIMARY KEY NOT NULL,
    article_id            TEXT    NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    entity_id             TEXT    REFERENCES entities(id) ON DELETE CASCADE,
    analysis_id           TEXT    REFERENCES article_ai_analysis(id) ON DELETE SET NULL,
    raw_name              TEXT    NOT NULL,
    raw_type              TEXT    NOT NULL,
    match_method          TEXT    NOT NULL
                                  CHECK (match_method IN ('canonical','alias','manual','ambiguous')),
    status                TEXT    NOT NULL DEFAULT 'resolved'
                                  CHECK (status IN ('resolved','ambiguous')),
    confidence            REAL    NOT NULL DEFAULT 0.5
                                  CHECK (confidence >= 0.0 AND confidence <= 1.0),
    merged_from_entity_id TEXT    REFERENCES entities(id) ON DELETE SET NULL,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(raw_name) BETWEEN 1 AND 200),
    CHECK (length(raw_type) BETWEEN 1 AND 32),
    CHECK (status = 'resolved' OR entity_id IS NULL),
    CHECK (status = 'ambiguous' OR entity_id IS NOT NULL),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX ux_article_entities_pair
    ON article_entities(article_id, entity_id)
    WHERE entity_id IS NOT NULL;

CREATE UNIQUE INDEX ux_article_entities_ambiguous
    ON article_entities(article_id, lower(raw_name))
    WHERE entity_id IS NULL;

CREATE INDEX ix_article_entities_article
    ON article_entities(article_id);

CREATE INDEX ix_article_entities_entity
    ON article_entities(entity_id, created_at DESC);

CREATE TABLE events (
    id                    TEXT    PRIMARY KEY NOT NULL,
    title                 TEXT    NOT NULL,
    summary               TEXT,
    category              TEXT    NOT NULL DEFAULT '其他'
                                  CHECK (category IN ('科技','财经','政治','国际','社会',
                                                      '健康','教育','文化','体育','其他')),
    status                TEXT    NOT NULL DEFAULT 'candidate'
                                  CHECK (status IN ('candidate','active','evolving','dormant',
                                                    'closed','merged','archived')),
    status_reason         TEXT,
    first_seen_at         TEXT    NOT NULL,
    last_seen_at          TEXT    NOT NULL,
    first_published_at    TEXT,
    last_published_at     TEXT,
    occurred_at           TEXT,
    article_count         INTEGER NOT NULL DEFAULT 0 CHECK (article_count >= 0),
    source_count          INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    is_manual             INTEGER NOT NULL DEFAULT 0 CHECK (is_manual IN (0,1)),
    merged_into_event_id  TEXT    REFERENCES events(id) ON DELETE SET NULL,
    algorithm_version     TEXT    NOT NULL DEFAULT 'event-cluster-v1',
    title_source          TEXT    NOT NULL DEFAULT 'auto'
                                  CHECK (title_source IN ('auto','manual')),
    summary_source        TEXT    NOT NULL DEFAULT 'auto'
                                  CHECK (summary_source IN ('auto','manual')),
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CHECK (length(title) BETWEEN 1 AND 300),
    CHECK (summary IS NULL OR length(summary) <= 2000),
    CHECK (status_reason IS NULL OR length(status_reason) <= 500),
    CHECK (status <> 'merged' OR merged_into_event_id IS NOT NULL),
    CHECK (merged_into_event_id IS NULL OR merged_into_event_id <> id),
    CHECK (length(algorithm_version) BETWEEN 1 AND 64),
    CHECK (first_published_at IS NULL OR length(first_published_at) = 24),
    CHECK (last_published_at IS NULL OR length(last_published_at) = 24),
    CHECK (occurred_at IS NULL OR length(occurred_at) = 24),
    CHECK (length(first_seen_at) = 24),
    CHECK (length(last_seen_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (updated_at >= created_at)
);

CREATE INDEX ix_events_status_seen
    ON events(status, last_seen_at DESC);

CREATE INDEX ix_events_category_published
    ON events(category, last_published_at DESC);

CREATE INDEX ix_events_last_published
    ON events(last_published_at DESC, id);

CREATE INDEX ix_events_manual
    ON events(is_manual);

CREATE TABLE event_articles (
    id                 TEXT    PRIMARY KEY NOT NULL,
    event_id           TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    article_id         TEXT    NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    role               TEXT    NOT NULL DEFAULT 'report'
                               CHECK (role IN ('report','follow_up','commentary','duplicate','primary')),
    similarity         REAL    CHECK (similarity IS NULL
                                      OR (similarity >= 0.0 AND similarity <= 1.0)),
    match_reasons_json TEXT    NOT NULL DEFAULT '[]',
    is_manual          INTEGER NOT NULL DEFAULT 0 CHECK (is_manual IN (0,1)),
    added_at           TEXT    NOT NULL,
    created_at         TEXT    NOT NULL,
    CHECK (length(match_reasons_json) <= 4000),
    CHECK (length(added_at) = 24),
    CHECK (length(created_at) = 24),
    UNIQUE (event_id, article_id)
);

CREATE UNIQUE INDEX ux_event_articles_article
    ON event_articles(article_id);

CREATE INDEX ix_event_articles_event
    ON event_articles(event_id, added_at);

CREATE TABLE event_article_exclusions (
    article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    event_id   TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    reason     TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (article_id, event_id),
    CHECK (reason IS NULL OR length(reason) <= 500),
    CHECK (length(created_at) = 24)
);

CREATE INDEX ix_event_article_exclusions_event
    ON event_article_exclusions(event_id);

CREATE TABLE event_entities (
    id                  TEXT    PRIMARY KEY NOT NULL,
    event_id            TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    entity_id           TEXT    NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    role                TEXT    NOT NULL DEFAULT 'mentioned'
                                CHECK (role IN ('subject','actor','organization',
                                                'location','mentioned')),
    article_count       INTEGER NOT NULL DEFAULT 0 CHECK (article_count >= 0),
    confidence          REAL    NOT NULL DEFAULT 0.5
                                CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence_article_id TEXT    REFERENCES articles(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (updated_at >= created_at),
    UNIQUE (event_id, entity_id)
);

CREATE INDEX ix_event_entities_event
    ON event_entities(event_id, role);

CREATE INDEX ix_event_entities_entity
    ON event_entities(entity_id);

CREATE TABLE event_timeline_items (
    id            TEXT    PRIMARY KEY NOT NULL,
    event_id      TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    article_id    TEXT    REFERENCES articles(id) ON DELETE SET NULL,
    kind          TEXT    NOT NULL
                          CHECK (kind IN ('first_report','follow_up','key_development',
                                          'status_change','merge','split','manual_note')),
    title         TEXT    NOT NULL,
    description   TEXT,
    occurred_at   TEXT,
    published_at  TEXT,
    recognized_at TEXT    NOT NULL,
    confidence    REAL    CHECK (confidence IS NULL
                                 OR (confidence >= 0.0 AND confidence <= 1.0)),
    is_key        INTEGER NOT NULL DEFAULT 0 CHECK (is_key IN (0,1)),
    evidence_json TEXT    NOT NULL DEFAULT '{}',
    created_at    TEXT    NOT NULL,
    CHECK (length(title) BETWEEN 1 AND 300),
    CHECK (description IS NULL OR length(description) <= 2000),
    CHECK (length(evidence_json) <= 4000),
    CHECK (occurred_at IS NULL OR length(occurred_at) = 24),
    CHECK (published_at IS NULL OR length(published_at) = 24),
    CHECK (length(recognized_at) = 24),
    CHECK (length(created_at) = 24)
);

CREATE UNIQUE INDEX ux_event_timeline_article
    ON event_timeline_items(event_id, article_id)
    WHERE article_id IS NOT NULL;

CREATE INDEX ix_event_timeline_event
    ON event_timeline_items(event_id, recognized_at DESC);

CREATE INDEX ix_event_timeline_key
    ON event_timeline_items(event_id, is_key, published_at DESC);

CREATE TABLE event_relations (
    id                        TEXT    PRIMARY KEY NOT NULL,
    source_event_id           TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    target_event_id           TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    relation_type             TEXT    NOT NULL
                                      CHECK (relation_type IN ('related_to','follows','caused_by',
                                                               'part_of','same_topic','contradicts')),
    confidence                REAL    NOT NULL DEFAULT 0.4
                                      CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status                    TEXT    NOT NULL DEFAULT 'candidate'
                                      CHECK (status IN ('candidate','confirmed','rejected')),
    rationale                 TEXT,
    evidence_article_ids_json TEXT    NOT NULL DEFAULT '[]',
    actor                     TEXT    NOT NULL DEFAULT 'algorithm'
                                      CHECK (actor IN ('algorithm','manual')),
    algorithm_version         TEXT    NOT NULL DEFAULT 'event-relation-v1',
    created_at                TEXT    NOT NULL,
    updated_at                TEXT    NOT NULL,
    CHECK (source_event_id <> target_event_id),
    CHECK (rationale IS NULL OR length(rationale) <= 1000),
    CHECK (length(evidence_article_ids_json) <= 8000),
    CHECK (length(algorithm_version) BETWEEN 1 AND 64),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (updated_at >= created_at),
    UNIQUE (source_event_id, target_event_id, relation_type)
);

CREATE INDEX ix_event_relations_source
    ON event_relations(source_event_id);

CREATE INDEX ix_event_relations_target
    ON event_relations(target_event_id);

CREATE INDEX ix_event_relations_status
    ON event_relations(status);

CREATE TABLE event_score_snapshots (
    id                 TEXT    PRIMARY KEY NOT NULL,
    event_id           TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    algorithm_version  TEXT    NOT NULL,
    scored_at          TEXT    NOT NULL,
    importance_score   REAL    NOT NULL CHECK (importance_score >= 0 AND importance_score <= 100),
    heat_score         REAL    NOT NULL CHECK (heat_score >= 0 AND heat_score <= 100),
    freshness_score    REAL    NOT NULL CHECK (freshness_score >= 0 AND freshness_score <= 100),
    coverage_score     REAL    NOT NULL CHECK (coverage_score >= 0 AND coverage_score <= 100),
    confidence_score   REAL    NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
    total_score        REAL    NOT NULL CHECK (total_score >= 0 AND total_score <= 100),
    inputs_json        TEXT    NOT NULL,
    explanation_json   TEXT    NOT NULL,
    is_current         INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    created_at         TEXT    NOT NULL,
    CHECK (length(algorithm_version) BETWEEN 1 AND 64),
    CHECK (length(inputs_json) <= 8000),
    CHECK (length(explanation_json) <= 12000),
    CHECK (length(scored_at) = 24),
    CHECK (length(created_at) = 24)
);

CREATE UNIQUE INDEX ux_event_score_current
    ON event_score_snapshots(event_id)
    WHERE is_current = 1;

CREATE INDEX ix_event_score_event
    ON event_score_snapshots(event_id, scored_at DESC);

CREATE INDEX ix_event_score_total
    ON event_score_snapshots(is_current, total_score DESC);

CREATE INDEX ix_event_score_heat
    ON event_score_snapshots(is_current, heat_score DESC);

CREATE INDEX ix_event_score_confidence
    ON event_score_snapshots(is_current, confidence_score DESC);

CREATE TABLE event_cluster_runs (
    id                   TEXT    PRIMARY KEY NOT NULL,
    trigger_type         TEXT    NOT NULL CHECK (trigger_type IN ('manual','retry')),
    scope                TEXT    NOT NULL CHECK (scope IN ('incremental','full','selected')),
    status               TEXT    NOT NULL
                                 CHECK (status IN ('pending','running','succeeded',
                                                   'partially_succeeded','failed','cancelled')),
    requested_count      INTEGER NOT NULL DEFAULT 0 CHECK (requested_count >= 0),
    processed_count      INTEGER NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
    attached_count       INTEGER NOT NULL DEFAULT 0 CHECK (attached_count >= 0),
    created_event_count  INTEGER NOT NULL DEFAULT 0 CHECK (created_event_count >= 0),
    updated_event_count  INTEGER NOT NULL DEFAULT 0 CHECK (updated_event_count >= 0),
    candidate_pair_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_pair_count >= 0),
    ambiguous_count      INTEGER NOT NULL DEFAULT 0 CHECK (ambiguous_count >= 0),
    llm_called_count     INTEGER NOT NULL DEFAULT 0 CHECK (llm_called_count >= 0),
    llm_accepted_count   INTEGER NOT NULL DEFAULT 0 CHECK (llm_accepted_count >= 0),
    skipped_count        INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    failed_count         INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    use_llm              INTEGER NOT NULL DEFAULT 0 CHECK (use_llm IN (0,1)),
    article_ids_json     TEXT    NOT NULL DEFAULT '[]',
    model_name           TEXT,
    error_message        TEXT,
    cancel_requested     INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    started_at           TEXT,
    finished_at          TEXT,
    duration_ms          INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL,
    CHECK (error_message IS NULL OR length(error_message) <= 1000),
    CHECK (length(article_ids_json) <= 60000),
    CHECK (model_name IS NULL OR length(model_name) BETWEEN 1 AND 200),
    CHECK (started_at IS NULL OR length(started_at) = 24),
    CHECK (finished_at IS NULL OR length(finished_at) = 24),
    CHECK (length(created_at) = 24),
    CHECK (length(updated_at) = 24),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CHECK (updated_at >= created_at)
);

CREATE INDEX ix_event_cluster_runs_created
    ON event_cluster_runs(created_at DESC, id);

CREATE INDEX ix_event_cluster_runs_status
    ON event_cluster_runs(status, created_at DESC);

CREATE TABLE event_candidate_decisions (
    id                 TEXT    PRIMARY KEY NOT NULL,
    run_id             TEXT    REFERENCES event_cluster_runs(id) ON DELETE SET NULL,
    article_id         TEXT    NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    candidate_event_id TEXT    REFERENCES events(id) ON DELETE SET NULL,
    decision           TEXT    NOT NULL
                               CHECK (decision IN ('attached','created','ambiguous','skipped',
                                                   'llm_rejected','llm_accepted','manual_resolved')),
    score              REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    reasons_json       TEXT    NOT NULL DEFAULT '[]',
    method             TEXT    NOT NULL DEFAULT 'similarity'
                               CHECK (method IN ('rules','similarity','llm','manual')),
    llm_used           INTEGER NOT NULL DEFAULT 0 CHECK (llm_used IN (0,1)),
    status             TEXT    NOT NULL DEFAULT 'resolved'
                               CHECK (status IN ('pending','resolved','ignored')),
    created_at         TEXT    NOT NULL,
    resolved_at        TEXT,
    CHECK (length(reasons_json) <= 4000),
    CHECK (length(created_at) = 24),
    CHECK (resolved_at IS NULL OR length(resolved_at) = 24)
);

CREATE INDEX ix_event_decisions_run
    ON event_candidate_decisions(run_id);

CREATE INDEX ix_event_decisions_state
    ON event_candidate_decisions(decision, status, created_at DESC);

CREATE INDEX ix_event_decisions_article
    ON event_candidate_decisions(article_id, created_at DESC);

CREATE TABLE event_audit_log (
    id          TEXT    PRIMARY KEY NOT NULL,
    event_id    TEXT    REFERENCES events(id) ON DELETE SET NULL,
    entity_id   TEXT    REFERENCES entities(id) ON DELETE SET NULL,
    action      TEXT    NOT NULL
                        CHECK (action IN ('create_event','merge_events','unmerge_events',
                                          'split_event',
                                          'attach_article','detach_article','rename_event',
                                          'recategorize_event','change_status','add_timeline_note',
                                          'confirm_event','create_relation','update_relation',
                                          'merge_entities','unmerge_entities','resolve_candidate',
                                          'entity_metadata')),
    actor       TEXT    NOT NULL DEFAULT 'user' CHECK (actor IN ('user','algorithm')),
    detail_json TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    CHECK (length(detail_json) <= 12000),
    CHECK (length(created_at) = 24)
);

CREATE INDEX ix_event_audit_event
    ON event_audit_log(event_id, created_at DESC);

CREATE INDEX ix_event_audit_entity
    ON event_audit_log(entity_id, created_at DESC);

CREATE INDEX ix_event_audit_created
    ON event_audit_log(created_at DESC);
