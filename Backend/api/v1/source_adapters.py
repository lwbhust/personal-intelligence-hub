"""`/api/v1/sources/{id}/adapter` — official web adapter configuration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from services.adapter_service import AdapterService

from .models import (
    AdapterConfigRequest,
    AdapterConfigResponse,
    AdapterDryRunResponse,
)

router = APIRouter(prefix="/api/v1/sources", tags=["source-adapters"])
_service = AdapterService()


@router.get("/{source_id}/adapter", response_model=AdapterConfigResponse)
def get_adapter(source_id: uuid.UUID) -> AdapterConfigResponse:
    return AdapterConfigResponse.model_validate(_service.get(str(source_id)))


@router.put("/{source_id}/adapter", response_model=AdapterConfigResponse)
def upsert_adapter(
    source_id: uuid.UUID, payload: AdapterConfigRequest
) -> AdapterConfigResponse:
    result = _service.upsert(str(source_id), payload.model_dump())
    return AdapterConfigResponse.model_validate(result)


@router.delete("/{source_id}/adapter", status_code=204)
def delete_adapter(source_id: uuid.UUID) -> Response:
    _service.delete(str(source_id))
    return Response(status_code=204)


@router.post("/{source_id}/adapter/dry-run", response_model=AdapterDryRunResponse)
def dry_run_adapter(
    source_id: uuid.UUID,
    limit: int = Query(default=3, ge=1, le=10),
) -> AdapterDryRunResponse:
    return AdapterDryRunResponse.model_validate(
        _service.dry_run(str(source_id), limit=limit)
    )
