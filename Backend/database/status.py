"""Value object returned by `initialize()` / `health_check()`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    """Database state projected onto the `/health` `database` object.

    `status`        : "ok" | "error"
    `schema_version`: MAX(version) from schema_migrations, None when unreadable
    `path_kind`     : "application_support" | "custom"
    `code`          : stable contract error code, only when status == "error"
    """

    status: str
    schema_version: int | None
    path_kind: str
    code: str | None = None
