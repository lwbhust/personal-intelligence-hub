"""Migration 0014 adds the body-fetch timestamp without touching user data."""

from __future__ import annotations

import sqlite3

from database import database_path, initialize


def _columns(path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(articles)")]
    finally:
        conn.close()


def test_schema_has_content_fetched_at(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    status = initialize()
    assert status.status == "ok"
    assert status.schema_version >= 14
    assert "content_fetched_at" in _columns(database_path())


def test_reinitializing_keeps_migration_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    first = initialize()
    assert first.status == "ok"
    second = initialize()
    assert second.status == "ok"
    assert second.schema_version == first.schema_version
