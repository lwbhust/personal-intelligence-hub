"""Parameterised SQL for `article_ai_analysis` (Phase 3)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from .models import AIAnalysisRecord

_COLUMNS = (
    "id",
    "article_id",
    "analysis_type",
    "provider_kind",
    "model_name",
    "model_digest",
    "prompt_version",
    "params_json",
    "content_hash",
    "category",
    "summary",
    "keywords_json",
    "entities_json",
    "confidence",
    "input_chars",
    "duration_ms",
    "created_at",
)


def _row_to_record(row: sqlite3.Row) -> AIAnalysisRecord:
    try:
        params = json.loads(str(row["params_json"]))
    except (TypeError, json.JSONDecodeError):
        params = {}
    try:
        keywords = json.loads(str(row["keywords_json"]))
    except (TypeError, json.JSONDecodeError):
        keywords = []
    try:
        entities = json.loads(str(row["entities_json"]))
    except (TypeError, json.JSONDecodeError):
        entities = []
    return AIAnalysisRecord(
        id=str(row["id"]),
        article_id=str(row["article_id"]),
        analysis_type=str(row["analysis_type"]),
        provider_kind=str(row["provider_kind"]),
        model_name=str(row["model_name"]),
        model_digest=row["model_digest"],
        prompt_version=str(row["prompt_version"]),
        params=params if isinstance(params, dict) else {},
        content_hash=str(row["content_hash"]),
        category=str(row["category"]),
        summary=str(row["summary"]),
        keywords=tuple(str(item) for item in keywords if isinstance(item, str)),
        entities=tuple(
            {"name": str(item.get("name", "")), "type": str(item.get("type", "other"))}
            for item in entities
            if isinstance(item, dict)
        ),
        confidence=float(row["confidence"]),
        input_chars=int(row["input_chars"]),
        duration_ms=int(row["duration_ms"]),
        created_at=str(row["created_at"]),
    )


def insert(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(_COLUMNS)
    placeholders = ", ".join("?" for _ in _COLUMNS)
    conn.execute(
        f"INSERT INTO article_ai_analysis ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in _COLUMNS),
    )


def list_for_article(conn: sqlite3.Connection, article_id: str) -> list[AIAnalysisRecord]:
    rows = conn.execute(
        "SELECT * FROM article_ai_analysis WHERE article_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (article_id,),
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def exists_for(
    conn: sqlite3.Connection,
    *,
    article_id: str,
    content_hash: str,
    model_name: str,
    prompt_version: str,
) -> str | None:
    row = conn.execute(
        "SELECT id FROM article_ai_analysis WHERE article_id = ? AND content_hash = ? "
        "AND model_name = ? AND prompt_version = ? LIMIT 1",
        (article_id, content_hash, model_name, prompt_version),
    ).fetchone()
    return None if row is None else str(row[0])


def exists_for_any_model(
    conn: sqlite3.Connection, *, article_id: str, content_hash: str
) -> bool:
    """True when the article already has an analysis for its current content.

    Used by the pipeline to avoid re-analysing; the model/prompt check remains
    the responsibility of `AIAnalysisService.create_run`.
    """

    row = conn.execute(
        "SELECT 1 FROM article_ai_analysis "
        "WHERE article_id = ? AND content_hash = ? LIMIT 1",
        (article_id, content_hash),
    ).fetchone()
    return row is not None


def eligible_article_ids(
    conn: sqlite3.Connection,
    *,
    model_name: str,
    prompt_version: str,
    limit: int,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT a.id
        FROM articles AS a
        WHERE a.deleted_at IS NULL
          AND a.status = 'active'
          AND length(trim(COALESCE(NULLIF(a.content_text, ''), NULLIF(a.summary, ''), ''))) > 0
          AND NOT EXISTS (
              SELECT 1 FROM article_ai_analysis AS x
              WHERE x.article_id = a.id
                AND x.analysis_type = 'article_analysis'
                AND x.content_hash = a.content_hash
                AND x.model_name = ?
                AND x.prompt_version = ?
          )
        ORDER BY (a.published_at IS NULL) ASC, a.published_at DESC, a.id ASC
        LIMIT ?
        """,
        (model_name, prompt_version, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def count_for_article(conn: sqlite3.Connection, article_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM article_ai_analysis WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0
