"""Phase 7.1 test helpers: real SQLite seeding and a deterministic model stub."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone

import database
from ai_engine.provider import GenerationResult, ProviderHealth, RemoteModel
from core.timeutil import utc_timestamp


def stamp(days_ago: float = 0.0) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def today_at(hour: int = 0, minute: int = 0) -> str:
    """A fixed instant inside the current UTC day (independent of local clock)."""

    day = datetime.now(timezone.utc).date()
    value = datetime.combine(day, dtime(hour=hour, minute=minute), tzinfo=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Seed:
    article_title: str
    source_name: str
    keywords: list[str]
    category: str
    days_ago: float = 0.0
    entity: str = "测试实体"
    at: str | None = None


def seed_graph(items: list[Seed]) -> dict[str, list[str]]:
    """Insert real articles + analysis + one event with members, scores, entities."""

    article_ids: list[str] = []
    source_ids: list[str] = []
    now = utc_timestamp()
    with database.session() as conn:
        for item in items:
            source_id = str(uuid.uuid4())
            article_id = str(uuid.uuid4())
            published = item.at or stamp(item.days_ago)
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
                    item.source_name,
                    f"https://{source_id[:8]}.example.com/feed.xml",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO articles (
                    id, source_id, external_id, canonical_url, original_url, title,
                    author, summary, content_text, content_state, published_at,
                    source_updated_at, fetched_at, content_hash, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, NULL, 'summary_only',
                          ?, NULL, ?, ?, 'active', ?, ?)
                """,
                (
                    article_id,
                    source_id,
                    f"ext-{article_id[:10]}",
                    item.article_title,
                    f"{item.article_title} 摘要",
                    published,
                    published,
                    uuid.uuid4().hex * 2,
                    now,
                    now,
                ),
            )
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
                    str(uuid.uuid4()),
                    article_id,
                    uuid.uuid4().hex * 2,
                    item.category,
                    f"{item.article_title} 摘要",
                    json.dumps(item.keywords, ensure_ascii=False),
                    json.dumps(
                        [{"name": item.entity, "type": "organization"}],
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            article_ids.append(article_id)
            source_ids.append(source_id)

        event_id = str(uuid.uuid4())
        published_values = [item.at or stamp(item.days_ago) for item in items]
        first = min(published_values)
        last = max(published_values)
        conn.execute(
            """
            INSERT INTO events (
                id, title, summary, category, status, status_reason,
                first_seen_at, last_seen_at, first_published_at, last_published_at,
                occurred_at, article_count, source_count, is_manual,
                merged_into_event_id, algorithm_version, title_source, summary_source,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?, NULL, ?, ?, 0, NULL,
                      'event-cluster-v1', 'auto', 'auto', ?, ?)
            """,
            (
                event_id,
                "测试事件：本地情报生成",
                "事件摘要",
                items[0].category,
                first,
                last,
                first,
                last,
                len(article_ids),
                len(source_ids),
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
                (str(uuid.uuid4()), event_id, article_id, now, now),
            )
        conn.execute(
            """
            INSERT INTO event_score_snapshots (
                id, event_id, algorithm_version, scored_at, importance_score,
                heat_score, freshness_score, coverage_score, confidence_score,
                total_score, inputs_json, explanation_json, is_current, created_at
            ) VALUES (?, ?, 'event-score-v1', ?, 80, 62, 70, 55, 85, 74, '{}', '{}', 1, ?)
            """,
            (str(uuid.uuid4()), event_id, now, now),
        )

        entity_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO entities (
                id, canonical_name, entity_type, type_group, normalized_key, status,
                confidence, normalization_basis, merged_into_entity_id, first_seen_at,
                last_seen_at, created_at, updated_at
            ) VALUES (?, ?, 'organization', 'organization', ?, 'active', 0.9,
                      'ai_extraction', NULL, ?, ?, ?, ?)
            """,
            (
                entity_id,
                items[0].entity,
                f"org:{items[0].entity.lower()}",
                first,
                last,
                now,
                now,
            ),
        )
        for article_id in article_ids:
            conn.execute(
                """
                INSERT INTO article_entities (
                    id, article_id, entity_id, analysis_id, raw_name, raw_type,
                    match_method, status, confidence, merged_from_entity_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, 'organization', 'canonical', 'resolved',
                          0.9, NULL, ?, ?)
                """,
                (str(uuid.uuid4()), article_id, entity_id, items[0].entity, now, now),
            )
        conn.execute(
            """
            INSERT INTO event_entities (
                id, event_id, entity_id, role, article_count, confidence,
                evidence_article_id, created_at, updated_at
            ) VALUES (?, ?, ?, 'organization', ?, 0.9, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                event_id,
                entity_id,
                len(article_ids),
                article_ids[0],
                now,
                now,
            ),
        )
    return {"articles": article_ids, "sources": source_ids, "events": [event_id]}


def default_seed() -> dict[str, list[str]]:
    return seed_graph(
        [
            Seed(
                article_title="量子计算突破引发关注",
                source_name="来源A",
                keywords=["量子计算", "芯片", "研究"],
                category="科技",
                at=today_at(1),
            ),
            Seed(
                article_title="量子计算芯片进入测试阶段",
                source_name="来源B",
                keywords=["量子计算", "芯片", "测试"],
                category="科技",
                at=today_at(2),
            ),
            Seed(
                article_title="量子计算企业获得新一轮融资",
                source_name="来源C",
                keywords=["量子计算", "融资", "企业"],
                category="财经",
                at=today_at(3),
            ),
        ]
    )


class StubProvider:
    """Deterministic local-model stand-in; never touches the network."""

    def __init__(
        self, *, available: bool = True, payloads: list[dict] | None = None
    ) -> None:
        self.available = available
        self.payloads = list(payloads or [])
        self.calls = 0

    def health_check(self) -> ProviderHealth:
        models = (
            (
                RemoteModel(
                    name="qwen3.5:4b-mlx",
                    digest="stub",
                    size_bytes=1,
                    parameter_size="4B",
                    quantization="mlx",
                    remote_host=None,
                ),
            )
            if self.available
            else ()
        )
        return ProviderHealth(
            available=self.available,
            version="stub" if self.available else None,
            models=models,
            error_code=None if self.available else "model_unavailable",
            checked_at=utc_timestamp(),
        )

    def generate_structured(
        self, *, model, messages, num_ctx, temperature, num_predict, allowed_models, timeout=None
    ) -> GenerationResult:
        self.calls += 1
        if not self.payloads:
            raise AssertionError("stub called without payload")
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        return GenerationResult(
            text=json.dumps(payload, ensure_ascii=False),
            model_name=model,
            model_digest="stub",
            total_duration_ms=10,
            load_duration_ms=1,
            prompt_eval_count=100,
            eval_count=50,
            eval_duration_ms=500,
            tok_per_s=100.0,
            truncated=False,
        )


def wait_for(service, report_id: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record, citations = service.report_detail(report_id)
        if record.status in {"succeeded", "degraded", "failed", "cancelled"}:
            return record, citations
        time.sleep(0.02)
    raise AssertionError(f"report {report_id} did not finish in {timeout}s")
