"""Explainable event scoring, score history and rankings (Phase 4)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import database
from core.timeutil import utc_timestamp
from database.repositories import event_cluster_run_repository as cluster_repo
from database.repositories import event_repository as event_repo
from database.repositories import event_score_repository as score_repo
from database.repositories.models import EventRecord, EventScoreRecord
from event_intelligence.scoring import ALGORITHM_VERSION, ScoreInputs, compute_scores
from event_intelligence.text import parse_timestamp
from services.errors import ServiceError, conflict, validation

MAX_BATCH = 200
SNAPSHOT_KEEP = 50
STALE_AFTER_HOURS = 24
WINDOW_HOURS = {"24h": 24, "7d": 168, "30d": 720}


def _cutoff(window: str) -> str | None:
    hours = WINDOW_HOURS.get(window)
    if hours is None:
        return None
    moment = datetime.now(timezone.utc) - timedelta(hours=hours)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _build_inputs(conn: sqlite3.Connection, event: EventRecord, now: datetime) -> ScoreInputs:
    stats = event_repo.event_stats(conn, event.id)
    content_times = event_repo.content_source_times(conn, event.id)
    times = [parse_timestamp(value) for value, _ in content_times]
    times = [value for value in times if value is not None]

    recent_72h = sum(1 for value in times if (now - value) <= timedelta(hours=72))
    recent_24h = sum(1 for value in times if (now - value) <= timedelta(hours=24))
    previous_24h = sum(
        1
        for value in times
        if timedelta(hours=24) < (now - value) <= timedelta(hours=48)
    )
    recent_72h_sources = len(
        {
            source_id
            for raw, source_id in content_times
            if (parsed := parse_timestamp(raw)) is not None
            and (now - parsed) <= timedelta(hours=72)
        }
    )
    first = parse_timestamp(stats["first_published_at"])
    last = parse_timestamp(stats["last_published_at"])
    duration_days = 0.0
    if first is not None and last is not None:
        duration_days = max(0.0, (last - first).total_seconds() / 86400.0)

    entity_stats = event_repo.event_entity_stats(conn, event.id)
    decisions = cluster_repo.count_decisions_for_event(conn, event.id)
    ambiguous = cluster_repo.count_ambiguous_for_event(conn, event.id)
    ambiguity_ratio = (ambiguous / decisions) if decisions else 0.0

    return ScoreInputs(
        category=event.category,
        article_count=int(stats["article_count"]),
        unique_content_count=int(stats["content_count"]),
        unique_source_count=int(stats["source_count"]),
        recent_72h_articles=recent_72h,
        recent_72h_sources=recent_72h_sources,
        recent_24h_articles=recent_24h,
        previous_24h_articles=previous_24h,
        org_count=int(entity_stats["org_count"]),
        person_count=int(entity_stats["person_count"]),
        location_count=int(entity_stats["location_count"]),
        duration_days=duration_days,
        avg_entity_confidence=float(entity_stats["avg_confidence"]),
        ambiguity_ratio=ambiguity_ratio,
        is_manual=event.is_manual,
        last_published_at=event.last_published_at,
        last_seen_at=event.last_seen_at,
    )


def score_event_in_conn(
    conn: sqlite3.Connection, event_id: str, *, now: str | None = None
) -> tuple[EventScoreRecord | None, bool]:
    """Score one event inside the caller's transaction.

    Returns ``(snapshot, created)``; ``created`` is False when the inputs and
    scores are unchanged and the current snapshot's ``scored_at`` is refreshed.
    """

    event = event_repo.get(conn, event_id)
    if event is None or event.status in {"merged", "archived"}:
        return None, False
    moment = parse_timestamp(now) or datetime.now(timezone.utc)
    result = compute_scores(_build_inputs(conn, event, moment))
    current = score_repo.current(conn, event.id)
    unchanged = (
        current is not None
        and current.algorithm_version == result.algorithm_version
        and current.inputs == result.inputs
        and current.importance_score == result.importance
        and current.heat_score == result.heat
        and current.freshness_score == result.freshness
        and current.coverage_score == result.coverage
        and current.confidence_score == result.confidence
        and current.total_score == result.total
    )
    if unchanged and current is not None:
        scored_at = now or utc_timestamp()
        score_repo.touch(conn, current.id, scored_at)
        return current, False

    scored_at = now or utc_timestamp()
    score_repo.clear_current(conn, event.id)
    snapshot_id = str(uuid.uuid4())
    score_repo.insert(
        conn,
        {
            "id": snapshot_id,
            "event_id": event.id,
            "algorithm_version": result.algorithm_version,
            "scored_at": scored_at,
            "importance_score": result.importance,
            "heat_score": result.heat,
            "freshness_score": result.freshness,
            "coverage_score": result.coverage,
            "confidence_score": result.confidence,
            "total_score": result.total,
            "inputs_json": json.dumps(result.inputs, ensure_ascii=False, separators=(",", ":")),
            "explanation_json": json.dumps(
                result.explanation, ensure_ascii=False, separators=(",", ":")
            ),
            "is_current": 1,
            "created_at": scored_at,
        },
    )
    score_repo.prune(conn, event.id, SNAPSHOT_KEEP)
    return score_repo.current(conn, event.id), True


def score_event(event_id: str) -> EventScoreRecord | None:
    now = utc_timestamp()
    with database.session() as conn:
        snapshot, _ = score_event_in_conn(conn, event_id, now=now)
        return snapshot


class EventScoringService:
    def snapshots(
        self, event_id: str, *, limit: int, offset: int
    ) -> tuple[list[EventScoreRecord], int]:
        with database.read_session() as conn:
            event = event_repo.get(conn, event_id)
            if event is None:
                from services.errors import not_found

                raise not_found("event_not_found", "事件不存在")
            return score_repo.list_snapshots(conn, event_id, limit=limit, offset=offset)

    def recompute(
        self,
        *,
        scope: str,
        event_ids: list[str] | None,
        limit: int,
    ) -> dict[str, object]:
        if scope not in {"stale", "all", "selected"}:
            raise ServiceError("score_scope_invalid", 422, "scope 必须是 stale、all 或 selected")
        bounded = max(1, min(int(limit), MAX_BATCH))
        if scope == "selected":
            if not event_ids:
                raise validation("event_ids", "required", "至少选择一个事件")
            if len(set(event_ids)) > MAX_BATCH:
                raise conflict("event_batch_too_large", "单次最多重算 200 个事件")
            candidates = list(dict.fromkeys(event_ids))
        elif scope == "stale":
            stale_before = (
                datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            with database.read_session() as conn:
                candidates = score_repo.list_event_ids_needing_score(
                    conn,
                    limit=bounded,
                    algorithm_version=ALGORITHM_VERSION,
                    stale_before=stale_before,
                )
        else:
            with database.read_session() as conn:
                candidates = score_repo.list_scored_event_ids(conn, limit=bounded)

        scored = 0
        created = 0
        unchanged = 0
        failed = 0
        started = time.monotonic()
        for event_id in candidates:
            try:
                with database.session() as conn:
                    _, did_create = score_event_in_conn(conn, event_id)
                scored += 1
                if did_create:
                    created += 1
                else:
                    unchanged += 1
            except Exception:  # noqa: BLE001 - one event must not stop the batch
                failed += 1

        return {
            "scored_events": scored,
            "created_snapshots": created,
            "skipped_unchanged": unchanged,
            "failed_events": failed,
            "algorithm_version": ALGORITHM_VERSION,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    def rankings(
        self,
        *,
        kind: str,
        window: str,
        category: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        if kind not in {"importance", "recent", "heat", "emerging", "confidence", "new"}:
            raise validation("kind", "invalid", "kind 不在允许范围")
        if window not in {"24h", "7d", "30d", "all"}:
            raise validation("window", "invalid", "window 不在允许范围")
        cutoff = _cutoff(window) if window != "all" else None
        order = kind

        with database.read_session() as conn:
            records, total = event_repo.list_ranked_events(
                conn,
                kind=order,
                limit=limit,
                offset=offset,
                category=category,
                cutoff=cutoff,
            )
            items: list[dict[str, object]] = []
            for index, event in enumerate(records):
                scores = event.current_scores
                if kind == "recent":
                    score = float(scores.freshness_score) if scores else 0.0
                elif kind == "emerging" and scores is not None:
                    score = round(
                        0.6 * float(scores.heat_score) + 0.4 * float(scores.freshness_score),
                        2,
                    )
                elif kind == "new" and scores is not None:
                    score = float(scores.total_score)
                elif kind == "heat" and scores is not None:
                    score = float(scores.heat_score)
                elif kind == "confidence" and scores is not None:
                    score = float(scores.confidence_score)
                elif scores is not None:
                    score = float(scores.importance_score)
                else:
                    score = 0.0

                previous_total = None
                change = None
                if scores is not None:
                    previous = score_repo.previous(conn, event.id, scores.id)
                    if previous is not None:
                        previous_total = previous.total_score
                        change = round(scores.total_score - previous.total_score, 2)
                items.append(
                    {
                        "rank": offset + index + 1,
                        "event": event,
                        "score": score,
                        "previous_total_score": previous_total,
                        "score_change": change,
                    }
                )

        return {
            "kind": kind,
            "window": window,
            "algorithm_version": ALGORITHM_VERSION,
            "generated_at": utc_timestamp(),
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


_scoring_service: EventScoringService | None = None


def get_scoring_service() -> EventScoringService:
    global _scoring_service
    if _scoring_service is None:
        _scoring_service = EventScoringService()
    return _scoring_service
