"""Schema v4 → v5 migration tests (AI tables, seeds, cloud guard)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import database
from database import migrator

STAMP = "2026-11-16T09:00:00.000Z"


def _build_v4_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = database.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        migrator.bootstrap(conn)
        for migration in migrator.discover_migrations():
            if migration.version > 4:
                break
            migrator._apply_one(conn, migration)
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES ('src-1', NULL, 'Phase 2 Feed', 'rss', 'https://example.com/feed',
                      NULL, NULL, 'en', NULL, 5, NULL, 60, 1, 'unknown', ?, ?)
            """,
            (STAMP, STAMP),
        )
        conn.execute(
            """
            INSERT INTO articles (
                id, source_id, external_id, canonical_url, original_url, title,
                author, summary, content_text, content_state, published_at,
                source_updated_at, fetched_at, content_hash, status,
                created_at, updated_at
            ) VALUES ('a-1', 'src-1', 'ext-1', 'https://example.com/1',
                      'https://example.com/1', '保留了标题', NULL, NULL, '正文',
                      'full', ?, NULL, ?, ?, 'active', ?, ?)
            """,
            (STAMP, STAMP, "a" * 64, STAMP, STAMP),
        )
        conn.execute(
            """
            INSERT INTO collection_jobs (
                id, trigger_type, scope, status, requested_source_count,
                processed_source_count, succeeded_source_count, failed_source_count,
                discovered_count, inserted_count, updated_count, duplicate_count,
                error_count, error_message, cancel_requested, started_at, finished_at,
                duration_ms, created_at, updated_at
            ) VALUES ('job-1', 'manual', 'single_source', 'succeeded', 1, 1, 1, 0,
                      1, 1, 0, 0, 0, NULL, 0, ?, ?, 10, ?, ?)
            """,
            (STAMP, STAMP, STAMP, STAMP),
        )
        conn.commit()
    finally:
        conn.close()


def test_v4_upgrades_to_v5_and_preserves_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(data_dir))
    db_path = data_dir / "pih.sqlite3"
    _build_v4_database(db_path)

    status = database.initialize()
    assert status.status == "ok"
    assert status.schema_version >= 6

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
        assert conn.execute("SELECT title FROM articles WHERE id='a-1'").fetchone()[0] == "保留了标题"
        assert conn.execute("SELECT COUNT(*) FROM collection_jobs").fetchone()[0] == 1

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "ai_model_registry",
            "ai_runs",
            "ai_run_items",
            "article_ai_analysis",
            "article_embeddings",
        } <= tables

        seed = {
            row["model_name"]: (int(row["enabled"]), row["num_ctx"])
            for row in conn.execute(
                "SELECT model_name, enabled, num_ctx FROM ai_model_registry"
            )
        }
        assert seed["qwen3.5:4b-mlx"] == (1, 4096)
        assert seed["qwen3:1.7b"] == (0, 4096)
        assert seed["gemma3:4b"] == (0, 4096)

        # Database-level guard: cloud models can never be registered.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ai_model_registry (
                    model_name, num_ctx, roles, enabled, created_at, updated_at
                ) VALUES ('bad:1b-cloud', 4096, 'summary', 0, ?, ?)
                """,
                (STAMP, STAMP),
            )
        conn.rollback()

        # Foreign keys still work for the new item table.
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ai_run_items (
                    id, run_id, article_id, status, attempts, created_at, updated_at
                ) VALUES ('i-1', 'missing-run', 'a-1', 'pending', 0, ?, ?)
                """,
                (STAMP, STAMP),
            )
    finally:
        conn.close()


def test_repeated_initialize_keeps_schema_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    assert database.initialize().schema_version >= 6
    assert database.initialize().schema_version >= 6
    conn = sqlite3.connect(tmp_path / "data" / "pih.sqlite3")
    try:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 6
        assert conn.execute("SELECT COUNT(*) FROM article_embeddings").fetchone()[0] == 0
    finally:
        conn.close()
