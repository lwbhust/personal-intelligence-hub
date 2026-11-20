"""Migration 0013: automation stays opt-in for existing databases.

Every assertion runs against a real SQLite file; the migration SQL is the exact
file shipped in `Backend/database/migrations/`.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from database import database_path, initialize, migrator


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(target))
    return Path(os.path.realpath(target))


def _automation_enabled(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT automation_enabled FROM pipeline_settings WHERE id = 1"
    ).fetchone()
    return int(row[0])


def _apply_0013(conn: sqlite3.Connection) -> None:
    sql = (migrator.MIGRATIONS_DIR / "0013_automation_default.sql").read_text(
        encoding="utf-8"
    )
    for statement in migrator._split_statements(sql):
        conn.execute(statement)


def test_fresh_database_enables_automation(data_dir: Path) -> None:
    status = initialize()

    assert status.status == "ok"
    assert status.schema_version >= 13

    conn = sqlite3.connect(str(database_path()))
    try:
        assert _automation_enabled(conn) == 1
    finally:
        conn.close()


def _minimal_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pipeline_settings (
            id INTEGER PRIMARY KEY,
            automation_enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE articles (id TEXT PRIMARY KEY);
        CREATE TABLE pipeline_tasks (id TEXT PRIMARY KEY);
        INSERT INTO pipeline_settings (id, automation_enabled, updated_at)
        VALUES (1, 0, '2026-11-18T00:00:00.000Z');
        """
    )
    return conn


def test_empty_database_guard_flips_to_enabled() -> None:
    conn = _minimal_conn()
    try:
        _apply_0013(conn)
        assert _automation_enabled(conn) == 1
    finally:
        conn.close()


def test_database_with_articles_is_untouched() -> None:
    conn = _minimal_conn()
    try:
        conn.execute("INSERT INTO articles (id) VALUES ('a1')")
        _apply_0013(conn)
        assert _automation_enabled(conn) == 0
    finally:
        conn.close()


def test_database_with_pipeline_tasks_is_untouched() -> None:
    conn = _minimal_conn()
    try:
        conn.execute("INSERT INTO pipeline_tasks (id) VALUES ('t1')")
        _apply_0013(conn)
        assert _automation_enabled(conn) == 0
    finally:
        conn.close()
