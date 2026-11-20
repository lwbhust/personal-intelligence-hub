"""On-demand article body retrieval.

Design constraints (Phase 8):

* Only fetched when a user opens an article and asks for the full text — never
  in bulk, so we do not hammer sources or inflate storage.
* All HTTP goes through `NetGuard` (SSRF, robots.txt, timeouts, size caps).
* Failures never fabricate content: the RSS summary stays and the article is
  marked as `summary_only` with a recorded fetch time.
"""

from __future__ import annotations

from collections.abc import Callable

import database
from collectors.content_extractor import extract_main_text
from collectors.net_guard import NetGuard, NetGuardError
from core.timeutil import utc_timestamp
from database.repositories import article_repository as repo
from database.repositories.models import ArticleRecord

from .errors import not_found

HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
MAX_HTML_BYTES = 3 * 1024 * 1024


class ContentFetchService:
    def __init__(
        self,
        guard: NetGuard | None = None,
        *,
        now: Callable[[], str] = utc_timestamp,
    ) -> None:
        self._guard = guard
        self._now = now

    def _net_guard(self) -> NetGuard:
        if self._guard is None:
            self._guard = NetGuard()
        return self._guard

    def _record_attempt(
        self, article_id: str, record: ArticleRecord
    ) -> ArticleRecord:
        with database.session() as conn:
            repo.mark_content_fetch(conn, article_id, fetched_at=self._now())
        with database.read_session() as conn:
            return repo.get_active(conn, article_id) or record

    def fetch(self, article_id: str) -> tuple[ArticleRecord, dict[str, object]]:
        with database.read_session() as conn:
            record = repo.get_active(conn, article_id)
        if record is None:
            raise not_found("article_not_found", "文章不存在")

        if record.content_state == "full" and record.content_text:
            return record, {
                "status": "cached",
                "chars": len(record.content_text),
                "url": record.canonical_url or record.original_url,
                "error_code": None,
                "error_message": None,
            }

        url = (record.canonical_url or record.original_url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return record, {
                "status": "failed",
                "chars": 0,
                "url": None,
                "error_code": "no_source_url",
                "error_message": "该文章没有可访问的原文地址",
            }

        try:
            response = self._net_guard().fetch(
                url,
                allowed_content_types=HTML_CONTENT_TYPES,
                max_bytes=MAX_HTML_BYTES,
            )
            text = extract_main_text(response.body, response.content_type)
        except NetGuardError as exc:
            refreshed = self._record_attempt(article_id, record)
            return refreshed, {
                "status": "failed",
                "chars": 0,
                "url": url,
                "error_code": exc.code,
                "error_message": exc.message[:300],
            }
        except Exception as exc:  # noqa: BLE001 - network failures are expected
            refreshed = self._record_attempt(article_id, record)
            return refreshed, {
                "status": "failed",
                "chars": 0,
                "url": url,
                "error_code": "content_fetch_failed",
                "error_message": f"{type(exc).__name__}: {exc}"[:300],
            }

        now = self._now()
        if text is None:
            with database.session() as conn:
                repo.mark_content_fetch(conn, article_id, fetched_at=now)
            with database.read_session() as conn:
                refreshed = repo.get_active(conn, article_id) or record
            return refreshed, {
                "status": "failed",
                "chars": 0,
                "url": url,
                "error_code": "content_insufficient",
                "error_message": "页面正文过少或抽取失败，已保留 RSS 摘要",
            }

        with database.session() as conn:
            repo.update_content(
                conn,
                article_id,
                content_text=text,
                content_state="full",
                fetched_at=now,
            )
        with database.read_session() as conn:
            refreshed = repo.get_active(conn, article_id) or record
        return refreshed, {
            "status": "fetched",
            "chars": len(text),
            "url": url,
            "error_code": None,
            "error_message": None,
        }


_service: ContentFetchService | None = None


def get_content_fetch_service() -> ContentFetchService:
    global _service
    if _service is None:
        _service = ContentFetchService()
    return _service
