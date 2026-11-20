"""stderr structured logging contract and stdout purity."""

from __future__ import annotations

import json

from support import Sidecar, http, stderr_lines, stop_sidecar, wait_for_event

REQUIRED_FIELDS = ("ts", "level", "event", "request_id")
ALLOWED_LEVELS = {"debug", "info", "warn", "error"}


def test_request_completed_event_matches_response_request_id(sidecar: Sidecar) -> None:
    response = http(sidecar, token=sidecar.token)
    request_id = response.headers["x-request-id"]

    event = wait_for_event(sidecar, "request_completed", request_id=request_id)
    assert event["method"] == "GET"
    assert event["path"] == "/health"
    assert event["status_code"] == 200
    assert event["level"] == "info"
    assert event["ts"].endswith("Z")
    assert isinstance(event["duration_ms"], (int, float))


def test_every_stderr_line_is_single_line_json(sidecar: Sidecar) -> None:
    http(sidecar, token=sidecar.token)
    http(sidecar)  # unauthorized: still logged
    assert stop_sidecar(sidecar, timeout=3.0) == 0

    lines = stderr_lines(sidecar)
    assert lines
    for line in lines:
        assert "\n" not in line
        entry = json.loads(line)
        for field in REQUIRED_FIELDS:
            assert field in entry, entry
        assert entry["level"] in ALLOWED_LEVELS

    events = {json.loads(line)["event"] for line in lines}
    assert {
        "sidecar_starting",
        "database_ready",
        "sidecar_ready",
        "request_completed",
        "sidecar_stopping",
    } <= events

    stderr_text = sidecar.stderr_text()
    assert sidecar.token not in stderr_text
    assert "Authorization" not in stderr_text


def test_stdout_carries_only_the_handshake(sidecar: Sidecar) -> None:
    assert stop_sidecar(sidecar, timeout=3.0) == 0

    stdout_text = sidecar.stdout_text()
    assert len(stdout_text.splitlines()) == 1
    assert stdout_text.startswith("PIH_SIDECAR_READY ")
    assert sidecar.token not in stdout_text
    assert "database_ready" not in stdout_text
    assert "request_completed" not in stdout_text
