"""Parameterised SQL for `source_adapter_configs`.

No connection lifecycle and no transactions here: callers own both.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .models import SourceAdapterRecord

_COLUMNS = (
    "source_id",
    "adapter_type",
    "entry_url",
    "config_json",
    "config_version",
    "rate_limit_seconds",
    "max_entries_per_run",
    "fetch_full_text",
    "last_verified_at",
    "last_verification",
    "last_sample_json",
    "created_at",
    "updated_at",
)


def _row_to_record(row: sqlite3.Row) -> SourceAdapterRecord:
    return SourceAdapterRecord(
        source_id=str(row["source_id"]),
        adapter_type=str(row["adapter_type"]),
        entry_url=str(row["entry_url"]),
        config_json=str(row["config_json"]),
        config_version=str(row["config_version"]),
        rate_limit_seconds=int(row["rate_limit_seconds"]),
        max_entries_per_run=int(row["max_entries_per_run"]),
        fetch_full_text=bool(int(row["fetch_full_text"])),
        last_verified_at=row["last_verified_at"],
        last_verification=str(row["last_verification"]),
        last_sample_json=row["last_sample_json"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def get(conn: sqlite3.Connection, source_id: str) -> SourceAdapterRecord | None:
    row = conn.execute(
        "SELECT * FROM source_adapter_configs WHERE source_id = ?", (source_id,)
    ).fetchone()
    return None if row is None else _row_to_record(row)


def list_all(conn: sqlite3.Connection) -> list[SourceAdapterRecord]:
    rows = conn.execute(
        "SELECT * FROM source_adapter_configs ORDER BY created_at ASC, source_id ASC"
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def upsert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    keys = [key for key in _COLUMNS if key in values]
    placeholders = ", ".join("?" for _ in keys)
    columns = ", ".join(keys)
    updates = ", ".join(f"{key} = excluded.{key}" for key in keys if key != "source_id")
    conn.execute(
        f"INSERT INTO source_adapter_configs ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(source_id) DO UPDATE SET {updates}",
        tuple(values[key] for key in keys),
    )


def update_verification(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    last_verified_at: str,
    last_verification: str,
    last_sample_json: str | None,
    updated_at: str,
) -> None:
    conn.execute(
        "UPDATE source_adapter_configs "
        "SET last_verified_at = ?, last_verification = ?, "
        "    last_sample_json = ?, updated_at = ? "
        "WHERE source_id = ?",
        (last_verified_at, last_verification, last_sample_json, updated_at, source_id),
    )


def delete(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute(
        "DELETE FROM source_adapter_configs WHERE source_id = ?", (source_id,)
    )
