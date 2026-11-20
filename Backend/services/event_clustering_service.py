"""Incremental event clustering worker (Phase 4).

Deterministic L1/L2 clustering plus optional local-LLM L3 for ambiguous pairs.
One worker thread, per-article transactions, persisted decisions, manual
boundaries are never overridden.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import replace

import database
from core.logging import log_event
from core.timeutil import utc_timestamp
from database.repositories import event_cluster_run_repository as cluster_repo
from database.repositories import event_audit_repository as audit_repo
from database.repositories import event_relation_repository as relation_repo
from database.repositories import event_repository as event_repo
from database.repositories.models import EventClusterRunRecord, EventRecord
from event_intelligence.clustering import (
    AMBIGUOUS_THRESHOLD,
    ArticleFeatures,
    EventFeatures,
    PairScore,
    score_article_against_event,
)
from event_intelligence.lifecycle import next_status, transition_reason
from event_intelligence.relations import generate_relation_candidates
from event_intelligence.summary import build_event_summary
from event_intelligence.text import hours_between, normalize_text
from event_intelligence.taxonomy import event_domain_name
from services.classification_service import refresh_event_category
from services.entity_service import sync_article
from services.errors import conflict, not_found, validation
from services.event_aggregation import (
    rebuild_event_entities,
    recompute_event_aggregates,
    refresh_event_summary,
)
from services.event_ai_judge import AmbiguousJudge, JudgeOutcome
from services.event_scoring_service import ALGORITHM_VERSION, score_event_in_conn

CLUSTER_VERSION = "event-cluster-v1"
MAX_ARTICLES = 500
MAX_SELECTED = 100
MAX_EVENTS = 200
EVENT_WINDOW_DAYS = 30
MAX_CANDIDATE_EVENTS = 10
RUN_KEEP = 200
TERMINAL = {"merged", "archived", "closed"}


def _keywords(value: object) -> frozenset[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(parsed, list):
        return frozenset()
    result = set()
    for item in parsed:
        if isinstance(item, str) and item.strip():
            result.add(item.strip().lower()[:50])
    return frozenset(result)


def _category(value: str | None) -> str:
    return event_domain_name(value)


def _summaries(values: list[str | None]) -> tuple[str, ...]:
    return tuple(value for value in values if value)[-3:]


def _titles(values: list[str]) -> tuple[str, ...]:
    return tuple(value for value in values if value)[-3:]


class EventClusteringService:
    def __init__(self, judge: AmbiguousJudge | None = None) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._judge = judge or AmbiguousJudge()

    # ------------------------------------------------------------------
    # lifecycle of the worker
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            try:
                with database.session() as conn:
                    interrupted = cluster_repo.mark_stale(conn, utc_timestamp())
                    pending = cluster_repo.list_pending_run_ids(conn)
            except Exception as exc:  # noqa: BLE001 - degraded DB must not block startup
                log_event(
                    "event_clustering_recovery_skipped",
                    level="warn",
                    exc_type=type(exc).__name__,
                )
                return
            if interrupted:
                log_event("event_clustering_interrupted", count=interrupted, level="warn")
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._worker, name="event-clustering", daemon=True
            )
            self._thread.start()
            for run_id in pending:
                self._queue.put(run_id)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._thread = None

    def _worker(self) -> None:
        while not self._stop.is_set():
            run_id = self._queue.get()
            if run_id is None:
                break
            try:
                self._execute(run_id)
            except Exception as exc:  # noqa: BLE001 - worker must not die
                log_event(
                    "event_clustering_run_crashed",
                    level="error",
                    run_id=run_id,
                    exc_type=type(exc).__name__,
                )
                self._fail_run(run_id, "聚类任务异常终止")
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # public operations
    # ------------------------------------------------------------------

    def create_run(
        self,
        *,
        scope: str,
        article_ids: list[str] | None,
        limit: int,
        use_llm: bool,
        trigger_type: str = "manual",
    ) -> EventClusterRunRecord:
        if scope not in {"incremental", "full", "selected"}:
            raise validation("scope", "invalid", "scope 必须是 incremental、full 或 selected")
        if os.getenv("PIH_EVENT_CLUSTERING_ENABLED", "1") != "1":
            raise conflict("clustering_disabled", "事件聚类已被配置关闭")
        bounded = max(1, min(int(limit), MAX_ARTICLES))
        now = utc_timestamp()

        with database.read_session() as conn:
            active = cluster_repo.any_active_run(conn)
            if active is not None:
                raise conflict(
                    "clustering_run_in_progress",
                    "已有聚类任务在排队或运行中",
                )
            if scope == "selected":
                if not article_ids:
                    raise validation("article_ids", "required", "selected 必须提供文章 ID")
                if len(article_ids) > MAX_SELECTED:
                    raise validation("article_ids", "too_many", "单次最多选择 100 篇文章")
                unique_ids = list(dict.fromkeys(article_ids))
                for article_id in unique_ids:
                    if event_repo.article_feature_row(conn, article_id) is None:
                        raise validation(
                            "article_ids", "not_found", f"文章不存在或不可用：{article_id}"
                        )
                ids = unique_ids
            else:
                ids = event_repo.eligible_article_ids(
                    conn, limit=bounded, include_assigned=False
                )
                if not ids and scope == "incremental":
                    raise conflict("no_clusterable_articles", "没有可聚类的未归属文章")
                if not ids and scope == "full":
                    events, total = event_repo.list_events(conn, limit=1, offset=0)
                    if total == 0:
                        raise conflict("no_clusterable_articles", "没有可聚类的文章或事件")

        run_id = str(uuid.uuid4())
        with database.session() as conn:
            cluster_repo.insert_run(
                conn,
                {
                    "id": run_id,
                    "trigger_type": trigger_type,
                    "scope": scope,
                    "status": "pending",
                    "requested_count": len(ids),
                    "processed_count": 0,
                    "attached_count": 0,
                    "created_event_count": 0,
                    "updated_event_count": 0,
                    "candidate_pair_count": 0,
                    "ambiguous_count": 0,
                    "llm_called_count": 0,
                    "llm_accepted_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "use_llm": 1 if use_llm else 0,
                    "article_ids_json": json.dumps(ids, ensure_ascii=False, separators=(",", ":")),
                    "model_name": None,
                    "error_message": None,
                    "cancel_requested": 0,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            cluster_repo.prune_runs(conn, RUN_KEEP)
            cluster_repo.prune_decisions(conn, keep_runs=RUN_KEEP)
        self.start()
        self._queue.put(run_id)
        run = self.get_run(run_id)
        if run is None:
            raise not_found("clustering_run_not_found", "聚类任务不存在")
        return run

    def get_run(self, run_id: str) -> EventClusterRunRecord:
        with database.read_session() as conn:
            run = cluster_repo.get_run(conn, run_id)
            if run is None:
                raise not_found("clustering_run_not_found", "聚类任务不存在")
            return run

    def list_runs(
        self, *, limit: int, offset: int, status: str | None
    ) -> tuple[list[EventClusterRunRecord], int]:
        with database.read_session() as conn:
            return cluster_repo.list_runs(conn, limit=limit, offset=offset, status=status)

    def cancel(self, run_id: str) -> EventClusterRunRecord:
        now = utc_timestamp()
        with database.session() as conn:
            run = cluster_repo.get_run(conn, run_id)
            if run is None:
                raise not_found("clustering_run_not_found", "聚类任务不存在")
            if run.status not in {"pending", "running"}:
                raise conflict("clustering_run_not_cancellable", "该任务当前不可取消")
            if run.status == "pending":
                cluster_repo.update_run(
                    conn,
                    run_id,
                    {
                        "status": "cancelled",
                        "cancel_requested": 1,
                        "finished_at": now,
                        "updated_at": now,
                    },
                )
            else:
                cluster_repo.update_run(
                    conn, run_id, {"cancel_requested": 1, "updated_at": now}
                )
            updated = cluster_repo.get_run(conn, run_id)
            if updated is None:
                raise not_found("clustering_run_not_found", "聚类任务不存在")
            return updated

    def retry(self, run_id: str) -> EventClusterRunRecord:
        previous = self.get_run(run_id)
        if previous.status not in {"failed", "partially_succeeded", "cancelled"}:
            raise conflict("clustering_run_not_retryable", "该任务当前不可重试")
        if previous.trigger_type == "retry":
            raise conflict(
                "clustering_run_not_retryable",
                "重试任务再次失败时不再自动重试，请检查错误后手动发起新任务",
            )
        return self.create_run(
            scope=previous.scope,
            article_ids=list(previous.article_ids),
            limit=max(1, min(len(previous.article_ids) or previous.requested_count, MAX_ARTICLES)),
            use_llm=previous.use_llm,
            trigger_type="retry",
        )

    def status(self) -> dict[str, object]:
        enabled = os.getenv("PIH_EVENT_CLUSTERING_ENABLED", "1") == "1"
        with database.read_session() as conn:
            active = cluster_repo.any_active_run(conn)
            latest = cluster_repo.latest_run(conn)
        llm_available = False
        try:
            health = self._judge.health()
            llm_available = bool(health.available)
        except Exception:  # noqa: BLE001 - status must stay available
            llm_available = False
        return {
            "enabled": enabled,
            "running_run_id": active.id if active is not None else None,
            "queue_depth": self._queue.qsize(),
            "llm_enabled": llm_available,
            "last_run_id": latest.id if latest is not None else None,
            "last_run_status": latest.status if latest is not None else None,
            "last_run_at": latest.created_at if latest is not None else None,
            "algorithm_version": CLUSTER_VERSION,
        }

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    def _execute(self, run_id: str) -> None:
        now = utc_timestamp()
        with database.session() as conn:
            run = cluster_repo.get_run(conn, run_id)
            if run is None or run.status != "pending":
                return
            cluster_repo.update_run(
                conn,
                run_id,
                {"status": "running", "started_at": now, "updated_at": now},
            )
            run = cluster_repo.get_run(conn, run_id)
            if run is None:
                return

        counters = {
            "processed_count": 0,
            "attached_count": 0,
            "created_event_count": 0,
            "updated_event_count": 0,
            "candidate_pair_count": 0,
            "ambiguous_count": 0,
            "llm_called_count": 0,
            "llm_accepted_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
        }
        affected: set[str] = set()
        judge_model: str | None = None
        started = time.monotonic()

        with database.read_session() as conn:
            cache, statuses = self._build_cache(conn)
        log_event(
            "event_clustering_started",
            run_id=run_id,
            scope=run.scope,
            articles=len(run.article_ids),
            events=len(cache),
            use_llm=run.use_llm,
        )

        for article_id in run.article_ids:
            if self._stop.is_set():
                break
            if self._is_cancel_requested(run_id):
                break
            try:
                action = self._process_article(
                    run_id=run_id,
                    article_id=article_id,
                    cache=cache,
                    use_llm=run.use_llm,
                    counters=counters,
                    affected=affected,
                    statuses=statuses,
                )
                if action is not None and self._judge.model_name:
                    judge_model = self._judge.model_name
            except Exception as exc:  # noqa: BLE001 - isolate one article
                counters["processed_count"] += 1
                counters["failed_count"] += 1
                log_event(
                    "event_clustering_article_failed",
                    level="warn",
                    run_id=run_id,
                    article_id=article_id,
                    exc_type=type(exc).__name__,
                )
                self._persist_counters(run_id, counters)

        if self._is_cancel_requested(run_id):
            self._finalize(run_id, counters, started, status="cancelled", model_name=judge_model)
            return

        try:
            if run.scope == "full":
                affected |= set(cache.keys())
            self._post_process(affected=affected, cache=cache, counters=counters)
        except Exception as exc:  # noqa: BLE001
            log_event(
                "event_clustering_post_process_failed",
                level="error",
                run_id=run_id,
                exc_type=type(exc).__name__,
            )
            counters["failed_count"] += 1

        status = "succeeded" if counters["failed_count"] == 0 else (
            "partially_succeeded" if counters["processed_count"] > 0 else "failed"
        )
        self._finalize(run_id, counters, started, status=status, model_name=judge_model)

    def _process_article(
        self,
        *,
        run_id: str,
        article_id: str,
        cache: dict[str, EventFeatures],
        use_llm: bool,
        counters: dict[str, int],
        affected: set[str],
        statuses: dict[str, str],
    ) -> str | None:
        now = utc_timestamp()
        # 1. Entity normalisation for this article (own transaction).
        with database.session() as conn:
            sync_article(conn, article_id, now=now, stats={})

        # 2. Read features and candidates. The optional LLM call is made only
        #    after this read session is closed (no network I/O inside SQLite).
        judge_outcome: JudgeOutcome | None = None
        judge_event: EventFeatures | None = None
        judge_members: list[tuple[str, str, str | None]] = []
        best_event: str | None = None
        best_score: PairScore | None = None
        article: ArticleFeatures | None = None
        skip_reason: str | None = None
        membership_event_id: str | None = None
        with database.read_session() as conn:
            membership = event_repo.get_article_membership(conn, article_id)
            if membership is not None:
                skip_reason = "article_already_assigned"
                membership_event_id = str(membership["event_id"])
            else:
                article = self._article_features(conn, article_id)
                if article is None:
                    skip_reason = "article_not_available"
                else:
                    excluded = event_repo.excluded_event_ids(conn, article_id)
                    candidates = self._candidate_scores(article, cache, excluded)
                    if candidates:
                        candidates.sort(key=lambda item: item[0].total, reverse=True)
                        best_score, best_event = candidates[0]
                        counters["candidate_pair_count"] += sum(
                            1 for score, _ in candidates if score.total >= 0.4
                        )
                    if (
                        best_score is not None
                        and best_event is not None
                        and best_score.decision == "ambiguous"
                        and use_llm
                        and counters["llm_called_count"] < 20
                    ):
                        event = cache.get(best_event)
                        if event is not None:
                            judge_event = event
                            judge_members = [
                                (
                                    str(row["id"]),
                                    str(row["title"]),
                                    row["ai_summary"] or row["summary"],
                                )
                                for row in event_repo.list_member_rows(conn, best_event)[-4:]
                            ]

        if judge_event is not None and article is not None:
            counters["llm_called_count"] += 1
            judge_outcome = self._judge.judge(
                article=article, event=judge_event, member_rows=judge_members
            )

        if skip_reason is not None:
            counters["processed_count"] += 1
            counters["skipped_count"] += 1
            if membership_event_id is not None:
                with database.session() as conn:
                    self._record_decision(
                        conn,
                        run_id=run_id,
                        article_id=article_id,
                        event_id=membership_event_id,
                        decision="skipped",
                        score=None,
                        reasons=[skip_reason],
                        method="rules",
                        status="resolved",
                        now=now,
                    )
                    self._update_counts(conn, run_id, counters)
            else:
                self._persist_counters(run_id, counters)
            return None

        assert article is not None

        # 3. Write decision in one transaction.
        with database.session() as conn:
            if event_repo.get_article_membership(conn, article_id) is not None:
                counters["processed_count"] += 1
                counters["skipped_count"] += 1
                self._update_counts(conn, run_id, counters)
                return None

            if judge_outcome is not None and AmbiguousJudge.accepts(judge_outcome):
                event = event_repo.get(conn, best_event) if best_event else None
                if event is not None and not event.is_manual and event.status not in TERMINAL:
                    changed = self._attach_article(
                        conn,
                        event_id=event.id,
                        article=article,
                        score=best_score,
                        now=now,
                        is_manual=False,
                    )
                    if changed is not None:
                        counters["attached_count"] += 1
                        counters["updated_event_count"] += 1
                        counters["llm_accepted_count"] += 1
                        counters["processed_count"] += 1
                        affected.add(event.id)
                        self._record_decision(
                            conn,
                            run_id=run_id,
                            article_id=article_id,
                            event_id=event.id,
                            decision="llm_accepted",
                            score=best_score.total if best_score else None,
                            reasons=(
                                *(best_score.reasons if best_score else ()),
                                f"llm_confidence={judge_outcome.confidence:.2f}",
                                f"llm_reason={judge_outcome.reason[:120]}",
                            ),
                            method="llm",
                            status="resolved",
                            now=now,
                            llm_used=True,
                        )
                        self._merge_cache(cache, event.id, article)
                        self._update_counts(conn, run_id, counters)
                        return "llm_attached"

            if (
                best_score is not None
                and best_event is not None
                and best_score.decision == "attach"
            ):
                event = event_repo.get(conn, best_event)
                if event is not None and not event.is_manual and event.status not in TERMINAL:
                    changed = self._attach_article(
                        conn,
                        event_id=event.id,
                        article=article,
                        score=best_score,
                        now=now,
                        is_manual=False,
                    )
                    if changed is not None:
                        counters["attached_count"] += 1
                        counters["updated_event_count"] += 1
                        counters["processed_count"] += 1
                        affected.add(event.id)
                        self._record_decision(
                            conn,
                            run_id=run_id,
                            article_id=article_id,
                            event_id=event.id,
                            decision="attached",
                            score=best_score.total,
                            reasons=best_score.reasons,
                            method="similarity",
                            status="resolved",
                            now=now,
                        )
                        self._merge_cache(cache, event.id, article)
                        self._update_counts(conn, run_id, counters)
                        return "attached"

            if (
                best_score is not None
                and best_event is not None
                and best_score.decision == "ambiguous"
            ):
                counters["ambiguous_count"] += 1
                counters["processed_count"] += 1
                reasons = list(best_score.reasons)
                if judge_outcome is not None:
                    reasons.append(f"llm_same_event={judge_outcome.same_event}")
                    reasons.append(f"llm_confidence={judge_outcome.confidence:.2f}")
                    if judge_outcome.reason:
                        reasons.append(f"llm_reason={judge_outcome.reason[:120]}")
                self._record_decision(
                    conn,
                    run_id=run_id,
                    article_id=article_id,
                    event_id=best_event,
                    decision="ambiguous",
                    score=best_score.total,
                    reasons=tuple(reasons),
                    method="llm" if judge_outcome is not None else "similarity",
                    status="pending",
                    now=now,
                    llm_used=judge_outcome is not None,
                )
                self._update_counts(conn, run_id, counters)
                return "ambiguous"

            event_id = self._create_event(conn, article, now)
            self._attach_article(
                conn,
                event_id=event_id,
                article=article,
                score=None,
                now=now,
                is_manual=False,
            )
            counters["attached_count"] += 1
            counters["created_event_count"] += 1
            counters["processed_count"] += 1
            affected.add(event_id)
            self._record_decision(
                conn,
                run_id=run_id,
                article_id=article_id,
                event_id=event_id,
                decision="created",
                score=None,
                reasons=["no_matching_event", "event_created"],
                method="similarity",
                status="resolved",
                now=now,
            )
            self._add_to_cache(cache, event_id, article)
            statuses[event_id] = "candidate"
            self._update_counts(conn, run_id, counters)
            return "created"

    def _post_process(
        self,
        *,
        affected: set[str],
        cache: dict[str, EventFeatures],
        counters: dict[str, int],
    ) -> None:
        now = utc_timestamp()
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=EVENT_WINDOW_DAYS)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        with database.read_session() as conn:
            rows = event_repo.events_for_clustering(conn, cutoff=cutoff, limit=MAX_EVENTS)
            relation_cache = dict(cache)
            for row in rows:
                event_id = str(row["id"])
                if event_id in relation_cache or str(row["status"]) in TERMINAL:
                    continue
                relation_cache[event_id] = self._event_features(conn, row)
            mentions = {
                event_id: event_repo.event_entity_mentions(conn, event_id)
                for event_id in relation_cache
            }
        candidates = generate_relation_candidates(
            list(relation_cache.values()), mentions_by_event=mentions, limit=200
        )
        with database.session() as conn:
            for candidate in candidates:
                relation_repo.upsert_algorithm_candidate(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "source_event_id": candidate.source_event_id,
                        "target_event_id": candidate.target_event_id,
                        "relation_type": candidate.relation_type,
                        "confidence": candidate.confidence,
                        "status": "candidate",
                        "rationale": candidate.rationale,
                        "evidence_article_ids_json": json.dumps(
                            candidate.evidence_article_ids,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "actor": "algorithm",
                        "algorithm_version": "event-relation-v1",
                        "created_at": now,
                        "updated_at": now,
                    },
                )

        event_ids = affected or set(cache.keys())
        for event_id in event_ids:
            try:
                with database.session() as conn:
                    self._refresh_lifecycle(conn, event_id, now)
                    score_event_in_conn(conn, event_id, now=now)
            except Exception:  # noqa: BLE001
                counters["failed_count"] += 1
                log_event(
                    "event_clustering_post_event_failed",
                    level="warn",
                    event_id=event_id,
                    exc_type="scoring_or_lifecycle",
                )

    # ------------------------------------------------------------------
    # features and scoring
    # ------------------------------------------------------------------

    def _build_cache(
        self, conn: sqlite3.Connection
    ) -> tuple[dict[str, EventFeatures], dict[str, str]]:
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=EVENT_WINDOW_DAYS)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        rows = event_repo.events_for_clustering(conn, cutoff=cutoff, limit=MAX_EVENTS)
        cache: dict[str, EventFeatures] = {}
        statuses: dict[str, str] = {}
        for row in rows:
            if bool(int(row["is_manual"])) or str(row["status"]) in TERMINAL:
                continue
            feature = self._event_features(conn, row)
            cache[feature.id] = feature
            statuses[feature.id] = str(row["status"])
        return cache, statuses

    def _article_features(
        self, conn: sqlite3.Connection, article_id: str
    ) -> ArticleFeatures | None:
        row = event_repo.article_feature_row(conn, article_id)
        if row is None:
            return None
        entity_ids, entity_keys, event_entity_ids, event_entity_keys = (
            event_repo.article_entity_keys(conn, article_id)
        )
        return ArticleFeatures(
            id=str(row["id"]),
            title=normalize_text(row["title"])[:300] or "未命名文章",
            summary=(
                row["ai_summary"]
                or row["summary"]
                or (row["content_text"] or "")[:500]
                or None
            ),
            published_at=row["published_at"],
            source_id=str(row["source_id"]),
            category=_category(row["ai_category"] or row["source_category"]),
            keywords=_keywords(row["ai_keywords"]),
            entity_ids=frozenset(entity_ids),
            entity_keys=frozenset(entity_keys),
            event_entity_ids=frozenset(event_entity_ids),
            event_entity_keys=frozenset(event_entity_keys),
            content_hash=str(row["content_hash"] or ""),
        )

    def _event_features(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> EventFeatures:
        event_id = str(row["id"])
        members = event_repo.list_member_rows(conn, event_id)
        entity_ids, entity_keys, event_entity_ids, event_entity_keys = (
            event_repo.event_entity_union(conn, event_id)
        )
        # event_entity_union returns lists; ambiguous keys are a set.
        entity_keys = set(entity_keys) | event_repo.event_ambiguous_keys(conn, event_id)
        return EventFeatures(
            id=event_id,
            title=str(row["title"]),
            summary=row["summary"],
            category=str(row["category"]),
            entity_ids=frozenset(entity_ids),
            entity_keys=frozenset(entity_keys),
            event_entity_ids=frozenset(event_entity_ids),
            event_entity_keys=frozenset(event_entity_keys),
            keywords=frozenset(event_repo.event_keywords(conn, event_id)),
            member_article_ids=tuple(str(member["id"]) for member in members),
            member_titles=_titles([str(member["title"]) for member in members]),
            member_summaries=_summaries(
                [member["ai_summary"] or member["summary"] for member in members]
            ),
            member_content_hashes=tuple(
                str(member["content_hash"] or "") for member in members
            ),
            source_ids=frozenset(str(member["source_id"]) for member in members),
            first_published_at=row["first_published_at"],
            last_published_at=row["last_published_at"],
            article_count=len(members),
            is_manual=bool(int(row["is_manual"])),
        )

    def _candidate_scores(
        self,
        article: ArticleFeatures,
        cache: dict[str, EventFeatures],
        excluded: set[str],
    ) -> list[tuple[PairScore, str]]:
        primary: list[tuple[PairScore, str]] = []
        fallback: list[tuple[PairScore, str]] = []
        for event in cache.values():
            if event.id in excluded or event.is_manual:
                continue
            overlap = bool(
                (article.entity_ids & event.entity_ids)
                or (article.entity_keys & event.entity_keys)
                or (article.keywords & event.keywords)
                or (
                    article.content_hash
                    and article.content_hash in event.member_content_hashes
                )
            )
            score = score_article_against_event(article, event)
            if overlap:
                primary.append((score, event.id))
            elif article.category and article.category == event.category:
                fallback.append((score, event.id))
        if primary:
            # Rank before truncating: generic shared keywords can make hundreds
            # of events "candidates", and the correct one must not be cut off.
            ordered = sorted(
                primary,
                key=lambda item: (item[0].total, item[0].shared_event_entity),
                reverse=True,
            )
        else:
            ordered = sorted(fallback, key=lambda item: item[0].total, reverse=True)[:30]
        return ordered[:MAX_CANDIDATE_EVENTS]

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def _create_event(
        self, conn: sqlite3.Connection, article: ArticleFeatures, now: str
    ) -> str:
        event_id = str(uuid.uuid4())
        title = article.title[:300] or "未命名事件"
        summary = (article.summary or title)[:2000]
        event_repo.insert_event(
            conn,
            {
                "id": event_id,
                "title": title,
                "summary": summary,
                "category": _category(article.category),
                "status": "candidate",
                "status_reason": "新识别的事件候选",
                "first_seen_at": now,
                "last_seen_at": now,
                "first_published_at": article.published_at,
                "last_published_at": article.published_at,
                "occurred_at": None,
                "article_count": 0,
                "source_count": 0,
                "is_manual": 0,
                "merged_into_event_id": None,
                "algorithm_version": CLUSTER_VERSION,
                "title_source": "auto",
                "summary_source": "auto",
                "created_at": now,
                "updated_at": now,
            },
        )
        return event_id

    def _attach_article(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        article: ArticleFeatures,
        score: PairScore | None,
        now: str,
        is_manual: bool,
    ) -> str | None:
        event = event_repo.get(conn, event_id)
        if event is None or event.status in TERMINAL or (event.is_manual and not is_manual):
            return None
        if event_repo.get_event_article(conn, event_id, article.id) is not None:
            return None
        before_entities = {item.entity_id for item in event_repo.list_event_entities(conn, event_id)}
        previous_status = event.status
        previous_last_published = event.last_published_at

        event_repo.insert_event_article(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "article_id": article.id,
                "role": "report" if event.article_count == 0 else "follow_up",
                "similarity": score.total if score is not None else None,
                "match_reasons_json": json.dumps(
                    list(score.reasons) if score is not None else ["manual_or_initial"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "is_manual": 1 if is_manual else 0,
                "added_at": now,
                "created_at": now,
            },
        )
        stats = recompute_event_aggregates(conn, event_id, now)
        rebuild_event_entities(conn, event_id, now)

        gap = hours_between(previous_last_published, article.published_at)
        if event_repo.timeline_is_empty(conn, event_id):
            self._insert_timeline(
                conn,
                event_id=event_id,
                article_id=article.id,
                kind="first_report",
                title=article.title,
                description=article.summary,
                published_at=article.published_at,
                now=now,
                confidence=score.total if score is not None else None,
                is_key=True,
                evidence={"match_reasons": list(score.reasons) if score else []},
            )
        elif not event_repo.timeline_exists_for_article(conn, event_id, article.id):
            after_entities = {
                item.entity_id for item in event_repo.list_event_entities(conn, event_id)
            }
            new_entities = sorted(after_entities - before_entities)
            is_key = bool(new_entities) or (
                gap is not None and gap >= 48
            ) or int(stats["article_count"]) in {2, 5, 10}
            self._insert_timeline(
                conn,
                event_id=event_id,
                article_id=article.id,
                kind="follow_up",
                title=article.title,
                description=article.summary,
                published_at=article.published_at,
                now=now,
                confidence=score.total if score is not None else None,
                is_key=is_key,
                evidence={
                    "match_reasons": list(score.reasons) if score else [],
                    "new_entities": new_entities[:10],
                    "gap_hours": round(gap, 2) if gap is not None else None,
                },
            )

        new_status = next_status(
            previous_status,
            article_count=int(stats["article_count"]),
            first_seen_at=event.first_seen_at,
            last_published_at=stats["last_published_at"],
            now=None,
            new_article=True,
        )
        if new_status != previous_status:
            reason = transition_reason(previous_status, new_status)
            event_repo.update_event(
                conn,
                event_id,
                {
                    "status": new_status,
                    "status_reason": reason[:500] or None,
                    "updated_at": now,
                },
            )
            self._insert_timeline(
                conn,
                event_id=event_id,
                article_id=None,
                kind="status_change",
                title=f"事件状态变化：{previous_status} → {new_status}",
                description=reason,
                published_at=None,
                now=now,
                confidence=None,
                is_key=True,
                evidence={"previous": previous_status, "current": new_status},
            )
            self._audit_status(
                conn,
                event_id=event_id,
                previous=previous_status,
                current=new_status,
                reason=reason,
                now=now,
            )
        refresh_event_summary(conn, event_id)
        # The event's domain follows all member articles, not only the first.
        refresh_event_category(conn, event_id, now=now)
        return new_status

    def _insert_timeline(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        article_id: str | None,
        kind: str,
        title: str,
        description: str | None,
        published_at: str | None,
        now: str,
        confidence: float | None,
        is_key: bool,
        evidence: dict[str, object],
    ) -> None:
        event_repo.insert_timeline_item(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "article_id": article_id,
                "kind": kind,
                "title": title[:300] or "时间线节点",
                "description": (description or "")[:2000] or None,
                "occurred_at": None,
                "published_at": published_at,
                "recognized_at": now,
                "confidence": confidence,
                "is_key": 1 if is_key else 0,
                "evidence_json": json.dumps(
                    evidence, ensure_ascii=False, separators=(",", ":")
                )[:4000],
                "created_at": now,
            },
        )

    def _refresh_lifecycle(
        self, conn: sqlite3.Connection, event_id: str, now: str
    ) -> None:
        event = event_repo.get(conn, event_id)
        if event is None or event.status in TERMINAL or event.is_manual:
            return
        new_status = next_status(
            event.status,
            article_count=event.article_count,
            first_seen_at=event.first_seen_at,
            last_published_at=event.last_published_at,
            now=None,
            new_article=False,
        )
        if new_status == event.status:
            return
        reason = transition_reason(event.status, new_status)
        event_repo.update_event(
            conn,
            event_id,
            {
                "status": new_status,
                "status_reason": reason[:500] or None,
                "updated_at": now,
            },
        )
        self._insert_timeline(
            conn,
            event_id=event_id,
            article_id=None,
            kind="status_change",
            title=f"事件状态变化：{event.status} → {new_status}",
            description=reason,
            published_at=None,
            now=now,
            confidence=None,
            is_key=True,
            evidence={"previous": event.status, "current": new_status, "automatic": True},
        )
        self._audit_status(
            conn,
            event_id=event_id,
            previous=event.status,
            current=new_status,
            reason=reason,
            now=now,
        )

    def _audit_status(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        previous: str,
        current: str,
        reason: str,
        now: str,
    ) -> None:
        audit_repo.insert(
            conn,
            audit_id=str(uuid.uuid4()),
            event_id=event_id,
            entity_id=None,
            action="change_status",
            actor="algorithm",
            detail={
                "previous": previous,
                "current": current,
                "reason": reason,
                "automatic": True,
            },
            created_at=now,
        )

    def _record_decision(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        article_id: str,
        event_id: str | None,
        decision: str,
        score: float | None,
        reasons: tuple[str, ...] | list[str],
        method: str,
        status: str,
        now: str,
        llm_used: bool = False,
    ) -> None:
        cluster_repo.insert_decision(
            conn,
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "article_id": article_id,
                "candidate_event_id": event_id,
                "decision": decision,
                "score": score,
                "reasons_json": json.dumps(
                    list(reasons)[:20], ensure_ascii=False, separators=(",", ":")
                )[:4000],
                "method": method,
                "llm_used": 1 if llm_used else 0,
                "status": status,
                "created_at": now,
                "resolved_at": now if status != "pending" else None,
            },
        )

    # ------------------------------------------------------------------
    # cache updates and run bookkeeping
    # ------------------------------------------------------------------

    def _merge_cache(
        self, cache: dict[str, EventFeatures], event_id: str, article: ArticleFeatures
    ) -> None:
        event = cache.get(event_id)
        if event is None:
            self._add_to_cache(cache, event_id, article)
            return
        last_published = max(
            [value for value in (event.last_published_at, article.published_at) if value],
            default=None,
        )
        cache[event_id] = replace(
            event,
            entity_ids=event.entity_ids | article.entity_ids,
            entity_keys=event.entity_keys | article.entity_keys,
            event_entity_ids=event.event_entity_ids | article.event_entity_ids,
            event_entity_keys=event.event_entity_keys | article.event_entity_keys,
            keywords=event.keywords | article.keywords,
            member_article_ids=(*event.member_article_ids, article.id),
            member_titles=(*event.member_titles, article.title)[-3:],
            member_summaries=(
                *event.member_summaries,
                *( [article.summary] if article.summary else [] ),
            )[-3:],
            member_content_hashes=(
                *event.member_content_hashes,
                article.content_hash,
            ),
            source_ids=event.source_ids | {article.source_id},
            last_published_at=last_published,
            article_count=event.article_count + 1,
        )

    def _add_to_cache(
        self, cache: dict[str, EventFeatures], event_id: str, article: ArticleFeatures
    ) -> None:
        cache[event_id] = EventFeatures(
            id=event_id,
            title=article.title,
            summary=article.summary,
            category=article.category,
            entity_ids=article.entity_ids,
            entity_keys=article.entity_keys,
            event_entity_ids=article.event_entity_ids,
            event_entity_keys=article.event_entity_keys,
            keywords=article.keywords,
            member_article_ids=(article.id,),
            member_titles=(article.title,),
            member_summaries=(article.summary,) if article.summary else (),
            member_content_hashes=(article.content_hash,),
            source_ids=frozenset({article.source_id}),
            first_published_at=article.published_at,
            last_published_at=article.published_at,
            article_count=1,
            is_manual=False,
        )

    def _update_counts(
        self, conn: sqlite3.Connection, run_id: str, counters: dict[str, int]
    ) -> None:
        cluster_repo.update_run(
            conn, run_id, {**counters, "updated_at": utc_timestamp()}
        )

    def _persist_counters(self, run_id: str, counters: dict[str, int]) -> None:
        with database.session() as conn:
            self._update_counts(conn, run_id, counters)

    def _is_cancel_requested(self, run_id: str) -> bool:
        with database.read_session() as conn:
            run = cluster_repo.get_run(conn, run_id)
        return bool(run is not None and run.cancel_requested)

    def _finalize(
        self,
        run_id: str,
        counters: dict[str, int],
        started: float,
        *,
        status: str,
        model_name: str | None,
    ) -> None:
        now = utc_timestamp()
        with database.session() as conn:
            cluster_repo.update_run(
                conn,
                run_id,
                {
                    **counters,
                    "status": status,
                    "model_name": model_name,
                    "finished_at": now,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "updated_at": now,
                },
            )
        log_event(
            "event_clustering_finished",
            run_id=run_id,
            status=status,
            **counters,
        )

    def _fail_run(self, run_id: str, message: str) -> None:
        now = utc_timestamp()
        try:
            with database.session() as conn:
                run = cluster_repo.get_run(conn, run_id)
                if run is None or run.status not in {"pending", "running"}:
                    return
                cluster_repo.update_run(
                    conn,
                    run_id,
                    {
                        "status": "failed",
                        "error_message": message[:1000],
                        "finished_at": now,
                        "updated_at": now,
                    },
                )
        except Exception:  # noqa: BLE001
            log_event("event_clustering_fail_mark_failed", level="error", run_id=run_id)


_clustering_service: EventClusteringService | None = None


def get_event_clustering_service() -> EventClusteringService:
    global _clustering_service
    if _clustering_service is None:
        _clustering_service = EventClusteringService()
    return _clustering_service
