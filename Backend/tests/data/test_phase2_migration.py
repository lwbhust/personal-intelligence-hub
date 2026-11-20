"""Phase 2 migration tests: v3 → v4 must preserve Phase 1 data."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import database
from database import migrator

STAMP = "2026-11-16T08:00:00.000Z"


def _build_v3_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = database.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        migrator.bootstrap(conn)
        for migration in migrator.discover_migrations():
            if migration.version > 3:
                break
            migrator._apply_one(conn, migration)
        conn.execute(
            """
            INSERT INTO source_categories (id, name, description, sort_order, created_at, updated_at)
            VALUES ('cat-1', '技术', NULL, 0, ?, ?)
            """,
            (STAMP, STAMP),
        )
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES ('src-1', 'cat-1', 'Phase 1 Feed', 'rss', 'https://example.com/feed',
                      NULL, NULL, 'en', NULL, 5, NULL, 60, 1, 'unknown', ?, ?)
            """,
            (STAMP, STAMP),
        )
        conn.commit()
    finally:
        conn.close()


def test_v3_database_upgrades_and_keeps_phase1_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(data_dir))
    db_path = data_dir / "pih.sqlite3"
    _build_v3_database(db_path)

    status = database.initialize()
    assert status.status == "ok"
    assert status.schema_version >= 6

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("SELECT COUNT(*) FROM source_categories").fetchone()[0] == 1
        source = conn.execute("SELECT * FROM sources WHERE id='src-1'").fetchone()
        assert source is not None
        assert source["name"] == "Phase 1 Feed"
        assert source["category_id"] == "cat-1"

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"articles", "collection_jobs", "collection_job_items",
                "source_health_logs", "source_fetch_state"} <= tables

        # Foreign keys are active and point at the preserved source row.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO articles (
                id, source_id, title, content_state, fetched_at, content_hash,
                status, created_at, updated_at
            ) VALUES ('a1', 'src-1', 'First', 'unavailable', ?, ?, 'active', ?, ?)
            """,
            (STAMP, "a" * 64, STAMP, STAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO articles (
                    id, source_id, title, content_state, fetched_at, content_hash,
                    status, created_at, updated_at
                ) VALUES ('a2', 'missing', 'Bad', 'unavailable', ?, ?, 'active', ?, ?)
                """,
                (STAMP, "b" * 64, STAMP, STAMP),
            )
        conn.rollback()
        conn.execute("PRAGMA foreign_keys = OFF")
        # Only the valid row from this test may exist; rollback dropped it.
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_repeated_initialize_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    first = database.initialize()
    second = database.initialize()
    assert first.schema_version >= 6
    assert second.schema_version >= 6

    conn = sqlite3.connect(tmp_path / "data" / "pih.sqlite3")
    try:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 6
    finally:
        conn.close()


def test_checksum_tampering_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    assert database.initialize().status == "ok"
    db_path = tmp_path / "data" / "pih.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=4")
        conn.commit()
    finally:
        conn.close()

    status = database.initialize()
    assert status.status == "error"
    assert status.code == database.DATABASE_SCHEMA_ERROR
