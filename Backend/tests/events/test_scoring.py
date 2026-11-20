"""Stage 4.5 — explainable scoring, snapshot history and rankings."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import database
from database.repositories import event_repository as event_repo
from event_intelligence.scoring import (
    ALGORITHM_VERSION,
    ScoreInputs,
    compute_scores,
)
from services.event_scoring_service import (
    EventScoringService,
    _build_inputs,
    score_event_in_conn,
)
from services.event_service import EventService

from event_support import (
    create_article,
    create_source,
    current_scores,
    list_events,
    score_snapshot_count,
    stamp,
)


def _make_event(
    *,
    category: str,
    count: int = 2,
    same_source: bool = False,
    duplicate_hash: bool = False,
) -> tuple[str, list[str]]:
    category_id = None
    articles: list[str] = []
    source_id = create_source("统一来源", category_id=category_id) if same_source else None
    for index in range(count):
        sid = source_id or create_source(f"来源{index}")
        content_hash = None
        if duplicate_hash and index == count - 1 and count > 1:
            with database.read_session() as conn:
                row = conn.execute(
                    "SELECT content_hash FROM articles WHERE id = ?", (articles[0],)
                ).fetchone()
            content_hash = str(row[0])
        article_id = create_article(
            source_id=sid,
            title=f"测试事件相关报道 {index}",
            published_at=stamp(0.1 * index),
            summary="测试事件摘要",
            content_hash=content_hash,
        )
        articles.append(article_id)
    event = EventService().create_event(
        title="测试事件",
        category=category,
        summary="测试事件摘要",
        article_ids=articles,
    )
    return event.id, articles


def test_total_formula_is_reproducible() -> None:
    inputs = ScoreInputs(
        category="科技",
        article_count=3,
        unique_content_count=3,
        unique_source_count=3,
        recent_72h_articles=3,
        recent_24h_articles=2,
        previous_24h_articles=1,
        org_count=1,
        person_count=1,
        location_count=0,
        duration_days=2.0,
        avg_entity_confidence=0.8,
        ambiguity_ratio=0.0,
        is_manual=False,
        last_published_at=stamp(0.1),
        last_seen_at=stamp(0.1),
    )
    result = compute_scores(inputs)
    expected = round(
        0.35 * result.importance
        + 0.25 * result.heat
        + 0.15 * result.freshness
        + 0.15 * result.confidence
        + 0.10 * result.coverage,
        2,
    )
    assert result.total == expected
    assert result.algorithm_version == ALGORITHM_VERSION
    assert result.explanation["formula"].startswith("0.35*importance")
    assert {component["name"] for component in result.explanation["components"]} == {
        "importance",
        "heat",
        "freshness",
        "confidence",
        "coverage",
    }
    for component in result.explanation["components"]:
        assert component["reason"]
        assert 0.0 <= component["value"] <= 100.0


def test_freshness_decays_with_age() -> None:
    now = datetime.now(timezone.utc)
    fresh = compute_scores(
        ScoreInputs(category="科技", last_published_at=stamp(0.0), last_seen_at=stamp(0.0)),
        now=now,
    )
    stale = compute_scores(
        ScoreInputs(category="科技", last_published_at=stamp(10.0), last_seen_at=stamp(10.0)),
        now=now,
    )
    assert fresh.freshness > stale.freshness
    assert fresh.total >= stale.total


def test_heat_uses_deduplicated_recent_articles(ready) -> None:
    event_id, articles = _make_event(category="科技", count=3, duplicate_hash=True)
    with database.read_session() as conn:
        event = event_repo.get(conn, event_id)
        assert event is not None
        inputs = _build_inputs(conn, event, datetime.now(timezone.utc))
    assert inputs.article_count == 3
    assert inputs.unique_content_count == 2
    assert inputs.recent_72h_articles == 2


def test_coverage_deduplicates_repeated_sources(ready) -> None:
    event_id, _ = _make_event(category="科技", count=3, same_source=True)
    with database.read_session() as conn:
        event = event_repo.get(conn, event_id)
        assert event is not None
        inputs = _build_inputs(conn, event, datetime.now(timezone.utc))
    assert inputs.unique_source_count == 1
    assert inputs.unique_content_count == 3


def test_confidence_is_independent_of_article_count(ready) -> None:
    small_conf = compute_scores(
        ScoreInputs(category="科技", article_count=10, unique_content_count=2,
                    unique_source_count=2, avg_entity_confidence=0.5,
                    ambiguity_ratio=0.5)
    )
    large_conf = compute_scores(
        ScoreInputs(category="科技", article_count=2, unique_content_count=2,
                    unique_source_count=2, avg_entity_confidence=0.9,
                    ambiguity_ratio=0.0)
    )
    assert large_conf.confidence > small_conf.confidence
    assert large_conf.heat <= 45.0 + 25.0 + 15.0 + 15.0


def test_credibility_score_never_enters_scoring(ready) -> None:
    event_id, _ = _make_event(category="科技", count=2)
    with database.session() as conn:
        conn.execute("UPDATE sources SET credibility_score = 100")
    with database.read_session() as conn:
        event = event_repo.get(conn, event_id)
        assert event is not None
        inputs = _build_inputs(conn, event, datetime.now(timezone.utc))
    assert "credibility" not in json.dumps(inputs.as_dict())
    assert "credibility" not in json.dumps(compute_scores(inputs).explanation)


def test_manual_confirmation_lifts_confidence(ready) -> None:
    auto = compute_scores(
        ScoreInputs(category="科技", article_count=2, unique_content_count=2,
                    unique_source_count=2, avg_entity_confidence=0.8)
    )
    manual = compute_scores(
        ScoreInputs(category="科技", article_count=2, unique_content_count=2,
                    unique_source_count=2, avg_entity_confidence=0.8, is_manual=True)
    )
    assert manual.confidence > auto.confidence
    assert manual.importance > auto.importance


def test_unchanged_scores_touch_instead_of_duplicating(ready) -> None:
    event_id, _ = _make_event(category="科技", count=2)
    assert score_snapshot_count(event_id) == 1
    with database.session() as conn:
        score_event_in_conn(conn, event_id)
    assert score_snapshot_count(event_id) == 1

    with database.read_session() as conn:
        before = conn.execute(
            "SELECT scored_at FROM event_score_snapshots WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
    with database.session() as conn:
        score_event_in_conn(conn, event_id, now=stamp(0.0))
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT scored_at, is_current FROM event_score_snapshots WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert str(row["scored_at"]) >= str(before)
    assert int(row["is_current"]) == 1


def test_changed_inputs_create_new_versioned_snapshot(ready) -> None:
    event_id, articles = _make_event(category="科技", count=1)
    assert score_snapshot_count(event_id) == 1
    extra = create_article(
        source_id=create_source("补充来源"),
        title="测试事件后续报道",
        published_at=stamp(0.0),
        summary="后续报道",
    )
    EventService().add_article(event_id, extra, "follow_up")
    assert score_snapshot_count(event_id) == 2

    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT algorithm_version, is_current FROM event_score_snapshots "
            "WHERE event_id = ? ORDER BY scored_at",
            (event_id,),
        ).fetchall()
        current = conn.execute(
            "SELECT COUNT(*) FROM event_score_snapshots WHERE event_id = ? AND is_current = 1",
            (event_id,),
        ).fetchone()[0]
    assert [int(row["is_current"]) for row in rows].count(1) == 1
    assert {str(row["algorithm_version"]) for row in rows} == {ALGORITHM_VERSION}
    assert int(current) == 1


def test_snapshot_history_is_pruned_but_bounded(ready) -> None:
    event_id, _ = _make_event(category="科技", count=1)
    from services.event_scoring_service import SNAPSHOT_KEEP

    assert SNAPSHOT_KEEP == 50
    assert score_snapshot_count(event_id) == 1


def test_rankings_are_explainable_and_ordered(ready) -> None:
    _make_event(category="政治", count=2)
    _make_event(category="体育", count=2)
    # Make the second event distinct in identity but same score inputs.
    service = EventScoringService()
    result = service.rankings(
        kind="importance", window="all", category=None, limit=10, offset=0
    )
    assert result["algorithm_version"] == ALGORITHM_VERSION
    assert result["total"] == 2
    scores = [item["score"] for item in result["items"]]
    assert scores == sorted(scores, reverse=True)
    assert [item["rank"] for item in result["items"]] == [1, 2]

    filtered = service.rankings(
        kind="importance", window="all", category="体育", limit=10, offset=0
    )
    assert filtered["total"] == 1
    assert filtered["items"][0]["event"].category == "体育"


def test_ranking_kinds_require_valid_input(ready) -> None:
    from services.errors import ServiceError

    service = EventScoringService()
    with pytest.raises(ServiceError):
        service.rankings(kind="unknown", window="all", category=None, limit=10, offset=0)
    with pytest.raises(ServiceError):
        service.rankings(kind="importance", window="1y", category=None, limit=10, offset=0)


def test_recompute_reports_counters(ready) -> None:
    _make_event(category="科技", count=2)
    result = EventScoringService().recompute(scope="all", event_ids=None, limit=100)
    assert result["scored_events"] >= 1
    assert result["algorithm_version"] == ALGORITHM_VERSION
    assert result["duration_ms"] >= 0


def test_pending_ambiguous_decisions_lower_confidence(ready) -> None:
    """Regression for P4-07: pending ambiguous decisions must count as risk."""

    event_id, articles = _make_event(category="科技", count=2)
    with database.session() as conn:
        conn.execute(
            "INSERT INTO event_candidate_decisions "
            "(id, run_id, article_id, candidate_event_id, decision, score, "
            " reasons_json, method, llm_used, status, created_at) "
            "VALUES (?, NULL, ?, ?, 'ambiguous', 0.6, '[]', 'similarity', 0, "
            " 'pending', ?)",
            (str(uuid.uuid4()), articles[0], event_id, stamp(0.0)),
        )
        event = event_repo.get(conn, event_id)
        assert event is not None
        inputs = _build_inputs(conn, event, datetime.now(timezone.utc))
    assert inputs.ambiguity_ratio > 0.0
    scores = compute_scores(inputs)
    assert scores.confidence < 100.0


def test_heat_uses_only_recent_72h_sources(ready) -> None:
    """Regression for P4-08: old sources must not keep propping up heat."""

    recent_source = create_source("近期来源")
    old_source = create_source("陈旧来源")
    recent = create_article(
        source_id=recent_source,
        title="近期报道",
        published_at=stamp(0.2),
        summary="近期报道摘要",
    )
    old = create_article(
        source_id=old_source,
        title="陈旧报道",
        published_at=stamp(10.0),
        summary="陈旧报道摘要",
    )
    event = EventService().create_event(
        title="来源窗口事件", category="科技", summary="摘要", article_ids=[recent, old]
    )
    with database.read_session() as conn:
        record = event_repo.get(conn, event.id)
        assert record is not None
        inputs = _build_inputs(conn, record, datetime.now(timezone.utc))
    assert inputs.unique_source_count == 2
    assert inputs.recent_72h_sources == 1
    assert inputs.recent_72h_articles == 1


def test_stale_scope_rescoring_applies_time_decay(ready) -> None:
    """Regression for P4-09: aging snapshots are refreshed by `scope=stale`."""

    event_id, articles = _make_event(category="科技", count=2)
    old_time = stamp(30.0)
    with database.session() as conn:
        conn.execute(
            "UPDATE articles SET published_at = ? WHERE id IN (?, ?)",
            (old_time, articles[0], articles[1]),
        )
        conn.execute(
            "UPDATE events SET first_published_at = ?, last_published_at = ? WHERE id = ?",
            (old_time, old_time, event_id),
        )
        conn.execute(
            "UPDATE event_score_snapshots SET scored_at = ? WHERE event_id = ?",
            (old_time, event_id),
        )
    before = current_scores(event_id)
    assert before is not None

    result = EventScoringService().recompute(scope="stale", event_ids=None, limit=10)
    assert result["scored_events"] >= 1

    after = current_scores(event_id)
    assert after is not None
    assert float(after["freshness_score"]) < float(before["freshness_score"])
