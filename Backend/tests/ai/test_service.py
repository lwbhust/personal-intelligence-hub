"""AI analysis service tests with a scripted provider and a real SQLite DB.

The fake provider is a test double only; live verification against Ollama is
recorded separately in `Docs/PHASE3_LIVE_VERIFICATION.md`.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

import database
from ai_engine.errors import AIError
from ai_engine.prompts import PROMPT_VERSION
from ai_engine.provider import GenerationResult, ProviderHealth, RemoteModel
from database.repositories import ai_analysis_repository as analysis_repo
from database.repositories import ai_run_repository as run_repo
from database.repositories import article_repository as article_repo
from services.ai_analysis_service import AIAnalysisService
from services.errors import ServiceError

STAMP = "2026-11-16T10:00:00.000Z"
MODEL = "qwen3.5:4b-mlx"


def _valid_payload(index: int) -> dict:
    return {
        "category": "科技",
        "summary": f"第 {index} 篇文章的测试摘要，用于验证结构校验与入库流程。",
        "keywords": ["本地模型", "结构化", f"样本{index}"],
        "entities": [{"name": f"实体{index}", "type": "organization"}],
    }


class FakeProvider:
    base_url = "http://127.0.0.1:11434"

    def __init__(self, outputs: list[object], *, gate: threading.Event | None = None):
        self.outputs = list(outputs)
        self.calls: list[dict] = []
        self.gate = gate
        self.health = ProviderHealth(
            available=True,
            version="test",
            models=(
                RemoteModel(
                    name=MODEL,
                    digest="d" * 64,
                    size_bytes=4_000_000_000,
                    parameter_size="4.5B",
                    quantization="nvfp4",
                    remote_host=None,
                ),
                RemoteModel(
                    name="gpt-oss:20b-cloud",
                    digest="c" * 64,
                    size_bytes=381,
                    parameter_size="20.9B",
                    quantization="",
                    remote_host="https://ollama.com:443",
                ),
            ),
            error_code=None,
            checked_at=STAMP,
        )

    def health_check(self) -> ProviderHealth:
        return self.health

    def generate_structured(self, **kwargs) -> GenerationResult:
        self.calls.append(kwargs)
        if self.gate is not None:
            assert self.gate.wait(timeout=5), "test gate was never released"
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        return GenerationResult(
            text=text,
            model_name=kwargs["model"],
            model_digest="d" * 64,
            total_duration_ms=1200,
            load_duration_ms=10,
            prompt_eval_count=100,
            eval_count=40,
            eval_duration_ms=500,
            tok_per_s=80.0,
            truncated=False,
        )


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int = 2) -> list[str]:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIH_AI_ENABLED", "1")
    status = database.initialize()
    assert status.status == "ok"
    article_ids: list[str] = []
    with database.session() as conn:
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES ('src-1', NULL, 'Test Feed', 'rss', 'https://example.com/feed',
                      NULL, NULL, 'en', NULL, 5, NULL, 60, 1, 'unknown', ?, ?)
            """,
            (STAMP, STAMP),
        )
        for index in range(count):
            article_id = f"article-{index}"
            article_ids.append(article_id)
            title = f"测试文章 {index}"
            article_repo.insert(
                conn,
                {
                    "id": article_id,
                    "source_id": "src-1",
                    "external_id": f"ext-{index}",
                    "canonical_url": f"https://example.com/{index}",
                    "original_url": f"https://example.com/{index}",
                    "title": title,
                    "author": None,
                    "summary": None,
                    "content_text": f"这是第 {index} 篇测试正文，用于本地模型分析。",
                    "content_state": "full",
                    "published_at": STAMP,
                    "source_updated_at": None,
                    "fetched_at": STAMP,
                    "content_hash": hashlib.sha256(title.encode()).hexdigest(),
                    "status": "active",
                    "created_at": STAMP,
                    "updated_at": STAMP,
                },
            )
    return article_ids


def _wait_terminal(service: AIAnalysisService, run_id: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = service.get_run(run_id)
        if record.status in (
            "succeeded",
            "partially_succeeded",
            "failed",
            "cancelled",
            "paused",
        ):
            return record
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not settle: {service.get_run(run_id)}")


def test_unanalyzed_run_persists_validated_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=2)
    provider = FakeProvider([_valid_payload(0), _valid_payload(1)])
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.create_run(scope="unanalyzed", limit=10)
        assert run.status in ("pending", "running")
        assert run.requested_count == 2
        final = _wait_terminal(service, run.id)
        assert final.status == "succeeded"
        assert final.succeeded_count == 2
        assert final.processed_count == 2

        with database.read_session() as conn:
            first = analysis_repo.list_for_article(conn, "article-0")
            second = analysis_repo.list_for_article(conn, "article-1")
        assert len(first) == 1 and len(second) == 1
        assert first[0].category == "科技"
        assert first[0].prompt_version == PROMPT_VERSION
        assert first[0].model_name == MODEL
        assert first[0].params["num_ctx"] == 4096

        assert len(provider.calls) == 2
        assert all(call["num_ctx"] == 4096 for call in provider.calls)
        assert all(call["allowed_models"] == (MODEL,) for call in provider.calls)

        status = service.status()
        assert status["enabled"] is True
        assert status["available"] is True
        assert status["default_model"] == MODEL
        assert status["embedding"] == {
            "enabled": False,
            "reason": "embedding_model_not_configured",
        }
    finally:
        service.stop()


def test_duplicate_active_run_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    gate = threading.Event()
    provider = FakeProvider([_valid_payload(0)], gate=gate)
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        first = service.create_run(scope="unanalyzed", limit=10)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if service.get_run(first.id).status == "running":
                break
            time.sleep(0.01)
        with pytest.raises(ServiceError) as excinfo:
            service.create_run(scope="unanalyzed", limit=10)
        assert excinfo.value.code == "ai_run_in_progress"
        gate.set()
        _wait_terminal(service, first.id)
    finally:
        gate.set()
        service.stop()


def test_pause_and_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, monkeypatch, count=2)
    gate = threading.Event()
    provider = FakeProvider([_valid_payload(0), _valid_payload(1)], gate=gate)
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.create_run(scope="unanalyzed", limit=10)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if service.get_run(run.id).status == "running":
                break
            time.sleep(0.01)
        paused = service.pause_run(run.id)
        assert paused.status == "paused"
        gate.set()
        time.sleep(0.2)
        settled = service.get_run(run.id)
        assert settled.status == "paused"
        # Pausing must stop the run before both articles are processed.
        assert settled.succeeded_count < 2
        assert settled.processed_count < 2

        provider.gate = None
        resumed = service.resume_run(run.id)
        assert resumed.status in ("pending", "running")
        final = _wait_terminal(service, run.id)
        assert final.status == "succeeded"
        assert final.succeeded_count == 2
    finally:
        gate.set()
        service.stop()


def test_cancel_stops_remaining_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=2)
    gate = threading.Event()
    provider = FakeProvider([_valid_payload(0)], gate=gate)
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.create_run(scope="unanalyzed", limit=10)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if service.get_run(run.id).status == "running":
                break
            time.sleep(0.01)
        service.cancel_run(run.id)
        gate.set()
        final = _wait_terminal(service, run.id)
        assert final.status == "cancelled"
        assert final.succeeded_count == 1
        statuses = sorted(item.status for item in final.items)
        assert statuses == ["cancelled", "succeeded"]
    finally:
        gate.set()
        service.stop()


def test_schema_failures_retry_then_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    bad = {"category": "科技", "summary": "只有两个关键词", "keywords": ["a", "b"]}
    provider = FakeProvider([bad, bad, bad])
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.create_run(scope="unanalyzed", limit=10)
        final = _wait_terminal(service, run.id)
        assert final.status == "failed"
        assert final.failed_count == 1
        assert final.items[0].error_code == "schema_invalid"
        assert final.items[0].attempts == 3
        with database.read_session() as conn:
            assert analysis_repo.list_for_article(conn, "article-0") == []
    finally:
        service.stop()


def test_provider_unavailable_degrades_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    provider = FakeProvider(
        [
            AIError("model_unavailable", "模型不可用", retryable=True),
            AIError("model_unavailable", "模型不可用", retryable=True),
            AIError("model_unavailable", "模型不可用", retryable=True),
        ]
    )
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.create_run(scope="unanalyzed", limit=10)
        final = _wait_terminal(service, run.id)
        assert final.status == "failed"
        assert final.items[0].error_code == "model_unavailable"
        with database.read_session() as conn:
            assert analysis_repo.count_for_article(conn, "article-0") == 0
    finally:
        service.stop()


def test_analyze_article_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    provider = FakeProvider([_valid_payload(0)])
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.analyze_article("article-0")
        _wait_terminal(service, run.id)
        with pytest.raises(ServiceError) as excinfo:
            service.analyze_article("article-0")
        assert excinfo.value.code == "article_already_analyzed"
    finally:
        service.stop()


def test_no_eligible_articles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, monkeypatch, count=0)
    service = AIAnalysisService(provider=FakeProvider([]), enabled=True)
    service.start()
    try:
        with pytest.raises(ServiceError) as excinfo:
            service.create_run(scope="unanalyzed", limit=10)
        assert excinfo.value.code == "no_analyzable_articles"
    finally:
        service.stop()


def test_disabled_service_rejects_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    service = AIAnalysisService(provider=FakeProvider([]), enabled=False)
    service.start()
    try:
        with pytest.raises(ServiceError) as excinfo:
            service.create_run(scope="unanalyzed", limit=10)
        assert excinfo.value.code == "ai_disabled"
    finally:
        service.stop()


def test_unexpected_provider_error_does_not_poison_article(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    provider = FakeProvider([RuntimeError("boom"), _valid_payload(0)])
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        first = service.create_run(scope="unanalyzed", limit=10)
        failed = _wait_terminal(service, first.id)
        assert failed.status == "failed"
        assert failed.items[0].status == "failed"
        assert failed.items[0].error_code == "internal_error"

        second = service.create_run(scope="selected", article_ids=["article-0"])
        final = _wait_terminal(service, second.id)
        assert final.status == "succeeded"
        assert final.items[0].status == "succeeded"
    finally:
        service.stop()


def test_transport_errors_are_reported_as_model_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    provider = FakeProvider(
        [
            AIError("provider_timeout", "请求超时", retryable=True),
            AIError("provider_timeout", "请求超时", retryable=True),
            AIError("provider_timeout", "请求超时", retryable=True),
        ]
    )
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        run = service.create_run(scope="unanalyzed", limit=10)
        final = _wait_terminal(service, run.id)
        assert final.status == "failed"
        assert final.items[0].error_code == "model_unavailable"
        assert "provider_timeout" in (final.items[0].error_message or "")
    finally:
        service.stop()


def test_selected_run_records_pre_skipped_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=2)
    provider = FakeProvider([_valid_payload(0), _valid_payload(1)])
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        first = service.analyze_article("article-0")
        _wait_terminal(service, first.id)

        second = service.create_run(
            scope="selected", article_ids=["article-0", "article-1"]
        )
        final = _wait_terminal(service, second.id)
        assert final.status == "succeeded"
        assert final.requested_count == 2
        assert final.processed_count == 2
        assert final.succeeded_count == 1
        assert final.skipped_count == 1
        statuses = sorted(item.status for item in final.items)
        assert statuses == ["skipped", "succeeded"]
    finally:
        service.stop()


def test_paused_run_survives_restart_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    with database.session() as conn:
        run_repo.insert_run(
            conn,
            {
                "id": "run-paused",
                "trigger_type": "manual",
                "scope": "unanalyzed",
                "status": "paused",
                "requested_count": 1,
                "processed_count": 0,
                "succeeded_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "model_name": MODEL,
                "error_message": None,
                "cancel_requested": 0,
                "pause_requested": 1,
                "started_at": STAMP,
                "finished_at": None,
                "duration_ms": None,
                "created_at": STAMP,
                "updated_at": STAMP,
            },
        )
        run_repo.insert_item(
            conn,
            {
                "id": "item-paused",
                "run_id": "run-paused",
                "article_id": "article-0",
                "status": "pending",
                "attempts": 0,
                "error_code": None,
                "error_message": None,
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
                "created_at": STAMP,
                "updated_at": STAMP,
            },
        )
    provider = FakeProvider([_valid_payload(0)])
    service = AIAnalysisService(provider=provider, enabled=True)
    service.start()
    try:
        after_restart = service.get_run("run-paused")
        assert after_restart.status == "paused"
        assert after_restart.items[0].status == "pending"

        service.resume_run("run-paused")
        final = _wait_terminal(service, "run-paused")
        assert final.status == "succeeded"
        assert final.succeeded_count == 1
    finally:
        service.stop()


def test_restart_marks_running_work_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, monkeypatch, count=1)
    service = AIAnalysisService(provider=FakeProvider([]), enabled=True)
    try:
        with database.session() as conn:
            run_repo.insert_run(
                conn,
                {
                    "id": "run-stale",
                    "trigger_type": "manual",
                    "scope": "unanalyzed",
                    "status": "running",
                    "requested_count": 1,
                    "processed_count": 0,
                    "succeeded_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "model_name": MODEL,
                    "error_message": None,
                    "cancel_requested": 0,
                    "pause_requested": 0,
                    "started_at": STAMP,
                    "finished_at": None,
                    "duration_ms": None,
                    "created_at": STAMP,
                    "updated_at": STAMP,
                },
            )
            run_repo.insert_item(
                conn,
                {
                    "id": "item-stale",
                    "run_id": "run-stale",
                    "article_id": "article-0",
                    "status": "running",
                    "attempts": 1,
                    "error_code": None,
                    "error_message": None,
                    "started_at": STAMP,
                    "finished_at": None,
                    "duration_ms": None,
                    "created_at": STAMP,
                    "updated_at": STAMP,
                },
            )
        changed = service.recover_interrupted()
        assert changed == 1
        record = service.get_run("run-stale")
        assert record.status == "failed"
        assert "重启" in (record.error_message or "")
        assert record.items[0].status == "failed"
        assert record.items[0].error_code == "interrupted"
    finally:
        service.stop()
