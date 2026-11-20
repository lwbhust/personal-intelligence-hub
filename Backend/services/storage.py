"""Best-effort disk guard for write endpoints.

All Phase 2 writes (manual collection jobs, article batches) must fail with an
explicit 507 instead of a half-written row or an opaque SQLite error when the
volume is nearly full. This is a per-write check, not a hard quota guarantee.
"""

from __future__ import annotations

import shutil

import database

from .errors import insufficient_storage

MIN_FREE_BYTES = 1 << 30  # 1 GiB


def disk_snapshot() -> dict[str, int] | None:
    """Best-effort free/total bytes for the data volume (for logging only)."""

    try:
        target = database.resolve_data_dir()
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(target)
    except OSError:
        return None
    return {"free_bytes": int(usage.free), "total_bytes": int(usage.total)}


def ensure_writable() -> None:
    snapshot = disk_snapshot()
    if snapshot is None:
        return
    if snapshot["free_bytes"] < MIN_FREE_BYTES:
        raise insufficient_storage()
