"""Handshake, binding, token secrecy and graceful shutdown (real processes)."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

from support import (
    Sidecar,
    http,
    make_token,
    parse_handshake,
    run_entry,
    start_sidecar,
    stderr_events,
    stop_sidecar,
)
import support


def test_handshake_is_single_valid_line(sidecar: Sidecar) -> None:
    text = sidecar.stdout_text()
    assert text.endswith("\n")
    assert len(text.splitlines()) == 1
    assert len(text.encode("utf-8")) <= 4096
    assert text.startswith("PIH_SIDECAR_READY ")

    data = parse_handshake(text.splitlines()[0])
    assert set(data) == {"port", "pid", "service", "version"}
    assert data["service"] == "pih-backend"
    assert data["version"] == "0.14.0"
    assert data["pid"] == sidecar.proc.pid
    assert isinstance(data["port"], int)
    assert 1 <= data["port"] <= 65535
    assert data["port"] == sidecar.port
    assert sidecar.token not in text


def test_two_instances_use_different_random_ports(tmp_path: Path) -> None:
    first = start_sidecar(tmp_path / "first")
    second = start_sidecar(tmp_path / "second")
    try:
        assert first.port != second.port
        for instance in (first, second):
            response = http(instance, token=instance.token)
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
    finally:
        stop_sidecar(first)
        stop_sidecar(second)


def test_listens_only_on_loopback(sidecar: Sidecar) -> None:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{sidecar.port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert f"127.0.0.1:{sidecar.port}" in output
    assert "0.0.0.0" not in output
    assert f"*:{sidecar.port}" not in output
    assert "::1" not in output


def test_token_is_not_in_argv_logs_or_responses(sidecar: Sidecar) -> None:
    response = http(sidecar, token=sidecar.token)
    assert response.status_code == 200

    ps = subprocess.run(
        ["ps", "-o", "command=", "-p", str(sidecar.proc.pid)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert ps.returncode == 0
    assert sidecar.token not in ps.stdout

    exit_code = stop_sidecar(sidecar, timeout=3.0)
    assert exit_code == 0
    assert sidecar.token not in sidecar.stdout_text()
    assert sidecar.token not in sidecar.stderr_text()
    assert sidecar.token not in response.text


def test_sigterm_exits_zero_and_releases_port(sidecar: Sidecar) -> None:
    port = sidecar.port
    started = time.monotonic()
    exit_code = stop_sidecar(sidecar, timeout=3.0)
    elapsed = time.monotonic() - started

    assert exit_code == 0
    assert elapsed < 3.0

    events = {entry["event"] for entry in stderr_events(sidecar)}
    assert "sidecar_stopping" in events

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_port_bind_failure_exits_3_without_handshake(tmp_path: Path) -> None:
    token = make_token()
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = int(holder.getsockname()[1])
    try:
        env = support.base_env(token, port=str(port), data_dir=tmp_path / "data")
        env["HOME"] = str(tmp_path / "home")
        result = run_entry(env)
    finally:
        holder.close()

    assert result.returncode == 3, result.stderr
    assert result.stdout == ""
    assert "startup_failed" in result.stderr
    assert token not in result.stderr
