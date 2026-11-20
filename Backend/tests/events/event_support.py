"""Helpers that seed real articles + AI analysis and run the clustering worker."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import database
from core.timeutil import utc_timestamp
from database import session as write_session
from services.entity_service import sync_article


def stamp(days_ago: float = 0.0) -> str:
    """A 24-character UTC timestamp relative to now."""

    value = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SeededArticle:
    article_id: str
    source_id: str
    analysis_id: str


def create_category(name: str = "科技") -> str:
    category_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO source_categories
                (id, name, description, sort_order, created_at, updated_at)
            VALUES (?, ?, NULL, 0, ?, ?)
            """,
            (category_id, name, now, now),
        )
    return category_id


def create_source(
    name: str, *, url: str | None = None, category_id: str | None = None
) -> str:
    source_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES (?, ?, ?, 'rss', ?, NULL, NULL, 'zh', NULL, 10, NULL,
                      60, 1, 'unknown', ?, ?)
            """,
            (
                source_id,
                category_id,
                name,
                url or f"https://{uuid.uuid4().hex[:8]}.example.com/feed.xml",
                now,
                now,
            ),
        )
    return source_id


def create_article(
    *,
    source_id: str,
    title: str,
    published_at: str | None = None,
    summary: str | None = None,
    content_text: str | None = None,
    content_hash: str | None = None,
) -> str:
    article_id = str(uuid.uuid4())
    now = utc_timestamp()
    published = published_at or now
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                id, source_id, external_id, canonical_url, original_url, title,
                author, summary, content_text, content_state, published_at,
                source_updated_at, fetched_at, content_hash, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, ?, 'summary_only', ?,
                      NULL, ?, ?, 'active', ?, ?)
            """,
            (
                article_id,
                source_id,
                f"ext-{article_id[:12]}",
                title,
                summary,
                content_text,
                published,
                published,
                content_hash or uuid.uuid4().hex * 2,
                now,
                now,
            ),
        )
    return article_id


def create_analysis(
    *,
    article_id: str,
    category: str,
    summary: str,
    keywords: list[str],
    entities: list[tuple[str, str]],
    confidence: float = 0.85,
) -> str:
    analysis_id = str(uuid.uuid4())
    now = utc_timestamp()
    content_hash = uuid.uuid4().hex * 2
    with write_session() as conn:
        row = conn.execute(
            "SELECT content_hash FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if row is not None:
            content_hash = str(row["content_hash"])
        conn.execute(
            """
            INSERT INTO article_ai_analysis (
                id, article_id, analysis_type, provider_kind, model_name,
                model_digest, prompt_version, params_json, content_hash, category,
                summary, keywords_json, entities_json, confidence, input_chars,
                duration_ms, created_at
            ) VALUES (?, ?, 'article_analysis', 'ollama-local', 'test-model',
                      NULL, 'article-analysis-v1', '{}', ?, ?, ?, ?, ?, ?, 100, 10, ?)
            """,
            (
                analysis_id,
                article_id,
                content_hash,
                category,
                summary[:300],
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(
                    [{"name": name, "type": kind} for name, kind in entities],
                    ensure_ascii=False,
                ),
                confidence,
                now,
            ),
        )
    return analysis_id


def seed_article(
    *,
    title: str,
    category: str,
    summary: str,
    keywords: list[str],
    entities: list[tuple[str, str]],
    source_name: str = "测试源",
    category_id: str | None = None,
    published_at: str | None = None,
    content_hash: str | None = None,
) -> SeededArticle:
    source_id = create_source(source_name, category_id=category_id)
    article_id = create_article(
        source_id=source_id,
        title=title,
        published_at=published_at,
        summary=summary,
        content_hash=content_hash,
    )
    analysis_id = create_analysis(
        article_id=article_id,
        category=category,
        summary=summary,
        keywords=keywords,
        entities=entities,
    )
    with write_session() as conn:
        sync_article(conn, article_id, now=utc_timestamp(), stats={})
    return SeededArticle(article_id=article_id, source_id=source_id, analysis_id=analysis_id)


def seed_many(items: list[dict[str, object]]) -> list[SeededArticle]:
    return [seed_article(**item) for item in items]  # type: ignore[arg-type]


class FakeJudge:
    """Deterministic stand-in: never calls a model, reports healthy=False."""

    def __init__(self, outcomes: dict[str, object] | None = None) -> None:
        self.model_name = None
        self._outcomes = outcomes or {}

    def health(self):
        class _Health:
            available = False

        return _Health()

    def judge(self, *, article, event, member_rows):
        return self._outcomes.get(article.id)


TERMINAL = {"succeeded", "partially_succeeded", "failed", "cancelled"}


def run_clustering(
    *,
    scope: str = "incremental",
    article_ids: list[str] | None = None,
    use_llm: bool = False,
    judge: FakeJudge | None = None,
    timeout: float = 60.0,
):
    """Drive the real worker thread and block until the run reaches a terminal state."""

    from services.event_clustering_service import EventClusteringService

    service = EventClusteringService(judge=judge or FakeJudge())
    try:
        limit = len(article_ids) if article_ids else 200
        run = service.create_run(
            scope=scope,
            article_ids=article_ids,
            limit=limit,
            use_llm=use_llm,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = service.get_run(run.id)
            if current.status in TERMINAL:
                return current
            time.sleep(0.02)
        raise AssertionError(f"clustering run {run.id} did not finish in {timeout}s")
    finally:
        service.stop()


def article_event(article_id: str) -> str | None:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT event_id FROM event_articles WHERE article_id = ?", (article_id,)
        ).fetchone()
    return None if row is None else str(row["event_id"])


def event_article_ids(event_id: str) -> list[str]:
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT article_id FROM event_articles WHERE event_id = ? ORDER BY added_at",
            (event_id,),
        ).fetchall()
    return [str(row["article_id"]) for row in rows]


def list_events(status: str | None = None) -> list[dict[str, object]]:
    with database.read_session() as conn:
        clause = "" if status is None else "WHERE status = ?"
        params = () if status is None else (status,)
        rows = conn.execute(
            f"SELECT id, title, category, status, article_count, source_count, "
            f"is_manual, first_published_at, last_published_at FROM events {clause} "
            f"ORDER BY created_at",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def event_row(event_id: str) -> dict[str, object] | None:
    with database.read_session() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return None if row is None else dict(row)


def entity_by_name(name: str) -> dict[str, object] | None:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT * FROM entities WHERE canonical_name = ? "
            "AND merged_into_entity_id IS NULL",
            (name,),
        ).fetchone()
    return None if row is None else dict(row)


def entity_count() -> int:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE merged_into_entity_id IS NULL"
        ).fetchone()
    return int(row[0]) if row is not None else 0


def entity_articles(entity_id: str) -> list[str]:
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT article_id FROM article_entities WHERE entity_id = ? "
            "AND status = 'resolved'",
            (entity_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def ambiguous_rows() -> list[dict[str, object]]:
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT article_id, raw_name FROM article_entities "
            "WHERE status = 'ambiguous' ORDER BY raw_name"
        ).fetchall()
    return [dict(row) for row in rows]


def audit_actions(event_id: str | None = None) -> list[str]:
    with database.read_session() as conn:
        if event_id is None:
            rows = conn.execute(
                "SELECT action FROM event_audit_log ORDER BY created_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT action FROM event_audit_log WHERE event_id = ? "
                "ORDER BY created_at",
                (event_id,),
            ).fetchall()
    return [str(row["action"]) for row in rows]


def count_entities_for_article(article_id: str) -> int:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM article_entities WHERE article_id = ?", (article_id,)
        ).fetchone()
    return int(row[0]) if row is not None else 0


def current_scores(event_id: str) -> dict[str, object] | None:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT * FROM event_score_snapshots WHERE event_id = ? AND is_current = 1",
            (event_id,),
        ).fetchone()
    return None if row is None else dict(row)


def score_snapshot_count(event_id: str) -> int:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM event_score_snapshots WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def relations(status: str | None = None) -> list[dict[str, object]]:
    with database.read_session() as conn:
        clause = "" if status is None else "WHERE status = ?"
        params = () if status is None else (status,)
        rows = conn.execute(
            f"SELECT * FROM event_relations {clause} ORDER BY created_at", params
        ).fetchall()
    return [dict(row) for row in rows]


def timeline(event_id: str) -> list[dict[str, object]]:
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT * FROM event_timeline_items WHERE event_id = ? "
            "ORDER BY COALESCE(published_at, recognized_at), created_at",
            (event_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def reset_singletons() -> None:
    """Drop module-level service singletons between tests."""

    import services.entity_service as entity_service
    import services.event_clustering_service as clustering
    import services.event_scoring_service as scoring
    import services.event_service as events

    entity_service._entity_service = None
    clustering._clustering_service = None
    scoring._scoring_service = None
    events._event_service = None


__all__ = [
    "FakeJudge",
    "SeededArticle",
    "ambiguous_rows",
    "article_event",
    "audit_actions",
    "count_entities_for_article",
    "create_analysis",
    "create_article",
    "create_category",
    "create_source",
    "current_scores",
    "entity_articles",
    "entity_by_name",
    "entity_count",
    "event_article_ids",
    "event_row",
    "list_events",
    "relations",
    "reset_singletons",
    "run_clustering",
    "score_snapshot_count",
    "seed_article",
    "seed_many",
    "stamp",
    "timeline",
]
