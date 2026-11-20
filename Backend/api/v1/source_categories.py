"""`/api/v1/source-categories` routes (Phase 1).

Routers only parse/validate transport input, call the service and shape HTTP
responses. No SQL, no transactions and no business rules here.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response

from services.errors import validation
from services.source_category_service import SourceCategoryService

from .models import (
    CategoryCreate,
    CategoryPage,
    CategoryResponse,
    CategoryUpdate,
    category_response,
)

router = APIRouter(prefix="/api/v1/source-categories", tags=["source-categories"])
_service = SourceCategoryService()


@router.get("", response_model=CategoryPage)
def list_categories(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    order: Literal["sort_order", "name"] = "sort_order",
    direction: Literal["asc", "desc"] = "asc",
) -> CategoryPage:
    records, total = _service.list(
        limit=limit, offset=offset, order=order, direction=direction
    )
    return CategoryPage(
        items=[category_response(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/all", response_model=list[CategoryResponse])
def list_all_categories() -> list[CategoryResponse]:
    return [category_response(record) for record in _service.list_all()]


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(category_id: uuid.UUID) -> CategoryResponse:
    return category_response(_service.get(str(category_id)))


@router.post("", status_code=201, response_model=CategoryResponse)
def create_category(payload: CategoryCreate) -> CategoryResponse:
    record = _service.create(
        name=payload.name,
        description=payload.description,
        sort_order=payload.sort_order,
    )
    return category_response(record)


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(category_id: uuid.UUID, payload: CategoryUpdate) -> CategoryResponse:
    fields = {name: getattr(payload, name) for name in payload.model_fields_set}
    if not fields:
        raise validation("request", "empty", "没有可更新的字段")
    if "name" in fields and fields["name"] is None:
        raise validation("name", "null", "不能为空")
    if "sort_order" in fields and fields["sort_order"] is None:
        raise validation("sort_order", "null", "不能为空")
    return category_response(_service.update(str(category_id), fields))


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID) -> Response:
    _service.delete(str(category_id))
    return Response(status_code=204)
