"""Real-database tests for the Phase 0 SQLite data layer.

No mocks: every assertion inspects a real SQLite file under `tmp_path`.
Run with:
    cd "…/Personal Intelligence Hub/Backend" && .venv/bin/python -m pytest tests/data -q
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from database import (
    ALLOWED_CODES,
    DatabaseError,
    database_path,
    get_meta,
    health_check,
    initialize,
    migrator,
    path_kind,
    session,
    set_meta,
)
from database.connection import connect

UTC_SECONDS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `PIH_DATA_DIR` at a real, empty temporary directory."""

    target = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(target))
    return Path(os.path.realpath(target))


def _table_names() -> set[str]:
    conn = connect(database_path())
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row["name"]) for row in rows}


def test_initialize_creates_real_database_file(data_dir: Path) -> None:
    status = initialize()

    assert status.status == "ok"
    assert status.schema_version >= 6
    assert status.code is None
    assert status.path_kind == "custom"
    assert path_kind() == "custom"

    db_file = database_path()
    assert db_file == data_dir / "pih.sqlite3"
    assert db_file.is_file()
    assert db_file.stat().st_size > 0
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(db_file.stat().st_mode) == 0o600
    assert _table_names() == {
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


def test_migration_records_all_versions(data_dir: Path) -> None:
    assert initialize().status == "ok"

    conn = connect(database_path())
    try:
        rows = conn.execute(
            "SELECT version, applied_at, checksum FROM schema_migrations "
            "ORDER BY version"
        ).fetchall()
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    assert len(rows) >= 6
    assert [row["version"] for row in rows] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    assert UTC_SECONDS_RE.match(str(rows[0]["applied_at"]))
    expected_checksum = hashlib.sha256(
        (migrator.MIGRATIONS_DIR / "0001_init.sql").read_bytes()
    ).hexdigest()
    assert rows[0]["checksum"] == expected_checksum
    assert HEX_SHA256_RE.match(str(rows[0]["checksum"]))
    assert str(journal_mode).lower() == "wal"


def test_connection_level_pragmas(data_dir: Path) -> None:
    assert initialize().status == "ok"

    conn = connect(database_path())
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    finally:
        conn.close()


def test_app_meta_roundtrip(data_dir: Path) -> None:
    assert initialize().status == "ok"

    assert get_meta("phase0.check") is None
    set_meta("phase0.check", "ready")
    assert get_meta("phase0.check") == "ready"

    set_meta("phase0.check", "updated")
    assert get_meta("phase0.check") == "updated"

    with session() as conn:
        row = conn.execute(
            "SELECT value, updated_at FROM app_meta WHERE key = ?",
            ("phase0.check",),
        ).fetchone()
    assert row is not None
    assert row["value"] == "updated"
    assert UTC_SECONDS_RE.match(str(row["updated_at"]))


def test_session_rolls_back_on_exception(data_dir: Path) -> None:
    assert initialize().status == "ok"

    with pytest.raises(RuntimeError):
        with session() as conn:
            conn.execute(
                "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("rollback.key", "must-not-persist", "2026-11-16T00:00:00Z"),
            )
            assert conn.execute(
                "SELECT COUNT(*) FROM app_meta WHERE key = ?", ("rollback.key",)
            ).fetchone()[0] == 1
            raise RuntimeError("boom")

    assert get_meta("rollback.key") is None


def test_initialize_is_idempotent(data_dir: Path) -> None:
    first = initialize()
    second = initialize()

    assert first.status == "ok"
    assert second.status == "ok"
    assert second.schema_version >= 6

    conn = connect(database_path())
    try:
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]
    finally:
        conn.close()
    assert count >= 6
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]


def test_unwritable_data_dir_returns_error_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    monkeypatch.setenv("PIH_DATA_DIR", str(readonly / "nested"))
    try:
        status = initialize()
    finally:
        readonly.chmod(0o700)

    assert status.status == "error"
    assert status.schema_version is None
    assert status.code in ALLOWED_CODES
    assert status.code == "database_unavailable"
    assert status.path_kind == "custom"


def test_checksum_mismatch_returns_schema_error(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations_copy = tmp_path / "migrations"
    shutil.copytree(migrator.MIGRATIONS_DIR, migrations_copy)
    monkeypatch.setattr(migrator, "MIGRATIONS_DIR", migrations_copy)

    assert initialize().status == "ok"

    migration_file = migrations_copy / "0001_init.sql"
    migration_file.write_text(
        migration_file.read_text(encoding="utf-8") + "\n-- tampered after apply\n",
        encoding="utf-8",
    )

    status = initialize()
    assert status.status == "error"
    assert status.code == "database_schema_error"
    assert status.schema_version is None


def test_missing_applied_migration_returns_schema_error(data_dir: Path) -> None:
    assert initialize().status == "ok"

    conn = connect(database_path())
    try:
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, checksum) "
            "VALUES (?, ?, ?)",
            (99, "2026-11-16T00:00:00Z", "0" * 64),
        )
    finally:
        conn.close()

    status = initialize()
    assert status.status == "error"
    assert status.code == "database_schema_error"


def test_failed_migration_rolls_back(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations_copy = tmp_path / "broken-migrations"
    migrations_copy.mkdir()
    shutil.copy2(
        migrator.MIGRATIONS_DIR / "0001_init.sql",
        migrations_copy / "0001_init.sql",
    )
    (migrations_copy / "0002_broken.sql").write_text(
        "CREATE TABLE half_done (id TEXT);\n"
        "INSERT INTO missing_table (id) VALUES ('x');\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrator, "MIGRATIONS_DIR", migrations_copy)

    status = initialize()
    assert status.status == "error"
    assert status.code == "database_migration_failed"
    assert status.schema_version is None

    conn = connect(database_path())
    try:
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()
    assert versions == [1]
    assert tables == {"schema_migrations", "app_meta"}


def test_health_check_ok_then_missing_database(data_dir: Path) -> None:
    missing = health_check()
    assert missing.status == "error"
    assert missing.code == "database_unavailable"
    assert missing.schema_version is None
    assert missing.path_kind == "custom"

    assert initialize().status == "ok"
    healthy = health_check()
    assert healthy.status == "ok"
    assert healthy.schema_version >= 6
    assert healthy.code is None


def test_relative_data_dir_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIH_DATA_DIR", "relative-data-dir")

    status = initialize()

    assert status.status == "error"
    assert status.code == "database_unavailable"
    assert status.schema_version is None
    assert status.path_kind == "custom"


def test_session_requires_initialized_database(data_dir: Path) -> None:
    with pytest.raises(DatabaseError) as excinfo:
        with session():
            pass
    assert excinfo.value.code == "database_unavailable"


def test_data_persists_across_process_restart(data_dir: Path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PIH_DATA_DIR"] = str(data_dir)

    writer = (
        "from database import initialize, set_meta\n"
        "status = initialize()\n"
        "assert status.status == 'ok', status\n"
        "set_meta('restart.check', 'written')\n"
    )
    subprocess.run(
        [sys.executable, "-c", writer],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    reader = (
        "from database import get_meta, initialize\n"
        "status = initialize()\n"
        "assert status.status == 'ok', status\n"
        "assert status.schema_version >= 6\n"
        "print(get_meta('restart.check'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", reader],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "written"
