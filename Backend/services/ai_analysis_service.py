"""AI analysis orchestration: runs, single-concurrency queue, validation.

Constraints (`Docs/PHASE3_AI_ENGINE.md`):
* one article at a time (concurrency = 1);
* network calls never run inside a SQLite transaction;
* only validated output is persisted;
* pause/resume/cancel are honoured at item boundaries;
* a restart marks stale running work as interrupted;
* Ollama being unavailable never blocks reading or collection.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

import database
from ai_engine.errors import (
    AIError,
    ARTICLE_NOT_ANALYZABLE,
    INTERNAL_ERROR,
    INTERRUPTED,
    INVALID_JSON,
    INVALID_RESPONSE,
    MODEL_UNAVAILABLE,
    PROVIDER_HTTP_ERROR,
    PROVIDER_TIMEOUT,
    PROVIDER_UNREACHABLE,
    RESPONSE_TOO_LARGE,
    SCHEMA_INVALID,
)
from ai_engine.prompts import PROMPT_VERSION, build_messages
from ai_engine.provider import (
    GenerationResult,
    OllamaLocalProvider,
    ProviderHealth,
)
from ai_engine.schema import extract_json, validate_analysis
from core.logging import log_event
from core.timeutil import utc_timestamp
from database.repositories import ai_analysis_repository as analysis_repo
from database.repositories import ai_model_repository as model_repo
from database.repositories import ai_run_repository as run_repo
from database.repositories import article_repository as article_repo
from database.repositories.models import (
    AIAnalysisRecord,
    AIModelRecord,
    AIRunItemRecord,
    AIRunRecord,
    ArticleRecord,
)
from services.errors import conflict, not_found, validation

MAX_BATCH_ARTICLES = 100
MAX_UNANALYZED = 200
DEFAULT_UNANALYZED = 20
MAX_ATTEMPTS = 3
RUN_KEEP = 200
CONCURRENCY = 1
HEALTH_CACHE_SECONDS = 10.0
AI_ENABLED_ENV = "PIH_AI_ENABLED"

DEFAULT_TEMPERATURE = 0.1
DEFAULT_NUM_PREDICT = 512

_RETRYABLE_ERRORS = {INVALID_JSON, SCHEMA_INVALID, MODEL_UNAVAILABLE}
# Transport failures are surfaced to clients as the stable `model_unavailable`
# code; the precise provider code stays in the item's error_message.
_TRANSPORT_ERRORS = {
    PROVIDER_UNREACHABLE,
    PROVIDER_TIMEOUT,
    PROVIDER_HTTP_ERROR,
    INVALID_RESPONSE,
    RESPONSE_TOO_LARGE,
}


@dataclass(frozen=True, slots=True)
class ModelView:
    record: AIModelRecord
    installed: bool
    remote: bool
    live_parameter_size: str | None = None
    live_quantization: str | None = None
    live_size_bytes: int | None = None
    live_digest: str | None = None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_ms(started_at: str | None, finished_at: str) -> int:
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(finished_at)
    if start is None or end is None:
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


class AIAnalysisService:
    def __init__(
        self,
        *,
        provider: OllamaLocalProvider | None = None,
        enabled: bool | None = None,
        clock=time.monotonic,
    ) -> None:
        if enabled is None:
            enabled = os.environ.get(AI_ENABLED_ENV, "1") != "0"
        self.enabled = enabled
        self.provider = provider or OllamaLocalProvider()
        self._clock = clock
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._running_run_id: str | None = None
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
        self._requeue_pending_runs()
        self._worker = threading.Thread(
            target=self._worker_loop, name="pih-ai-worker", daemon=True
        )
        self._worker.start()

    def _requeue_pending_runs(self) -> None:
        if not self.enabled:
            return
        try:
            with database.read_session() as conn:
                run_ids = run_repo.list_pending_run_ids(conn)
        except Exception:  # noqa: BLE001 - startup must not crash
            return
        for run_id in run_ids:
            self._queue.put(run_id)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("")
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        self._started = False

    def recover_interrupted(self) -> int:
        try:
            now = utc_timestamp()
            with database.session() as conn:
                changed = run_repo.mark_stale(conn, now)
                run_repo.prune_runs(conn, RUN_KEEP)
            if changed:
                log_event("ai_recovered", level="warn", run_count=changed)
            return changed
        except Exception as exc:  # noqa: BLE001 - startup must not crash
            log_event(
                "ai_recovery_failed",
                level="error",
                error_code=INTERRUPTED,
                exc_type=type(exc).__name__,
            )
            return 0

    # ------------------------------------------------------------------
    # health / models
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

    def _registry_models(self) -> list[AIModelRecord]:
        with database.read_session() as conn:
            return model_repo.list_models(conn)

    def model_views(self) -> list[ModelView]:
        records = self._registry_models()
        health = self.health()
        live = {model.name: model for model in health.models}
        views: list[ModelView] = []
        for record in records:
            remote = live.get(record.model_name)
            views.append(
                ModelView(
                    record=record,
                    installed=remote is not None,
                    remote=bool(remote and remote.is_remote),
                    live_parameter_size=remote.parameter_size if remote else None,
                    live_quantization=remote.quantization if remote else None,
                    live_size_bytes=remote.size_bytes if remote else None,
                    live_digest=remote.digest if remote else None,
                )
            )
        return views

    def status(self) -> dict[str, object]:
        health = self.health()
        try:
            records = self._registry_models()
        except Exception:  # noqa: BLE001 - status must not fail
            records = []
        live_names = {model.name for model in health.models}
        enabled_models = [record.model_name for record in records if record.enabled]
        installed = [record.model_name for record in records if record.model_name in live_names]
        cloud_blocked = sum(1 for model in health.models if model.is_remote)
        default = next((record for record in records if record.enabled), None)
        with self._lock:
            running = self._running_run_id
            depth = self._queue.qsize()
        return {
            "enabled": self.enabled,
            "provider_kind": "ollama-local",
            "base_url": self.provider.base_url,
            "available": health.available,
            "version": health.version,
            "error_code": None if health.available else MODEL_UNAVAILABLE,
            "default_model": default.model_name if default else None,
            "enabled_models": enabled_models,
            "installed_models": installed,
            "cloud_models_blocked": cloud_blocked,
            "concurrency": CONCURRENCY,
            "queue_depth": depth,
            "running_run_id": running,
            "embedding": {
                "enabled": False,
                "reason": "embedding_model_not_configured",
            },
            "checked_at": health.checked_at,
        }

    # ------------------------------------------------------------------
    # runs: read
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> AIRunRecord:
        with database.read_session() as conn:
            record = run_repo.get_run(conn, run_id)
        if record is None:
            raise not_found("ai_run_not_found", "AI 运行不存在")
        return record

    def list_runs(
        self, *, limit: int, offset: int, status: str | None = None
    ) -> tuple[list[AIRunRecord], int]:
        with database.read_session() as conn:
            return run_repo.list_runs(conn, limit=limit, offset=offset, status=status)

    def article_analysis(self, article_id: str) -> list[AIAnalysisRecord]:
        with database.read_session() as conn:
            article = article_repo.get_active(conn, article_id)
            if article is None:
                raise not_found("article_not_found", "文章不存在")
            return analysis_repo.list_for_article(conn, article_id)

    # ------------------------------------------------------------------
    # runs: create / control
    # ------------------------------------------------------------------

    def _default_model(self) -> AIModelRecord:
        with database.read_session() as conn:
            model = model_repo.default_model(conn)
        if model is None:
            raise conflict("ai_model_not_configured", "没有启用的本地模型")
        return model

    def create_run(
        self,
        *,
        scope: str,
        article_ids: list[str] | None = None,
        limit: int = DEFAULT_UNANALYZED,
        trigger_type: str = "manual",
    ) -> AIRunRecord:
        if not self.enabled:
            raise conflict("ai_disabled", "本地 AI 分析已禁用")
        model = self._default_model()

        skipped = 0
        skipped_articles: list[str] = []
        if scope == "selected":
            if not article_ids:
                raise validation("article_ids", "required", "至少选择一篇文章")
            if len(set(article_ids)) > MAX_BATCH_ARTICLES:
                raise conflict("ai_run_batch_too_large", "单次最多分析 100 篇文章")
            selected: list[str] = []
            with database.read_session() as conn:
                for article_id in dict.fromkeys(article_ids):
                    article = article_repo.get_active(conn, article_id)
                    if article is None:
                        raise not_found("article_not_found", "文章不存在")
                    if analysis_repo.exists_for(
                        conn,
                        article_id=article.id,
                        content_hash=article.content_hash,
                        model_name=model.model_name,
                        prompt_version=PROMPT_VERSION,
                    ):
                        skipped += 1
                        skipped_articles.append(article.id)
                        continue
                    selected.append(article.id)
            if not selected:
                raise conflict("article_already_analyzed", "选中的文章均已有分析结果")
            article_ids_final = selected
        elif scope == "unanalyzed":
            bounded = max(1, min(int(limit), MAX_UNANALYZED))
            with database.read_session() as conn:
                article_ids_final = analysis_repo.eligible_article_ids(
                    conn,
                    model_name=model.model_name,
                    prompt_version=PROMPT_VERSION,
                    limit=bounded,
                )
            if not article_ids_final:
                raise conflict("no_analyzable_articles", "没有需要分析的文章")
        else:
            raise validation("scope", "invalid", "scope 必须是 selected 或 unanalyzed")

        now = utc_timestamp()
        run_id = str(uuid.uuid4())
        with database.session() as conn:
            if run_repo.find_active_run(conn, scope=scope) is not None:
                raise conflict("ai_run_in_progress", "已有同类型的 AI 运行在进行中")
            run_repo.insert_run(
                conn,
                {
                    "id": run_id,
                    "trigger_type": trigger_type,
                    "scope": scope,
                    "status": "pending",
                    "requested_count": len(article_ids_final) + skipped,
                    "processed_count": 0,
                    "succeeded_count": 0,
                    "failed_count": 0,
                    "skipped_count": skipped,
                    "model_name": model.model_name,
                    "error_message": None,
                    "cancel_requested": 0,
                    "pause_requested": 0,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            for article_id in article_ids_final:
                run_repo.insert_item(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "article_id": article_id,
                        "status": "pending",
                        "attempts": 0,
                        "error_code": None,
                        "error_message": None,
                        "started_at": None,
                        "finished_at": None,
                        "duration_ms": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            for article_id in skipped_articles:
                run_repo.insert_item(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "article_id": article_id,
                        "status": "skipped",
                        "attempts": 0,
                        "error_code": None,
                        "error_message": "同内容已有分析结果",
                        "started_at": None,
                        "finished_at": now,
                        "duration_ms": 0,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            run_repo.prune_runs(conn, RUN_KEEP)
        log_event(
            "ai_run_created",
            run_id=run_id,
            scope=scope,
            article_count=len(article_ids_final),
            model=model.model_name,
        )
        self._enqueue(run_id)
        return self.get_run(run_id)

    def analyze_article(self, article_id: str) -> AIRunRecord:
        model = self._default_model()
        with database.read_session() as conn:
            article = article_repo.get_active(conn, article_id)
            if article is None:
                raise not_found("article_not_found", "文章不存在")
            existing = analysis_repo.exists_for(
                conn,
                article_id=article.id,
                content_hash=article.content_hash,
                model_name=model.model_name,
                prompt_version=PROMPT_VERSION,
            )
        if existing:
            raise conflict("article_already_analyzed", "该文章已有分析结果")
        return self.create_run(scope="selected", article_ids=[article_id])

    def pause_run(self, run_id: str) -> AIRunRecord:
        record = self.get_run(run_id)
        if record.status not in ("pending", "running"):
            raise conflict("run_not_pausable", "当前状态不可暂停")
        now = utc_timestamp()
        with database.session() as conn:
            run_repo.update_run(
                conn,
                run_id,
                {"status": "paused", "pause_requested": 1, "updated_at": now},
            )
        return self.get_run(run_id)

    def resume_run(self, run_id: str) -> AIRunRecord:
        record = self.get_run(run_id)
        if record.status != "paused":
            raise conflict("run_not_resumable", "当前状态不可恢复")
        now = utc_timestamp()
        with database.session() as conn:
            run_repo.update_run(
                conn,
                run_id,
                {"status": "pending", "pause_requested": 0, "updated_at": now},
            )
        self._enqueue(run_id)
        return self.get_run(run_id)

    def cancel_run(self, run_id: str) -> AIRunRecord:
        record = self.get_run(run_id)
        if record.status not in ("pending", "running", "paused"):
            raise conflict("run_not_cancellable", "当前状态不可取消")
        now = utc_timestamp()
        with database.session() as conn:
            run_repo.update_run(
                conn, run_id, {"cancel_requested": 1, "updated_at": now}
            )
            if record.status in ("pending", "paused"):
                run_repo.fail_pending_items(
                    conn,
                    run_id,
                    status="cancelled",
                    error_code=INTERRUPTED,
                    error_message="运行已取消",
                    finished_at=now,
                )
                counts = run_repo.counts(conn, run_id)
                run_repo.update_run(
                    conn,
                    run_id,
                    {
                        "status": "cancelled",
                        "processed_count": counts["processed"],
                        "succeeded_count": counts["succeeded"],
                        "failed_count": counts["failed"],
                        "skipped_count": counts["skipped"],
                        "finished_at": now,
                        "duration_ms": _duration_ms(record.started_at, now),
                        "updated_at": now,
                    },
                )
        return self.get_run(run_id)

    def retry_run(self, run_id: str) -> AIRunRecord:
        record = self.get_run(run_id)
        if record.status not in ("failed", "partially_succeeded", "cancelled"):
            raise conflict("run_not_retryable", "当前状态不可重试")
        with database.read_session() as conn:
            article_ids = run_repo.retryable_article_ids(conn, run_id)
        if not article_ids:
            raise conflict("run_not_retryable", "没有可重试的文章")
        return self.create_run(
            scope="selected", article_ids=article_ids, trigger_type="retry"
        )

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _enqueue(self, run_id: str) -> None:
        if self.enabled:
            self._queue.put(run_id)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not run_id or self._stop.is_set():
                continue
            try:
                self._execute_run(run_id)
            except Exception as exc:  # noqa: BLE001 - one run must not kill the worker
                log_event(
                    "ai_run_crashed",
                    level="error",
                    run_id=run_id,
                    error_code=INTERNAL_ERROR,
                    exc_type=type(exc).__name__,
                )
                self._fail_run(run_id, INTERNAL_ERROR, "AI 运行内部错误")

    def _execute_run(self, run_id: str) -> None:
        record = self.get_run(run_id)
        if record.status not in ("pending", "running"):
            return
        now = utc_timestamp()
        started_at = record.started_at or now
        with database.session() as conn:
            started = run_repo.start_run(
                conn, run_id, started_at=started_at, now=now
            )
        if not started:
            # A pause or cancel arrived between the read and the update.
            current = self.get_run(run_id)
            if current.cancel_requested:
                self._finalize(run_id, terminal="cancelled", cancel_pending=True)
            elif current.status == "paused" or current.pause_requested:
                self._finalize(run_id, terminal="paused")
            return
        with self._lock:
            self._running_run_id = run_id

        try:
            with database.read_session() as conn:
                registry = model_repo.get(conn, record.model_name or "")
            if registry is None or not registry.enabled:
                self._fail_run(run_id, "model_not_allowed", "模型未启用")
                return
            allowed = self._allowed_models()

            while not self._stop.is_set():
                with database.read_session() as conn:
                    current = run_repo.get_run(conn, run_id)
                if current is None:
                    return
                if current.cancel_requested:
                    self._finalize(run_id, terminal="cancelled", cancel_pending=True)
                    return
                if current.status == "paused" or current.pause_requested:
                    self._finalize(run_id, terminal="paused")
                    return
                with database.read_session() as conn:
                    item = run_repo.next_pending_item(conn, run_id)
                if item is None:
                    self._finalize(run_id)
                    return
                self._process_item(run_id, item, registry)
        finally:
            with self._lock:
                self._running_run_id = None

    def _allowed_models(self) -> tuple[str, ...]:
        with database.read_session() as conn:
            return model_repo.enabled_model_names(conn)

    def _process_item(
        self, run_id: str, item: AIRunItemRecord, model: AIModelRecord
    ) -> None:
        started_at = utc_timestamp()
        started_clock = time.monotonic()
        with database.session() as conn:
            if not run_repo.claim_item(conn, item.id, started_at):
                return

        article: ArticleRecord | None
        with database.read_session() as conn:
            article = article_repo.get_active(conn, item.article_id)
        if article is None:
            self._finish_item(
                run_id,
                item.id,
                article_id=item.article_id,
                status="failed",
                attempts=0,
                started_at=started_at,
                started_clock=started_clock,
                error_code=ARTICLE_NOT_ANALYZABLE,
                error_message="文章不存在或已删除",
            )
            return

        attempts = 0
        last_error: AIError | None = None
        result: GenerationResult | None = None
        analysis = None
        input_chars = 0

        try:
            messages, input_chars = build_messages(
                title=article.title,
                source_name=article.source_name,
                published_at=article.published_at,
                body=article.content_text,
                summary=article.summary,
            )
            allowed = self._allowed_models()
            for attempt in range(MAX_ATTEMPTS):
                attempts = attempt + 1
                try:
                    result = self.provider.generate_structured(
                        model=model.model_name,
                        messages=messages,
                        num_ctx=model.num_ctx,
                        temperature=DEFAULT_TEMPERATURE,
                        num_predict=DEFAULT_NUM_PREDICT,
                        allowed_models=allowed,
                    )
                    payload = extract_json(result.text)
                    analysis = validate_analysis(payload)
                    last_error = None
                    break
                except AIError as exc:
                    last_error = exc
                    if attempts >= MAX_ATTEMPTS or (
                        exc.code not in _RETRYABLE_ERRORS and not exc.retryable
                    ):
                        break
        except AIError as exc:
            last_error = exc
        except Exception as exc:  # noqa: BLE001 - must not leave the item running
            last_error = AIError(
                INTERNAL_ERROR, f"AI 分析内部错误（{type(exc).__name__}）"
            )

        if analysis is None or result is None:
            error = last_error or AIError(INTERNAL_ERROR, "分析失败")
            code, message = self._item_error(error)
            self._finish_item(
                run_id,
                item.id,
                article_id=article.id,
                status="failed",
                attempts=attempts,
                started_at=started_at,
                started_clock=started_clock,
                error_code=code,
                error_message=message,
            )
            return

        finished_at = utc_timestamp()
        duration_ms = max(0, int((time.monotonic() - started_clock) * 1000))
        item_status = "succeeded"
        try:
            with database.session() as conn:
                exists = analysis_repo.exists_for(
                    conn,
                    article_id=article.id,
                    content_hash=article.content_hash,
                    model_name=model.model_name,
                    prompt_version=PROMPT_VERSION,
                )
                if exists:
                    item_status = "skipped"
                    run_repo.update_item(
                        conn,
                        item.id,
                        {
                            "status": "skipped",
                            "attempts": attempts,
                            "started_at": started_at,
                            "finished_at": finished_at,
                            "duration_ms": duration_ms,
                            "updated_at": finished_at,
                        },
                    )
                else:
                    analysis_repo.insert(
                        conn,
                        {
                            "id": str(uuid.uuid4()),
                            "article_id": article.id,
                            "analysis_type": "article_analysis",
                            "provider_kind": "ollama-local",
                            "model_name": model.model_name,
                            "model_digest": result.model_digest,
                            "prompt_version": PROMPT_VERSION,
                            "params_json": json.dumps(
                                {
                                    "num_ctx": model.num_ctx,
                                    "temperature": DEFAULT_TEMPERATURE,
                                    "num_predict": DEFAULT_NUM_PREDICT,
                                },
                                separators=(",", ":"),
                            ),
                            "content_hash": article.content_hash,
                            "category": analysis.category,
                            "summary": analysis.summary,
                            "keywords_json": json.dumps(
                                list(analysis.keywords), ensure_ascii=False
                            ),
                            "entities_json": json.dumps(
                                list(analysis.entities), ensure_ascii=False
                            ),
                            "confidence": analysis.confidence,
                            "input_chars": input_chars,
                            "duration_ms": duration_ms,
                            "created_at": finished_at,
                        },
                    )
                    run_repo.update_item(
                        conn,
                        item.id,
                        {
                            "status": "succeeded",
                            "attempts": attempts,
                            "started_at": started_at,
                            "finished_at": finished_at,
                            "duration_ms": duration_ms,
                            "updated_at": finished_at,
                        },
                    )
                model_repo.update_observation(
                    conn,
                    model_name=model.model_name,
                    digest=result.model_digest,
                    size_bytes=None,
                    parameter_size=None,
                    quantization=None,
                    checked_at=finished_at,
                )
        except Exception as exc:  # noqa: BLE001 - keep the item state truthful
            self._finish_item(
                run_id,
                item.id,
                article_id=article.id,
                status="failed",
                attempts=attempts,
                started_at=started_at,
                started_clock=started_clock,
                error_code=INTERNAL_ERROR,
                error_message=f"分析结果写入失败（{type(exc).__name__}）",
            )
            return
        log_event(
            "ai_item_finished",
            run_id=run_id,
            article_id=article.id,
            status=item_status,
            attempts=attempts,
            duration_ms=duration_ms,
            model=model.model_name,
            tok_per_s=result.tok_per_s,
        )

    @staticmethod
    def _item_error(error: AIError) -> tuple[str, str]:
        if error.code in _TRANSPORT_ERRORS:
            return (
                MODEL_UNAVAILABLE,
                f"本地模型不可用（{error.code}）：{error.message}"[:500],
            )
        return error.code, error.message

    def _finish_item(
        self,
        run_id: str,
        item_id: str,
        *,
        article_id: str,
        status: str,
        attempts: int,
        started_at: str,
        started_clock: float,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        finished_at = utc_timestamp()
        duration_ms = max(0, int((time.monotonic() - started_clock) * 1000))
        with database.session() as conn:
            run_repo.update_item(
                conn,
                item_id,
                {
                    "status": status,
                    "attempts": attempts,
                    "error_code": error_code,
                    "error_message": (error_message or "")[:500] or None,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_ms": duration_ms,
                    "updated_at": finished_at,
                },
            )
        log_event(
            "ai_item_failed",
            level="warn",
            run_id=run_id,
            item_id=item_id,
            article_id=article_id,
            status=status,
            attempts=attempts,
            error_code=error_code,
            duration_ms=duration_ms,
        )

    def _finalize(
        self, run_id: str, *, terminal: str | None = None, cancel_pending: bool = False
    ) -> None:
        now = utc_timestamp()
        with database.session() as conn:
            record = run_repo.get_run(conn, run_id)
            if record is None:
                return
            if cancel_pending:
                run_repo.fail_pending_items(
                    conn,
                    run_id,
                    status="cancelled",
                    error_code=INTERRUPTED,
                    error_message="运行已取消",
                    finished_at=now,
                )
            counts = run_repo.counts(conn, run_id)
            if terminal == "paused":
                run_repo.update_run(
                    conn,
                    run_id,
                    {
                        "status": "paused",
                        "pause_requested": 1,
                        "processed_count": counts["processed"],
                        "succeeded_count": counts["succeeded"],
                        "failed_count": counts["failed"],
                        "skipped_count": counts["skipped"],
                        "updated_at": now,
                    },
                )
                return
            if terminal == "cancelled":
                status = "cancelled"
            elif counts["failed"] == 0:
                status = "succeeded"
            elif counts["succeeded"] > 0 or counts["skipped"] > 0:
                status = "partially_succeeded"
            else:
                status = "failed"
            run_repo.update_run(
                conn,
                run_id,
                {
                    "status": status,
                    "processed_count": counts["processed"],
                    "succeeded_count": counts["succeeded"],
                    "failed_count": counts["failed"],
                    "skipped_count": counts["skipped"],
                    "pause_requested": 0,
                    "finished_at": now,
                    "duration_ms": _duration_ms(record.started_at or record.created_at, now),
                    "updated_at": now,
                },
            )
        log_event("ai_run_finished", run_id=run_id, status=status)

    def _fail_run(self, run_id: str, code: str, message: str) -> None:
        now = utc_timestamp()
        try:
            with database.session() as conn:
                record = run_repo.get_run(conn, run_id)
                if record is None:
                    return
                run_repo.fail_pending_items(
                    conn,
                    run_id,
                    status="failed",
                    error_code=code,
                    error_message=message,
                    finished_at=now,
                )
                counts = run_repo.counts(conn, run_id)
                run_repo.update_run(
                    conn,
                    run_id,
                    {
                        "status": "failed",
                        "error_message": message[:500],
                        "processed_count": counts["processed"],
                        "succeeded_count": counts["succeeded"],
                        "failed_count": counts["failed"],
                        "skipped_count": counts["skipped"],
                        "finished_at": now,
                        "duration_ms": _duration_ms(record.started_at or record.created_at, now),
                        "updated_at": now,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - best effort
            log_event(
                "ai_run_finalize_failed",
                level="error",
                run_id=run_id,
                exc_type=type(exc).__name__,
            )


_service: AIAnalysisService | None = None
_service_lock = threading.Lock()


def get_ai_service() -> AIAnalysisService:
    global _service
    with _service_lock:
        if _service is None:
            _service = AIAnalysisService()
        return _service


def reset_ai_service(service: AIAnalysisService | None = None) -> None:
    global _service
    with _service_lock:
        if _service is not None:
            _service.stop()
        _service = service
