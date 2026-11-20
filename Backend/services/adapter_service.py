"""Source adapter configuration and dry-run (Phase 7.6)."""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlsplit

import database
from collectors.html_list_collector import AdapterFetchResult, HtmlListCollector
from collectors.net_guard import NetGuard, NetPolicy
from core.timeutil import utc_timestamp
from database.repositories import adapter_repository as repo
from database.repositories import source_repository as source_repo
from database.repositories.models import SourceAdapterRecord

from .errors import conflict, not_found, unsupported, validation

ADAPTER_TYPES = {"html_list"}
SOURCE_TYPES = {"website", "official_announcement", "api"}
CONFIG_VERSION = "html-list-v1"
MAX_LIST_URLS = 10


def _validate_url(raw: object, field: str) -> str:
    value = str(raw or "").strip()
    if not value or len(value) > 2048:
        raise validation(field, "range", "URL 长度必须在 1–2048 之间")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise validation(field, "format", "必须是 http(s) URL")
    return value


def _clean_config(payload: dict[str, object]) -> dict[str, object]:
    adapter_type = str(payload.get("adapter_type") or "html_list")
    if adapter_type not in ADAPTER_TYPES:
        raise unsupported("adapter_not_supported", "当前仅支持 html_list 适配器")

    raw_urls = payload.get("list_urls")
    if not isinstance(raw_urls, list) or not raw_urls:
        raise validation("list_urls", "required", "至少提供一个列表页 URL")
    if len(raw_urls) > MAX_LIST_URLS:
        raise validation("list_urls", "range", "列表页最多 10 个")
    list_urls = [_validate_url(item, "list_urls") for item in raw_urls]

    pattern = str(payload.get("link_pattern") or "").strip()
    if not pattern or len(pattern) > 500:
        raise validation("link_pattern", "range", "链接正则长度必须在 1–500 之间")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise validation("link_pattern", "format", f"正则无效：{exc}") from exc

    max_pages = int(payload.get("max_pages") or 1)
    if not 1 <= max_pages <= 3:
        raise validation("max_pages", "range", "max_pages 必须在 1–3 之间")
    rate = int(payload.get("rate_limit_seconds") or 5)
    if not 1 <= rate <= 60:
        raise validation("rate_limit_seconds", "range", "限流间隔必须在 1–60 秒")
    max_entries = int(payload.get("max_entries_per_run") or 12)
    if not 1 <= max_entries <= 50:
        raise validation("max_entries_per_run", "range", "单次上限必须在 1–50")
    fetch_full_text = bool(payload.get("fetch_full_text"))

    return {
        "adapter_type": adapter_type,
        "entry_url": list_urls[0],
        "list_urls": list_urls,
        "link_pattern": pattern,
        "max_pages": max_pages,
        "rate_limit_seconds": rate,
        "max_entries_per_run": max_entries,
        "fetch_full_text": fetch_full_text,
    }


def _record_payload(record: SourceAdapterRecord) -> dict[str, object]:
    config = json.loads(record.config_json or "{}")
    return {
        "source_id": record.source_id,
        "adapter_type": record.adapter_type,
        "entry_url": record.entry_url,
        "list_urls": config.get("list_urls") or [record.entry_url],
        "link_pattern": config.get("link_pattern"),
        "max_pages": config.get("max_pages", 1),
        "rate_limit_seconds": record.rate_limit_seconds,
        "max_entries_per_run": record.max_entries_per_run,
        "fetch_full_text": record.fetch_full_text,
        "config_version": record.config_version,
        "last_verified_at": record.last_verified_at,
        "last_verification": record.last_verification,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class AdapterService:
    def __init__(self, *, guard: NetGuard | None = None) -> None:
        self.guard = guard or NetGuard(NetPolicy())

    def get(self, source_id: str) -> dict[str, object]:
        with database.read_session() as conn:
            record = repo.get(conn, source_id)
        if record is None:
            raise not_found("adapter_not_found", "该信息源尚未配置适配器")
        return _record_payload(record)

    def upsert(self, source_id: str, payload: dict[str, object]) -> dict[str, object]:
        cleaned = _clean_config(payload)
        now = utc_timestamp()
        with database.session() as conn:
            source = source_repo.get_active(conn, source_id)
            if source is None:
                raise not_found("source_not_found", "信息源不存在")
            if source.source_type in ("rss", "atom"):
                raise conflict(
                    "adapter_not_applicable", "RSS/Atom 信息源不需要网页适配器"
                )
            if source.source_type not in SOURCE_TYPES:
                raise unsupported(
                    "adapter_not_supported", "该来源类型不支持网页适配器"
                )
            existing = repo.get(conn, source_id)
            repo.upsert(
                conn,
                {
                    "source_id": source_id,
                    "adapter_type": cleaned["adapter_type"],
                    "entry_url": cleaned["entry_url"],
                    "config_json": json.dumps(
                        {
                            "list_urls": cleaned["list_urls"],
                            "link_pattern": cleaned["link_pattern"],
                            "max_pages": cleaned["max_pages"],
                        },
                        ensure_ascii=False,
                    ),
                    "config_version": CONFIG_VERSION,
                    "rate_limit_seconds": cleaned["rate_limit_seconds"],
                    "max_entries_per_run": cleaned["max_entries_per_run"],
                    "fetch_full_text": 1 if cleaned["fetch_full_text"] else 0,
                    "last_verified_at": existing.last_verified_at if existing else None,
                    "last_verification": existing.last_verification if existing else "unknown",
                    "last_sample_json": existing.last_sample_json if existing else None,
                    "created_at": existing.created_at if existing else now,
                    "updated_at": now,
                },
            )
            record = repo.get(conn, source_id)
        assert record is not None
        return _record_payload(record)

    def delete(self, source_id: str) -> None:
        with database.session() as conn:
            if repo.get(conn, source_id) is None:
                raise not_found("adapter_not_found", "该信息源尚未配置适配器")
            repo.delete(conn, source_id)

    def dry_run(self, source_id: str, *, limit: int = 3) -> dict[str, object]:
        if not 1 <= limit <= 10:
            raise validation("limit", "range", "dry-run 条数必须在 1–10 之间")
        with database.read_session() as conn:
            record = repo.get(conn, source_id)
        if record is None:
            raise not_found("adapter_not_found", "该信息源尚未配置适配器")
        config = json.loads(record.config_json or "{}")
        started = time.monotonic()
        result: AdapterFetchResult = HtmlListCollector(self.guard).collect(
            list_urls=[str(item) for item in config.get("list_urls") or []],
            link_pattern=str(config.get("link_pattern") or ""),
            max_entries=limit,
            rate_limit_seconds=record.rate_limit_seconds,
            fetch_full_text=record.fetch_full_text,
            max_pages=int(config.get("max_pages") or 1),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if len(result.entries) >= min(3, limit):
            suggestion = "verified"
        elif result.entries:
            suggestion = "needs_review"
        elif any("robots" in item or "http_client_error" in item for item in result.errors):
            suggestion = "blocked"
        else:
            suggestion = "selector_drift"
        return {
            "source_id": source_id,
            "adapter_type": record.adapter_type,
            "http_status": result.http_status,
            "duration_ms": duration_ms,
            "suggestion": suggestion,
            "entries": [
                {
                    "title": entry.title,
                    "link": entry.link,
                    "published_at": entry.published_at,
                    "summary_chars": len(entry.summary or ""),
                    "content_chars": len(entry.content or ""),
                    "content_state": entry.content_state,
                }
                for entry in result.entries
            ],
            "errors": list(result.errors),
        }


_service: AdapterService | None = None


def get_adapter_service() -> AdapterService:
    global _service
    if _service is None:
        _service = AdapterService()
    return _service
