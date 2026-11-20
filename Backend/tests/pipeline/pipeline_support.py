"""Shared fixtures helpers for Phase 7.2 pipeline tests (real SQLite, no mocks)."""

from __future__ import annotations

import json
import uuid

import database
from core.timeutil import utc_timestamp
from database import session as write_session


def create_source(name: str = "测试源") -> str:
    source_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES (?, NULL, ?, 'rss', ?, NULL, NULL, 'zh', NULL, 10, NULL,
                      60, 1, 'unknown', ?, ?)
            """,
            (
                source_id,
                name,
                f"https://{uuid.uuid4().hex[:8]}.example.com/feed.xml",
                now,
                now,
            ),
        )
    return source_id


DEFAULT_SUMMARY = (
    "这是一段用于测试管道阶段推进的完整摘要内容，长度超过最低阈值，"
    "包含足够的语义信息供后续实体同步与事件匹配使用。"
)


def create_article(
    *,
    source_id: str,
    title: str,
    summary: str | None = DEFAULT_SUMMARY,
    content_text: str | None = None,
    content_state: str = "summary_only",
    published_at: str | None = None,
) -> str:
    article_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                id, source_id, external_id, canonical_url, original_url, title,
                author, summary, content_text, content_state, published_at,
                source_updated_at, fetched_at, content_hash, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, ?, ?, ?,
                      NULL, ?, ?, 'active', ?, ?)
            """,
            (
                article_id,
                source_id,
                f"ext-{article_id[:12]}",
                title,
                summary,
                content_text,
                content_state,
                published_at or now,
                now,
                uuid.uuid4().hex * 2,
                now,
                now,
            ),
        )
    return article_id


def create_analysis(
    *,
    article_id: str,
    category: str = "科技",
    summary: str = "测试摘要",
    keywords: tuple[str, ...] = ("测试", "管道", "阶段"),
    entities: tuple[tuple[str, str], ...] = (("示例公司", "organization"),),
) -> str:
    analysis_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        row = conn.execute(
            "SELECT content_hash FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        content_hash = str(row[0]) if row is not None else uuid.uuid4().hex * 2
        conn.execute(
            """
            INSERT INTO article_ai_analysis (
                id, article_id, analysis_type, provider_kind, model_name,
                model_digest, prompt_version, params_json, content_hash, category,
                summary, keywords_json, entities_json, confidence, input_chars,
                duration_ms, created_at
            ) VALUES (?, ?, 'article_analysis', 'ollama-local', 'test-model',
                      NULL, 'article-analysis-v1', '{}', ?, ?, ?, ?, ?, 0.9, 100, 10, ?)
            """,
            (
                analysis_id,
                article_id,
                content_hash,
                category,
                summary,
                json.dumps(list(keywords), ensure_ascii=False),
                json.dumps(
                    [{"name": name, "type": kind} for name, kind in entities],
                    ensure_ascii=False,
                ),
                now,
            ),
        )
    return analysis_id


def seed_article(
    *,
    title: str = "测试文章",
    category: str = "科技",
    with_analysis: bool = True,
    summary: str | None = DEFAULT_SUMMARY,
) -> dict[str, str]:
    source_id = create_source()
    article_id = create_article(source_id=source_id, title=title, summary=summary)
    analysis_id = ""
    if with_analysis:
        analysis_id = create_analysis(article_id=article_id, category=category)
    return {"article_id": article_id, "source_id": source_id, "analysis_id": analysis_id}


def task_row(task_id: str) -> dict[str, object]:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    assert row is not None
    return dict(row)


def event_for_article(article_id: str) -> str | None:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT event_id FROM event_articles WHERE article_id = ?", (article_id,)
        ).fetchone()
    return None if row is None else str(row["event_id"])
