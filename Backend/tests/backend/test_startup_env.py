"""Startup configuration failures: exit code 2, `startup_failed`, no handshake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support import REPO_ROOT, base_env, make_token, run_entry

REQUIRED_LOG_FIELDS = ("ts", "level", "event", "request_id")

CASES = [
    "missing_token",
    "empty_token",
    "short_token",
    "long_token",
    "non_base64url_token",
    "port_text",
    "port_too_large",
    "port_negative",
    "port_empty",
    "data_dir_relative",
    "data_dir_source_tree",
    "data_dir_app_bundle",
]


def _overrides_for(case: str, token: str) -> dict[str, str | None]:
    if case == "missing_token":
        return {"PIH_SIDECAR_TOKEN": None}
    if case == "empty_token":
        return {"PIH_SIDECAR_TOKEN": ""}
    if case == "short_token":
        return {"PIH_SIDECAR_TOKEN": token[:42]}
    if case == "long_token":
        return {"PIH_SIDECAR_TOKEN": token + "A"}
    if case == "non_base64url_token":
        return {"PIH_SIDECAR_TOKEN": token[:42] + "!"}
    if case == "port_text":
        return {"PIH_PORT": "abc"}
    if case == "port_too_large":
        return {"PIH_PORT": "65536"}
    if case == "port_negative":
        return {"PIH_PORT": "-1"}
    if case == "port_empty":
        return {"PIH_PORT": ""}
    if case == "data_dir_relative":
        return {"PIH_DATA_DIR": "relative/data"}
    if case == "data_dir_source_tree":
        return {"PIH_DATA_DIR": str(REPO_ROOT)}
    if case == "data_dir_app_bundle":
        return {"PIH_DATA_DIR": str(Path("/tmp") / "Fake.app" / "data")}
    raise AssertionError(case)


@pytest.mark.parametrize("case", CASES)
def test_invalid_environment_exits_2_without_handshake(tmp_path: Path, case: str) -> None:
    token = make_token()
    env = base_env(token, data_dir=tmp_path / "data")
    env["HOME"] = str(tmp_path / "home")
    for key, value in _overrides_for(case, token).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    result = run_entry(env)

    assert result.returncode == 2, result.stderr
    assert result.stdout == ""

    entries = [json.loads(line) for line in result.stderr.splitlines() if line.strip()]
    failed = [entry for entry in entries if entry.get("event") == "startup_failed"]
    assert failed, result.stderr
    for entry in entries:
        for field in REQUIRED_LOG_FIELDS:
            assert field in entry, entry
    assert failed[0]["level"] == "error"
    assert failed[0]["request_id"] == "-"

    # The token (valid or malformed) must never be echoed.
    assert token not in result.stderr
    assert token not in result.stdout


def test_valid_token_required_even_without_optional_env(tmp_path: Path) -> None:
    env = base_env(None, data_dir=tmp_path / "data")
    env["HOME"] = str(tmp_path / "home")
    result = run_entry(env)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid_token" in result.stderr
