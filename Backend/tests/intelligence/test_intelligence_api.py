"""Phase 7.1 `/api/v1/intelligence` integration tests against a real Sidecar."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BACKEND_TESTS = Path(__file__).resolve().parent.parent / "backend"
for path in (str(BACKEND_ROOT), str(BACKEND_TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from support import Sidecar, http, start_sidecar  # noqa: E402


@pytest.fixture()
def sidecar(tmp_path: Path) -> Sidecar:
    instance = start_sidecar(tmp_path, env_overrides={"PIH_AI_ENABLED": "0"})
    yield instance
    if instance.proc.poll() is None:
        instance.proc.kill()
        instance.proc.wait(timeout=5)


def _poll_report(sc: Sidecar, report_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = http(sc, f"/api/v1/intelligence/reports/{report_id}", token=sc.token)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["report"]["status"] in {"succeeded", "degraded", "failed", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError("report did not finish in time")


def test_intelligence_requires_token(sidecar):
    response = http(sidecar, "/api/v1/intelligence/status")
    assert response.status_code == 401


def test_status_reports_star_versions_and_ai_availability(sidecar):
    response = http(sidecar, "/api/v1/intelligence/status", token=sidecar.token)
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_version"] == "intelligence-report-v1"
    assert body["stats_version"] == "intelligence-stats-v1"
    assert body["queue_depth"] == 0
    assert body["running_report_id"] is None


def test_generate_degrade_and_dedupe(sidecar):
    response = http(
        sidecar,
        "/api/v1/intelligence/reports/generate",
        method="POST",
        token=sidecar.token,
        json_body={"report_type": "daily", "force": False},
    )
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["reused"] is False
    report_id = created["report"]["id"]

    body = _poll_report(sidecar, report_id)
    report = body["report"]
    # AI is disabled in this fixture: the report must degrade, not fabricate.
    assert report["status"] == "degraded"
    assert report["ai_status"] == "unavailable"
    assert report["content"]["key_events"] == []
    assert report["stats_version"] == "intelligence-stats-v1"
    assert report["period_start"] == report["period_end"]
    assert body["citations"] == []

    again = http(
        sidecar,
        "/api/v1/intelligence/reports/generate",
        method="POST",
        token=sidecar.token,
        json_body={"report_type": "daily", "force": False},
    )
    assert again.status_code == 202
    repeated = again.json()
    assert repeated["reused"] is True
    assert repeated["report"]["id"] == report_id

    history = http(
        sidecar, "/api/v1/intelligence/reports", token=sidecar.token,
        params={"report_type": "daily"},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1


def test_cancel_finished_report_is_conflict(sidecar):
    response = http(
        sidecar,
        "/api/v1/intelligence/reports/generate",
        method="POST",
        token=sidecar.token,
        json_body={"report_type": "weekly"},
    )
    report_id = response.json()["report"]["id"]
    _poll_report(sidecar, report_id)
    cancel = http(
        sidecar,
        f"/api/v1/intelligence/reports/{report_id}/cancel",
        method="POST",
        token=sidecar.token,
    )
    assert cancel.status_code == 409
    assert cancel.json()["error"]["code"] == "report_not_cancellable"


def test_emerging_and_rankings_are_real_and_empty_safe(sidecar):
    emerging = http(sidecar, "/api/v1/intelligence/emerging", token=sidecar.token)
    assert emerging.status_code == 200
    body = emerging.json()
    assert body["window_days"] == 7
    assert body["totals"]["articles"] == 0
    assert body["rising_keywords"] == []

    rankings = http(
        sidecar, "/api/v1/intelligence/rankings", token=sidecar.token,
        params={"kind": "new", "window": "7d"},
    )
    assert rankings.status_code == 200
    assert rankings.json()["items"] == []


def test_unknown_report_type_is_rejected(sidecar):
    response = http(
        sidecar,
        "/api/v1/intelligence/reports/generate",
        method="POST",
        token=sidecar.token,
        json_body={"report_type": "hourly"},
    )
    assert response.status_code == 422
