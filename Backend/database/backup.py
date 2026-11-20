"""Consistent SQLite backup and restore for Phase 1.

Design rules (Docs/PHASE1_DATABASE_DESIGN.md §7):
- use the SQLite online backup API, never a raw copy of the main file;
- verify `integrity_check` on every backup before declaring success;
- refuse to proceed when free disk is below a safe margin;
- keep a safety backup of the current database before replacing it;
- never destroy the only copy: replace via a verified temporary file, and roll
  back to the safety copy if the restored database fails verification.

Restore expects the Sidecar to be stopped; a locked database aborts the restore.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import database_path, resolve_data_dir
from .connection import connect
from .migrator import discover_migrations

BACKUP_DIR_NAME = "backups"
BACKUP_SUFFIX = ".sqlite3"
METADATA_SUFFIX = ".json"
REASON_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")
NAME_RE = re.compile(r"^pih-[0-9]{8}T[0-9]{12}Z-[a-z0-9-]{1,20}\.sqlite3$")

MIN_FREE_AFTER_BACKUP = 5 << 30  # 5 GiB
BACKUP_SPACE_FACTOR = 2
BACKUP_SPACE_MARGIN = 256 << 20
RETENTION_DAILY = 7
RETENTION_WEEKLY = 4


class BackupError(Exception):
    """Restore/backup failure carrying a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def backup_dir() -> Path:
    return resolve_data_dir() / BACKUP_DIR_NAME


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_bytes() -> int:
    total = 0
    for suffix in ("", "-wal"):
        candidate = Path(str(database_path()) + suffix)
        if candidate.is_file():
            total += candidate.stat().st_size
    return total


def _check_space() -> None:
    target = resolve_data_dir()
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(target)
    required = _database_bytes() * BACKUP_SPACE_FACTOR + BACKUP_SPACE_MARGIN
    if usage.free < required or usage.free - _database_bytes() < MIN_FREE_AFTER_BACKUP:
        raise BackupError(
            "insufficient_space",
            "可用磁盘空间不足，已拒绝生成备份（需要约 "
            f"{required / (1 << 20):.0f} MiB 且备份后保留 5 GiB）",
        )


def _integrity_ok(path: Path) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return row is not None and str(row[0]).strip().lower() == "ok"
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _schema_version(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0]) if row is not None and row[0] is not None else 0
    finally:
        conn.close()


def _metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + METADATA_SUFFIX)


def _write_metadata(path: Path, payload: dict[str, object]) -> None:
    meta = _metadata_path(path)
    meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(meta, 0o600)


def create_backup(reason: str = "manual") -> dict[str, object]:
    """Create a verified backup and apply the retention policy."""

    if not REASON_RE.fullmatch(reason):
        raise BackupError("invalid_reason", "reason 只能是小写字母、数字和短横线（≤20）")

    source = database_path()
    if not source.is_file():
        raise BackupError("database_missing", "数据库不存在，无法备份")

    _check_space()
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)

    filename = f"pih-{_utc_stamp()}-{reason}{BACKUP_SUFFIX}"
    target = directory / filename
    fd, temp_name = tempfile.mkstemp(dir=directory, prefix=".backup-", suffix=".tmp")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        src = connect(source)
        dest = sqlite3.connect(str(temp_path), isolation_level=None)
        try:
            src.backup(dest, pages=256)
        finally:
            dest.close()
            src.close()

        if not _integrity_ok(temp_path):
            raise BackupError("backup_corrupt", "备份完整性校验失败")
        os.replace(temp_path, target)
        os.chmod(target, 0o600)

        payload: dict[str, object] = {
            "filename": filename,
            "created_at": _iso_now(),
            "reason": reason,
            "schema_version": _schema_version(target),
            "size_bytes": target.stat().st_size,
            "sha256": _sha256(target),
            "integrity_ok": True,
        }
        _write_metadata(target, payload)
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        _apply_retention()
        return payload
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(temp_path) + suffix).unlink(missing_ok=True)


def _read_metadata(path: Path) -> dict[str, object] | None:
    meta = _metadata_path(path)
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_backups() -> list[dict[str, object]]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    items: list[dict[str, object]] = []
    for path in sorted(directory.glob(f"pih-*{BACKUP_SUFFIX}")):
        if not NAME_RE.fullmatch(path.name):
            continue
        meta = _read_metadata(path) or {}
        items.append(
            {
                "filename": path.name,
                "created_at": meta.get("created_at"),
                "reason": meta.get("reason"),
                "schema_version": meta.get("schema_version"),
                "size_bytes": path.stat().st_size,
                "integrity_ok": meta.get("integrity_ok", False),
            }
        )
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def _parse_created(value: object) -> datetime:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _apply_retention() -> None:
    """Keep the newest 7 backups plus one per ISO week (up to 4 weeks).

    Never groups by day: creating a second backup on the same day must not
    delete the first one (a restore may still need it as its target).
    """

    entries: list[tuple[Path, datetime]] = []
    directory = backup_dir()
    for path in directory.glob(f"pih-*{BACKUP_SUFFIX}"):
        if not NAME_RE.fullmatch(path.name):
            continue
        meta = _read_metadata(path) or {}
        entries.append((path, _parse_created(meta.get("created_at"))))
    entries.sort(key=lambda item: item[1], reverse=True)

    keep = {str(path) for path, _ in entries[:RETENTION_DAILY]}

    weekly: dict[str, Path] = {}
    for path, created in entries:
        weekly.setdefault(created.strftime("%G-W%V"), path)
    keep.update(str(path) for path in list(weekly.values())[:RETENTION_WEEKLY])

    for path, _ in entries:
        if str(path) in keep:
            continue
        path.unlink(missing_ok=True)
        _metadata_path(path).unlink(missing_ok=True)


def _assert_not_in_use() -> None:
    main = database_path()
    if not main.is_file():
        return
    conn = sqlite3.connect(str(main), timeout=0.2, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 200")
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("ROLLBACK")
        # WAL readers do not block BEGIN EXCLUSIVE; a checkpoint does.
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and int(row[0]) != 0:
            raise BackupError(
                "database_in_use",
                "数据库正在被使用（Sidecar 可能仍在运行），请先完全退出 App 再恢复",
            )
    except sqlite3.OperationalError as exc:
        raise BackupError(
            "database_in_use",
            "数据库正在被使用（Sidecar 可能仍在运行），请先完全退出 App 再恢复",
        ) from exc
    finally:
        conn.close()


def _assert_sidecar_stopped() -> None:
    """An idle Sidecar holds no SQLite lock, so also check the process list."""

    if sys.platform != "darwin":
        return
    # The App launches the Sidecar with an absolute path, while dev runs often
    # use a relative one; match the stable suffix in both cases.
    pattern = "Backend/main.py"
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if result.returncode == 0 and result.stdout.strip():
        raise BackupError(
            "database_in_use",
            "检测到 Sidecar 仍在运行，请完全退出 App 后再恢复",
        )


def restore_backup(filename: str) -> dict[str, object]:
    """Replace the live database with a verified backup, with rollback."""

    if Path(filename).name != filename or not NAME_RE.fullmatch(filename):
        raise BackupError("invalid_name", "备份文件名非法")

    source = backup_dir() / filename
    if not source.is_file():
        raise BackupError("backup_missing", "备份文件不存在")
    if not _integrity_ok(source):
        raise BackupError("backup_corrupt", "备份文件完整性校验失败")

    version = _schema_version(source)
    highest = max(migration.version for migration in discover_migrations())
    if version > highest:
        raise BackupError(
            "backup_schema_newer", "备份的数据库版本高于当前程序，拒绝恢复"
        )
    if version < 1:
        raise BackupError("backup_schema_invalid", "备份缺少迁移记录，拒绝恢复")

    _assert_sidecar_stopped()
    _assert_not_in_use()
    safety = create_backup("pre-restore")

    main = database_path()
    directory = main.parent
    fd, temp_name = tempfile.mkstemp(dir=directory, prefix=".restore-", suffix=".tmp")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copyfile(source, temp_path)
        if not _integrity_ok(temp_path):
            raise BackupError("backup_corrupt", "临时恢复文件完整性校验失败")

        for suffix in ("-wal", "-shm"):
            Path(str(main) + suffix).unlink(missing_ok=True)
        os.replace(temp_path, main)
        os.chmod(main, 0o600)

        if not _integrity_ok(main):
            _rollback_from_safety(safety)
            raise BackupError("restore_failed", "恢复后完整性校验失败，已回滚")

        restored_version = _schema_version(main)
        if restored_version != version:
            _rollback_from_safety(safety)
            raise BackupError("restore_failed", "恢复后 schema 版本不一致，已回滚")

        return {
            "restored_from": filename,
            "schema_version": restored_version,
            "safety_backup": safety["filename"],
            "verified": True,
        }
    finally:
        temp_path.unlink(missing_ok=True)


def _rollback_from_safety(safety: dict[str, object]) -> None:
    filename = safety.get("filename")
    if not isinstance(filename, str):
        return
    source = backup_dir() / filename
    if not source.is_file():
        return
    main = database_path()
    temp = main.parent / ".rollback.tmp"
    shutil.copyfile(source, temp)
    for suffix in ("-wal", "-shm"):
        Path(str(main) + suffix).unlink(missing_ok=True)
    os.replace(temp, main)
    os.chmod(main, 0o600)
