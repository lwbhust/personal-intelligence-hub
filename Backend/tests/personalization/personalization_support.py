"""Seed helpers for personalization tests (real rows, no mocks)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import database
from core.timeutil import utc_timestamp
from database import session as write_session

from pipeline_support import create_analysis, create_article, create_source


def iso_ago(hours: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(hours=hours)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def seed_article_with_analysis(
    *,
    title: str,
    category: str = "科技",
    source_id: str | None = None,
    published_hours_ago: float = 1,
    summary: str = "这是一段用于推荐测试的完整摘要内容，长度超过最低阈值，包含足够的语义信息。",
) -> dict[str, str]:
    source_id = source_id or create_source()
    article_id = create_article(
        source_id=source_id,
        title=title,
        summary=summary,
        published_at=iso_ago(published_hours_ago),
    )
    analysis_id = create_analysis(article_id=article_id, category=category)
    return {"article_id": article_id, "source_id": source_id, "analysis_id": analysis_id}


def create_event(
    *,
    title: str,
    category: str = "科技",
    article_ids: list[str] | None = None,
    score: float | None = 62.0,
    last_seen_hours_ago: float = 1,
    status: str = "candidate",
) -> str:
    event_id = str(uuid.uuid4())
    now = utc_timestamp()
    last_seen = iso_ago(last_seen_hours_ago)
    article_ids = article_ids or []
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO events (
                id, title, summary, category, status, status_reason, first_seen_at,
                last_seen_at, first_published_at, last_published_at, occurred_at,
                article_count, source_count, is_manual, merged_into_event_id,
                algorithm_version, title_source, summary_source, created_at, updated_at
            ) VALUES (?, ?, '事件摘要', ?, ?, 'test', ?, ?, ?, ?, NULL, ?, 1, 0, NULL,
                      'event-cluster-v1', 'auto', 'auto', ?, ?)
            """,
            (
                event_id,
                title,
                category,
                status,
                last_seen,
                last_seen,
                last_seen,
                last_seen,
                len(article_ids),
                now,
                now,
            ),
        )
        for article_id in article_ids:
            conn.execute(
                """
                INSERT INTO event_articles (
                    id, event_id, article_id, role, similarity, match_reasons_json,
                    is_manual, added_at, created_at
                ) VALUES (?, ?, ?, 'report', 0.9, '[]', 0, ?, ?)
                """,
                (str(uuid.uuid4()), event_id, article_id, last_seen, now),
            )
        if score is not None:
            conn.execute(
                """
                INSERT INTO event_score_snapshots (
                    id, event_id, algorithm_version, scored_at, importance_score,
                    heat_score, freshness_score, coverage_score, confidence_score,
                    total_score, inputs_json, explanation_json, is_current, created_at
                ) VALUES (?, ?, 'event-score-v1', ?, ?, 30.0, 80.0, 40.0, 70.0, ?,
                          '{}', '{}', 1, ?)
                """,
                (str(uuid.uuid4()), event_id, now, score, score, now),
            )
    return event_id


def create_entity(name: str, *, entity_type: str = "organization") -> str:
    entity_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO entities (
                id, canonical_name, entity_type, type_group, normalized_key, status,
                confidence, normalization_basis, merged_into_entity_id, first_seen_at,
                last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'organization', ?, 'active', 0.9, 'manual', NULL, ?, ?, ?, ?)
            """,
            (entity_id, name, entity_type, name.lower(), now, now, now, now),
        )
    return entity_id


def link_article_entity(article_id: str, entity_id: str) -> None:
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO article_entities (
                id, article_id, entity_id, analysis_id, raw_name, raw_type,
                match_method, status, confidence, merged_from_entity_id, created_at, updated_at
            ) VALUES (?, ?, ?, NULL, 'x', 'organization', 'canonical', 'resolved', 0.9, NULL, ?, ?)
            """,
            (str(uuid.uuid4()), article_id, entity_id, now, now),
        )


def set_source_credibility(source_id: str, value: float | None) -> None:
    with write_session() as conn:
        conn.execute(
            "UPDATE sources SET credibility_score = ? WHERE id = ?", (value, source_id)
        )


def set_analysis_keywords(article_id: str, keywords: list[str]) -> None:
    with write_session() as conn:
        conn.execute(
            "UPDATE article_ai_analysis SET keywords_json = ? WHERE article_id = ?",
            (json.dumps(keywords, ensure_ascii=False), article_id),
        )
