"""Real backup/restore tests for Phase 1.

These exercise the online backup API, integrity verification, retention and
rollback on a temporary database. They are NOT the full >=20 GiB restore
drill required for phase exit (see Docs/PHASE1_DATABASE_DESIGN.md §7.2).
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import pytest

import database
from core.timeutil import utc_timestamp
from database import backup, connect, database_path, initialize
from database.repositories import source_category_repository as categories
from database.repositories import source_repository as sources


@pytest.fixture()
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(target))
    assert initialize().status == "ok"
    return Path(os.path.realpath(target))


def _seed() -> tuple[str, str]:
    with database.session() as conn:
        category_id = str(uuid.uuid4())
        now = utc_timestamp()
        categories.insert(
            conn,
            category_id=category_id,
            name="Tech",
            description=None,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        source_id = str(uuid.uuid4())
        sources.insert(
            conn,
            {
                "id": source_id,
                "category_id": category_id,
                "name": "Backup Source",
                "source_type": "rss",
                "url": "https://example.com/feed.xml",
                "homepage_url": None,
                "description": None,
                "language": None,
                "country": None,
                "priority": 10,
                "credibility_score": None,
                "fetch_interval_minutes": 60,
                "enabled": 1,
                "health_status": "unknown",
                "created_at": now,
                "updated_at": now,
            },
        )
    return category_id, source_id


def _counts() -> tuple[int, int]:
    with database.read_session() as conn:
        category_count = conn.execute(
            "SELECT COUNT(*) FROM source_categories WHERE deleted_at IS NULL"
        ).fetchone()[0]
        source_count = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE deleted_at IS NULL"
        ).fetchone()[0]
    return int(category_count), int(source_count)


def test_backup_creates_verified_file_and_metadata(ready: Path) -> None:
    _seed()
    info = backup.create_backup("manual")

    path = backup.backup_dir() / str(info["filename"])
    assert path.is_file()
    assert info["integrity_ok"] is True
    assert info["schema_version"] >= 6
    assert int(info["size_bytes"]) > 0
    assert len(str(info["sha256"])) == 64

    meta = path.with_suffix(path.suffix + ".json")
    assert meta.is_file()
    assert (os.stat(path).st_mode & 0o777) == 0o600
    assert (os.stat(backup.backup_dir()).st_mode & 0o777) == 0o700

    listed = backup.list_backups()
    assert [item["filename"] for item in listed] == [info["filename"]]


def test_restore_brings_data_back_and_keeps_safety_backup(ready: Path) -> None:
    category_id, source_id = _seed()
    info = backup.create_backup("manual")

    with database.session() as conn:
        sources.soft_delete(conn, source_id, utc_timestamp())
        categories.soft_delete(conn, category_id, utc_timestamp())
    assert _counts() == (0, 0)

    result = backup.restore_backup(str(info["filename"]))
    assert result["verified"] is True
    assert result["schema_version"] >= 6
    assert _counts() == (1, 1)

    safety = backup.backup_dir() / str(result["safety_backup"])
    assert safety.is_file()
    assert (os.stat(database_path()).st_mode & 0o777) == 0o600


def test_restore_rejects_unknown_or_unsafe_names(ready: Path) -> None:
    _seed()
    for name in ("../pih.sqlite3", "pih-nope.sqlite3", "evil.sqlite3"):
        with pytest.raises(backup.BackupError) as excinfo:
            backup.restore_backup(name)
        assert excinfo.value.code == "invalid_name"


def test_restore_rejects_corrupt_backup(ready: Path) -> None:
    _seed()
    backup.create_backup("manual")
    directory = backup.backup_dir()
    corrupt = directory / "pih-20260101T000000000000Z-corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    os.chmod(corrupt, 0o600)

    with pytest.raises(backup.BackupError) as excinfo:
        backup.restore_backup(corrupt.name)
    assert excinfo.value.code == "backup_corrupt"


def test_restore_aborts_when_database_is_locked(ready: Path) -> None:
    info = backup.create_backup("manual")
    writer = connect(database_path())
    try:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(backup.BackupError) as excinfo:
            backup.restore_backup(str(info["filename"]))
        assert excinfo.value.code == "database_in_use"
    finally:
        if writer.in_transaction:
            writer.execute("ROLLBACK")
        writer.close()


def test_backup_refuses_low_disk(ready: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    class Usage:
        free = 1024

    monkeypatch.setattr(shutil, "disk_usage", lambda _path: Usage())
    _seed()
    with pytest.raises(backup.BackupError) as excinfo:
        backup.create_backup("manual")
    assert excinfo.value.code == "insufficient_space"


def test_restore_rejects_newer_schema_backup(ready: Path) -> None:
    info = backup.create_backup("manual")
    path = backup.backup_dir() / str(info["filename"])
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
            (999, "2026-11-16T00:00:00Z", "0" * 64),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(backup.BackupError) as excinfo:
        backup.restore_backup(str(info["filename"]))
    assert excinfo.value.code == "backup_schema_newer"
