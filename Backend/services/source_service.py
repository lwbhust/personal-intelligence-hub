"""Information-source business logic: validation, transaction boundary, errors."""

from __future__ import annotations

import sqlite3
import uuid

import database
from core.timeutil import utc_timestamp
from database.repositories import source_category_repository as category_repo
from database.repositories import source_repository as repo
from database.repositories.models import SourceRecord

from .errors import conflict, not_found, validation
from .storage import ensure_writable
from .validation import (
    SOURCE_TYPES,
    ensure_range,
    normalize_country,
    normalize_language,
    normalize_source_type,
    normalize_text,
    normalize_url,
    optional_credibility,
)

_ORDER = {"priority", "name", "created_at", "updated_at", "last_success_at"}


def _category_exists(conn: sqlite3.Connection, category_id: str) -> bool:
    return category_repo.get_active(conn, category_id) is not None


class SourceService:
    def list(
        self,
        *,
        limit: int,
        offset: int,
        keyword: str | None = None,
        source_type: str | None = None,
        category_id: str | None = None,
        uncategorized: bool = False,
        enabled: bool | None = None,
        language: str | None = None,
        order: str = "priority",
        direction: str = "desc",
    ) -> tuple[list[SourceRecord], int]:
        if order not in _ORDER:
            raise validation("order", "enum", "不支持的排序字段")
        if direction.lower() not in ("asc", "desc"):
            raise validation("direction", "enum", "排序方向只能是 asc 或 desc")
        if uncategorized and category_id is not None:
            raise validation(
                "category_id", "conflict", "不能同时指定 category_id 与 uncategorized"
            )
        normalised_type = None
        if source_type is not None:
            normalised_type = normalize_source_type(source_type)
        clean_keyword = None
        if keyword is not None:
            clean_keyword = normalize_text(keyword, field="q", max_length=100)
        with database.read_session() as conn:
            return repo.list_sources(
                conn,
                limit=limit,
                offset=offset,
                keyword=clean_keyword,
                source_type=normalised_type,
                category_id=category_id,
                uncategorized=uncategorized,
                enabled=enabled,
                language=normalize_language(language) if language else None,
                order=order,
                direction=direction,
            )

    def get(self, source_id: str) -> SourceRecord:
        with database.read_session() as conn:
            record = repo.get_active(conn, source_id)
        if record is None:
            raise not_found("source_not_found", "信息源不存在")
        return record

    def create(
        self,
        *,
        name: str,
        source_type: str,
        url: str,
        homepage_url: str | None = None,
        category_id: str | None = None,
        description: str | None = None,
        language: str | None = None,
        country: str | None = None,
        priority: int = 0,
        credibility_score: int | None = None,
        fetch_interval_minutes: int = 60,
        max_entries_per_fetch: int | None = None,
        enabled: bool = True,
    ) -> SourceRecord:
        ensure_writable()

        clean_name = normalize_text(name, field="name", max_length=120, required=True)
        assert clean_name is not None
        clean_type = normalize_source_type(source_type)
        clean_url = normalize_url(
            url, field="url", allowed_ports=frozenset({80, 443})
        )
        clean_homepage = (
            normalize_url(homepage_url, field="homepage_url")
            if homepage_url is not None
            else None
        )
        clean_description = (
            normalize_text(description, field="description", max_length=500)
            if description is not None
            else None
        )
        clean_language = normalize_language(language)
        clean_country = normalize_country(country)
        ensure_range(priority, field="priority", minimum=0, maximum=100)
        clean_credibility = optional_credibility(credibility_score)
        ensure_range(
            fetch_interval_minutes,
            field="fetch_interval_minutes",
            minimum=5,
            maximum=1440,
        )
        clean_max_entries = None
        if max_entries_per_fetch is not None:
            clean_max_entries = ensure_range(
                int(max_entries_per_fetch),
                field="max_entries_per_fetch",
                minimum=1,
                maximum=100,
            )

        now = utc_timestamp()
        source_id = str(uuid.uuid4())
        with database.session() as conn:
            if category_id is not None and not _category_exists(conn, category_id):
                raise validation("category_id", "not_found", "分类不存在")
            if repo.url_exists(conn, clean_url):
                raise conflict("source_url_conflict", "该 URL 的信息源已存在")
            try:
                repo.insert(
                    conn,
                    {
                        "id": source_id,
                        "category_id": category_id,
                        "name": clean_name,
                        "source_type": clean_type,
                        "url": clean_url,
                        "homepage_url": clean_homepage,
                        "description": clean_description,
                        "language": clean_language,
                        "country": clean_country,
                        "priority": priority,
                        "credibility_score": clean_credibility,
                        "fetch_interval_minutes": fetch_interval_minutes,
                        "max_entries_per_fetch": clean_max_entries,
                        "enabled": 1 if enabled else 0,
                        "health_status": "unknown",
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            except sqlite3.IntegrityError as exc:
                if repo.url_exists(conn, clean_url):
                    raise conflict(
                        "source_url_conflict", "该 URL 的信息源已存在"
                    ) from exc
                raise
            record = repo.get_active(conn, source_id)
        if record is None:  # pragma: no cover - insert just succeeded
            raise not_found("source_not_found", "信息源不存在")
        return record

    def update(self, source_id: str, fields: dict[str, object]) -> SourceRecord:
        ensure_writable()

        for required in (
            "name",
            "source_type",
            "url",
            "priority",
            "fetch_interval_minutes",
            "enabled",
        ):
            if required in fields and fields[required] is None:
                raise validation(required, "null", "不能为空")

        patch: dict[str, object] = {}
        if "name" in fields:
            clean_name = normalize_text(
                str(fields["name"]), field="name", max_length=120, required=True
            )
            assert clean_name is not None
            patch["name"] = clean_name
        if "source_type" in fields:
            patch["source_type"] = normalize_source_type(str(fields["source_type"]))
        if "url" in fields:
            patch["url"] = normalize_url(
                str(fields["url"]), field="url", allowed_ports=frozenset({80, 443})
            )
        if "homepage_url" in fields:
            raw = fields["homepage_url"]
            patch["homepage_url"] = (
                None if raw is None else normalize_url(str(raw), field="homepage_url")
            )
        if "category_id" in fields:
            raw = fields["category_id"]
            patch["category_id"] = None if raw is None else str(raw)
        if "description" in fields:
            raw = fields["description"]
            patch["description"] = (
                None
                if raw is None
                else normalize_text(str(raw), field="description", max_length=500)
            )
        if "language" in fields:
            patch["language"] = normalize_language(
                None if fields["language"] is None else str(fields["language"])
            )
        if "country" in fields:
            patch["country"] = normalize_country(
                None if fields["country"] is None else str(fields["country"])
            )
        if "priority" in fields:
            patch["priority"] = ensure_range(
                int(fields["priority"]), field="priority", minimum=0, maximum=100
            )
        if "credibility_score" in fields:
            raw = fields["credibility_score"]
            patch["credibility_score"] = optional_credibility(
                None if raw is None else int(raw)
            )
        if "fetch_interval_minutes" in fields:
            patch["fetch_interval_minutes"] = ensure_range(
                int(fields["fetch_interval_minutes"]),
                field="fetch_interval_minutes",
                minimum=5,
                maximum=1440,
            )
        if "max_entries_per_fetch" in fields:
            raw = fields["max_entries_per_fetch"]
            patch["max_entries_per_fetch"] = (
                None
                if raw is None
                else ensure_range(
                    int(raw),
                    field="max_entries_per_fetch",
                    minimum=1,
                    maximum=100,
                )
            )
        if "enabled" in fields:
            patch["enabled"] = 1 if bool(fields["enabled"]) else 0

        with database.session() as conn:
            current = repo.get_active(conn, source_id)
            if current is None:
                raise not_found("source_not_found", "信息源不存在")
            # Schema rule: a disabled source may not stay "healthy".
            if patch.get("enabled") == 0 and current.health_status == "healthy":
                patch["health_status"] = "unknown"
            category_id = patch.get("category_id")
            if category_id is not None and not _category_exists(conn, str(category_id)):
                raise validation("category_id", "not_found", "分类不存在")
            new_url = patch.get("url")
            if new_url is not None and repo.url_exists(
                conn, str(new_url), exclude_id=source_id
            ):
                raise conflict("source_url_conflict", "该 URL 的信息源已存在")
            if patch:
                patch["updated_at"] = utc_timestamp()
                try:
                    repo.update(conn, source_id, patch)
                except sqlite3.IntegrityError as exc:
                    if new_url is not None and repo.url_exists(
                        conn, str(new_url), exclude_id=source_id
                    ):
                        raise conflict(
                            "source_url_conflict", "该 URL 的信息源已存在"
                        ) from exc
                    raise
            record = repo.get_active(conn, source_id)
        if record is None:  # pragma: no cover
            raise not_found("source_not_found", "信息源不存在")
        return record

    def delete(self, source_id: str) -> None:
        ensure_writable()
        now = utc_timestamp()
        with database.session() as conn:
            if repo.get_active(conn, source_id) is None:
                raise not_found("source_not_found", "信息源不存在")
            repo.soft_delete(conn, source_id, now)


__all__ = ["SOURCE_TYPES", "SourceService"]
