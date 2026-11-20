"""Real-database tests for Phase 1 repositories and constraints.

No mocks: every assertion uses a real SQLite file under `tmp_path`.
"""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

import database
from core.timeutil import utc_timestamp
from database import connect, database_path, initialize
from database.repositories import source_category_repository as categories
from database.repositories import article_repository as articles
from database.repositories import source_repository as sources

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture()
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(target))
    status = initialize()
    assert status.status == "ok", status
    return Path(os.path.realpath(target))


def _new_category(conn: sqlite3.Connection, name: str = "Tech") -> str:
    category_id = str(uuid.uuid4())
    now = utc_timestamp()
    categories.insert(
        conn,
        category_id=category_id,
        name=name,
        description=None,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    return category_id


def _new_source(
    conn: sqlite3.Connection,
    *,
    url: str,
    category_id: str | None = None,
    name: str = "Example",
    enabled: int = 1,
    language: str | None = None,
) -> str:
    source_id = str(uuid.uuid4())
    now = utc_timestamp()
    sources.insert(
        conn,
        {
            "id": source_id,
            "category_id": category_id,
            "name": name,
            "source_type": "rss",
            "url": url,
            "homepage_url": None,
            "description": None,
            "language": language,
            "country": None,
            "priority": 10,
            "credibility_score": None,
            "fetch_interval_minutes": 60,
            "enabled": enabled,
            "health_status": "unknown",
            "created_at": now,
            "updated_at": now,
        },
    )
    return source_id


def test_migration_creates_tables_and_indexes(ready: Path) -> None:
    conn = connect(database_path())
    try:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        indexes = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        conn.close()

    assert tables == {
        "schema_migrations",
        "app_meta",
        "source_categories",
        "sources",
        "articles",
        "source_fetch_state",
        "collection_jobs",
        "collection_job_items",
        "source_health_logs",
        "source_adapter_configs",
        "ai_model_registry",
        "ai_runs",
        "ai_run_items",
        "article_ai_analysis",
        "article_embeddings",
        "entities",
        "entity_aliases",
        "article_entities",
        "events",
        "event_articles",
        "event_article_exclusions",
        "event_entities",
        "event_timeline_items",
        "event_relations",
        "event_score_snapshots",
        "event_cluster_runs",
        "event_candidate_decisions",
        "event_audit_log",
        "intelligence_reports",
        "intelligence_report_citations",
        "pipeline_settings",
        "pipeline_runs",
        "pipeline_tasks",
        "pipeline_task_logs",
        "interest_profiles",
        "interests",
        "interest_keywords",
        "interest_entity_links",
        "interest_source_links",
        "blocked_sources",
        "recommendation_feedback",
        "recommendation_results",
        "daily_digests",
        "daily_digest_items",
        "articles_fts",
        "articles_fts_config",
        "articles_fts_content",
        "articles_fts_data",
        "articles_fts_docsize",
        "articles_fts_idx",
    }
    assert version >= 6
    assert fk == 1
    assert {
        "ux_source_categories_name_active",
        "ix_source_categories_sort",
        "ux_sources_url_active",
        "ix_sources_list",
        "ix_sources_category_active",
        "ix_sources_priority_active",
        "ux_articles_source_external",
        "ux_articles_source_canonical",
        "ux_collection_job_items_running",
    } <= indexes


def test_category_crud_soft_delete_and_timestamp_format(ready: Path) -> None:
    with database.session() as conn:
        category_id = _new_category(conn, "AI 与科技")

    with database.read_session() as conn:
        record = categories.get_active(conn, category_id)
        items, total = categories.list_categories(conn, limit=20, offset=0)
    assert record is not None
    assert record.name == "AI 与科技"
    assert TS_RE.match(record.created_at)
    assert total == 1 and items[0].source_count == 0

    with database.session() as conn:
        categories.update(conn, category_id, {"name": "AI", "updated_at": utc_timestamp()})
    with database.read_session() as conn:
        updated = categories.get_active(conn, category_id)
    assert updated is not None and updated.name == "AI"

    with database.session() as conn:
        categories.soft_delete(conn, category_id, utc_timestamp())
    with database.read_session() as conn:
        assert categories.get_active(conn, category_id) is None
        assert categories.list_categories(conn, limit=20, offset=0)[1] == 0


def test_category_name_unique_only_for_active_rows(ready: Path) -> None:
    with database.session() as conn:
        first = _new_category(conn, "News")
    with pytest.raises(sqlite3.IntegrityError):
        with database.session() as conn:
            _new_category(conn, "News")

    with database.session() as conn:
        categories.soft_delete(conn, first, utc_timestamp())
        second = _new_category(conn, "News")

    with database.read_session() as conn:
        assert categories.get_active(conn, second) is not None


def test_source_crud_filters_and_soft_delete(ready: Path) -> None:
    with database.session() as conn:
        category_id = _new_category(conn, "Tech")
        first = _new_source(conn, url="https://example.com/feed.xml", category_id=category_id)
        _new_source(conn, url="https://other.example/feed", name="Other", enabled=0)

    with database.read_session() as conn:
        items, total = sources.list_sources(conn, limit=20, offset=0)
        only_enabled, enabled_total = sources.list_sources(
            conn, limit=20, offset=0, enabled=True
        )
        by_category, category_total = sources.list_sources(
            conn, limit=20, offset=0, category_id=category_id
        )
        by_keyword, keyword_total = sources.list_sources(
            conn, limit=20, offset=0, keyword="Exa"
        )
    assert total == 2
    assert enabled_total == 1 and only_enabled[0].id == first
    assert category_total == 1 and by_category[0].category_name == "Tech"
    assert keyword_total == 1

    with database.session() as conn:
        sources.soft_delete(conn, first, utc_timestamp())
    with database.read_session() as conn:
        assert sources.get_active(conn, first) is None
        assert sources.list_sources(conn, limit=20, offset=0)[1] == 1


def test_source_url_unique_only_for_active_rows(ready: Path) -> None:
    with database.session() as conn:
        first = _new_source(conn, url="https://example.com/feed.xml")
    with pytest.raises(sqlite3.IntegrityError):
        with database.session() as conn:
            _new_source(conn, url="https://example.com/feed.xml")

    with database.session() as conn:
        sources.soft_delete(conn, first, utc_timestamp())
        second = _new_source(conn, url="https://example.com/feed.xml")
    with database.read_session() as conn:
        assert sources.get_active(conn, second) is not None


def test_foreign_key_references_and_category_clear(ready: Path) -> None:
    with database.session() as conn:
        category_id = _new_category(conn, "Tech")
        source_id = _new_source(conn, url="https://example.com/feed.xml", category_id=category_id)

    with pytest.raises(sqlite3.IntegrityError):
        with database.session() as conn:
            _new_source(conn, url="https://bad.example/feed", category_id=str(uuid.uuid4()))

    with database.session() as conn:
        categories.clear_category_on_sources(conn, category_id, utc_timestamp())
        categories.soft_delete(conn, category_id, utc_timestamp())
    with database.read_session() as conn:
        record = sources.get_active(conn, source_id)
    assert record is not None and record.category_id is None


def test_check_constraints_reject_invalid_rows(ready: Path) -> None:
    with database.session() as conn:
        category_id = _new_category(conn, "Tech")

    with pytest.raises(sqlite3.IntegrityError):
        with database.session() as conn:
            sources.insert(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "category_id": category_id,
                    "name": "Bad priority",
                    "source_type": "rss",
                    "url": "https://example.com/bad",
                    "homepage_url": None,
                    "description": None,
                    "language": None,
                    "country": None,
                    "priority": 101,
                    "credibility_score": None,
                    "fetch_interval_minutes": 60,
                    "enabled": 1,
                    "health_status": "unknown",
                    "created_at": utc_timestamp(),
                    "updated_at": utc_timestamp(),
                },
            )

    with pytest.raises(sqlite3.IntegrityError):
        with database.session() as conn:
            categories.insert(
                conn,
                category_id=str(uuid.uuid4()),
                name="Bad timestamp",
                description=None,
                sort_order=0,
                created_at="2026-11-16T00:00:00Z",
                updated_at="2026-11-16T00:00:00Z",
            )


def test_read_session_is_query_only(ready: Path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        with database.read_session() as conn:
            conn.execute(
                "INSERT INTO app_meta (key, value, updated_at) VALUES ('x','y',?)",
                (utc_timestamp(),),
            )


def test_list_filters_by_language_and_counts_active_articles(ready: Path) -> None:
    now = utc_timestamp()
    with database.session() as conn:
        zh = _new_source(
            conn, url="https://example.com/zh.xml", name="中文源", language="zh"
        )
        _new_source(conn, url="https://example.com/en.xml", name="English", language="en")
        articles.insert(
            conn,
            {
                "id": str(uuid.uuid4()),
                "source_id": zh,
                "external_id": "zh-1",
                "canonical_url": "https://example.com/zh/1",
                "original_url": "https://example.com/zh/1",
                "title": "中文文章",
                "author": None,
                "summary": "摘要",
                "content_text": "正文",
                "content_state": "full",
                "published_at": now,
                "source_updated_at": None,
                "fetched_at": now,
                "content_hash": uuid.uuid4().hex * 2,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )

    with database.read_session() as conn:
        rows, total = sources.list_sources(conn, limit=10, offset=0, language="zh")

    assert total == 1
    assert len(rows) == 1
    assert rows[0].language == "zh"
    assert rows[0].article_count == 1
