"""On-demand body retrieval stores real content and keeps failures honest."""

from __future__ import annotations

from types import SimpleNamespace

import database
from collectors.net_guard import NetGuardError
from core.timeutil import utc_timestamp
from database import session as write_session
from services.content_fetch_service import ContentFetchService
from services.search_service import SearchService

from pipeline_support import create_article, create_source

_BODY_TEXT = "量子退火专用词用于验证全文索引已经包含抓取到的正文。" * 12


class _FakeGuard:
    def __init__(self, body: bytes | None = None, error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.calls: list[str] = []

    def fetch(self, url: str, **_kwargs):  # noqa: ANN003 - test double
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            status_code=200,
            body=self.body or b"",
            content_type="text/html",
            final_url=url,
        )


def _article_with_url(content_state: str = "summary_only") -> str:
    source_id = create_source()
    article_id = create_article(
        source_id=source_id,
        title="量子退火调度系统上线",
        content_state=content_state,
    )
    with write_session() as conn:
        conn.execute(
            "UPDATE articles SET canonical_url = ? WHERE id = ?",
            ("https://example.com/posts/quantum", article_id),
        )
    return article_id


def test_fetch_stores_body_and_updates_full_text_index(ready) -> None:
    article_id = _article_with_url()
    guard = _FakeGuard(
        body=(
            "<html><body><article><p>" + _BODY_TEXT + "</p></article></body></html>"
        ).encode("utf-8")
    )
    service = ContentFetchService(guard=guard, now=utc_timestamp)

    record, result = service.fetch(article_id)

    assert result["status"] == "fetched"
    assert record.content_state == "full"
    assert record.content_text is not None and "量子退火专用词" in record.content_text
    assert record.content_fetched_at is not None

    results, total = SearchService().search(
        query="量子退火专用词", limit=10, offset=0
    )
    assert total >= 1
    assert any(item.article_id == article_id for item in results)


def test_cached_article_is_not_downloaded_twice(ready) -> None:
    article_id = _article_with_url(content_state="full")
    with write_session() as conn:
        conn.execute(
            "UPDATE articles SET content_text = ? WHERE id = ?",
            ("已有正文内容" * 40, article_id),
        )
    guard = _FakeGuard(body=b"<html></html>")
    service = ContentFetchService(guard=guard)

    _, result = service.fetch(article_id)

    assert result["status"] == "cached"
    assert guard.calls == []


def test_net_guard_failure_keeps_summary_and_records_attempt(ready) -> None:
    article_id = _article_with_url()
    guard = _FakeGuard(error=NetGuardError("robots_disallowed", "robots 禁止采集"))
    service = ContentFetchService(guard=guard, now=utc_timestamp)

    record, result = service.fetch(article_id)

    assert result["status"] == "failed"
    assert result["error_code"] == "robots_disallowed"
    assert record.content_state == "summary_only"
    assert record.content_text is None
    assert record.content_fetched_at is not None


def test_insufficient_page_keeps_summary(ready) -> None:
    article_id = _article_with_url()
    guard = _FakeGuard(body=b"<html><body><p>short</p></body></html>")
    service = ContentFetchService(guard=guard, now=utc_timestamp)

    record, result = service.fetch(article_id)

    assert result["status"] == "failed"
    assert result["error_code"] == "content_insufficient"
    assert record.content_state == "summary_only"
    assert record.content_fetched_at is not None


def test_missing_url_fails_without_network(ready) -> None:
    source_id = create_source()
    article_id = create_article(source_id=source_id, title="没有原文地址")
    guard = _FakeGuard(body=b"")
    service = ContentFetchService(guard=guard)

    _, result = service.fetch(article_id)

    assert result["status"] == "failed"
    assert result["error_code"] == "no_source_url"
    assert guard.calls == []
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT content_fetched_at FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
    assert row[0] is None
