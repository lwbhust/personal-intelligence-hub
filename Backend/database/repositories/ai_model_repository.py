"""Parameterised SQL for `ai_model_registry` (Phase 3)."""

from __future__ import annotations

import sqlite3

from .models import AIModelRecord


def _row_to_record(row: sqlite3.Row) -> AIModelRecord:
    roles = tuple(
        part.strip()
        for part in str(row["roles"]).split(",")
        if part.strip()
    )
    return AIModelRecord(
        model_name=str(row["model_name"]),
        provider_kind=str(row["provider_kind"]),
        digest=row["digest"],
        size_bytes=row["size_bytes"],
        parameter_size=row["parameter_size"],
        quantization=row["quantization"],
        max_context=row["max_context"],
        num_ctx=int(row["num_ctx"]),
        roles=roles,
        enabled=bool(int(row["enabled"])),
        last_checked_at=row["last_checked_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def list_models(conn: sqlite3.Connection) -> list[AIModelRecord]:
    rows = conn.execute(
        "SELECT * FROM ai_model_registry ORDER BY enabled DESC, model_name ASC"
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def get(conn: sqlite3.Connection, model_name: str) -> AIModelRecord | None:
    row = conn.execute(
        "SELECT * FROM ai_model_registry WHERE model_name = ?",
        (model_name,),
    ).fetchone()
    return None if row is None else _row_to_record(row)


def enabled_models(conn: sqlite3.Connection) -> list[AIModelRecord]:
    rows = conn.execute(
        "SELECT * FROM ai_model_registry WHERE enabled = 1 "
        "ORDER BY created_at ASC, model_name ASC"
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def enabled_model_names(conn: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(model.model_name for model in enabled_models(conn))


def default_model(conn: sqlite3.Connection, *, role: str = "summary") -> AIModelRecord | None:
    for model in enabled_models(conn):
        if role in model.roles:
            return model
    return None


def update_observation(
    conn: sqlite3.Connection,
    *,
    model_name: str,
    digest: str | None,
    size_bytes: int | None,
    parameter_size: str | None,
    quantization: str | None,
    checked_at: str,
) -> None:
    conn.execute(
        "UPDATE ai_model_registry SET digest = ?, size_bytes = ?, parameter_size = ?, "
        "quantization = ?, last_checked_at = ?, updated_at = ? WHERE model_name = ?",
        (
            digest,
            size_bytes,
            parameter_size,
            quantization,
            checked_at,
            checked_at,
            model_name,
        ),
    )
