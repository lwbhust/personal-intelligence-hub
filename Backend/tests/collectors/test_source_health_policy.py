"""Phase 8.0 source health governance: failure classification and retry pacing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import database
from core.timeutil import utc_timestamp
from database import session as write_session
from services.collection_service import CollectionService
from services.source_health_service import (
    ADAPTER_INVALID,
    FEED_INVALID,
    HTTP_CLIENT,
    HTTP_GONE,
    SECURITY_BLOCKED,
    TRANSIENT_NETWORK,
    classify_failure,
    describe_failure,
    effective_interval_minutes,
)


@pytest.fixture()
def data_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIH_SCHEDULER_ENABLED", "0")
    status = database.initialize()
    assert status.status == "ok"
    return tmp_path / "data"


def _add_source(
    *,
    health_status: str,
    interval: int = 60,
) -> str:
    source_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES (?, NULL, ?, 'rss', ?, NULL, NULL, 'en', NULL, 0, NULL,
                      ?, 1, ?, ?, ?)
            """,
            (
                source_id,
                f"源-{source_id[:6]}",
                f"https://{source_id[:8]}.example.com/feed.xml",
                interval,
                health_status,
                now,
                now,
            ),
        )
    return source_id


def _set_fetch_state(
    source_id: str,
    *,
    last_fetch_minutes_ago: int,
    consecutive_failures: int = 0,
    error_code: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    fetched = (now - timedelta(minutes=last_fetch_minutes_ago)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO source_fetch_state (
                source_id, etag, last_modified, last_fetch_at, last_success_at,
                last_error_code, last_error_message, consecutive_failures, updated_at
            ) VALUES (?, NULL, NULL, ?, NULL, ?, ?, ?, ?)
            """,
            (
                source_id,
                fetched,
                error_code,
                None if error_code is None else "测试错误",
                consecutive_failures,
                fetched,
            ),
        )


def test_classify_failure_covers_each_kind() -> None:
    assert classify_failure("dns_failure").kind == TRANSIENT_NETWORK
    assert classify_failure("dns_failure").systemic is True
    assert classify_failure("network_timeout").systemic is False
    assert classify_failure("http_client_error", 404).kind == HTTP_GONE
    assert classify_failure("http_client_error", 404).escalate_after == 2
    assert classify_failure("http_client_error", 403).kind == HTTP_CLIENT
    assert classify_failure("xml_parse_error").kind == FEED_INVALID
    assert classify_failure("adapter_no_entries").kind == ADAPTER_INVALID
    assert classify_failure("blocked_target").kind == SECURITY_BLOCKED
    assert classify_failure("blocked_target").escalate_after == 1
    assert classify_failure(None).kind == "unknown"


def test_describe_failure_appends_human_label() -> None:
    message = describe_failure("dns_failure", "域名解析失败")
    assert "域名解析失败" in message
    assert "临时异常" in message
    long_message = describe_failure("xml_parse_error", "x" * 900)
    assert len(long_message) <= 500


def test_effective_interval_keeps_healthy_sources_on_schedule() -> None:
    assert (
        effective_interval_minutes(
            base_interval=60,
            health_status="healthy",
            consecutive_failures=0,
            error_code=None,
        )
        == 60
    )


def test_effective_interval_backs_off_failing_sources() -> None:
    assert (
        effective_interval_minutes(
            base_interval=60,
            health_status="failing",
            consecutive_failures=4,
            error_code="dns_failure",
        )
        == 120
    )
    assert (
        effective_interval_minutes(
            base_interval=60,
            health_status="failing",
            consecutive_failures=2,
            error_code="http_client_error",
        )
        >= 360
    )


def test_due_sources_skip_failing_source_until_cooldown(data_env: Path) -> None:
    healthy = _add_source(health_status="healthy", interval=5)
    failing = _add_source(health_status="failing", interval=5)
    _set_fetch_state(healthy, last_fetch_minutes_ago=10)
    _set_fetch_state(
        failing, last_fetch_minutes_ago=10, consecutive_failures=4, error_code="dns_failure"
    )

    service = CollectionService(enabled=False)
    try:
        due = set(service.due_source_ids())
    finally:
        service._item_pool.shutdown(wait=True, cancel_futures=True)

    assert healthy in due
    assert failing not in due


def test_systemic_outage_requires_majority_of_batch() -> None:
    def item(status: str, code: str | None = None):
        return SimpleNamespace(status=status, error_code=code)

    assert CollectionService._systemic_outage(
        [item("failed", "dns_failure") for _ in range(3)]
    )
    assert not CollectionService._systemic_outage(
        [item("failed", "dns_failure"), item("succeeded"), item("succeeded")]
    )
    assert not CollectionService._systemic_outage(
        [item("failed", "http_client_error") for _ in range(4)]
    )
