"""`GET /health` contract tests against a real Sidecar process."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from support import (
    Sidecar,
    assert_json_headers,
    http,
    start_sidecar,
    stop_sidecar,
    wait_for_event,
)


def _parse_rfc3339_utc(value: str) -> datetime:
    assert value.endswith("Z"), value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_health_ok_reports_real_database(sidecar: Sidecar) -> None:
    response = http(sidecar, token=sidecar.token)

    assert response.status_code == 200
    assert_json_headers(response)

    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "pih-backend"
    assert body["version"] == "0.14.0"
    assert _parse_rfc3339_utc(body["timestamp"]).tzinfo is not None
    assert isinstance(body["uptime_seconds"], (int, float))
    assert body["uptime_seconds"] >= 0

    assert body["database"] == {
        "status": "ok",
        "schema_version": 14,
        "path_kind": "custom",
    }
    assert "code" not in body["database"]

    # No sensitive material in the body (contract §6.5).
    assert sidecar.token not in response.text
    assert str(sidecar.data_dir) not in response.text
    assert str(Path.home()) not in response.text
    for forbidden in ("pid", "host", "hostname"):
        assert forbidden not in body


def test_request_id_is_server_generated(sidecar: Sidecar) -> None:
    response = http(
        sidecar,
        token=sidecar.token,
        headers={"X-Request-ID": "client-supplied-value"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "client-supplied-value"
    assert_json_headers(response)


def test_health_log_path_excludes_query_string(sidecar: Sidecar) -> None:
    response = http(sidecar, path="/health?q=sensitive-search-term", token=sidecar.token)
    assert response.status_code == 200

    request_id = response.headers["x-request-id"]
    event = wait_for_event(sidecar, "request_completed", request_id=request_id)

    assert event["method"] == "GET"
    assert event["path"] == "/health"
    assert event["status_code"] == 200
    assert isinstance(event["duration_ms"], (int, float))
    assert "sensitive-search-term" not in sidecar.stderr_text()


def test_health_degraded_when_data_dir_unwritable(tmp_path: Path) -> None:
    data_dir = tmp_path / "locked-data"
    data_dir.mkdir()
    data_dir.chmod(0o500)

    sidecar = start_sidecar(tmp_path, data_dir=data_dir)
    try:
        response = http(sidecar, token=sidecar.token)

        assert response.status_code == 200
        assert_json_headers(response)

        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"]["status"] == "error"
        assert body["database"]["code"] in {
            "database_unavailable",
            "database_locked",
            "database_migration_failed",
            "database_schema_error",
        }
        assert body["database"]["schema_version"] is None
        assert body["database"]["path_kind"] == "custom"
        assert str(data_dir) not in response.text
        assert sidecar.token not in response.text
    finally:
        stop_sidecar(sidecar)
        data_dir.chmod(0o700)


@pytest.mark.parametrize("path", ["/health", "/health?debug=1"])
def test_health_uptime_is_monotonic_and_non_negative(sidecar: Sidecar, path: str) -> None:
    first = http(sidecar, path=path, token=sidecar.token).json()
    second = http(sidecar, path=path, token=sidecar.token).json()

    assert second["uptime_seconds"] >= first["uptime_seconds"] >= 0
    assert first["status"] == second["status"] == "ok"
