"""Source-category business logic: validation, transaction boundary, errors."""

from __future__ import annotations

import sqlite3
import uuid

import database
from core.timeutil import utc_timestamp
from database.repositories import source_category_repository as repo
from database.repositories.models import SourceCategoryRecord

from .errors import conflict, not_found, validation
from .storage import ensure_writable
from .validation import ensure_range, normalize_text

_ORDER = {"sort_order", "name"}


class SourceCategoryService:
    def list(
        self,
        *,
        limit: int,
        offset: int,
        order: str = "sort_order",
        direction: str = "asc",
    ) -> tuple[list[SourceCategoryRecord], int]:
        if order not in _ORDER:
            raise validation("order", "enum", "不支持的排序字段")
        if direction.lower() not in ("asc", "desc"):
            raise validation("direction", "enum", "排序方向只能是 asc 或 desc")
        with database.read_session() as conn:
            return repo.list_categories(
                conn,
                limit=limit,
                offset=offset,
                order=order,
                direction=direction,
            )

    def list_all(self) -> list[SourceCategoryRecord]:
        with database.read_session() as conn:
            return repo.list_active_categories(conn)

    def get(self, category_id: str) -> SourceCategoryRecord:
        with database.read_session() as conn:
            record = repo.get_active(conn, category_id)
        if record is None:
            raise not_found("source_category_not_found", "分类不存在")
        return record

    def create(
        self,
        *,
        name: str,
        description: str | None,
        sort_order: int,
    ) -> SourceCategoryRecord:
        ensure_writable()
        clean_name = normalize_text(
            name, field="name", max_length=40, required=True
        )
        assert clean_name is not None
        clean_description = (
            normalize_text(description, field="description", max_length=200)
            if description is not None
            else None
        )
        ensure_range(sort_order, field="sort_order", minimum=-1000, maximum=1000)

        now = utc_timestamp()
        category_id = str(uuid.uuid4())
        with database.session() as conn:
            if repo.name_exists(conn, clean_name):
                raise conflict(
                    "source_category_name_conflict", "分类名称已存在"
                )
            try:
                repo.insert(
                    conn,
                    category_id=category_id,
                    name=clean_name,
                    description=clean_description,
                    sort_order=sort_order,
                    created_at=now,
                    updated_at=now,
                )
            except sqlite3.IntegrityError as exc:
                if repo.name_exists(conn, clean_name):
                    raise conflict(
                        "source_category_name_conflict", "分类名称已存在"
                    ) from exc
                raise
            record = repo.get_active(conn, category_id)
        if record is None:  # pragma: no cover - insert just succeeded
            raise not_found("source_category_not_found", "分类不存在")
        return record

    def update(self, category_id: str, fields: dict[str, object]) -> SourceCategoryRecord:
        ensure_writable()
        if "name" in fields and fields["name"] is None:
            raise validation("name", "null", "不能为空")
        patch: dict[str, object] = {}
        if "name" in fields:
            clean_name = normalize_text(
                str(fields["name"]), field="name", max_length=40, required=True
            )
            assert clean_name is not None
            patch["name"] = clean_name
        if "description" in fields:
            raw = fields["description"]
            patch["description"] = (
                None
                if raw is None
                else normalize_text(str(raw), field="description", max_length=200)
            )
        if "sort_order" in fields:
            patch["sort_order"] = ensure_range(
                int(fields["sort_order"]), field="sort_order", minimum=-1000, maximum=1000
            )

        with database.session() as conn:
            current = repo.get_active(conn, category_id)
            if current is None:
                raise not_found("source_category_not_found", "分类不存在")
            if "name" in patch and repo.name_exists(
                conn, str(patch["name"]), exclude_id=category_id
            ):
                raise conflict("source_category_name_conflict", "分类名称已存在")
            if patch:
                patch["updated_at"] = utc_timestamp()
                try:
                    repo.update(conn, category_id, patch)
                except sqlite3.IntegrityError as exc:
                    if repo.name_exists(
                        conn, str(patch.get("name", "")), exclude_id=category_id
                    ):
                        raise conflict(
                            "source_category_name_conflict", "分类名称已存在"
                        ) from exc
                    raise
            record = repo.get_active(conn, category_id)
        if record is None:  # pragma: no cover
            raise not_found("source_category_not_found", "分类不存在")
        return record

    def delete(self, category_id: str) -> None:
        ensure_writable()
        now = utc_timestamp()
        with database.session() as conn:
            current = repo.get_active(conn, category_id)
            if current is None:
                raise not_found("source_category_not_found", "分类不存在")
            if repo.count_active_sources(conn, category_id) > 0:
                raise conflict(
                    "source_category_in_use", "该分类仍被信息源引用"
                )
            repo.clear_category_on_sources(conn, category_id, now)
            repo.soft_delete(conn, category_id, now)
