"""Helpers for real-process Sidecar integration tests.

Every helper starts `Backend/main.py` as a real child process and talks HTTP
over 127.0.0.1. No mocks, no in-process ASGI shortcuts.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
ENTRY = BACKEND_DIR / "main.py"
PYTHON = sys.executable

HANDSHAKE_PREFIX = "PIH_SIDECAR_READY"
UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@dataclass
class Sidecar:
    proc: subprocess.Popen
    token: str
    port: int
    handshake: dict
    stdout_path: Path
    stderr_path: Path
    data_dir: Path

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stdout_text(self) -> str:
        return _read_text(self.stdout_path)

    def stderr_text(self) -> str:
        return _read_text(self.stderr_path)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def make_token() -> str:
    """43-char base64url token with 256 bits of entropy (contract §5.1)."""

    return secrets.token_urlsafe(32)


def base_env(token: str | None, *, port: str = "0", data_dir: Path | None = None) -> dict[str, str]:
    """Minimal, isolated environment: no inherited PIH_* or proxy settings."""

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "PYTHONUNBUFFERED": "1",
        "PIH_PORT": port,
        # Deterministic tests: the scheduler must not fetch public feeds.
        "PIH_SCHEDULER_ENABLED": "0",
    }
    if token is not None:
        env["PIH_SIDECAR_TOKEN"] = token
    if data_dir is not None:
        env["PIH_DATA_DIR"] = str(data_dir)
    return env


def parse_handshake(line: str) -> dict:
    prefix, separator, payload = line.partition(" ")
    assert prefix == HANDSHAKE_PREFIX, f"bad handshake prefix: {line!r}"
    assert separator == " ", f"missing handshake separator: {line!r}"
    data = json.loads(payload)
    assert isinstance(data, dict), f"handshake payload must be an object: {payload!r}"
    return data


def _wait_for_first_line(sc: Sidecar, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = sc.stdout_text()
        if "\n" in text:
            return text.split("\n", 1)[0]
        if sc.proc.poll() is not None:
            raise AssertionError(
                "sidecar exited before handshake: "
                f"code={sc.proc.returncode} stdout={text!r} stderr={sc.stderr_text()!r}"
            )
        time.sleep(0.02)
    raise AssertionError(
        f"handshake not received within {timeout}s: stderr={sc.stderr_text()!r}"
    )


def start_sidecar(
    tmp_path: Path,
    *,
    token: str | None = None,
    data_dir: Path | None = None,
    port: str = "0",
    env_overrides: dict[str, str | None] | None = None,
    wait: bool = True,
    timeout: float = 10.0,
) -> Sidecar:
    """Spawn a real Sidecar; `PIH_DATA_DIR` defaults inside `tmp_path`."""

    tmp_path = Path(tmp_path)
    token = make_token() if token is None else token
    data = Path(data_dir) if data_dir is not None else tmp_path / "data"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / f"run-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    env = base_env(token, port=port, data_dir=data)
    # Never let a stray default path reach the real Application Support dir.
    env["HOME"] = str(home)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    stdout_file = stdout_path.open("wb")
    stderr_file = stderr_path.open("wb")
    try:
        proc = subprocess.Popen(
            [PYTHON, str(ENTRY)],
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
        )
    finally:
        stdout_file.close()
        stderr_file.close()

    sidecar = Sidecar(
        proc=proc,
        token=token,
        port=0,
        handshake={},
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        data_dir=data,
    )
    if not wait:
        return sidecar

    try:
        line = _wait_for_first_line(sidecar, timeout)
        handshake = parse_handshake(line)
        sidecar.handshake = handshake
        sidecar.port = int(handshake["port"])
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        raise
    return sidecar


def run_entry(env: dict[str, str], *, timeout: float = 15.0) -> subprocess.CompletedProcess:
    """Run the entry point to completion (used for invalid-environment tests)."""

    return subprocess.run(
        [PYTHON, str(ENTRY)],
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def stop_sidecar(sidecar: Sidecar, *, timeout: float = 5.0) -> int | None:
    """SIGTERM then wait; SIGKILL only after the timeout (never silently)."""

    proc = sidecar.proc
    if proc.poll() is not None:
        return proc.returncode
    proc.send_signal(signal.SIGTERM)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError(f"sidecar did not exit within {timeout}s after SIGTERM")


def http(
    sidecar: Sidecar,
    path: str = "/health",
    *,
    method: str = "GET",
    token: str | None = None,
    raw_authorization: str | None = None,
    headers: dict[str, str] | None = None,
    json_body: object | None = None,
    params: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float = 2.0,
) -> httpx.Response:
    request_headers = dict(headers or {})
    if raw_authorization is not None:
        request_headers["Authorization"] = raw_authorization
    elif token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(trust_env=False, timeout=timeout) as client:
        return client.request(
            method,
            sidecar.base_url + path,
            headers=request_headers,
            json=json_body,
            params=params,
            content=content,
        )


def assert_json_headers(response: httpx.Response) -> None:
    assert response.headers.get("content-type") == "application/json; charset=utf-8"
    assert response.headers.get("cache-control") == "no-store"
    assert UUID4_RE.fullmatch(response.headers.get("x-request-id", "")), response.headers


def stderr_lines(sidecar: Sidecar) -> list[str]:
    return [line for line in sidecar.stderr_text().splitlines() if line.strip()]


def stderr_events(sidecar: Sidecar) -> list[dict]:
    return [json.loads(line) for line in stderr_lines(sidecar)]


def wait_for_event(
    sidecar: Sidecar,
    event: str,
    *,
    request_id: str | None = None,
    timeout: float = 3.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        for entry in stderr_events(sidecar):
            if entry.get("event") != event:
                continue
            if request_id is not None and entry.get("request_id") != request_id:
                continue
            last = entry
        if last is not None:
            return last
        time.sleep(0.02)
    raise AssertionError(
        f"event {event!r} (request_id={request_id!r}) not logged; stderr={sidecar.stderr_text()!r}"
    )
