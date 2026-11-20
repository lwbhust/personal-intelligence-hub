"""Phase 4 performance benchmark on the real local hardware.

Creates a throw-away SQLite database under the system temp directory, seeds
synthetic articles, runs the real clustering worker and reports timings for
the read paths used by the event center. Never touches the user's PIH data dir.

Run:
    cd Backend && .venv/bin/python scripts/perf_event_intelligence.py
"""

from __future__ import annotations

import json
import os
import resource
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

WORK_DIR = tempfile.mkdtemp(prefix="pih-perf-")
os.environ["PIH_DATA_DIR"] = str(Path(WORK_DIR) / "data")

import database  # noqa: E402
from core.timeutil import utc_timestamp  # noqa: E402
from database.repositories import event_repository as event_repo  # noqa: E402
from services.entity_service import sync_article  # noqa: E402
from services.event_scoring_service import EventScoringService  # noqa: E402

EVENT_COUNT = 30
ARTICLES_PER_EVENT = 10
EXTRA_PER_EVENT = 5
SOURCE_COUNT = 20


def _stamp(days_ago: float) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def seed() -> list[str]:
    status = database.initialize()
    assert status.status == "ok", status
    now = utc_timestamp()
    category_id = str(uuid.uuid4())
    sources: list[str] = []
    with database.session() as conn:
        conn.execute(
            "INSERT INTO source_categories (id,name,description,sort_order,created_at,updated_at) "
            "VALUES (?,?,NULL,0,?,?)",
            (category_id, "性能测试", now, now),
        )
        for index in range(SOURCE_COUNT):
            source_id = str(uuid.uuid4())
            sources.append(source_id)
            conn.execute(
                """
                INSERT INTO sources (
                    id, category_id, name, source_type, url, homepage_url, description,
                    language, country, priority, credibility_score,
                    fetch_interval_minutes, enabled, health_status, created_at, updated_at
                ) VALUES (?,?,?, 'rss', ?, NULL, NULL, 'zh', NULL, 10, NULL, 60, 1,
                          'unknown', ?, ?)
                """,
                (source_id, category_id, f"性能源{index}", f"https://perf{index}.example/feed", now, now),
            )

    article_ids: list[str] = []
    with database.session() as conn:
        for event_index in range(EVENT_COUNT):
            company = f"性能公司{event_index:02d}"
            event_entity = f"性能事件{event_index:02d}"
            for article_index in range(ARTICLES_PER_EVENT):
                article_id = str(uuid.uuid4())
                source_id = sources[(event_index + article_index) % SOURCE_COUNT]
                published = _stamp(article_index * 0.3)
                title = f"{company}发布{event_entity}进展 第{article_index + 1}报"
                conn.execute(
                    """
                    INSERT INTO articles (
                        id, source_id, external_id, canonical_url, original_url, title,
                        author, summary, content_text, content_state, published_at,
                        source_updated_at, fetched_at, content_hash, status,
                        created_at, updated_at
                    ) VALUES (?,?,?,NULL,NULL,?,NULL,?,NULL,'summary_only',?,NULL,?,?,'active',?,?)
                    """,
                    (
                        article_id,
                        source_id,
                        f"perf-{article_id[:12]}",
                        title,
                        f"{company}{event_entity}进展摘要。",
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
                    ) VALUES (?,?, 'article_analysis','ollama-local','perf-model',NULL,
                              'article-analysis-v1','{}',?,?,?,?,?,0.9,100,10,?)
                    """,
                    (
                        str(uuid.uuid4()),
                        article_id,
                        uuid.uuid4().hex * 2,
                        "科技",
                        f"{company}{event_entity}进展摘要。",
                        json.dumps(["财报", "进展"], ensure_ascii=False),
                        json.dumps(
                            [
                                {"name": company, "type": "organization"},
                                {"name": event_entity, "type": "event"},
                            ],
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
                article_ids.append(article_id)
    for article_id in article_ids:
        with database.session() as conn:
            sync_article(conn, article_id, now=utc_timestamp(), stats={})
    return article_ids


def seed_extra() -> list[str]:
    """Append new reports to the existing events to exercise a second run."""

    now = utc_timestamp()
    article_ids: list[str] = []
    for event_index in range(EVENT_COUNT):
        company = f"性能公司{event_index:02d}"
        event_entity = f"性能事件{event_index:02d}"
        for extra_index in range(EXTRA_PER_EVENT):
            source_id = str(uuid.uuid4())
            article_id = str(uuid.uuid4())
            with database.session() as conn:
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, category_id, name, source_type, url, homepage_url, description,
                        language, country, priority, credibility_score,
                        fetch_interval_minutes, enabled, health_status, created_at, updated_at
                    ) VALUES (?, NULL, ?, 'rss', ?, NULL, NULL, 'zh', NULL, 10, NULL, 60, 1,
                              'unknown', ?, ?)
                    """,
                    (
                        source_id,
                        f"性能追加源{event_index}-{extra_index}",
                        f"https://perf-extra{event_index}-{extra_index}.example/feed",
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
                    ) VALUES (?,?,?,NULL,NULL,?,NULL,?,NULL,'summary_only',?,NULL,?,?,'active',?,?)
                    """,
                    (
                        article_id,
                        source_id,
                        f"perf-extra-{article_id[:12]}",
                        f"{company}发布{event_entity}进展 追加{extra_index + 1}",
                        f"{company}{event_entity}进展摘要。",
                        _stamp(0.0),
                        _stamp(0.0),
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
                    ) VALUES (?,?, 'article_analysis','ollama-local','perf-model',NULL,
                              'article-analysis-v1','{}',?,?,?,?,?,0.9,100,10,?)
                    """,
                    (
                        str(uuid.uuid4()),
                        article_id,
                        uuid.uuid4().hex * 2,
                        "科技",
                        f"{company}{event_entity}进展摘要。",
                        json.dumps(["财报", "进展"], ensure_ascii=False),
                        json.dumps(
                            [
                                {"name": company, "type": "organization"},
                                {"name": event_entity, "type": "event"},
                            ],
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
            article_ids.append(article_id)
    for article_id in article_ids:
        with database.session() as conn:
            sync_article(conn, article_id, now=utc_timestamp(), stats={})
    return article_ids


TERMINAL = {"succeeded", "partially_succeeded", "failed", "cancelled"}


def run_clustering():
    from services.event_clustering_service import EventClusteringService

    class NoJudge:
        model_name = None

        def health(self):
            class Health:
                available = False

            return Health()

        def judge(self, **_kwargs):
            return None

    service = EventClusteringService(judge=NoJudge())
    try:
        run = service.create_run(scope="incremental", article_ids=None, limit=2000, use_llm=False)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            current = service.get_run(run.id)
            if current.status in TERMINAL:
                return current
            time.sleep(0.1)
        raise RuntimeError("clustering timed out")
    finally:
        service.stop()


def main() -> None:
    started = time.monotonic()
    article_ids = seed()
    seed_seconds = time.monotonic() - started

    cluster_started = time.monotonic()
    run = run_clustering()
    cluster_seconds = time.monotonic() - cluster_started

    with database.read_session() as conn:
        list_started = time.monotonic()
        items, total = event_repo.list_events(conn, limit=20, offset=0, order="importance")
        list_ms = (time.monotonic() - list_started) * 1000

        event_id = str(items[0].id) if items else None
        timeline_ms = None
        if event_id is not None:
            timeline_started = time.monotonic()
            event_repo.list_timeline(conn, event_id, limit=50, offset=0)
            timeline_ms = (time.monotonic() - timeline_started) * 1000

        members_ms = None
        if event_id is not None:
            members_started = time.monotonic()
            event_repo.list_event_articles(conn, event_id, limit=50, offset=0)
            members_ms = (time.monotonic() - members_started) * 1000

        assigned = conn.execute("SELECT COUNT(*) FROM event_articles").fetchone()[0]
        event_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    scoring_started = time.monotonic()
    ranking = EventScoringService().rankings(
        kind="importance", window="all", category=None, limit=20, offset=0
    )
    ranking_ms = (time.monotonic() - scoring_started) * 1000

    # Steady state: a second incremental run over existing automatic events.
    extra_seeded = seed_extra()
    second_started = time.monotonic()
    second_run = run_clustering()
    second_seconds = time.monotonic() - second_started
    with database.read_session() as conn:
        final_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        final_members = conn.execute("SELECT COUNT(*) FROM event_articles").fetchone()[0]

    db_path = Path(os.environ["PIH_DATA_DIR"]) / "pih.sqlite3"
    usage = resource.getrusage(resource.RUSAGE_SELF)

    report = {
        "event_count": int(event_total),
        "final_event_count": int(final_events),
        "final_articles_assigned": int(final_members),
        "articles_seeded": len(article_ids),
        "articles_assigned": int(assigned),
        "extra_articles_seeded": len(extra_seeded),
        "cluster_status": run.status,
        "cluster_run_duration_ms": run.duration_ms,
        "cluster_wall_seconds": round(cluster_seconds, 2),
        "second_cluster_status": second_run.status,
        "second_cluster_run_duration_ms": second_run.duration_ms,
        "second_cluster_wall_seconds": round(second_seconds, 2),
        "seed_seconds": round(seed_seconds, 2),
        "list_events_20_ms": round(list_ms, 2),
        "timeline_50_ms": None if timeline_ms is None else round(timeline_ms, 2),
        "event_articles_50_ms": None if members_ms is None else round(members_ms, 2),
        "rankings_20_ms": round(ranking_ms, 2),
        "ranking_total": ranking["total"],
        "db_size_mb": round(db_path.stat().st_size / (1024 * 1024), 2),
        "process_max_rss_mb": round(usage.ru_maxrss / (1024 * 1024), 1),
        "work_dir": WORK_DIR,
    }
    print("PERF_REPORT=" + json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
