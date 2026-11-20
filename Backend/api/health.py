"""`GET /health` — real Sidecar + database status.

Contract: `Docs/API_CONTRACT.md` §6. The database probe is the lightweight
`database.health_check()`; a database failure yields HTTP 200 + `degraded`,
never 503/500. No token, absolute path, PID or hostname is returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import database
from core.timeutil import uptime_seconds, utc_timestamp
from core.version import BUILD_COMMIT, BUILD_TIME, SERVICE_NAME, VERSION

router = APIRouter()


@router.get("/health")
def get_health(request: Request) -> JSONResponse:
    db_status = database.health_check()
    overall = "ok" if db_status.status == "ok" else "degraded"

    database_payload: dict[str, object] = {
        "status": db_status.status,
        "schema_version": db_status.schema_version,
        "path_kind": db_status.path_kind,
    }
    if db_status.status != "ok":
        database_payload["code"] = db_status.code or "database_unavailable"

    payload = {
        "status": overall,
        "service": SERVICE_NAME,
        "version": VERSION,
        "timestamp": utc_timestamp(),
        "uptime_seconds": round(uptime_seconds(), 3),
        "database": database_payload,
        "build": {
            "git_commit": BUILD_COMMIT,
            "build_time": BUILD_TIME,
        },
    }
    return JSONResponse(payload)
