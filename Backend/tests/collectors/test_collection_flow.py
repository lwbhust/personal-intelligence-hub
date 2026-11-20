"""End-to-end collection flow tests against a real local feed server.

Network policy for these tests explicitly allows loopback; production defaults
are covered by `tests/security/test_net_guard.py`.
"""

from __future__ import annotations

import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import database
from collectors.net_guard import NetGuard, NetPolicy
from core.timeutil import utc_timestamp
from database.repositories import article_repository as article_repo
from database.repositories import collection_job_repository as job_repo
from database.repositories import source_health_repository as health_repo
from database.repositories import source_repository as source_repo
from services.collection_service import CollectionService
from services.errors import ServiceError

START = "2026-11-16T08:00:00.000Z"


def _rss(items: list[dict[str, str]]) -> bytes:
    blocks = []
    for item in items:
        parts = [f"<title>{item['title']}</title>"]
        if "link" in item:
            parts.append(f"<link>{item['link']}</link>")
        if "guid" in item:
            parts.append(f"<guid>{item['guid']}</guid>")
        if "description" in item:
            parts.append(f"<description><![CDATA[{item['description']}]]></description>")
        if "pubDate" in item:
            parts.append(f"<pubDate>{item['pubDate']}</pubDate>")
        if "content" in item:
            parts.append(
                "<content:encoded><![CDATA["
                + item["content"]
                + "]]></content:encoded>"
            )
        blocks.append("<item>" + "".join(parts) + "</item>")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        "<channel><title>Test Feed</title>" + "".join(blocks) + "</channel></rss>"
    )
    return body.encode("utf-8")


V1 = _rss(
    [
        {
            "title": "First post",
            "link": "https://example.com/posts/1?utm_source=rss",
            "guid": "post-1",
            "description": "First summary",
            "content": "<p>First full body</p>",
        },
        {
            "title": "Second post",
            "link": "https://example.com/posts/2",
            "guid": "post-2",
            "description": "Second summary only",
        },
    ]
)

V2 = _rss(
    [
        {
            "title": "First post (updated)",
            "link": "https://example.com/posts/1",
            "guid": "post-1",
            "description": "Updated summary",
            "content": "<p>Updated full body</p>",
        },
        {
            "title": "Second post",
            "link": "https://example.com/posts/2",
            "guid": "post-2",
            "description": "Second summary only",
        },
    ]
)

SUMMARY_ONLY = _rss(
    [
        {
            "title": "First post (updated)",
            "link": "https://example.com/posts/1",
            "guid": "post-1",
            "description": "Only a summary now",
        }
    ]
)

NO_GUID = _rss(
    [
        {
            "title": "No guid",
            "link": "https://example.com/posts/3?utm_medium=email",
            "description": "Same URL different tracking",
        }
    ]
)

NO_GUID_AGAIN = _rss(
    [
        {
            "title": "No guid",
            "link": "https://example.com/posts/3",
            "description": "Same URL different tracking",
        }
    ]
)

MANY = _rss(
    [
        {"title": "Oldest", "link": "https://example.com/many/1", "guid": "many-1",
         "pubDate": "Mon, 16 Nov 2026 01:00:00 GMT"},
        {"title": "Newest", "link": "https://example.com/many/2", "guid": "many-2",
         "pubDate": "Mon, 16 Nov 2026 04:00:00 GMT"},
        {"title": "Middle", "link": "https://example.com/many/3", "guid": "many-3",
         "pubDate": "Mon, 16 Nov 2026 03:00:00 GMT"},
        {"title": "Second newest", "link": "https://example.com/many/4", "guid": "many-4",
         "pubDate": "Mon, 16 Nov 2026 02:00:00 GMT"},
    ]
)

DUPLICATE_TITLE = _rss(
    [
        {"title": "同一篇新闻", "link": "https://example.com/dup/a", "guid": "dup-a",
         "description": "相同正文", "pubDate": "Mon, 16 Nov 2026 08:00:00 GMT"},
        {"title": "同一篇新闻", "link": "https://example.com/dup/b", "guid": "dup-b",
         "description": "相同正文", "pubDate": "Mon, 16 Nov 2026 08:02:00 GMT"},
    ]
)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    counts: dict[str, int] = {}

    def _send(self, status: int, body: bytes, ctype: str = "application/rss+xml") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: C901
        path = self.path.split("?", 1)[0]
        self.counts[path] = self.counts.get(path, 0) + 1
        if self.path.startswith("/feed-v1"):
            self._send(200, V1)
        elif self.path.startswith("/feed-v2"):
            self._send(200, V2)
        elif self.path.startswith("/feed-summary"):
            self._send(200, SUMMARY_ONLY)
        elif self.path.startswith("/feed-noguid"):
            self._send(200, NO_GUID)
        elif self.path.startswith("/feed-noguid-again"):
            self._send(200, NO_GUID_AGAIN)
        elif self.path.startswith("/feed-many"):
            self._send(200, MANY)
        elif self.path.startswith("/feed-duptitle"):
            self._send(200, DUPLICATE_TITLE)
        elif self.path.startswith("/feed-flaky"):
            if self.counts[path] <= 2:
                self._send(500, b"temporary", "text/plain")
            else:
                self._send(200, V1)
        elif self.path.startswith("/feed-500"):
            self._send(500, b"down", "text/plain")
        elif self.path.startswith("/feed-404"):
            self._send(404, b"missing", "text/plain")
        elif self.path.startswith("/feed-empty"):
            self._send(200, b"<?xml version='1.0'?><rss><channel></channel></rss>")
        elif self.path.startswith("/feed-octet"):
            self._send(200, V1, "application/octet-stream")
        elif self.path.startswith("/feed-binary"):
            self._send(200, b"\x00\x01\x02binary", "application/octet-stream")
        elif self.path.startswith("/feed-html"):
            self._send(200, b"<html></html>", "text/html")
        elif self.path.startswith("/feed-slow"):
            time.sleep(1.0)
            self._send(200, V1)
        else:
            self._send(404, b"missing", "text/plain")

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture()
def base_url() -> str:
    _Handler.counts.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    _Handler.counts.clear()


@pytest.fixture()
def data_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    status = database.initialize()
    assert status.status == "ok"
    assert status.schema_version >= 6
    return tmp_path / "data"


@pytest.fixture()
def service(data_env: Path) -> CollectionService:
    instance = CollectionService(
        enabled=False,
        guard=NetGuard(
            NetPolicy(
                allowed_ports=None,
                allow_loopback_for_tests=True,
                robots_enabled=False,
                total_timeout=5.0,
                read_timeout=2.0,
            )
        ),
    )
    yield instance
    instance._item_pool.shutdown(wait=True, cancel_futures=True)


def _add_source(
    url: str,
    *,
    name: str = "Feed",
    enabled: bool = True,
    max_entries: int | None = None,
) -> str:
    source_id = str(uuid.uuid4())
    with database.session() as conn:
        source_repo.insert(
            conn,
            {
                "id": source_id,
                "category_id": None,
                "name": name,
                "source_type": "rss",
                "url": url,
                "homepage_url": None,
                "description": None,
                "language": "en",
                "country": None,
                "priority": 0,
                "credibility_score": None,
                "fetch_interval_minutes": 60,
                "max_entries_per_fetch": max_entries,
                "enabled": 1 if enabled else 0,
                "health_status": "unknown",
                "created_at": START,
                "updated_at": START,
            },
        )
    return source_id


def _run(service: CollectionService, source_ids: list[str] | None = None):
    job = service.create_job(trigger_type="manual", source_ids=source_ids)
    service._execute_job(job.id)
    return service.get_job(job.id)


def _articles() -> list:
    with database.read_session() as conn:
        return article_repo.list_articles(conn, limit=100, offset=0)[0]


def test_first_collection_persists_articles(base_url: str, service: CollectionService) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    job = _run(service, [source_id])

    assert job.status == "succeeded"
    assert job.discovered_count == 2
    assert job.inserted_count == 2
    assert job.duplicate_count == 0
    assert job.error_count == 0

    articles = _articles()
    assert len(articles) == 2
    full = next(item for item in articles if item.title == "First post")
    assert full.content_state == "full"
    assert full.content_text == "First full body"
    assert full.canonical_url == "https://example.com/posts/1"
    summary = next(item for item in articles if item.title == "Second post")
    assert summary.content_state == "summary_only"
    assert summary.canonical_url == "https://example.com/posts/2"

    with database.read_session() as conn:
        source = source_repo.get_active(conn, source_id)
        logs, total = health_repo.list_recent(conn, source_id, limit=10)
    assert source is not None and source.health_status == "healthy"
    assert source.last_success_at is not None
    assert total == 1 and logs[0].status == "healthy"
    assert logs[0].http_status == 200


def test_second_collection_is_idempotent(base_url: str, service: CollectionService) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    _run(service, [source_id])
    second = _run(service, [source_id])

    assert second.status == "succeeded"
    assert second.inserted_count == 0
    assert second.duplicate_count == 2
    assert len(_articles()) == 2


def test_changed_content_updates_without_duplication(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    _run(service, [source_id])

    # Point the same source at the updated feed.
    with database.session() as conn:
        source_repo.update(conn, source_id, {"url": base_url + "/feed-v2", "updated_at": START})
    job = _run(service, [source_id])

    assert job.updated_count == 1
    assert job.inserted_count == 0
    articles = _articles()
    assert len(articles) == 2
    first = next(item for item in articles if item.external_id == "post-1")
    assert first.title == "First post (updated)"
    assert first.content_text == "Updated full body"


def test_summary_never_overwrites_full_content(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    _run(service, [source_id])

    with database.session() as conn:
        source_repo.update(conn, source_id, {"url": base_url + "/feed-summary", "updated_at": START})
    _run(service, [source_id])

    first = next(item for item in _articles() if item.external_id == "post-1")
    assert first.content_state == "full"
    assert first.content_text == "First full body"


def test_same_feed_on_two_sources_stays_separate(
    base_url: str, service: CollectionService
) -> None:
    first_source = _add_source(base_url + "/feed-v1?src=a", name="A")
    second_source = _add_source(base_url + "/feed-v1?src=b", name="B")
    job = _run(service, [first_source, second_source])

    assert job.status == "succeeded"
    assert job.inserted_count == 4
    articles = _articles()
    assert len(articles) == 4
    assert {item.source_id for item in articles} == {first_source, second_source}


def test_missing_guid_dedupes_by_canonical_url(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-noguid")
    _run(service, [source_id])

    with database.session() as conn:
        source_repo.update(
            conn, source_id, {"url": base_url + "/feed-noguid-again", "updated_at": START}
        )
    job = _run(service, [source_id])

    assert job.inserted_count == 0
    assert job.duplicate_count == 1
    assert len(_articles()) == 1
    assert _articles()[0].canonical_url == "https://example.com/posts/3"


def test_http_404_marks_job_failed_and_source_failing(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-404")
    job = _run(service, [source_id])

    assert job.status == "failed"
    assert job.failed_source_count == 1
    assert job.error_count >= 1
    assert job.items[0].error_code == "http_client_error"
    assert job.items[0].http_status == 404

    with database.read_session() as conn:
        source = source_repo.get_active(conn, source_id)
        logs, _ = health_repo.list_recent(conn, source_id, limit=10)
    assert source is not None
    assert source.health_status in ("degraded", "failing")
    assert source.last_error_code == "http_client_error"
    assert logs and logs[0].status in ("degraded", "failing")


def test_unsupported_content_type_fails_item(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-html")
    job = _run(service, [source_id])
    assert job.status == "failed"
    assert job.items[0].error_code == "unsupported_content_type"


def test_octet_stream_feed_is_accepted(base_url: str, service: CollectionService) -> None:
    """Many real blogs serve valid feeds as application/octet-stream."""

    source_id = _add_source(base_url + "/feed-octet")
    job = _run(service, [source_id])
    assert job.status == "succeeded"
    assert job.inserted_count == 2


def test_octet_stream_non_xml_payload_is_rejected(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-binary")
    job = _run(service, [source_id])
    assert job.status == "failed"
    assert job.items[0].error_code == "xml_parse_error"


def test_retryable_5xx_is_retried_then_succeeds(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-flaky")
    job = _run(service, [source_id])

    assert job.status == "succeeded"
    assert job.inserted_count == 2
    assert _Handler.counts["/feed-flaky"] == 3  # initial + 2 retries


def test_retry_stops_after_three_attempts(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-500")
    job = _run(service, [source_id])

    assert job.status == "failed"
    assert job.items[0].error_code == "http_server_error"
    assert _Handler.counts["/feed-500"] == 3


def test_empty_feed_fails_without_articles(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-empty")
    job = _run(service, [source_id])
    assert job.status == "failed"
    assert job.items[0].error_code == "feed_empty"
    assert _articles() == []


def test_disabled_and_deleted_sources_are_not_collected(
    base_url: str, service: CollectionService
) -> None:
    disabled = _add_source(base_url + "/feed-v1?src=disabled", name="disabled", enabled=False)
    deleted = _add_source(base_url + "/feed-v1?src=deleted", name="deleted")
    with database.session() as conn:
        source_repo.soft_delete(conn, deleted, START)

    with pytest.raises(ServiceError) as error:
        service.create_job(trigger_type="manual", source_ids=None)
    assert error.value.code == "no_enabled_sources"

    with pytest.raises(ServiceError) as single:
        service.create_job(trigger_type="manual", source_ids=[disabled])
    assert single.value.code == "source_not_collectable"


def test_non_feed_source_type_is_rejected(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    with database.session() as conn:
        source_repo.update(conn, source_id, {"source_type": "website", "updated_at": START})

    with pytest.raises(ServiceError) as error:
        service.create_job(trigger_type="manual", source_ids=[source_id])
    assert error.value.code == "adapter_not_supported"
    assert error.value.status_code == 422


def test_original_url_only_keeps_http_schemes() -> None:
    assert CollectionService._original_url("javascript:alert(1)") is None
    assert CollectionService._original_url("file:///etc/passwd") is None
    assert CollectionService._original_url("https://example.com/a") == (
        "https://example.com/a"
    )


def test_batch_limit_is_enforced_before_any_write(service: CollectionService) -> None:
    with pytest.raises(ServiceError) as error:
        service.create_job(
            trigger_type="manual", source_ids=[str(uuid.uuid4()) for _ in range(51)]
        )
    assert error.value.code == "collection_batch_too_large"
    assert error.value.status_code == 409


def test_all_enabled_batch_above_limit_is_rejected(
    service: CollectionService,
) -> None:
    for index in range(51):
        _add_source(
            f"https://example.com/feed-{index}.xml", name=f"feed-{index}"
        )
    with pytest.raises(ServiceError) as error:
        service.create_job(trigger_type="manual", source_ids=None)
    assert error.value.code == "collection_batch_too_large"
    assert error.value.status_code == 409


def test_cancel_pending_job(service: CollectionService, base_url: str) -> None:
    # No worker started: the job stays pending, so cancellation is deterministic.
    source_id = _add_source(base_url + "/feed-v1")
    job = service.create_job(trigger_type="manual", source_ids=[source_id])
    assert job.status == "pending"

    cancelled = service.cancel_job(job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_requested is True
    assert cancelled.items[0].status == "cancelled"

    with pytest.raises(ServiceError) as error:
        service.cancel_job(job.id)
    assert error.value.code == "job_not_cancellable"


def test_retry_creates_new_job_for_failed_source(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-404")
    failed = _run(service, [source_id])
    assert failed.status == "failed"

    with database.session() as conn:
        source_repo.update(conn, source_id, {"url": base_url + "/feed-v1", "updated_at": START})
    retried = service.retry_job(failed.id)
    assert retried.id != failed.id
    assert retried.status == "pending"
    assert retried.requested_source_count == 1

    with pytest.raises(ServiceError) as error:
        service.retry_job(failed.id)
    assert error.value.code in {"job_not_retryable", "source_already_collecting"}


def test_restart_recovery_marks_running_work_interrupted(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    job = service.create_job(trigger_type="manual", source_ids=[source_id])
    now = utc_timestamp()
    with database.session() as conn:
        job_repo.update_job(conn, job.id, {"status": "running", "started_at": now, "updated_at": now})
        job_repo.update_item(
            conn, job.items[0].id, {"status": "running", "started_at": now, "updated_at": now}
        )

    changed = service.recover_interrupted()
    assert changed == 1

    recovered = service.get_job(job.id)
    assert recovered.status == "failed"
    assert recovered.items[0].status == "failed"
    assert recovered.items[0].error_code == "interrupted"
    assert recovered.processed_source_count == 1
    assert recovered.succeeded_source_count == 0
    assert recovered.failed_source_count == 1
    assert recovered.error_count == 1


def test_scheduler_is_due_before_first_fetch_and_after_interval(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    assert source_id in service.due_source_ids()

    _run(service, [source_id])
    assert source_id not in service.due_source_ids()

    with database.session() as conn:
        conn.execute(
            "UPDATE source_fetch_state SET last_fetch_at = ? WHERE source_id = ?",
            ("2020-01-01T00:00:00.000Z", source_id),
        )
    assert source_id in service.due_source_ids()


def test_scheduler_once_creates_scheduled_job(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-v1")
    service.scheduler_enabled = True
    job = service.run_scheduled_once()
    assert job is not None
    assert job.trigger_type == "scheduled"
    assert job.requested_source_count == 1
    assert source_id in {item.source_id for item in job.items}


def test_source_entry_cap_keeps_newest_entries(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-many", max_entries=2)
    job = _run(service, [source_id])

    assert job.status == "succeeded"
    assert job.discovered_count == 2
    assert job.inserted_count == 2
    titles = {item.title for item in _articles()}
    assert titles == {"Newest", "Middle"}


def test_source_entry_cap_none_keeps_all_entries(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-many")
    job = _run(service, [source_id])

    assert job.status == "succeeded"
    assert job.inserted_count == 4


def test_same_source_duplicate_title_within_window_is_deduped(
    base_url: str, service: CollectionService
) -> None:
    source_id = _add_source(base_url + "/feed-duptitle")
    job = _run(service, [source_id])

    assert job.status == "succeeded"
    assert job.inserted_count == 1
    assert job.updated_count == 1
    assert len(_articles()) == 1
