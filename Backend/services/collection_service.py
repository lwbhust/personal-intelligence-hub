"""Collection orchestration: manual/scheduled jobs, dedup, retry, recovery.

Design constraints
------------------
* One job runs at a time; at most three source items are fetched concurrently.
* Network work never happens inside a SQLite transaction.
* All article writes for one source happen in a single transaction, so a crash
  cannot leave half a feed in the database.
* Duplicate protection is layered: feed GUID, canonical URL, content hash.
* Jobs survive in SQLite; a restart marks stale running work as interrupted.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import database
from collectors.feed_parser import FeedParseError, ParsedEntry, parse_feed
from collectors.html_list_collector import HtmlListCollector
from collectors.net_guard import NetGuard, NetGuardError, NetPolicy
from collectors.normalize import canonicalize_url, content_fingerprint, normalize_title
from core.logging import log_event
from core.timeutil import utc_timestamp
from database.repositories import article_repository as article_repo
from database.repositories import adapter_repository as adapter_repo
from database.repositories import collection_job_repository as job_repo
from database.repositories import source_fetch_state_repository as fetch_state_repo
from database.repositories import source_health_repository as health_repo
from database.repositories import source_repository as source_repo
from database.repositories.models import (
    ArticleRecord,
    CollectionJobRecord,
    SourceRecord,
)
from services.errors import conflict, not_found, unsupported, validation
from services.source_health_service import (
    SYSTEMIC_CODES,
    classify_failure,
    describe_failure,
    effective_interval_minutes,
)
from services.storage import disk_snapshot, ensure_writable

MAX_BATCH_SOURCES = 50
MAX_CONCURRENCY = 3
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 1.0
SCHEDULER_INTERVAL_SECONDS = 30.0
HEALTH_LOG_KEEP = 100
JOB_KEEP = 500
TITLE_DEDUP_WINDOW_MINUTES = 15
RETENTION_INTERVAL_SECONDS = 3600.0
SCHEDULER_ENV = "PIH_SCHEDULER_ENABLED"

_last_retention_at = 0.0

_ACTIVE_STATUSES = ("pending", "running")
_RETRYABLE_STATUSES = ("failed", "partially_succeeded", "cancelled")


@dataclass(frozen=True, slots=True)
class ItemOutcome:
    status: str
    http_status: int | None = None
    discovered: int = 0
    inserted: int = 0
    updated: int = 0
    duplicate: int = 0
    error_count: int = 0
    error_code: str | None = None
    error_message: str | None = None


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, NetGuardError):
        return error.retryable
    if isinstance(error, FeedParseError):
        return False
    return False


def _safe_message(error: Exception) -> str:
    if isinstance(error, (NetGuardError, FeedParseError)):
        return error.message[:500]
    return "采集过程中出现内部错误"


def _safe_code(error: Exception) -> str:
    if isinstance(error, (NetGuardError, FeedParseError)):
        return error.code
    return "internal_error"


def _now() -> str:
    return utc_timestamp()


def _notify_pipeline(article_ids: list[str]) -> None:
    """Hand freshly inserted articles to the orchestrator (best effort).

    Imported lazily to keep the collector independent from the pipeline module.
    The orchestrator itself decides whether automation is enabled.
    """

    if not article_ids:
        return
    try:
        from services.pipeline_orchestrator import get_orchestrator

        get_orchestrator().on_articles_ingested(article_ids)
    except Exception as exc:  # noqa: BLE001 - ingestion must not fail on this hook
        log_event(
            "pipeline_notify_failed",
            level="warn",
            exc_type=type(exc).__name__,
        )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _limit_entries(
    entries: tuple[ParsedEntry, ...], limit: int | None
) -> tuple[ParsedEntry, ...]:
    """Apply the per-source cap, preferring the newest entries.

    Parsed entries already carry the global 100-entry cap. When a source sets
    its own limit, sort by publish time (newest first) before truncating so a
    misordered feed cannot drop fresh items.
    """

    if limit is None or len(entries) <= limit:
        return entries
    ordered = sorted(entries, key=lambda entry: entry.published_at or "", reverse=True)
    return tuple(ordered[:limit])


class CollectionService:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        guard: NetGuard | None = None,
        scheduler_interval: float = SCHEDULER_INTERVAL_SECONDS,
    ) -> None:
        if enabled is None:
            enabled = os.environ.get(SCHEDULER_ENV, "1") != "0"
        self.scheduler_enabled = enabled
        self.scheduler_interval = scheduler_interval
        self.guard = guard or NetGuard(NetPolicy())
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._scheduler: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._running_job_id: str | None = None
        self._queued: set[str] = set()
        self._item_pool = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENCY, thread_name_prefix="pih-fetch"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self.recover_interrupted()
        disk = disk_snapshot()
        if disk is not None:
            log_event(
                "disk_usage",
                free_bytes=disk["free_bytes"],
                total_bytes=disk["total_bytes"],
                free_gib=round(disk["free_bytes"] / 1024**3, 2),
            )
        self._worker = threading.Thread(
            target=self._worker_loop, name="pih-collect-worker", daemon=True
        )
        self._worker.start()
        if self.scheduler_enabled:
            self._scheduler = threading.Thread(
                target=self._scheduler_loop, name="pih-collect-scheduler", daemon=True
            )
            self._scheduler.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("")  # wake the worker
        for thread in (self._scheduler, self._worker):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        self._item_pool.shutdown(wait=False, cancel_futures=True)
        self._started = False

    def recover_interrupted(self) -> int:
        """Mark jobs/items that cannot survive a restart as failed."""

        try:
            now = _now()
            with database.session() as conn:
                changed = job_repo.mark_stale_jobs(conn, now)
                job_repo.prune_jobs(conn, JOB_KEEP)
            if changed:
                log_event("collection_recovered", level="warn", job_count=changed)
            return changed
        except Exception as exc:  # noqa: BLE001 - startup must not crash
            log_event(
                "collection_recovery_failed",
                level="error",
                exc_type=type(exc).__name__,
            )
            return 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_jobs(
        self, *, limit: int, offset: int, status: str | None
    ) -> tuple[list[CollectionJobRecord], int]:
        if status is not None and status not in (
            "pending", "running", "succeeded", "partially_succeeded", "failed", "cancelled"
        ):
            raise validation("status", "enum", "不支持的任务状态")
        with database.read_session() as conn:
            return job_repo.list_jobs(conn, limit=limit, offset=offset, status=status)

    def get_job(self, job_id: str) -> CollectionJobRecord:
        with database.read_session() as conn:
            job = job_repo.get_job(conn, job_id)
        if job is None:
            raise not_found("job_not_found", "采集任务不存在")
        return job

    def status(self) -> dict[str, object]:
        with self._lock:
            running = self._running_job_id
            depth = len(self._queued)
        return {
            "scheduler_enabled": self.scheduler_enabled,
            "running_job_id": running,
            "max_concurrency": MAX_CONCURRENCY,
            "queue_depth": depth,
        }

    # ------------------------------------------------------------------
    # Job creation / cancel / retry
    # ------------------------------------------------------------------

    def create_job(
        self,
        *,
        trigger_type: str = "manual",
        source_ids: list[str] | None = None,
    ) -> CollectionJobRecord:
        ensure_writable()
        if trigger_type not in ("manual", "scheduled"):
            raise validation("trigger_type", "enum", "不支持的任务触发方式")
        if source_ids is not None:
            if not source_ids:
                raise validation("source_ids", "empty", "至少选择一个信息源")
            if len(set(source_ids)) > MAX_BATCH_SOURCES:
                raise conflict("collection_batch_too_large", "单次最多采集 50 个信息源")

        with database.session() as conn:
            if source_ids is None:
                candidates = source_repo.list_collectable(conn)
                scope = "all_enabled"
                if not candidates:
                    raise conflict("no_enabled_sources", "没有可采集的信息源")
                if len(candidates) > MAX_BATCH_SOURCES:
                    raise conflict(
                        "collection_batch_too_large", "单次最多采集 50 个信息源"
                    )
            else:
                scope = "single_source" if len(set(source_ids)) == 1 else "all_enabled"
                candidates = []
                for source_id in dict.fromkeys(source_ids):
                    source = source_repo.get_collectable(conn, source_id)
                    if source is None:
                        existing = source_repo.get_active(conn, source_id)
                        if existing is None:
                            raise not_found("source_not_found", "信息源不存在")
                        if existing.source_type not in ("rss", "atom"):
                            if adapter_repo.get(conn, source_id) is None:
                                raise unsupported(
                                    "adapter_not_supported",
                                    "该信息源尚未配置网页适配器",
                                )
                        raise conflict("source_not_collectable", "信息源已停用或不可采集")
                    candidates.append(source)

            runnable = [
                source
                for source in candidates
                if not job_repo.source_has_active_item(conn, source.id)
            ]
            if not runnable:
                raise conflict("source_already_collecting", "该信息源正在采集")
            if source_ids is not None and len(runnable) != len(candidates):
                raise conflict("source_already_collecting", "该信息源正在采集")

            job_id = str(uuid.uuid4())
            now = _now()
            job_repo.insert_job(
                conn,
                {
                    "id": job_id,
                    "trigger_type": trigger_type,
                    "scope": scope,
                    "status": "pending",
                    "requested_source_count": len(runnable),
                    "processed_source_count": 0,
                    "succeeded_source_count": 0,
                    "failed_source_count": 0,
                    "discovered_count": 0,
                    "inserted_count": 0,
                    "updated_count": 0,
                    "duplicate_count": 0,
                    "error_count": 0,
                    "error_message": None,
                    "cancel_requested": 0,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            for source in runnable:
                job_repo.insert_item(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "job_id": job_id,
                        "source_id": source.id,
                        "status": "pending",
                        "http_status": None,
                        "discovered_count": 0,
                        "inserted_count": 0,
                        "updated_count": 0,
                        "duplicate_count": 0,
                        "error_count": 0,
                        "error_code": None,
                        "error_message": None,
                        "started_at": None,
                        "finished_at": None,
                        "duration_ms": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            job = job_repo.get_job(conn, job_id)

        assert job is not None
        self._enqueue(job_id)
        log_event(
            "collection_job_created",
            job_id=job_id,
            trigger_type=trigger_type,
            source_count=len(runnable),
        )
        return job

    def cancel_job(self, job_id: str) -> CollectionJobRecord:
        with database.session() as conn:
            job = job_repo.get_job(conn, job_id, with_items=False)
            if job is None:
                raise not_found("job_not_found", "采集任务不存在")
            if job.status not in _ACTIVE_STATUSES:
                raise conflict("job_not_cancellable", "当前任务状态不可取消")
            now = _now()
            if job.status == "pending":
                job_repo.cancel_pending_items(conn, job_id, now)
                job_repo.update_job(
                    conn,
                    job_id,
                    {
                        "status": "cancelled",
                        "cancel_requested": 1,
                        "finished_at": now,
                        "updated_at": now,
                        "duration_ms": 0,
                    },
                )
                job_repo.recompute_job_totals(conn, job_id)
            else:
                job_repo.update_job(
                    conn, job_id, {"cancel_requested": 1, "updated_at": now}
                )
            result = job_repo.get_job(conn, job_id)
        assert result is not None
        log_event("collection_job_cancel_requested", job_id=job_id)
        return result

    def retry_job(self, job_id: str) -> CollectionJobRecord:
        with database.read_session() as conn:
            job = job_repo.get_job(conn, job_id, with_items=False)
            if job is None:
                raise not_found("job_not_found", "采集任务不存在")
            if job.status not in _RETRYABLE_STATUSES:
                raise conflict("job_not_retryable", "当前任务状态不可重试")
            source_ids = job_repo.retryable_source_ids(conn, job_id)
        if not source_ids:
            raise conflict("job_not_retryable", "没有需要重试的信息源")
        return self.create_job(trigger_type="manual", source_ids=source_ids)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _enqueue(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._queued:
                return
            self._queued.add(job_id)
        self._queue.put(job_id)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not job_id or self._stop.is_set():
                if job_id:
                    with self._lock:
                        self._queued.discard(job_id)
                continue
            try:
                self._execute_job(job_id)
            except Exception as exc:  # noqa: BLE001 - never kill the worker
                log_event(
                    "collection_job_crashed",
                    level="error",
                    job_id=job_id,
                    exc_type=type(exc).__name__,
                )
                self._fail_job(job_id, "collection_failed", "采集任务执行失败")
            finally:
                with self._lock:
                    self._queued.discard(job_id)
                    self._running_job_id = None
                try:
                    self._prune()
                except Exception:  # noqa: BLE001 - retention is best effort
                    pass

    def _prune(self) -> None:
        with database.session() as conn:
            job_repo.prune_jobs(conn, JOB_KEEP)

    def _fail_job(self, job_id: str, code: str, message: str) -> None:
        try:
            now = _now()
            with database.session() as conn:
                job_repo.update_job(
                    conn,
                    job_id,
                    {
                        "status": "failed",
                        "error_message": message[:1000],
                        "finished_at": now,
                        "updated_at": now,
                    },
                )
                conn.execute(
                    """
                    UPDATE collection_job_items
                    SET status = 'failed', error_code = ?, error_message = ?,
                        finished_at = ?, updated_at = ?,
                        error_count = error_count + 1
                    WHERE job_id = ? AND status IN ('pending','running')
                    """,
                    (code, message[:1000], now, now, job_id),
                )
                job_repo.recompute_job_totals(conn, job_id)
        except Exception:  # noqa: BLE001 - best effort
            pass

    def _execute_job(self, job_id: str) -> None:
        with database.read_session() as conn:
            job = job_repo.get_job(conn, job_id)
        if job is None or job.status != "pending":
            return

        started = _now()
        started_monotonic = time.monotonic()
        with database.session() as conn:
            job_repo.update_job(
                conn,
                job_id,
                {"status": "running", "started_at": started, "updated_at": started},
            )
        with self._lock:
            self._running_job_id = job_id

        futures = []
        for item in job.items:
            futures.append(
                self._item_pool.submit(self._process_item, job_id, item.id)
            )
        for future in futures:
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - item failures are isolated
                log_event(
                    "collection_item_crashed",
                    level="error",
                    job_id=job_id,
                    exc_type=type(exc).__name__,
                )

        finished = _now()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        with database.session() as conn:
            current = job_repo.get_job(conn, job_id, with_items=False)
            if current is None:
                return
            if self._stop.is_set():
                job_repo.cancel_pending_items(conn, job_id, finished)
            # A worker exception must not leave an item "running" under a
            # terminal job; surface it as an item failure instead.
            conn.execute(
                """
                UPDATE collection_job_items
                SET status = 'failed', error_code = 'internal_error',
                    error_message = '采集条目未完成', finished_at = ?, updated_at = ?
                WHERE job_id = ? AND status IN ('pending','running')
                """,
                (finished, finished, job_id),
            )
            items = job_repo.list_items(conn, job_id)
            succeeded = sum(1 for item in items if item.status == "succeeded")
            failed = sum(1 for item in items if item.status == "failed")
            cancelled = sum(1 for item in items if item.status == "cancelled")
            systemic = self._systemic_outage(items)
            if systemic:
                self._demote_systemic_failures(conn, items, finished)
            if current.cancel_requested or cancelled:
                status = "cancelled"
            elif failed and succeeded:
                status = "partially_succeeded"
            elif failed:
                status = "failed"
            elif succeeded:
                status = "succeeded"
            else:
                status = "failed"
            first_error = next(
                (item.error_message for item in items if item.error_message), None
            )
            if systemic:
                first_error = (
                    f"检测到本地网络/DNS 批量异常（{failed} 个来源同时失败），"
                    "已按系统故障处理，不归因于单个信息源"
                )
            job_repo.update_job(
                conn,
                job_id,
                {
                    "status": status,
                    "finished_at": finished,
                    "duration_ms": duration_ms,
                    "error_message": (first_error or None)
                    if status != "succeeded"
                    else None,
                    "updated_at": finished,
                },
            )
            job_repo.recompute_job_totals(conn, job_id)
        log_event(
            "collection_job_finished",
            job_id=job_id,
            status=status,
            duration_ms=duration_ms,
        )
        if status in ("succeeded", "partially_succeeded"):
            self._run_retention()
        disk = disk_snapshot()
        if disk is not None and disk["free_bytes"] < 5 * 1024**3:
            log_event(
                "disk_low",
                level="warn",
                free_bytes=disk["free_bytes"],
                free_gib=round(disk["free_bytes"] / 1024**3, 2),
            )

    @staticmethod
    def _systemic_outage(items: list) -> bool:
        """True when one job shows a machine-wide network/DNS outage.

        A single source failing with ``dns_failure`` is a source problem; a
        whole batch of sources failing at the same moment is the local
        resolver or the uplink. Phase 8.0 keeps that distinction so a flaky
        home network does not permanently mark good sources as ``failing``.
        """

        failed = [
            item
            for item in items
            if item.status == "failed" and item.error_code in SYSTEMIC_CODES
        ]
        return len(failed) >= 3 and len(failed) * 2 >= len(items)

    def _demote_systemic_failures(self, conn, items: list, now: str) -> None:
        note = "本地网络/DNS 批量异常，未归因于该来源"
        for item in items:
            if item.status != "failed" or item.error_code not in SYSTEMIC_CODES:
                continue
            state = fetch_state_repo.get(conn, item.source_id)
            if state is None:
                continue
            message = f"{(state.last_error_message or '')[:400]}（{note}）"[:500]
            fetch_state_repo.upsert(
                conn,
                {
                    "source_id": item.source_id,
                    "etag": state.etag,
                    "last_modified": state.last_modified,
                    "last_fetch_at": state.last_fetch_at,
                    "last_success_at": state.last_success_at,
                    "last_error_code": item.error_code,
                    "last_error_message": message,
                    "consecutive_failures": 0,
                    "updated_at": now,
                },
            )
            source_repo.update_collection_summary(
                conn,
                item.source_id,
                {
                    "health_status": "degraded",
                    "last_error_message": message,
                    "updated_at": now,
                },
            )
        log_event(
            "collection_systemic_network_failure",
            level="warn",
            affected_sources=sum(
                1
                for item in items
                if item.status == "failed" and item.error_code in SYSTEMIC_CODES
            ),
        )

    def _run_retention(self) -> None:
        """Best-effort stale-article cleanup; never fails the collection job."""

        global _last_retention_at
        now = time.monotonic()
        if now - _last_retention_at < RETENTION_INTERVAL_SECONDS:
            return
        try:
            from services.retention_service import prune_articles, retention_enabled

            if not retention_enabled():
                return
            report = prune_articles()
            _last_retention_at = now
            if report["deleted"]:
                log_event(
                    "articles_pruned",
                    days=report["days"],
                    deleted=report["deleted"],
                )
        except Exception as exc:  # noqa: BLE001 - retention is best effort
            log_event(
                "articles_prune_failed",
                level="warn",
                exc_type=type(exc).__name__,
            )

    def _process_item(self, job_id: str, item_id: str) -> None:
        started_monotonic = time.monotonic()
        now = _now()
        source: SourceRecord | None = None
        etag: str | None = None
        last_modified: str | None = None

        with database.session() as conn:
            item = job_repo.get_item(conn, item_id)
            if item is None or item.status != "pending":
                return
            try:
                claimed = job_repo.claim_item(conn, item_id, now)
            except sqlite3.IntegrityError:
                job_repo.update_item(
                    conn,
                    item_id,
                    {
                        "status": "skipped",
                        "error_code": "source_already_collecting",
                        "error_message": "该信息源已有采集任务在运行",
                        "finished_at": now,
                        "updated_at": now,
                    },
                )
                return
            if not claimed:
                return
            source = source_repo.get_collectable(conn, item.source_id)
            state = fetch_state_repo.get(conn, item.source_id)
            job = job_repo.get_job(conn, job_id, with_items=False)
            adapter = None
            if source is not None and source.source_type not in ("rss", "atom"):
                adapter = adapter_repo.get(conn, source.id)
            if state is not None:
                etag = state.etag
                last_modified = state.last_modified
            if source is None or job is None or job.cancel_requested:
                # Stay inside the claim transaction: opening a second write
                # connection here would block on the BEGIN IMMEDIATE lock.
                status = "cancelled" if job is not None else "skipped"
                code = "cancelled" if job is not None else "source_not_collectable"
                message = "任务已取消" if job is not None else "信息源已不可采集"
                job_repo.update_item(
                    conn,
                    item_id,
                    {
                        "status": status,
                        "error_code": code,
                        "error_message": message,
                        "finished_at": now,
                        "duration_ms": int(
                            (time.monotonic() - started_monotonic) * 1000
                        ),
                        "updated_at": now,
                    },
                )
                return

        if self._stop.is_set():
            self._finish_item(
                job_id,
                item_id,
                ItemOutcome(
                    status="cancelled",
                    error_code="interrupted",
                    error_message="服务正在停止",
                ),
                source,
                started_monotonic,
                check_cancel=False,
            )
            return

        if adapter is not None:
            self._process_adapter_item(
                job_id, item_id, source, adapter, started_monotonic
            )
            return

        result = None
        error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._cancel_requested(job_id):
                break
            try:
                result = self.guard.fetch(
                    source.url, etag=etag, last_modified=last_modified
                )
                error = None
                break
            except NetGuardError as exc:
                error = exc
                if not exc.retryable or attempt >= MAX_ATTEMPTS:
                    break
                if self._stop.wait(RETRY_BASE_SECONDS * (2 ** (attempt - 1))):
                    break
            except Exception as exc:  # noqa: BLE001 - unexpected fetch failure
                error = exc
                break

        if self._cancel_requested(job_id):
            self._finish_item(
                job_id,
                item_id,
                ItemOutcome(
                    status="cancelled",
                    error_code="cancelled",
                    error_message="任务已取消",
                ),
                source,
                started_monotonic,
                check_cancel=False,
            )
            return

        if error is not None or result is None:
            outcome = ItemOutcome(
                status="failed",
                http_status=(
                    error.status_code if isinstance(error, NetGuardError) else None
                ),
                error_code=_safe_code(error or RuntimeError("fetch failed")),
                error_message=_safe_message(error or RuntimeError("fetch failed")),
                error_count=1,
            )
            self._finish_item(job_id, item_id, outcome, source, started_monotonic)
            return

        if result.not_modified:
            self._finish_item(
                job_id,
                item_id,
                ItemOutcome(status="succeeded", http_status=304),
                source,
                started_monotonic,
                fetch_headers=result.headers,
            )
            return

        try:
            parsed = parse_feed(result.body)
        except Exception as exc:  # noqa: BLE001 - parse failures are item failures
            outcome = ItemOutcome(
                status="failed",
                http_status=result.status_code,
                error_code=_safe_code(exc),
                error_message=_safe_message(exc),
                error_count=1,
            )
            self._finish_item(job_id, item_id, outcome, source, started_monotonic)
            return

        outcome = self._store_entries(
            job_id,
            source,
            _limit_entries(parsed.entries, source.max_entries_per_fetch),
            result.status_code,
        )
        self._finish_item(
            job_id,
            item_id,
            outcome,
            source,
            started_monotonic,
            fetch_headers=result.headers,
        )

    def _process_adapter_item(
        self,
        job_id: str,
        item_id: str,
        source: SourceRecord,
        adapter,
        started_monotonic: float,
    ) -> None:
        config = json.loads(adapter.config_json or "{}")
        result = None
        error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._cancel_requested(job_id):
                break
            try:
                result = HtmlListCollector(self.guard).collect(
                    list_urls=[str(item) for item in config.get("list_urls") or []],
                    link_pattern=str(config.get("link_pattern") or ""),
                    max_entries=adapter.max_entries_per_run,
                    rate_limit_seconds=adapter.rate_limit_seconds,
                    fetch_full_text=adapter.fetch_full_text,
                    max_pages=int(config.get("max_pages") or 1),
                )
                error = None
                break
            except NetGuardError as exc:
                error = exc
                if not exc.retryable or attempt >= MAX_ATTEMPTS:
                    break
                if self._stop.wait(RETRY_BASE_SECONDS * (2 ** (attempt - 1))):
                    break
            except Exception as exc:  # noqa: BLE001 - unexpected adapter failure
                error = exc
                break

        if self._cancel_requested(job_id):
            self._finish_item(
                job_id,
                item_id,
                ItemOutcome(
                    status="cancelled",
                    error_code="cancelled",
                    error_message="任务已取消",
                ),
                source,
                started_monotonic,
                check_cancel=False,
            )
            return

        if error is not None or result is None:
            error_code = _safe_code(error or RuntimeError("adapter failed"))
            self._record_adapter_verification(
                adapter,
                entries=0,
                errors=(_safe_message(error or RuntimeError("adapter failed")),),
                blocked=error_code
                in {"robots_disallowed", "http_client_error", "unsupported_content_type"},
            )
            outcome = ItemOutcome(
                status="failed",
                http_status=(
                    error.status_code if isinstance(error, NetGuardError) else None
                ),
                error_code=error_code,
                error_message=_safe_message(error or RuntimeError("adapter failed")),
                error_count=1,
            )
            self._finish_item(job_id, item_id, outcome, source, started_monotonic)
            return

        if not result.entries:
            detail = result.errors[0] if result.errors else "列表页未匹配到可解析文章"
            self._record_adapter_verification(
                adapter,
                entries=0,
                errors=result.errors,
                blocked=any(
                    marker in detail
                    for marker in ("robots", "http_client_error", "unsupported_content_type")
                ),
            )
            outcome = ItemOutcome(
                status="failed",
                http_status=result.http_status,
                error_code="adapter_no_entries",
                error_message=detail[:500],
                error_count=1,
            )
            self._finish_item(job_id, item_id, outcome, source, started_monotonic)
            return

        outcome = self._store_entries(
            job_id, source, result.entries, result.http_status or 200
        )
        self._record_adapter_verification(
            adapter, entries=len(result.entries), errors=result.errors, blocked=False
        )
        if result.errors:
            outcome = replace(
                outcome,
                status="succeeded",
                error_count=len(result.errors),
                error_code="partial_entry_errors",
                error_message=f"{len(result.errors)} 个列表页或文章页失败"[:500],
            )
        self._finish_item(job_id, item_id, outcome, source, started_monotonic)

    def _record_adapter_verification(
        self,
        adapter,
        *,
        entries: int,
        errors: tuple[str, ...],
        blocked: bool,
    ) -> None:
        """Persist adapter health so the UI can surface selector drift."""

        if blocked and entries == 0:
            status = "blocked"
        elif entries > 0:
            status = "verified"
        else:
            status = "selector_drift"
        try:
            now = _now()
            with database.session() as conn:
                adapter_repo.update_verification(
                    conn,
                    adapter.source_id,
                    last_verified_at=now,
                    last_verification=status,
                    last_sample_json=json.dumps(
                        {"entries": entries, "errors": list(errors[:3])},
                        ensure_ascii=False,
                    )[:20000],
                    updated_at=now,
                )
        except Exception as exc:  # noqa: BLE001 - verification is best effort
            log_event(
                "adapter_verification_failed",
                level="warn",
                exc_type=type(exc).__name__,
            )

    def _store_entries(
        self,
        job_id: str,
        source: SourceRecord,
        entries: tuple[ParsedEntry, ...],
        http_status: int,
    ) -> ItemOutcome:
        inserted = updated = duplicate = errors = 0
        inserted_ids: list[str] = []
        now = _now()
        try:
            with database.session() as conn:
                for entry in entries:
                    try:
                        result, article_id = self._upsert_entry(conn, source.id, entry, now)
                    except sqlite3.IntegrityError:
                        duplicate += 1
                        continue
                    except Exception:  # noqa: BLE001 - one bad entry must not abort a feed
                        errors += 1
                        continue
                    if result == "inserted":
                        inserted += 1
                        if article_id is not None:
                            inserted_ids.append(article_id)
                    elif result == "updated":
                        updated += 1
                    elif result == "duplicate":
                        duplicate += 1
                    else:
                        errors += 1
        except Exception as exc:  # noqa: BLE001 - transaction failure fails the item
            return ItemOutcome(
                status="failed",
                http_status=http_status,
                discovered=len(entries),
                error_count=len(entries),
                error_code=_safe_code(exc),
                error_message="写入文章数据失败",
            )
        _notify_pipeline(inserted_ids)
        return ItemOutcome(
            status="succeeded",
            http_status=http_status,
            discovered=len(entries),
            inserted=inserted,
            updated=updated,
            duplicate=duplicate,
            error_count=errors,
            error_code="partial_entry_errors" if errors else None,
            error_message=(
                f"{errors} 条目数据无法处理" if errors else None
            ),
        )

    @staticmethod
    def _upsert_entry(
        conn: sqlite3.Connection,
        source_id: str,
        entry: ParsedEntry,
        now: str,
    ) -> tuple[str, str | None]:
        canonical = canonicalize_url(entry.link)
        if (
            not entry.external_id
            and canonical is None
            and entry.content_state == "unavailable"
        ):
            return "error", None

        body = entry.content or entry.summary
        fingerprint = content_fingerprint(
            title=entry.title,
            body=body,
            published_at=entry.published_at,
        )
        found = article_repo.find_existing(
            conn,
            source_id=source_id,
            external_id=entry.external_id,
            canonical_url=canonical,
            content_hash=fingerprint,
        )
        if found is not None:
            existing, _rule = found
            if existing.content_hash == fingerprint:
                return "duplicate", None
            fields = CollectionService._update_fields(existing, entry, canonical, fingerprint, now)
            article_repo.update(conn, existing.id, fields)
            return "updated", None

        # Fourth layer: same source + same normalised title + close publish
        # time. Feed platforms occasionally publish one story twice with
        # different GUIDs and URLs minutes apart.
        title_match = CollectionService._find_title_duplicate(
            conn, source_id, entry
        )
        if title_match is not None:
            if title_match.content_hash == fingerprint:
                return "duplicate", None
            fields = CollectionService._update_fields(
                title_match, entry, canonical, fingerprint, now
            )
            article_repo.update(conn, title_match.id, fields)
            return "updated", None

        article_id = str(uuid.uuid4())
        article_repo.insert(
            conn,
            {
                "id": article_id,
                "source_id": source_id,
                "external_id": entry.external_id,
                "canonical_url": canonical,
                "original_url": CollectionService._original_url(entry.link),
                "title": entry.title[:500],
                "author": entry.author,
                "summary": entry.summary,
                "content_text": entry.content,
                "content_state": entry.content_state,
                "published_at": entry.published_at,
                "source_updated_at": entry.source_updated_at,
                "fetched_at": now,
                "content_hash": fingerprint,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        return "inserted", article_id

    @staticmethod
    def _original_url(link: str | None) -> str | None:
        """Keep only absolute http(s) links; never surface javascript:/file:."""

        if not link:
            return None
        value = link.strip()
        try:
            parts = urlsplit(value)
        except ValueError:
            return None
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        return value[:2048]

    @staticmethod
    def _find_title_duplicate(
        conn: sqlite3.Connection,
        source_id: str,
        entry: ParsedEntry,
    ) -> ArticleRecord | None:
        if not entry.published_at or not entry.title:
            return None
        target = normalize_title(entry.title)
        if not target:
            return None
        try:
            moment = datetime.fromisoformat(
                entry.published_at.replace("Z", "+00:00")
            )
        except ValueError:
            return None
        start = (moment - timedelta(minutes=TITLE_DEDUP_WINDOW_MINUTES)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        end = (moment + timedelta(minutes=TITLE_DEDUP_WINDOW_MINUTES)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        for record in article_repo.list_by_source_window(
            conn, source_id=source_id, start=start, end=end
        ):
            if normalize_title(record.title) == target:
                return record
        return None

    @staticmethod
    def _update_fields(
        existing: ArticleRecord,
        entry: ParsedEntry,
        canonical: str | None,
        fingerprint: str,
        now: str,
    ) -> dict[str, object]:
        fields: dict[str, object] = {
            "content_hash": fingerprint,
            "fetched_at": now,
            "updated_at": now,
        }
        if entry.title and entry.title != existing.title:
            fields["title"] = entry.title[:500]
        if entry.author:
            fields["author"] = entry.author
        if entry.summary:
            fields["summary"] = entry.summary
        if canonical and canonical != existing.canonical_url:
            fields["canonical_url"] = canonical
        if entry.link:
            original = CollectionService._original_url(entry.link)
            if original:
                fields["original_url"] = original
        if entry.external_id:
            fields["external_id"] = entry.external_id
        if entry.published_at:
            fields["published_at"] = entry.published_at
        if entry.source_updated_at:
            fields["source_updated_at"] = entry.source_updated_at

        # Never downgrade a full body to a summary, and never erase content.
        if existing.content_state == "full" and entry.content_state != "full":
            fields["content_state"] = "full"
            if existing.content_text:
                fields["content_text"] = existing.content_text
        elif entry.content:
            fields["content_text"] = entry.content
            fields["content_state"] = (
                "full" if entry.content_state == "full" else entry.content_state
            )
        elif existing.content_text or existing.summary:
            # A later fetch without body/summary must not downgrade stored text.
            fields["content_state"] = existing.content_state
        else:
            fields["content_state"] = entry.content_state
        return fields

    def _finish_item(
        self,
        job_id: str,
        item_id: str,
        outcome: ItemOutcome,
        source: SourceRecord | None,
        started_monotonic: float,
        *,
        fetch_headers: dict[str, str] | None = None,
        check_cancel: bool = True,
    ) -> None:
        now = _now()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        if check_cancel and self._cancel_requested(job_id) and outcome.status == "succeeded":
            outcome = ItemOutcome(
                status="cancelled",
                http_status=outcome.http_status,
                discovered=outcome.discovered,
                inserted=outcome.inserted,
                updated=outcome.updated,
                duplicate=outcome.duplicate,
                error_count=outcome.error_count,
                error_code="cancelled",
                error_message="任务已取消",
            )
        try:
            with database.session() as conn:
                job_repo.update_item(
                    conn,
                    item_id,
                    {
                        "status": outcome.status,
                        "http_status": outcome.http_status,
                        "discovered_count": outcome.discovered,
                        "inserted_count": outcome.inserted,
                        "updated_count": outcome.updated,
                        "duplicate_count": outcome.duplicate,
                        "error_count": outcome.error_count,
                        "error_code": outcome.error_code,
                        "error_message": (outcome.error_message or None),
                        "finished_at": now,
                        "duration_ms": duration_ms,
                        "updated_at": now,
                    },
                )
                if source is not None and outcome.status in ("succeeded", "failed"):
                    self._record_source_state(
                        conn, source, outcome, now, fetch_headers, duration_ms
                    )
        except Exception as exc:  # noqa: BLE001 - never crash the worker
            log_event(
                "collection_item_update_failed",
                level="error",
                job_id=job_id,
                exc_type=type(exc).__name__,
            )

    def _record_source_state(
        self,
        conn: sqlite3.Connection,
        source: SourceRecord,
        outcome: ItemOutcome,
        now: str,
        headers: dict[str, str] | None,
        duration_ms: int,
    ) -> None:
        previous = fetch_state_repo.get(conn, source.id)
        consecutive = previous.consecutive_failures if previous else 0
        success = outcome.status == "succeeded"
        if success:
            consecutive = 0
        elif outcome.status == "failed":
            consecutive += 1

        # Phase 8.0: the escalation threshold depends on the failure kind. A
        # dead URL (404) or a security block should surface as "failing"
        # quickly; a one-off DNS hiccup must not.
        policy = classify_failure(outcome.error_code, outcome.http_status)
        error_message = (
            None
            if success
            else describe_failure(outcome.error_code, outcome.error_message)
        )
        if success:
            health = "degraded" if outcome.error_count else "healthy"
        else:
            health = "failing" if consecutive >= policy.escalate_after else "degraded"

        etag = (headers or {}).get("etag") or (previous.etag if previous else None)
        last_modified = (headers or {}).get("last-modified") or (
            previous.last_modified if previous else None
        )
        if success and headers:
            if "etag" in headers:
                etag = headers["etag"]
            if "last-modified" in headers:
                last_modified = headers["last-modified"]

        fetch_state_repo.upsert(
            conn,
            {
                "source_id": source.id,
                "etag": etag,
                "last_modified": last_modified,
                "last_fetch_at": now,
                "last_success_at": now if success else (previous.last_success_at if previous else None),
                "last_error_code": None if success else outcome.error_code,
                "last_error_message": error_message,
                "consecutive_failures": consecutive,
                "updated_at": now,
            },
        )

        summary: dict[str, object] = {
            "last_fetch_at": now,
            "health_status": health,
            "updated_at": now,
        }
        if success:
            summary["last_success_at"] = now
            summary["last_error_code"] = None
            summary["last_error_message"] = None
        else:
            summary["last_error_at"] = now
            summary["last_error_code"] = outcome.error_code
            summary["last_error_message"] = (error_message or "")[:500] or None
        source_repo.update_collection_summary(conn, source.id, summary)

        if outcome.status in ("succeeded", "failed"):
            health_repo.insert(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "source_id": source.id,
                    "checked_at": now,
                    "status": health,
                    "http_status": outcome.http_status,
                    "latency_ms": duration_ms,
                    "error_code": outcome.error_code,
                    "error_message": (outcome.error_message or "")[:500] or None,
                    "created_at": now,
                },
            )
            health_repo.prune(conn, source.id, HEALTH_LOG_KEEP)

    def _cancel_requested(self, job_id: str) -> bool:
        try:
            with database.read_session() as conn:
                job = job_repo.get_job(conn, job_id, with_items=False)
            return bool(job is not None and job.cancel_requested)
        except Exception:  # noqa: BLE001 - cancellation is best effort
            return False

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    def _scheduler_loop(self) -> None:
        while not self._stop.wait(self.scheduler_interval):
            try:
                self.run_scheduled_once()
            except Exception as exc:  # noqa: BLE001 - never kill the scheduler
                log_event(
                    "collection_scheduler_failed",
                    level="error",
                    exc_type=type(exc).__name__,
                )

    def run_scheduled_once(self) -> CollectionJobRecord | None:
        if not self.scheduler_enabled:
            return None
        with self._lock:
            if self._running_job_id is not None or self._queued:
                return None
        due = self.due_source_ids()
        if not due:
            return None
        try:
            return self.create_job(trigger_type="scheduled", source_ids=due)
        except Exception as exc:  # noqa: BLE001 - no work is a normal outcome
            log_event(
                "collection_scheduler_skipped",
                level="warn",
                exc_type=type(exc).__name__,
            )
            return None

    def due_source_ids(self) -> list[str]:
        now = datetime.now(timezone.utc)
        with database.read_session() as conn:
            sources = source_repo.list_collectable(conn)
            due: list[str] = []
            for source in sources:
                state = fetch_state_repo.get(conn, source.id)
                interval = effective_interval_minutes(
                    base_interval=source.fetch_interval_minutes,
                    health_status=source.health_status,
                    consecutive_failures=state.consecutive_failures if state else 0,
                    error_code=state.last_error_code if state else None,
                )
                last = _parse_timestamp(state.last_fetch_at if state else None)
                if last is None:
                    due.append(source.id)
                else:
                    elapsed = (now - last).total_seconds() / 60
                    if elapsed >= interval:
                        due.append(source.id)
                if len(due) >= MAX_BATCH_SOURCES:
                    break
        return due


_service: CollectionService | None = None
_service_lock = threading.Lock()


def get_collection_service() -> CollectionService:
    global _service
    with _service_lock:
        if _service is None:
            _service = CollectionService()
        return _service


def reset_collection_service(service: CollectionService | None = None) -> None:
    """Test hook: replace the process-wide service instance."""

    global _service
    with _service_lock:
        if _service is not None and _service is not service:
            try:
                _service.stop()
            except Exception:  # noqa: BLE001 - best effort in tests
                pass
        _service = service
