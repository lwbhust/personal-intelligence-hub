"""Phase 7.1 intelligence report orchestration.

Design notes:
* statistics are always computed from SQLite, never from the model;
* the model only writes interpretation over a bounded evidence packet;
* every citation is validated against supplied IDs before it is persisted;
* Ollama being unavailable degrades to a statistics-only report instead of
  losing history, and never falls back to a cloud model;
* one generation runs at a time; pending/running rows are marked failed on
  restart so nothing can be stuck forever.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid

import database
from ai_engine.errors import (
    AIError,
    INTERNAL_ERROR,
    INVALID_JSON,
    INVALID_RESPONSE,
    MODEL_UNAVAILABLE,
    PROVIDER_HTTP_ERROR,
    PROVIDER_TIMEOUT,
    PROVIDER_UNREACHABLE,
    RESPONSE_TOO_LARGE,
    SCHEMA_INVALID,
)
from ai_engine.intelligence import (
    MAX_EVENTS,
    PROMPT_VERSION,
    EventBrief,
    OverviewOut,
    build_event_messages,
    build_overview_messages,
    parse_event_brief,
    parse_overview,
)
from ai_engine.provider import OllamaLocalProvider, ProviderHealth
from core.logging import log_event
from core.timeutil import utc_timestamp
from database.repositories import ai_model_repository as model_repo
from database.repositories import intelligence_repository as intel_repo
from services.errors import conflict, not_found, validation
from services.intelligence_stats import (
    STATS_VERSION,
    build_stats,
    period_for,
    period_key_for,
)

REPORT_TYPES = {"daily", "weekly"}
MAX_ATTEMPTS = 2
DEFAULT_TEMPERATURE = 0.2
EVENT_NUM_PREDICT = 500
OVERVIEW_NUM_PREDICT = 700
GENERATE_TIMEOUT = 240.0
KEEP_REPORTS = 200
HEALTH_CACHE_SECONDS = 10.0
AI_ENABLED_ENV = "PIH_AI_ENABLED"

_RETRYABLE_ERRORS = {INVALID_JSON, SCHEMA_INVALID, MODEL_UNAVAILABLE}
_TRANSPORT_ERRORS = {
    PROVIDER_UNREACHABLE,
    PROVIDER_TIMEOUT,
    PROVIDER_HTTP_ERROR,
    INVALID_RESPONSE,
    RESPONSE_TOO_LARGE,
}

DEGRADED_NOTE = "本地模型当前不可用，本报告仅包含数据库统计与事件证据，未生成 AI 解读。"


def _duration_ms(started_at: str | None, finished_at: str) -> int:
    from datetime import datetime

    if not started_at:
        return 0
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


def _citation_row(
    report_id: str,
    *,
    citation_type: str,
    ref_id: str,
    section_key: str,
    rank: int,
    title: str | None = None,
    source_name: str | None = None,
    url: str | None = None,
    evidence: str | None = None,
    now: str,
) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "report_id": report_id,
        "citation_type": citation_type,
        "ref_id": ref_id[:64],
        "section_key": section_key,
        "rank": int(rank),
        "title": (title or "")[:500] or None,
        "source_name": (source_name or "")[:200] or None,
        "url": (url or "")[:2048] or None,
        "evidence": (evidence or "")[:1000] or None,
        "created_at": now,
    }


class IntelligenceService:
    def __init__(
        self,
        *,
        provider: OllamaLocalProvider | None = None,
        clock=time.monotonic,
    ) -> None:
        self.provider = provider or OllamaLocalProvider()
        self._clock = clock
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._running_id: str | None = None
        self._health_cache: tuple[float, ProviderHealth] | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self.recover_interrupted()
        self._worker = threading.Thread(
            target=self._worker_loop, name="pih-intelligence-worker", daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("")
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        self._started = False
        self._worker = None

    def recover_interrupted(self) -> int:
        """Pending/running rows cannot resume mid-generation after a restart."""

        try:
            now = utc_timestamp()
            with database.session() as conn:
                changed = intel_repo.mark_stale_running(
                    conn, now, error_code="interrupted"
                )
                intel_repo.prune(conn, KEEP_REPORTS)
            if changed:
                log_event("intelligence_recovered", level="warn", report_count=changed)
            return changed
        except Exception as exc:  # noqa: BLE001 - startup must not crash
            log_event(
                "intelligence_recovery_failed",
                level="error",
                exc_type=type(exc).__name__,
            )
            return 0

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    def health(self, *, force: bool = False) -> ProviderHealth:
        now = self._clock()
        if not force and self._health_cache is not None:
            cached_at, cached = self._health_cache
            if now - cached_at <= HEALTH_CACHE_SECONDS:
                return cached
        health = self.provider.health_check()
        self._health_cache = (self._clock(), health)
        return health

    def _default_model(self):
        with database.read_session() as conn:
            return model_repo.default_model(conn)

    def status(self) -> dict[str, object]:
        health = self.health()
        model = None
        try:
            model = self._default_model()
        except Exception:  # noqa: BLE001 - status must not fail
            model = None
        with self._lock:
            running = self._running_id
        try:
            with database.read_session() as conn:
                queued = intel_repo.queued_count(conn)
                latest = intel_repo.latest_succeeded(conn)
        except Exception:  # noqa: BLE001
            queued = 0
            latest = None
        return {
            "ollama_available": health.available,
            "ollama_version": health.version,
            "model_name": model.model_name if model else None,
            "model_installed": bool(
                model and any(item.name == model.model_name for item in health.models)
            ),
            "queue_depth": queued,
            "running_report_id": running,
            "last_report": None
            if latest is None
            else {
                "id": latest.id,
                "report_type": latest.report_type,
                "status": latest.status,
                "ai_status": latest.ai_status,
                "period_start": latest.period_start,
                "created_at": latest.created_at,
            },
            "prompt_version": PROMPT_VERSION,
            "stats_version": STATS_VERSION,
            "checked_at": health.checked_at,
        }

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list_reports(
        self,
        *,
        report_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ):
        with database.read_session() as conn:
            return intel_repo.list_reports(
                conn,
                report_type=report_type,
                status=status,
                limit=limit,
                offset=offset,
            )

    def report_detail(self, report_id: str):
        with database.read_session() as conn:
            record = intel_repo.get(conn, report_id)
            if record is None:
                raise not_found("report_not_found", "情报报告不存在")
            citations = intel_repo.list_citations(conn, report_id)
        return record, citations

    # ------------------------------------------------------------------
    # create / cancel
    # ------------------------------------------------------------------

    def create_report(
        self, *, report_type: str, force: bool = False
    ) -> tuple[object, bool]:
        if report_type not in REPORT_TYPES:
            raise validation("report_type", "invalid", "report_type 必须是 daily 或 weekly")
        start, end = period_for(report_type)
        period_key = period_key_for(report_type)
        now = utc_timestamp()
        with database.session() as conn:
            existing = intel_repo.find_active(
                conn, report_type=report_type, period_key=period_key
            )
            if existing is not None:
                if existing.status in ("pending", "running"):
                    raise conflict("report_in_progress", "该周期的情报正在生成中")
                if not force:
                    return existing, True
                intel_repo.supersede_active(
                    conn,
                    report_type=report_type,
                    period_key=period_key,
                    now=now,
                )
            model = model_repo.default_model(conn)
            report_id = str(uuid.uuid4())
            intel_repo.insert_report(
                conn,
                {
                    "id": report_id,
                    "report_type": report_type,
                    "period_key": period_key,
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "data_from_at": None,
                    "data_to_at": None,
                    "status": "pending",
                    "ai_status": "pending",
                    "headline": None,
                    "overview": None,
                    "content_json": "{}",
                    "stats_json": "{}",
                    "model_name": model.model_name if model else None,
                    "model_digest": None,
                    "prompt_version": PROMPT_VERSION,
                    "stats_version": STATS_VERSION,
                    "article_count": 0,
                    "event_count": 0,
                    "entity_count": 0,
                    "citation_count": 0,
                    "trigger_type": "retry" if force else "manual",
                    "cancel_requested": 0,
                    "error_code": None,
                    "error_message": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            intel_repo.prune(conn, KEEP_REPORTS)
            record = intel_repo.get(conn, report_id)
        log_event(
            "intelligence_report_created",
            report_id=report_id,
            report_type=report_type,
            force=force,
        )
        self._enqueue(report_id)
        return record, False

    def cancel_report(self, report_id: str):
        with database.session() as conn:
            record = intel_repo.get(conn, report_id)
            if record is None:
                raise not_found("report_not_found", "情报报告不存在")
            if record.status not in ("pending", "running"):
                raise conflict("report_not_cancellable", "当前状态不可取消")
            now = utc_timestamp()
            if record.status == "pending":
                intel_repo.update_report(
                    conn,
                    report_id,
                    {
                        "status": "cancelled",
                        "cancel_requested": 1,
                        "finished_at": now,
                        "duration_ms": 0,
                        "updated_at": now,
                    },
                )
            else:
                intel_repo.update_report(
                    conn,
                    report_id,
                    {"cancel_requested": 1, "updated_at": now},
                )
            record = intel_repo.get(conn, report_id)
        log_event("intelligence_report_cancel_requested", report_id=report_id)
        return record

    def _enqueue(self, report_id: str) -> None:
        self._queue.put(report_id)

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                report_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not report_id or self._stop.is_set():
                continue
            try:
                self._execute(report_id)
            except Exception as exc:  # noqa: BLE001 - one report must not kill the worker
                log_event(
                    "intelligence_report_crashed",
                    level="error",
                    report_id=report_id,
                    exc_type=type(exc).__name__,
                )
                self._fail(report_id, INTERNAL_ERROR, "情报生成内部错误")

    def _finalize_failure(
        self, report_id: str, status: str, code: str, message: str
    ) -> None:
        now = utc_timestamp()
        with database.session() as conn:
            record = intel_repo.get(conn, report_id)
            if record is None:
                return
            intel_repo.update_report(
                conn,
                report_id,
                {
                    "status": status,
                    "error_code": code,
                    "error_message": message[:1000],
                    "finished_at": now,
                    "duration_ms": _duration_ms(record.started_at, now),
                    "updated_at": now,
                },
            )
        log_event(
            "intelligence_report_failed",
            level="warn",
            report_id=report_id,
            error_code=code,
        )

    def _fail(self, report_id: str, code: str, message: str) -> None:
        self._finalize_failure(report_id, "failed", code, message)

    def _cancelled(self, report_id: str) -> bool:
        with database.read_session() as conn:
            record = intel_repo.get(conn, report_id)
        return bool(record and (record.cancel_requested or record.status == "cancelled"))

    def _execute(self, report_id: str) -> None:
        with database.read_session() as conn:
            record = intel_repo.get(conn, report_id)
        if record is None or record.status != "pending":
            return
        now = utc_timestamp()
        with database.session() as conn:
            intel_repo.update_report(
                conn,
                report_id,
                {"status": "running", "started_at": now, "updated_at": now},
            )
        with self._lock:
            self._running_id = report_id

        try:
            self._run(report_id, record.report_type)
        finally:
            with self._lock:
                self._running_id = None

    def _run(self, report_id: str, report_type: str) -> None:
        start, end = period_for(report_type)
        with database.read_session() as conn:
            stats = build_stats(
                conn, report_type=report_type, period_start=start, period_end=end
            )
        now = utc_timestamp()
        with database.session() as conn:
            intel_repo.update_report(
                conn,
                report_id,
                {
                    "stats_json": json.dumps(stats, ensure_ascii=False, separators=(",", ":")),
                    "data_from_at": (stats.get("data_range") or {}).get("from_at"),
                    "data_to_at": (stats.get("data_range") or {}).get("to_at"),
                    "article_count": int((stats.get("totals") or {}).get("articles") or 0),
                    "event_count": int((stats.get("totals") or {}).get("events") or 0),
                    "entity_count": len(stats.get("new_entities") or []),
                    "updated_at": now,
                },
            )
        if self._cancelled(report_id):
            self._finalize_failure(report_id, "cancelled", "interrupted", "生成已取消")
            return

        briefs: list[EventBrief] = []
        overview: OverviewOut | None = None
        ai_status = "unavailable"
        error_code: str | None = None
        error_message: str | None = None
        model_name: str | None = None
        model_digest: str | None = None

        health = self.health()
        model = None
        try:
            model = self._default_model()
        except Exception:  # noqa: BLE001
            model = None
        ai_enabled = os.environ.get(AI_ENABLED_ENV, "1") != "0"

        if health.available and model is not None and ai_enabled:
            model_name = model.model_name
            allowed_models = self._allowed_models()
            totals = stats.get("totals") if isinstance(stats.get("totals"), dict) else {}
            report_events = [
                item for item in (stats.get("key_events") or [])
                if isinstance(item, dict)
            ][:MAX_EVENTS]

            for event in report_events:
                if self._cancelled(report_id):
                    self._finalize_failure(
                        report_id, "cancelled", "interrupted", "生成已取消"
                    )
                    return
                messages, _ = build_event_messages(event, report_type=report_type)
                for attempt in range(MAX_ATTEMPTS):
                    try:
                        generation = self.provider.generate_structured(
                            model=model.model_name,
                            messages=messages,
                            num_ctx=model.num_ctx,
                            temperature=DEFAULT_TEMPERATURE,
                            num_predict=EVENT_NUM_PREDICT,
                            allowed_models=allowed_models,
                            timeout=GENERATE_TIMEOUT,
                        )
                        briefs.append(
                            parse_event_brief(generation.text, event=event)
                        )
                        model_digest = generation.model_digest
                        break
                    except AIError as exc:
                        error_code = exc.code
                        error_message = exc.message
                        ai_status = (
                            "unavailable" if exc.code in _TRANSPORT_ERRORS else "invalid"
                        )
                        if exc.code not in _RETRYABLE_ERRORS:
                            break
                    except Exception as exc:  # noqa: BLE001
                        error_code = INTERNAL_ERROR
                        error_message = f"事件简报异常（{type(exc).__name__}）"
                        ai_status = "invalid"
                        break

            if briefs:
                if self._cancelled(report_id):
                    self._finalize_failure(
                        report_id, "cancelled", "interrupted", "生成已取消"
                    )
                    return
                messages, _ = build_overview_messages(
                    [
                        {
                            "event_id": brief.event_id,
                            "title": brief.title,
                            "development": brief.development,
                            "impact": brief.impact,
                        }
                        for brief in briefs
                    ],
                    report_type=report_type,
                    totals=totals,
                )
                for attempt in range(MAX_ATTEMPTS):
                    try:
                        generation = self.provider.generate_structured(
                            model=model.model_name,
                            messages=messages,
                            num_ctx=model.num_ctx,
                            temperature=DEFAULT_TEMPERATURE,
                            num_predict=OVERVIEW_NUM_PREDICT,
                            allowed_models=allowed_models,
                            timeout=GENERATE_TIMEOUT,
                        )
                        overview = parse_overview(
                            generation.text,
                            allowed_events={brief.event_id for brief in briefs},
                        )
                        model_digest = generation.model_digest
                        ai_status = "used"
                        error_code = None
                        error_message = None
                        break
                    except AIError as exc:
                        error_code = exc.code
                        error_message = exc.message
                        ai_status = (
                            "unavailable" if exc.code in _TRANSPORT_ERRORS else "invalid"
                        )
                        if exc.code not in _RETRYABLE_ERRORS:
                            break
                    except Exception as exc:  # noqa: BLE001
                        error_code = INTERNAL_ERROR
                        error_message = f"情报汇总异常（{type(exc).__name__}）"
                        ai_status = "invalid"
                        break
            else:
                ai_status = ai_status if ai_status != "unavailable" else "invalid"

        if self._cancelled(report_id):
            self._finalize_failure(report_id, "cancelled", "interrupted", "生成已取消")
            return

        if overview is None or not briefs:
            self._persist_degraded(
                report_id,
                stats,
                model_name=model_name,
                ai_status=ai_status if health.available else "unavailable",
                error_code=error_code or ("model_unavailable" if not health.available else None),
                error_message=error_message,
            )
            return

        self._persist_success(
            report_id,
            stats,
            briefs,
            overview,
            model_name=model_name,
            model_digest=model_digest,
        )

    def _allowed_models(self) -> tuple[str, ...]:
        with database.read_session() as conn:
            return model_repo.enabled_model_names(conn)

    def _persist_degraded(
        self,
        report_id: str,
        stats: dict[str, object],
        *,
        model_name: str | None,
        ai_status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        now = utc_timestamp()
        content = {
            "key_events": [],
            "topics": [],
            "uncertainties": [DEGRADED_NOTE],
        }
        citations: list[dict[str, object]] = []
        for index, event in enumerate(stats.get("key_events") or []):
            if not isinstance(event, dict):
                continue
            citations.append(
                _citation_row(
                    report_id,
                    citation_type="event",
                    ref_id=str(event.get("event_id") or ""),
                    section_key="stats_events",
                    rank=index,
                    title=str(event.get("title") or ""),
                    evidence=(
                        f"报道 {int(event.get('article_count') or 0)} 篇｜"
                        f"来源 {int(event.get('source_count') or 0)} 个"
                    ),
                    now=now,
                )
            )
            for sub_index, item in enumerate((event.get("evidence") or [])[:4]):
                if not isinstance(item, dict):
                    continue
                citations.append(
                    _citation_row(
                        report_id,
                        citation_type="article",
                        ref_id=str(item.get("article_id") or ""),
                        section_key="stats_events",
                        rank=index * 10 + sub_index + 1,
                        title=str(item.get("title") or ""),
                        source_name=str(item.get("source_name") or ""),
                        url=item.get("url") if isinstance(item.get("url"), str) else None,
                        now=now,
                    )
                )
        with database.session() as conn:
            record = intel_repo.get(conn, report_id)
            intel_repo.update_report(
                conn,
                report_id,
                {
                    "status": "degraded",
                    "ai_status": ai_status,
                    "headline": "本地模型不可用：仅显示数据库统计",
                    "overview": DEGRADED_NOTE,
                    "content_json": json.dumps(
                        content, ensure_ascii=False, separators=(",", ":")
                    ),
                    "model_name": model_name,
                    "citation_count": len(citations),
                    "error_code": error_code,
                    "error_message": error_message,
                    "finished_at": now,
                    "duration_ms": _duration_ms(record.started_at if record else None, now),
                    "updated_at": now,
                },
            )
            intel_repo.insert_citations(conn, citations)
        log_event(
            "intelligence_report_degraded",
            level="warn",
            report_id=report_id,
            ai_status=ai_status,
            error_code=error_code,
        )

    def _persist_success(
        self,
        report_id: str,
        stats: dict[str, object],
        briefs: list[EventBrief],
        overview: OverviewOut,
        *,
        model_name: str | None,
        model_digest: str | None,
    ) -> None:
        now = utc_timestamp()
        event_index = {
            str(event.get("event_id")): event
            for event in (stats.get("key_events") or [])
            if isinstance(event, dict)
        }
        citations: list[dict[str, object]] = []
        for index, event in enumerate(briefs):
            source_event = event_index.get(event.event_id) or {}
            citations.append(
                _citation_row(
                    report_id,
                    citation_type="event",
                    ref_id=event.event_id,
                    section_key="key_events",
                    rank=index,
                    title=str(source_event.get("title") or event.title or ""),
                    evidence=(
                        f"热度 {float(((source_event.get('scores') or {}) if isinstance(source_event.get('scores'), dict) else {}).get('heat') or 0):.1f}｜"
                        f"报道 {int(source_event.get('article_count') or 0)} 篇"
                    ),
                    now=now,
                )
            )
            evidence_by_id = {
                str(item.get("article_id")): item
                for item in (source_event.get("evidence") or [])
                if isinstance(item, dict)
            }
            for sub_index, article_id in enumerate(event.article_ids):
                item = evidence_by_id.get(article_id) or {}
                citations.append(
                    _citation_row(
                        report_id,
                        citation_type="article",
                        ref_id=article_id,
                        section_key="key_events",
                        rank=index * 10 + sub_index + 1,
                        title=str(item.get("title") or ""),
                        source_name=str(item.get("source_name") or ""),
                        url=item.get("url") if isinstance(item.get("url"), str) else None,
                        now=now,
                    )
                )
        for index, topic in enumerate(overview.topics):
            for sub_index, event_id in enumerate(topic.evidence_event_ids):
                source_event = event_index.get(event_id) or {}
                citations.append(
                    _citation_row(
                        report_id,
                        citation_type="event",
                        ref_id=event_id,
                        section_key="topics",
                        rank=index * 10 + sub_index,
                        title=str(source_event.get("title") or ""),
                        now=now,
                    )
                )

        content = {
            "key_events": [
                {
                    "event_id": event.event_id,
                    "title": event.title,
                    "development": event.development,
                    "background": event.background,
                    "impact": event.impact,
                    "importance": event.importance,
                    "entities": list(event.entities),
                    "article_ids": list(event.article_ids),
                }
                for event in briefs
            ],
            "topics": [
                {
                    "name": topic.name,
                    "direction": topic.direction,
                    "evidence_event_ids": list(topic.evidence_event_ids),
                }
                for topic in overview.topics
            ],
            "uncertainties": list(overview.uncertainties),
            "warnings": list(overview.warnings),
        }
        with database.session() as conn:
            record = intel_repo.get(conn, report_id)
            intel_repo.update_report(
                conn,
                report_id,
                {
                    "status": "succeeded",
                    "ai_status": "used",
                    "headline": overview.headline,
                    "overview": overview.overview,
                    "content_json": json.dumps(
                        content, ensure_ascii=False, separators=(",", ":")
                    ),
                    "model_name": model_name,
                    "model_digest": model_digest,
                    "citation_count": len(citations),
                    "error_code": None,
                    "error_message": None,
                    "finished_at": now,
                    "duration_ms": _duration_ms(record.started_at if record else None, now),
                    "updated_at": now,
                },
            )
            intel_repo.insert_citations(conn, citations)
        log_event(
            "intelligence_report_finished",
            report_id=report_id,
            event_count=len(briefs),
            topic_count=len(overview.topics),
            citation_count=len(citations),
        )


_service: IntelligenceService | None = None
_service_lock = threading.Lock()


def get_intelligence_service() -> IntelligenceService:
    global _service
    with _service_lock:
        if _service is None:
            _service = IntelligenceService()
        return _service


def reset_intelligence_service(service: IntelligenceService | None = None) -> None:
    global _service
    with _service_lock:
        if _service is not None:
            _service.stop()
        _service = service
