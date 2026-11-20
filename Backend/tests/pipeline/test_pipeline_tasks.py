"""Pipeline task lifecycle: idempotency, state machine, retry, recovery, backfill."""

from __future__ import annotations

import uuid

import pytest

import database
from core.timeutil import utc_timestamp
from database import session as write_session
from services.pipeline_orchestrator import PipelineOrchestrator

from pipeline_support import seed_article, task_row


def _orchestrator() -> PipelineOrchestrator:
    return PipelineOrchestrator(
        tick_seconds=0.05, ai_timeout=1.0, cluster_timeout=20.0, poll_seconds=0.005
    )


def _enable(orchestrator: PipelineOrchestrator, **overrides) -> None:
    fields = {"automation_enabled": True}
    fields.update(overrides)
    orchestrator.update_settings(fields)


def test_automation_disabled_creates_no_task(ready) -> None:
    orchestrator = _orchestrator()
    orchestrator.update_settings({"automation_enabled": False})
    seed = seed_article()

    assert orchestrator.on_articles_ingested([seed["article_id"]]) == 0
    with database.read_session() as conn:
        row = conn.execute("SELECT COUNT(*) FROM pipeline_tasks").fetchone()
    assert int(row[0]) == 0


def test_task_creation_is_idempotent(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article()

    assert orchestrator.on_articles_ingested([seed["article_id"]]) == 1
    assert orchestrator.on_articles_ingested([seed["article_id"]]) == 0
    assert orchestrator.on_articles_ingested([seed["article_id"], seed["article_id"]]) == 0

    with database.read_session() as conn:
        rows = conn.execute("SELECT id, idempotency_key FROM pipeline_tasks").fetchall()
    assert len(rows) == 1
    assert rows[0]["idempotency_key"] == f"article_pipeline:{seed['article_id']}"


def test_quality_check_skips_insufficient_content(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False, summary="太短")

    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator._sweep_once()

    with database.read_session() as conn:
        row = conn.execute(
            "SELECT id, status, error_code FROM pipeline_tasks WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
    assert row is not None
    assert row["status"] == "skipped"
    assert row["error_code"] == "content_insufficient"


def test_ai_disabled_skips_with_explicit_reason(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator, ai_enabled=False)
    seed = seed_article(with_analysis=False)

    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator._sweep_once()

    with database.read_session() as conn:
        row = conn.execute(
            "SELECT status, error_code FROM pipeline_tasks WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
    assert row is not None
    assert row["status"] == "skipped"
    assert row["error_code"] == "ai_disabled"


def test_full_stage_progression_with_existing_analysis(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(title="量子芯片研究取得进展", category="科技")

    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator._sweep_once()

    with database.read_session() as conn:
        task = conn.execute(
            "SELECT * FROM pipeline_tasks WHERE article_id = ?", (seed["article_id"],)
        ).fetchone()
        membership = conn.execute(
            "SELECT event_id FROM event_articles WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
    assert task is not None
    assert task["status"] == "succeeded", task["error_message"]
    assert task["stage"] == "done"
    assert task["event_id"] is not None
    assert membership is not None
    event_id = str(task["event_id"])

    with database.read_session() as conn:
        snapshot = conn.execute(
            "SELECT * FROM event_score_snapshots WHERE event_id = ? AND is_current = 1",
            (event_id,),
        ).fetchone()
        links = conn.execute(
            "SELECT COUNT(*) FROM article_entities WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
        logs = conn.execute(
            "SELECT stage, message FROM pipeline_task_logs WHERE task_id = ? "
            "ORDER BY created_at",
            (task["id"],),
        ).fetchall()
    assert snapshot is not None
    assert int(links[0]) >= 1
    stages = [str(item["stage"]) for item in logs]
    assert "quality_check" in stages
    assert "entity_sync" in stages
    assert "event_score" in stages


def test_repeated_ingestion_does_not_duplicate_business_results(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(title="重复入队测试文章", category="科技")

    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator._sweep_once()
    with database.read_session() as conn:
        analyses_first = conn.execute(
            "SELECT COUNT(*) FROM article_ai_analysis WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
        events_first = conn.execute(
            "SELECT COUNT(*) FROM event_articles WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()

    # A second ingestion must not create a second task or a second event link.
    assert orchestrator.on_articles_ingested([seed["article_id"]]) == 0
    orchestrator._sweep_once()

    with database.read_session() as conn:
        tasks = conn.execute(
            "SELECT COUNT(*) FROM pipeline_tasks WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
        analyses = conn.execute(
            "SELECT COUNT(*) FROM article_ai_analysis WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
        events = conn.execute(
            "SELECT COUNT(*) FROM event_articles WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
    assert int(tasks[0]) == 1
    assert int(analyses[0]) == int(analyses_first[0])
    assert int(events[0]) == int(events_first[0])


def test_failure_retries_then_stops_at_max_attempts(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False)
    orchestrator.on_articles_ingested([seed["article_id"]])
    with database.read_session() as conn:
        task = conn.execute(
            "SELECT * FROM pipeline_tasks WHERE article_id = ?", (seed["article_id"],)
        ).fetchone()
    task_id = str(task["id"])
    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET max_attempts = 2 WHERE id = ?", (task_id,)
        )

    records, _ = orchestrator.list_tasks(
        limit=1, offset=0, status=None, stage=None, trigger_type=None
    )
    record = records[0]
    orchestrator._fail_task(record, "provider_timeout", "模型超时", retryable=True)
    first = task_row(task_id)
    assert first["status"] == "retry_wait"
    assert int(first["attempts"]) == 1

    orchestrator._fail_task(record, "provider_timeout", "模型超时", retryable=True)
    second = task_row(task_id)
    assert second["status"] == "failed"
    assert int(second["attempts"]) == 2
    assert second["completed_at"] is not None


def test_permanent_error_fails_immediately(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False)
    orchestrator.on_articles_ingested([seed["article_id"]])
    record = orchestrator.list_tasks(
        limit=1, offset=0, status=None, stage=None, trigger_type=None
    )[0][0]

    orchestrator._fail_task(record, "cloud_model_blocked", "禁止云端模型", retryable=False)
    row = task_row(record.id)
    assert row["status"] == "failed"
    assert int(row["attempts"]) == 1


def test_manual_retry_requeues_task(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False, summary="太短")
    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator._sweep_once()
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT id, status FROM pipeline_tasks WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
    assert row["status"] == "skipped"

    updated = orchestrator.retry_task(str(row["id"]))
    assert updated.status == "ready"
    assert updated.attempts == 0
    assert updated.error_code is None


def test_cannot_cancel_running_task(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False)
    orchestrator.on_articles_ingested([seed["article_id"]])
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE article_id = ?", (seed["article_id"],)
        ).fetchone()
    task_id = str(row["id"])
    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET status = 'running' WHERE id = ?", (task_id,)
        )

    from services.errors import ServiceError

    with pytest.raises(ServiceError) as excinfo:
        orchestrator.cancel_task(task_id)
    assert excinfo.value.code == "pipeline_task_running"

    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET status = 'ready' WHERE id = ?", (task_id,)
        )
    cancelled = orchestrator.cancel_task(task_id)
    assert cancelled.status == "cancelled"


def test_pause_prevents_processing(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False)
    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator.pause()

    result = orchestrator._sweep_once()
    assert result["reason"] == "paused"

    orchestrator.resume()
    swept = orchestrator._sweep_once()
    assert swept["processed"] >= 1


def test_expired_lease_is_recovered_after_restart(ready) -> None:
    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False)
    orchestrator.on_articles_ingested([seed["article_id"]])
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE article_id = ?", (seed["article_id"],)
        ).fetchone()
    task_id = str(row["id"])
    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET status = 'running', lease_owner = 'dead-worker', "
            "lease_expires_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
            (task_id,),
        )

    recovered = orchestrator._recover_leases()
    assert recovered == 1
    row = task_row(task_id)
    assert row["status"] == "retry_wait"
    assert int(row["attempts"]) == 1
    assert row["error_code"] == "lease_expired"


def test_backfill_preview_and_batch_creation(ready) -> None:
    orchestrator = _orchestrator()
    for index in range(3):
        seed_article(title=f"历史文章 {index}", with_analysis=False)

    preview = orchestrator.backfill_preview()
    assert preview["pending_articles"] == 3
    assert preview["ai_needed"] == 3

    created = orchestrator.create_backfill(limit=2)
    assert created["created_tasks"] == 2
    assert created["run"]["requested_tasks"] == 2

    after = orchestrator.backfill_preview()
    assert after["pending_articles"] == 1

    runs, total = orchestrator.list_runs(limit=10, offset=0)
    assert total == 1
    assert runs[0].status in {"pending", "running"}


def test_pipeline_refreshes_category_of_existing_event(ready) -> None:
    """An already-clustered article that gets analysed later must update its event."""

    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(title="已有事件的后续分析", category="科技")

    event_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO events (
                id, title, summary, category, status, status_reason, first_seen_at,
                last_seen_at, first_published_at, last_published_at, occurred_at,
                article_count, source_count, is_manual, merged_into_event_id,
                algorithm_version, title_source, summary_source, created_at, updated_at
            ) VALUES (?, '旧事件', '旧摘要', '其他', 'candidate', '历史数据', ?, ?, NULL,
                      NULL, NULL, 1, 1, 0, NULL, 'event-cluster-v1', 'auto', 'auto', ?, ?)
            """,
            (event_id, now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO event_articles (
                id, event_id, article_id, role, similarity, match_reasons_json,
                is_manual, added_at, created_at
            ) VALUES (?, ?, ?, 'report', NULL, '[]', 0, ?, ?)
            """,
            (str(uuid.uuid4()), event_id, seed["article_id"], now, now),
        )

    orchestrator.on_articles_ingested([seed["article_id"]])
    orchestrator._sweep_once()

    with database.read_session() as conn:
        event = conn.execute(
            "SELECT category, category_source FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        task = conn.execute(
            "SELECT status, event_id FROM pipeline_tasks WHERE article_id = ?",
            (seed["article_id"],),
        ).fetchone()
    assert event is not None
    assert event["category"] == "科技"
    assert event["category_source"] == "auto"
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["event_id"] == event_id


def test_database_rejects_invalid_task_status(ready) -> None:
    seed = seed_article(with_analysis=False)
    now = utc_timestamp()
    with pytest.raises(Exception):
        with write_session() as conn:
            conn.execute(
                "INSERT INTO pipeline_tasks (id, article_id, stage, status, idempotency_key, "
                "created_at, updated_at) VALUES (?, ?, 'quality_check', 'bogus', ?, ?, ?)",
                (str(uuid.uuid4()), seed["article_id"], f"x:{uuid.uuid4()}", now, now),
            )


def test_retry_wait_task_resumes_after_backoff(ready) -> None:
    """Phase 7.2.1 regression: retry_wait must be claimed again when due."""

    orchestrator = _orchestrator()
    _enable(orchestrator)
    seed = seed_article(with_analysis=False)
    orchestrator.on_articles_ingested([seed["article_id"]])
    with database.read_session() as conn:
        task = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE article_id = ?", (seed["article_id"],)
        ).fetchone()
    task_id = str(task["id"])

    record = orchestrator.list_tasks(
        limit=1, offset=0, status=None, stage=None, trigger_type=None
    )[0][0]
    orchestrator._fail_task(record, "provider_timeout", "模型超时", retryable=True)
    assert task_row(task_id)["status"] == "retry_wait"

    # Backoff elapsed → the next sweep must pick the task up again.
    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET next_retry_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
            (task_id,),
        )
    orchestrator._sweep_once()

    after = task_row(task_id)
    # The task must leave quality_check instead of resting in retry_wait forever;
    # the AI stage may defer it again, which is the correct bounded behaviour.
    assert after["stage"] == "ai_analysis"
    assert int(after["attempts"]) == 1


def test_backfill_retry_wait_resumes_with_automation_disabled(ready) -> None:
    """A restart-recovered backfill task must finish without enabling automation."""

    orchestrator = _orchestrator()
    seed_article(title="恢复批次文章", with_analysis=False)
    created = orchestrator.create_backfill(limit=1)
    task = orchestrator.list_tasks(
        limit=1, offset=0, status=None, stage=None, trigger_type="backfill"
    )[0][0]
    assert created["created_tasks"] == 1

    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET status = 'running', lease_owner = 'dead-worker', "
            "lease_expires_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
            (task.id,),
        )
    orchestrator._recover_leases()
    assert task_row(task.id)["status"] == "retry_wait"

    orchestrator._sweep_once()
    after = task_row(task.id)
    assert after["stage"] == "ai_analysis"


def test_recovered_late_stage_parks_at_event_match(ready) -> None:
    """A crash between scoring stages must not leave the task on a dead stage."""

    orchestrator = _orchestrator()
    seed = seed_article(with_analysis=False)
    orchestrator.update_settings({"automation_enabled": True})
    orchestrator.on_articles_ingested([seed["article_id"]])
    with database.read_session() as conn:
        task = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE article_id = ?", (seed["article_id"],)
        ).fetchone()
    task_id = str(task["id"])

    with database.session() as conn:
        conn.execute(
            "UPDATE pipeline_tasks SET stage = 'event_score', status = 'running', "
            "lease_owner = 'dead-worker', lease_expires_at = '2020-01-01T00:00:00.000Z' "
            "WHERE id = ?",
            (task_id,),
        )
    orchestrator._recover_leases()
    orchestrator._sweep_once()

    after = task_row(task_id)
    assert after["stage"] in {"event_match", "done"}
    assert after["status"] != "retry_wait" or after["error_code"] != "lease_expired"


def test_failure_after_success_never_regresses_task(ready) -> None:
    """Phase 8.0: a late error must not move a finished task back to retry."""

    from database.repositories import pipeline_repository as pipeline_repo

    orchestrator = _orchestrator()
    seed = seed_article()
    now = utc_timestamp()
    with database.session() as conn:
        settings = pipeline_repo.get_settings(conn)
        values = orchestrator._task_values(
            article_id=seed["article_id"],
            trigger_type="auto",
            settings=settings,
            now=now,
            priority=10,
        )
        assert pipeline_repo.insert_task(conn, values)
        pipeline_repo.update_task(
            conn,
            values["id"],
            {
                "status": "succeeded",
                "stage": "done",
                "completed_at": now,
                "updated_at": now,
            },
        )
        task = pipeline_repo.get_task(conn, values["id"])
    assert task is not None

    orchestrator._fail_task(task, "finalize_failed", "模拟提交后异常", retryable=True)

    after = task_row(values["id"])
    assert after["status"] == "succeeded"
    assert after["stage"] == "done"
    assert after["attempts"] == 0
    with database.read_session() as conn:
        logs = conn.execute(
            "SELECT message FROM pipeline_task_logs WHERE task_id = ?",
            (values["id"],),
        ).fetchall()
    assert any("忽略后续失败" in str(row["message"]) for row in logs)
