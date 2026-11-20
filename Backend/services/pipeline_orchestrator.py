"""Persistent pipeline orchestrator (Phase 7.2).

The orchestrator **schedules existing services**; it does not re-implement AI,
entity, clustering or scoring logic:

    quality check -> AIAnalysisService -> EntityService -> EventClusteringService
                  -> EventScoringService -> refresh

One worker thread executes small, bounded batches. Every task lives in SQLite
(`pipeline_tasks`) so an app restart resumes the exact same work instead of
relying on in-memory flags. Business writes stay idempotent because each stage
guards on existing rows (analysis per content hash, article/event membership,
score snapshot per inputs).

Automation is opt-in (`pipeline_settings.automation_enabled = 0` by default): an
update never starts analysing the existing history on its own.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import database
from ai_engine import errors as ai_errors
from core.logging import log_event
from core.timeutil import utc_timestamp
from database.repositories import ai_analysis_repository as analysis_repo
from database.repositories import article_repository as article_repo
from database.repositories import event_repository as event_repo
from database.repositories import pipeline_repository as pipeline_repo
from database.repositories.pipeline_repository import (
    PipelineRunRecord,
    PipelineSettingsRecord,
    PipelineTaskLogRecord,
    PipelineTaskRecord,
)
from event_intelligence.scoring import ALGORITHM_VERSION as SCORE_VERSION
from event_intelligence.taxonomy import TAXONOMY_VERSION
from services.ai_analysis_service import get_ai_service
from services.classification_service import refresh_event_category
from services.entity_service import sync_article
from services.errors import conflict, not_found, validation
from services.event_clustering_service import get_event_clustering_service
from services.event_scoring_service import score_event_in_conn

WORKER_NAME = "pipeline-orchestrator"
TICK_SECONDS = 5.0
LEASE_SECONDS = 180
AI_RUN_TIMEOUT_SECONDS = 300
CLUSTER_RUN_TIMEOUT_SECONDS = 240
MIN_CONTENT_CHARS = 40
HEARTBEAT_SECONDS = 30.0

STAGE_ORDER = (
    "quality_check",
    "ai_analysis",
    "entity_sync",
    "event_match",
    "event_score",
    "refresh",
    "done",
)

TERMINAL_STATUSES = {"succeeded", "failed", "skipped", "cancelled"}
RUN_TERMINAL_STATUSES = {"succeeded", "partially_succeeded", "failed", "cancelled"}

PERMANENT_ERROR_CODES = {
    ai_errors.ARTICLE_NOT_ANALYZABLE,
    ai_errors.CLOUD_MODEL_BLOCKED,
    ai_errors.MODEL_NOT_ALLOWED,
    "article_not_found",
    "content_insufficient",
    "ai_disabled",
    "event_disabled",
}


@dataclass(slots=True)
class _TaskFailure(Exception):
    code: str
    message: str
    retryable: bool = True

    def __str__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{self.code}: {self.message}"


@dataclass(slots=True)
class _TaskSkip(Exception):
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{self.code}: {self.message}"


@dataclass(slots=True)
class _TaskDeferred(Exception):
    code: str
    message: str
    delay_seconds: int

    def __str__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{self.code}: {self.message}"


def _now() -> str:
    return utc_timestamp()


def _iso_plus(seconds: int) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=max(0, seconds))
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _today_start() -> str:
    moment = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: dict[str, object] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        tick_seconds: float = TICK_SECONDS,
        ai_timeout: float = AI_RUN_TIMEOUT_SECONDS,
        cluster_timeout: float = CLUSTER_RUN_TIMEOUT_SECONDS,
        poll_seconds: float = 0.25,
    ) -> None:
        self.tick_seconds = tick_seconds
        self.ai_timeout = ai_timeout
        self.cluster_timeout = cluster_timeout
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._last_sweep_at: str | None = None
        self._last_sweep_ms: int | None = None
        self._last_sweep_error: str | None = None
        self._last_ai_finished_monotonic: float | None = None
        self._last_recovered = 0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started and self._thread is not None and self._thread.is_alive():
                return
            self._started = True
        self._stop.clear()
        self._last_recovered = self._recover_leases()
        self._thread = threading.Thread(
            target=self._worker_loop, name="pih-pipeline-orchestrator", daemon=True
        )
        self._thread.start()
        log_event(
            "pipeline_started",
            recovered_tasks=self._last_recovered,
        )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._started = False
        log_event("pipeline_stopped")

    def _recover_leases(self) -> int:
        try:
            with database.session() as conn:
                recovered = pipeline_repo.recover_expired_leases(conn, now=_now())
            if recovered:
                log_event(
                    "pipeline_recovered",
                    level="warn",
                    task_count=len(recovered),
                )
            return len(recovered)
        except Exception as exc:  # noqa: BLE001 - startup must not crash
            log_event(
                "pipeline_recovery_failed",
                level="error",
                exc_type=type(exc).__name__,
            )
            return 0

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._sweep_once()
                self._last_sweep_error = None
            except Exception as exc:  # noqa: BLE001 - one bad sweep must not stop the worker
                self._last_sweep_error = f"{type(exc).__name__}: {exc}"[:500]
                log_event(
                    "pipeline_sweep_failed",
                    level="error",
                    exc_type=type(exc).__name__,
                )
            self._last_sweep_at = _now()
            self._last_sweep_ms = int((time.monotonic() - started) * 1000)
            self._wake.wait(timeout=self.tick_seconds)
            self._wake.clear()

    def _sweep_once(self) -> dict[str, object]:
        self._recover_leases()
        settings = self.get_settings()
        if settings.paused:
            return {"processed": 0, "reason": "paused"}
        now = _now()
        if not settings.automation_enabled:
            with database.read_session() as conn:
                if not pipeline_repo.has_ready_backfill(conn, now=now):
                    return {"processed": 0, "reason": "automation_disabled"}

        processed = 0
        processed += self._process_queue(settings)
        processed += self._process_event_batch(settings)
        return {"processed": processed}

    # ------------------------------------------------------------------
    # settings / control
    # ------------------------------------------------------------------

    def get_settings(self) -> PipelineSettingsRecord:
        with database.read_session() as conn:
            return pipeline_repo.get_settings(conn)

    def settings_payload(self) -> dict[str, object]:
        record = self.get_settings()
        return {
            "automation_enabled": record.automation_enabled,
            "paused": record.paused,
            "ai_enabled": record.ai_enabled,
            "entity_enabled": record.entity_enabled,
            "event_enabled": record.event_enabled,
            "scoring_enabled": record.scoring_enabled,
            "batch_size": record.batch_size,
            "max_attempts": record.max_attempts,
            "ai_interval_seconds": record.ai_interval_seconds,
            "updated_at": record.updated_at,
        }

    def update_settings(self, fields: dict[str, object]) -> dict[str, object]:
        allowed = {
            "automation_enabled",
            "paused",
            "ai_enabled",
            "entity_enabled",
            "event_enabled",
            "scoring_enabled",
            "batch_size",
            "max_attempts",
            "ai_interval_seconds",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise validation(
                sorted(unknown)[0],
                "unknown",
                "存在未知的自动化设置字段",
            )
        if "batch_size" in fields:
            value = int(fields["batch_size"])  # type: ignore[arg-type]
            if not 1 <= value <= 50:
                raise validation("batch_size", "range", "每轮处理上限必须在 1–50 之间")
            fields["batch_size"] = value
        if "max_attempts" in fields:
            value = int(fields["max_attempts"])  # type: ignore[arg-type]
            if not 1 <= value <= 10:
                raise validation("max_attempts", "range", "最大尝试次数必须在 1–10 之间")
            fields["max_attempts"] = value
        if "ai_interval_seconds" in fields:
            value = int(fields["ai_interval_seconds"])  # type: ignore[arg-type]
            if not 0 <= value <= 3600:
                raise validation(
                    "ai_interval_seconds", "range", "AI 调用间隔必须在 0–3600 秒之间"
                )
            fields["ai_interval_seconds"] = value
        for key in (
            "automation_enabled",
            "paused",
            "ai_enabled",
            "entity_enabled",
            "event_enabled",
            "scoring_enabled",
        ):
            if key in fields:
                fields[key] = 1 if bool(fields[key]) else 0

        normalized = {key: int(value) if isinstance(value, bool) else value for key, value in fields.items()}
        with database.session() as conn:
            pipeline_repo.update_settings(conn, normalized, updated_at=_now())
        log_event("pipeline_settings_updated", fields=sorted(fields))
        if normalized.get("automation_enabled") == 0 or normalized.get("paused") == 1:
            pass
        else:
            self._wake.set()
        return self.settings_payload()

    def pause(self) -> dict[str, object]:
        return self.update_settings({"paused": True})

    def resume(self) -> dict[str, object]:
        return self.update_settings({"paused": False})

    def set_automation(self, enabled: bool) -> dict[str, object]:
        return self.update_settings({"automation_enabled": enabled})

    # ------------------------------------------------------------------
    # ingestion hook
    # ------------------------------------------------------------------

    def on_articles_ingested(self, article_ids: list[str]) -> int:
        """Create tasks for newly inserted articles when automation is on."""

        if not article_ids:
            return 0
        settings = self.get_settings()
        if settings.paused or not settings.automation_enabled:
            return 0
        now = _now()
        created = 0
        with database.session() as conn:
            for article_id in dict.fromkeys(article_ids):
                if pipeline_repo.insert_task(
                    conn,
                    self._task_values(
                        article_id=article_id,
                        trigger_type="auto",
                        settings=settings,
                        now=now,
                        priority=10,
                    ),
                ):
                    created += 1
        if created:
            log_event("pipeline_enqueued", article_count=created, trigger="auto")
            self._wake.set()
        return created

    def _task_values(
        self,
        *,
        article_id: str,
        trigger_type: str,
        settings: PipelineSettingsRecord,
        now: str,
        priority: int,
        batch_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "id": str(uuid.uuid4()),
            "task_type": "article_pipeline",
            "article_id": article_id,
            "event_id": None,
            "stage": "quality_check",
            "status": "pending",
            "priority": priority,
            "idempotency_key": f"article_pipeline:{article_id}",
            "attempts": 0,
            "max_attempts": settings.max_attempts,
            "next_retry_at": None,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_heartbeat_at": None,
            "error_code": None,
            "error_message": None,
            "input_summary": None,
            "output_summary": None,
            "trigger_type": trigger_type,
            "batch_id": batch_id,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "updated_at": now,
        }

    # ------------------------------------------------------------------
    # queue processing
    # ------------------------------------------------------------------

    def _process_queue(self, settings: PipelineSettingsRecord) -> int:
        now = _now()
        with database.session() as conn:
            tasks = pipeline_repo.claim_ready(
                conn,
                owner=WORKER_NAME,
                now=now,
                lease_until=_iso_plus(LEASE_SECONDS),
                limit=settings.batch_size,
            )
        processed = 0
        for index, task in enumerate(tasks):
            if self._stop.is_set():
                break
            if task.article_id is None:
                self._skip_task(task, "article_not_found", "任务缺少关联文章")
                processed += 1
                continue
            if index > 0:
                remaining = self._ai_throttle_remaining(settings)
                if remaining > 0:
                    with database.session() as conn:
                        pipeline_repo.release_task(conn, task.id, now=_now())
                        pipeline_repo.update_task(
                            conn,
                            task.id,
                            {
                                "next_retry_at": _iso_plus(remaining),
                                "updated_at": _now(),
                            },
                        )
                    continue
            processed += self._advance_task(task, settings)
        return processed

    def _ai_throttle_remaining(self, settings: PipelineSettingsRecord) -> int:
        if settings.ai_interval_seconds <= 0 or self._last_ai_finished_monotonic is None:
            return 0
        elapsed = time.monotonic() - self._last_ai_finished_monotonic
        remaining = settings.ai_interval_seconds - elapsed
        return int(remaining) + 1 if remaining > 0 else 0

    def _advance_task(self, task: PipelineTaskRecord, settings: PipelineSettingsRecord) -> int:
        try:
            for _ in range(len(STAGE_ORDER) + 1):
                if task.stage == "quality_check":
                    task = self._quality_check(task)
                elif task.stage == "ai_analysis":
                    task = self._ai_stage(task, settings)
                elif task.stage == "entity_sync":
                    task = self._entity_stage(task, settings)
                else:
                    # Park at event_match; the batch phase picks it up.
                    self._park(task)
                    return 1
            self._fail_task(
                task,
                "stage_loop",
                "任务阶段推进异常，已停止",
                retryable=False,
            )
        except _TaskSkip as exc:
            self._skip_task(task, exc.code, exc.message)
        except _TaskDeferred as exc:
            self._defer_task(task, exc.code, exc.message, exc.delay_seconds)
        except _TaskFailure as exc:
            self._fail_task(task, exc.code, exc.message, retryable=exc.retryable)
        except Exception as exc:  # noqa: BLE001 - isolate one task
            log_event(
                "pipeline_task_failed",
                level="error",
                task_id=task.id,
                exc_type=type(exc).__name__,
            )
            self._fail_task(
                task,
                "internal_error",
                f"{type(exc).__name__}: {exc}"[:500],
                retryable=True,
            )
        return 1

    # ------------------------------------------------------------------
    # stages
    # ------------------------------------------------------------------

    def _quality_check(self, task: PipelineTaskRecord) -> PipelineTaskRecord:
        assert task.article_id is not None
        with database.read_session() as conn:
            article = article_repo.get_active(conn, task.article_id)
        if article is None:
            raise _TaskSkip("article_not_found", "文章不存在或已删除")

        body = (article.content_text or "").strip()
        summary = (article.summary or "").strip()
        text = body or summary
        if len(text) < MIN_CONTENT_CHARS:
            raise _TaskSkip(
                "content_insufficient",
                f"内容不足（content_state={article.content_state}，{len(text)} 字符）",
            )
        if article.content_state in ("unavailable", "blocked", "paywalled", "parse_failed") and not summary:
            raise _TaskSkip(
                "content_insufficient",
                f"内容不可用（content_state={article.content_state}）",
            )

        input_kind = "full" if body and article.content_state == "full" else "summary"
        summary_payload = {
            "content_state": article.content_state,
            "input_kind": input_kind,
            "input_chars": len(text),
            "title": article.title[:200],
            "source_name": article.source_name,
            "published_at": article.published_at,
        }
        with database.session() as conn:
            pipeline_repo.update_task(
                conn,
                task.id,
                {
                    "stage": "ai_analysis",
                    "status": "running",
                    "input_summary": _json(summary_payload),
                    "updated_at": _now(),
                },
            )
            self._log(
                conn,
                task,
                stage="quality_check",
                message=f"内容检查通过：{input_kind} 输入 {len(text)} 字符",
                detail=summary_payload,
            )
        return replace(task, stage="ai_analysis")

    def _ai_stage(
        self, task: PipelineTaskRecord, settings: PipelineSettingsRecord
    ) -> PipelineTaskRecord:
        assert task.article_id is not None
        article_id = task.article_id
        with database.read_session() as conn:
            article = article_repo.get_active(conn, article_id)
            if article is None:
                raise _TaskSkip("article_not_found", "文章不存在或已删除")
            exists = analysis_repo.exists_for_any_model(
                conn, article_id=article_id, content_hash=article.content_hash
            )

        if exists:
            with database.session() as conn:
                self._log(
                    conn,
                    task,
                    stage="ai_analysis",
                    message="已有同一内容版本的分析结果，跳过 AI 调用",
                )
                pipeline_repo.update_task(
                    conn,
                    task.id,
                    {"stage": "entity_sync", "updated_at": _now()},
                )
            return replace(task, stage="entity_sync")

        if not settings.ai_enabled:
            raise _TaskSkip("ai_disabled", "自动 AI 分析已关闭，任务未进入事件管道")

        ai_service = get_ai_service()
        if not ai_service.enabled:
            raise _TaskSkip("ai_service_disabled", "AI 服务已被配置关闭，跳过自动分析")

        try:
            run = ai_service.create_run(
                scope="selected",
                article_ids=[article_id],
                trigger_type="manual",
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "ai_run_failed")
            message = getattr(exc, "message", str(exc))
            if code == "ai_run_in_progress":
                raise _TaskDeferred(code, str(message)[:500], 60) from exc
            if code in {"ai_disabled", "article_already_analyzed"}:
                raise _TaskSkip(code, str(message)[:500]) from exc
            raise _TaskFailure(
                code,
                str(message)[:500],
                retryable=code not in PERMANENT_ERROR_CODES,
            ) from exc

        deadline = time.monotonic() + self.ai_timeout
        item = None
        last_beat = time.monotonic()
        while time.monotonic() < deadline:
            if self._stop.is_set():
                raise _TaskDeferred("interrupted", "服务正在停止，任务稍后继续", 30)
            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                # Phase 8.0: a local model can take minutes; keep the lease
                # alive so a slow-but-healthy run is not stolen by recovery.
                self._heartbeat(task.id)
                last_beat = time.monotonic()
            run = ai_service.get_run(run.id)
            item = next(
                (entry for entry in run.items if entry.article_id == article_id), None
            )
            if run.status in TERMINAL_STATUSES and item is not None:
                break
            if run.status in TERMINAL_STATUSES and item is None:
                break
            time.sleep(self.poll_seconds)
        self._last_ai_finished_monotonic = time.monotonic()

        if run.status not in TERMINAL_STATUSES:
            raise _TaskDeferred("ai_timeout", "等待本地模型超时，任务稍后重试", 120)

        if item is not None and item.status == "succeeded":
            output = {
                "ai_run_id": run.id,
                "model_name": run.model_name,
                "duration_ms": item.duration_ms,
                "input_chars": None,
            }
            with database.session() as conn:
                self._log(
                    conn,
                    task,
                    stage="ai_analysis",
                    message="AI 分析完成",
                    detail=output,
                )
                pipeline_repo.update_task(
                    conn,
                    task.id,
                    {
                        "stage": "entity_sync",
                        "output_summary": _json(output),
                        "updated_at": _now(),
                    },
                )
            return replace(task, stage="entity_sync")

        if item is not None and item.status == "skipped":
            with database.session() as conn:
                self._log(
                    conn,
                    task,
                    stage="ai_analysis",
                    message="AI 服务跳过了该文章（已有分析或内容不适用）",
                )
                pipeline_repo.update_task(
                    conn, task.id, {"stage": "entity_sync", "updated_at": _now()}
                )
            return replace(task, stage="entity_sync")

        code = (item.error_code if item is not None else None) or "ai_run_failed"
        message = (item.error_message if item is not None else run.error_message) or "AI 分析失败"
        raise _TaskFailure(
            code,
            str(message)[:500],
            retryable=code not in PERMANENT_ERROR_CODES,
        )

    def _entity_stage(
        self, task: PipelineTaskRecord, settings: PipelineSettingsRecord
    ) -> PipelineTaskRecord:
        assert task.article_id is not None
        if not settings.entity_enabled:
            with database.session() as conn:
                self._log(
                    conn,
                    task,
                    stage="entity_sync",
                    message="实体自动同步已关闭，跳过",
                    level="warn",
                )
                pipeline_repo.update_task(
                    conn, task.id, {"stage": "event_match", "updated_at": _now()}
                )
            return replace(task, stage="event_match")

        stats: dict[str, int] = {}
        with database.session() as conn:
            sync_article(conn, task.article_id, now=_now(), stats=stats)
            self._log(
                conn,
                task,
                stage="entity_sync",
                message="实体同步完成",
                detail=dict(stats),
            )
            pipeline_repo.update_task(
                conn,
                task.id,
                {
                    "stage": "event_match",
                    "status": "ready",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": _now(),
                },
            )
        return replace(task, stage="event_match", status="ready")

    # ------------------------------------------------------------------
    # event matching batch
    # ------------------------------------------------------------------

    def _process_event_batch(self, settings: PipelineSettingsRecord) -> int:
        now = _now()
        with database.session() as conn:
            tasks = pipeline_repo.claim_stage(
                conn,
                stage="event_match",
                owner=WORKER_NAME,
                now=now,
                lease_until=_iso_plus(LEASE_SECONDS),
                limit=settings.batch_size,
            )
        if not tasks:
            return 0

        assigned: dict[str, str] = {}
        pending: list[PipelineTaskRecord] = []
        handled: set[str] = set()
        for task in tasks:
            if task.article_id is None:
                self._skip_task(task, "article_not_found", "任务缺少关联文章")
                handled.add(task.id)
                continue
            with database.read_session() as conn:
                membership = event_repo.get_article_membership(conn, task.article_id)
            if membership is not None:
                assigned[task.id] = str(membership["event_id"])
            else:
                pending.append(task)

        if pending:
            if not settings.event_enabled:
                for task in pending:
                    self._skip_task(task, "event_disabled", "事件自动更新已关闭")
                    handled.add(task.id)
            else:
                handled |= self._run_clustering_batch(pending)

        # Resolve memberships after the clustering run, then close the read
        # transaction before writing finalize state.
        remaining = [
            task
            for task in tasks
            if task.id not in handled and task.id not in assigned
        ]
        memberships: dict[str, str] = {}
        if remaining:
            with database.read_session() as conn:
                for task in remaining:
                    if task.article_id is None:
                        continue
                    membership = event_repo.get_article_membership(conn, task.article_id)
                    if membership is not None:
                        memberships[task.id] = str(membership["event_id"])

        finished = 0
        for task in tasks:
            if task.id in handled:
                continue
            event_id = assigned.get(task.id) or memberships.get(task.id)
            if event_id is None:
                self._fail_task(
                    task,
                    "event_not_created",
                    "聚类执行后文章仍未归属任何事件",
                    retryable=True,
                )
                continue
            finished += self._finalize_task(task, event_id, settings)
        return finished

    def _run_clustering_batch(self, tasks: list[PipelineTaskRecord]) -> set[str]:
        """Run one clustering batch; return the task ids it already resolved."""

        article_ids = [task.article_id for task in tasks if task.article_id]
        service = get_event_clustering_service()
        try:
            run = service.create_run(
                scope="selected",
                article_ids=article_ids,
                limit=len(article_ids),
                use_llm=False,
                trigger_type="manual",
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "clustering_run_failed")
            message = str(getattr(exc, "message", exc))[:500]
            if code == "clustering_disabled":
                for task in tasks:
                    self._skip_task(task, code, message)
            elif code == "clustering_run_in_progress":
                for task in tasks:
                    self._defer_task(task, code, message, 60)
            else:
                for task in tasks:
                    self._fail_task(task, code, message, retryable=True)
            return {task.id for task in tasks}

        deadline = time.monotonic() + self.cluster_timeout
        last_beat = time.monotonic()
        while time.monotonic() < deadline:
            if self._stop.is_set():
                for task in tasks:
                    self._defer_task(task, "interrupted", "服务正在停止，稍后继续", 30)
                return {task.id for task in tasks}
            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                for task in tasks:
                    self._heartbeat(task.id)
                last_beat = time.monotonic()
            run = service.get_run(run.id)
            if run.status in RUN_TERMINAL_STATUSES:
                break
            time.sleep(self.poll_seconds)

        if run.status not in RUN_TERMINAL_STATUSES:
            for task in tasks:
                self._defer_task(task, "clustering_timeout", "等待事件聚类超时", 120)
            return {task.id for task in tasks}
        if run.status == "failed":
            for task in tasks:
                self._fail_task(
                    task,
                    "clustering_failed",
                    (run.error_message or "事件聚类失败")[:500],
                    retryable=True,
                )
            return {task.id for task in tasks}
        if run.status == "cancelled":
            for task in tasks:
                self._defer_task(task, "clustering_cancelled", "事件聚类被取消", 60)
            return {task.id for task in tasks}
        return set()

    def _finalize_task(
        self, task: PipelineTaskRecord, event_id: str, settings: PipelineSettingsRecord
    ) -> int:
        try:
            with database.session() as conn:
                pipeline_repo.update_task(
                    conn,
                    task.id,
                    {
                        "stage": "event_score",
                        "event_id": event_id,
                        "status": "running",
                        "lease_owner": WORKER_NAME,
                        "lease_expires_at": _iso_plus(LEASE_SECONDS),
                        "updated_at": _now(),
                    },
                )
                self._log(
                    conn,
                    task,
                    stage="event_match",
                    message="文章已归属事件",
                    detail={"event_id": event_id},
                )

            # Backfill can re-analyse an article that is already a member of an
            # older event; re-evaluate the event's domain so downstream scoring
            # and dashboards use the unified dictionary.
            with database.session() as conn:
                refresh_event_category(conn, event_id, now=_now())

            if settings.scoring_enabled:
                with database.session() as conn:
                    _, created = score_event_in_conn(conn, event_id)
                with database.session() as conn:
                    self._log(
                        conn,
                        task,
                        stage="event_score",
                        message="事件评分已刷新" if created else "评分无变化，未生成新快照",
                        detail={"event_id": event_id, "score_version": SCORE_VERSION},
                    )
            else:
                with database.session() as conn:
                    self._log(
                        conn,
                        task,
                        stage="event_score",
                        message="评分自动刷新已关闭，跳过",
                        level="warn",
                    )

            now = _now()
            with database.session() as conn:
                pipeline_repo.update_task(
                    conn,
                    task.id,
                    {
                        "stage": "done",
                        "status": "succeeded",
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "completed_at": now,
                        "error_code": None,
                        "error_message": None,
                        "updated_at": now,
                    },
                )
                self._log(
                    conn,
                    task,
                    stage="refresh",
                    message="任务完成，派生数据已刷新",
                    detail={"event_id": event_id},
                )
                if task.batch_id:
                    pipeline_repo.refresh_run_counters(conn, task.batch_id, now=now)

            # Phase 7.3.1: keep the personal feed in sync with the event without
            # adding a second scheduler. Pure rule scoring, never a model call.
            from services.personalization_service import refresh_event

            refresh_event(event_id)
            return 1
        except Exception as exc:  # noqa: BLE001 - isolate one task
            self._fail_task(
                task,
                "finalize_failed",
                f"{type(exc).__name__}: {exc}"[:500],
                retryable=True,
            )
            return 1

    # ------------------------------------------------------------------
    # state helpers
    # ------------------------------------------------------------------

    def _heartbeat(self, task_id: str) -> None:
        """Extend the lease of a long-running stage (best effort)."""

        try:
            with database.session() as conn:
                pipeline_repo.touch_lease(
                    conn,
                    task_id,
                    owner=WORKER_NAME,
                    now=_now(),
                    lease_until=_iso_plus(LEASE_SECONDS),
                )
        except Exception as exc:  # noqa: BLE001 - heartbeat must never fail a task
            log_event(
                "pipeline_heartbeat_failed",
                level="warn",
                task_id=task_id,
                exc_type=type(exc).__name__,
            )

    def _park(self, task: PipelineTaskRecord) -> None:
        # A task recovered after a crash can resume at event_score/refresh; the
        # only remaining work is event matching, so park at that stage instead
        # of leaving a stage nothing will ever claim again.
        with database.session() as conn:
            pipeline_repo.update_task(
                conn,
                task.id,
                {
                    "stage": "event_match",
                    "status": "ready",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": _now(),
                },
            )

    def _log(
        self,
        conn,
        task: PipelineTaskRecord,
        *,
        stage: str,
        message: str,
        detail: dict[str, object] | None = None,
        level: str = "info",
    ) -> None:
        pipeline_repo.add_log(
            conn,
            log_id=str(uuid.uuid4()),
            task_id=task.id,
            stage=stage,
            level=level,
            message=message,
            detail=detail,
            created_at=_now(),
        )

    def _skip_task(self, task: PipelineTaskRecord, code: str, message: str) -> None:
        now = _now()
        with database.session() as conn:
            pipeline_repo.update_task(
                conn,
                task.id,
                {
                    "status": "skipped",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": now,
                    "error_code": code,
                    "error_message": message[:500],
                    "updated_at": now,
                },
            )
            self._log(conn, task, stage=task.stage, message=message, level="warn")
            if task.batch_id:
                pipeline_repo.refresh_run_counters(conn, task.batch_id, now=now)

    def _defer_task(
        self, task: PipelineTaskRecord, code: str, message: str, delay_seconds: int
    ) -> None:
        now = _now()
        with database.session() as conn:
            pipeline_repo.update_task(
                conn,
                task.id,
                {
                    "status": "retry_wait",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "next_retry_at": _iso_plus(delay_seconds),
                    "error_code": code,
                    "error_message": message[:500],
                    "updated_at": now,
                },
            )
            self._log(conn, task, stage=task.stage, message=f"任务延后：{message}", level="warn")

    def _fail_task(
        self, task: PipelineTaskRecord, code: str, message: str, *, retryable: bool
    ) -> None:
        now = _now()
        attempts = task.attempts + 1
        with database.session() as conn:
            current = pipeline_repo.get_task(conn, task.id)
            if current is not None and current.status in TERMINAL_STATUSES:
                # Phase 8.0: business writes already committed and the task is
                # finished; a late error (e.g. a post-commit refresh) must not
                # move it back to retry_wait/failed and replay the whole chain.
                self._log(
                    conn,
                    task,
                    stage=task.stage,
                    message=f"任务已结束（{current.status}），忽略后续失败：{message}",
                    level="warn",
                )
                return
            if current is not None:
                attempts = current.attempts + 1
                max_attempts = current.max_attempts
            else:
                max_attempts = task.max_attempts
            if not retryable or attempts >= max_attempts:
                pipeline_repo.update_task(
                    conn,
                    task.id,
                    {
                        "status": "failed",
                        "attempts": attempts,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "completed_at": now,
                        "error_code": code,
                        "error_message": message[:500],
                        "updated_at": now,
                    },
                )
                self._log(
                    conn,
                    task,
                    stage=task.stage,
                    message=f"任务失败（不再重试）：{message}",
                    level="error",
                )
                if task.batch_id:
                    pipeline_repo.refresh_run_counters(conn, task.batch_id, now=now)
            else:
                backoff = min(300, 15 * (2 ** (attempts - 1)))
                pipeline_repo.update_task(
                    conn,
                    task.id,
                    {
                        "status": "retry_wait",
                        "attempts": attempts,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "next_retry_at": _iso_plus(backoff),
                        "error_code": code,
                        "error_message": message[:500],
                        "updated_at": now,
                    },
                )
                self._log(
                    conn,
                    task,
                    stage=task.stage,
                    message=f"任务失败，{backoff} 秒后重试：{message}",
                    level="warn",
                )

    # ------------------------------------------------------------------
    # queries / commands
    # ------------------------------------------------------------------

    def overview(self) -> dict[str, object]:
        with database.read_session() as conn:
            counts = pipeline_repo.count_by_status(conn)
            stages = pipeline_repo.count_by_stage(conn)
            activity = pipeline_repo.recent_activity(conn)
            today = pipeline_repo.today_counts(conn, since=_today_start())
            settings = pipeline_repo.get_settings(conn)
        total = sum(counts.values())
        pending = counts.get("pending", 0) + counts.get("ready", 0)
        return {
            "automation": {
                "enabled": settings.automation_enabled,
                "paused": settings.paused,
                "ai_enabled": settings.ai_enabled,
                "entity_enabled": settings.entity_enabled,
                "event_enabled": settings.event_enabled,
                "scoring_enabled": settings.scoring_enabled,
            },
            "settings": self.settings_payload(),
            "counts": {
                "total": total,
                "pending": pending,
                "running": counts.get("running", 0),
                "retry_wait": counts.get("retry_wait", 0),
                "succeeded": counts.get("succeeded", 0),
                "failed": counts.get("failed", 0),
                "skipped": counts.get("skipped", 0),
                "cancelled": counts.get("cancelled", 0),
            },
            "queue": {
                "waiting": pending,
                "retry_wait": counts.get("retry_wait", 0),
                "running": counts.get("running", 0),
            },
            "stage_counts": stages,
            "activity": activity,
            "today": today,
            "runtime": self.runtime(),
            "taxonomy_version": TAXONOMY_VERSION,
            "score_version": SCORE_VERSION,
        }

    def runtime(self) -> dict[str, object]:
        thread = self._thread
        return {
            "worker_alive": bool(thread is not None and thread.is_alive()),
            "last_sweep_at": self._last_sweep_at,
            "last_sweep_duration_ms": self._last_sweep_ms,
            "last_sweep_error": self._last_sweep_error,
            "last_recovered_tasks": self._last_recovered,
        }

    def list_tasks(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None,
        stage: str | None,
        trigger_type: str | None,
    ) -> tuple[list[PipelineTaskRecord], int]:
        with database.read_session() as conn:
            return pipeline_repo.list_tasks(
                conn,
                limit=limit,
                offset=offset,
                status=status,
                stage=stage,
                trigger_type=trigger_type,
            )

    def get_task(self, task_id: str) -> PipelineTaskRecord:
        with database.read_session() as conn:
            task = pipeline_repo.get_task(conn, task_id)
        if task is None:
            raise not_found("pipeline_task_not_found", "管道任务不存在")
        return task

    def task_logs(
        self, task_id: str, *, limit: int, offset: int
    ) -> tuple[list[PipelineTaskLogRecord], int]:
        self.get_task(task_id)
        with database.read_session() as conn:
            return pipeline_repo.list_logs(conn, task_id, limit=limit, offset=offset)

    def retry_task(self, task_id: str) -> PipelineTaskRecord:
        now = _now()
        with database.session() as conn:
            task = pipeline_repo.get_task(conn, task_id)
            if task is None:
                raise not_found("pipeline_task_not_found", "管道任务不存在")
            if task.status == "running":
                raise conflict(
                    "pipeline_task_running", "运行中的任务不能重试，请等待当前阶段结束"
                )
            if task.status not in {"failed", "skipped", "cancelled", "retry_wait"}:
                raise conflict("pipeline_task_not_retryable", "该任务当前状态不可重试")
            pipeline_repo.update_task(
                conn,
                task_id,
                {
                    "status": "ready",
                    "attempts": 0,
                    "max_attempts": max(task.max_attempts, 3),
                    "next_retry_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": None,
                    "error_code": None,
                    "error_message": None,
                    "updated_at": now,
                },
            )
            pipeline_repo.add_log(
                conn,
                log_id=str(uuid.uuid4()),
                task_id=task_id,
                stage=task.stage,
                level="info",
                message="人工重试，任务已重新排队",
                detail={"previous_status": task.status, "previous_attempts": task.attempts},
                created_at=now,
            )
            updated = pipeline_repo.get_task(conn, task_id)
        self._wake.set()
        assert updated is not None
        return updated

    def cancel_task(self, task_id: str) -> PipelineTaskRecord:
        now = _now()
        with database.session() as conn:
            task = pipeline_repo.get_task(conn, task_id)
            if task is None:
                raise not_found("pipeline_task_not_found", "管道任务不存在")
            if task.status == "running":
                raise conflict(
                    "pipeline_task_running",
                    "运行中的任务不能强制取消，避免数据库状态不一致",
                )
            if task.status in TERMINAL_STATUSES:
                raise conflict("pipeline_task_not_cancellable", "该任务已结束，无需取消")
            pipeline_repo.update_task(
                conn,
                task_id,
                {
                    "status": "cancelled",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": now,
                    "updated_at": now,
                },
            )
            pipeline_repo.add_log(
                conn,
                log_id=str(uuid.uuid4()),
                task_id=task_id,
                stage=task.stage,
                level="warn",
                message="任务已人工取消",
                detail={"previous_status": task.status},
                created_at=now,
            )
            if task.batch_id:
                pipeline_repo.refresh_run_counters(conn, task.batch_id, now=now)
            updated = pipeline_repo.get_task(conn, task_id)
        assert updated is not None
        return updated

    # ------------------------------------------------------------------
    # backfill
    # ------------------------------------------------------------------

    def backfill_preview(self) -> dict[str, object]:
        with database.read_session() as conn:
            preview = pipeline_repo.backfill_preview(conn)
        ai_needed = preview["ai_needed"]
        return {
            **preview,
            "estimated_ai_seconds": ai_needed * 10,
            "estimated_total_minutes": round((ai_needed * 10) / 60, 1),
            "note": (
                "回填只创建持久化任务，不会立即改写历史数据；"
                "AI 与聚类按批处理上限逐步执行，可随时暂停。"
            ),
        }

    def create_backfill(self, *, limit: int) -> dict[str, object]:
        if not 1 <= int(limit) <= 500:
            raise validation("limit", "range", "单次回填数量必须在 1–500 之间")
        now = _now()
        settings = self.get_settings()
        with database.session() as conn:
            article_ids = pipeline_repo.next_backfill_article_ids(conn, limit=int(limit))
            if not article_ids:
                raise conflict("no_backfill_articles", "没有需要回填的文章")
            run_id = str(uuid.uuid4())
            pipeline_repo.insert_run(
                conn,
                {
                    "id": run_id,
                    "trigger_type": "backfill",
                    "status": "pending",
                    "requested_tasks": len(article_ids),
                    "created_tasks": 0,
                    "processed_tasks": 0,
                    "succeeded_tasks": 0,
                    "failed_tasks": 0,
                    "skipped_tasks": 0,
                    "cancel_requested": 0,
                    "error_message": None,
                    "started_at": None,
                    "finished_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            created = 0
            for article_id in article_ids:
                if pipeline_repo.insert_task(
                    conn,
                    self._task_values(
                        article_id=article_id,
                        trigger_type="backfill",
                        settings=settings,
                        now=now,
                        priority=200,
                        batch_id=run_id,
                    ),
                ):
                    created += 1
            pipeline_repo.update_run(
                conn,
                run_id,
                {
                    "created_tasks": created,
                    "status": "running",
                    "started_at": now,
                    "updated_at": now,
                },
            )
            run = pipeline_repo.get_run(conn, run_id)
        log_event("pipeline_backfill_created", run_id=run_id, task_count=created)
        self._wake.set()
        assert run is not None
        return {"run": self._run_payload(run), "created_tasks": created}

    def list_runs(
        self, *, limit: int, offset: int
    ) -> tuple[list[PipelineRunRecord], int]:
        with database.read_session() as conn:
            return pipeline_repo.list_runs(conn, limit=limit, offset=offset)

    def get_run(self, run_id: str) -> PipelineRunRecord:
        with database.read_session() as conn:
            run = pipeline_repo.get_run(conn, run_id)
        if run is None:
            raise not_found("pipeline_run_not_found", "回填批次不存在")
        return run

    def cancel_run(self, run_id: str) -> PipelineRunRecord:
        now = _now()
        with database.session() as conn:
            run = pipeline_repo.get_run(conn, run_id)
            if run is None:
                raise not_found("pipeline_run_not_found", "回填批次不存在")
            if run.status in {"succeeded", "partially_succeeded", "failed", "cancelled"}:
                raise conflict("pipeline_run_finished", "批次已结束，无需取消")
            pipeline_repo.update_run(
                conn,
                run_id,
                {"cancel_requested": 1, "status": "cancelled", "finished_at": now, "updated_at": now},
            )
            pipeline_repo.cancel_pending_tasks_for_run(conn, run_id, now=now)
            pipeline_repo.refresh_run_counters(conn, run_id, now=now)
            updated = pipeline_repo.get_run(conn, run_id)
        assert updated is not None
        return updated

    @staticmethod
    def _run_payload(run: PipelineRunRecord) -> dict[str, object]:
        return {
            "id": run.id,
            "trigger_type": run.trigger_type,
            "status": run.status,
            "requested_tasks": run.requested_tasks,
            "created_tasks": run.created_tasks,
            "processed_tasks": run.processed_tasks,
            "succeeded_tasks": run.succeeded_tasks,
            "failed_tasks": run.failed_tasks,
            "skipped_tasks": run.skipped_tasks,
            "cancel_requested": run.cancel_requested,
            "error_message": run.error_message,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }


_orchestrator: PipelineOrchestrator | None = None


def get_orchestrator() -> PipelineOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
    return _orchestrator


def reset_orchestrator(service: PipelineOrchestrator | None = None) -> None:
    global _orchestrator
    _orchestrator = service


__all__ = [
    "PipelineOrchestrator",
    "STAGE_ORDER",
    "get_orchestrator",
    "reset_orchestrator",
]
