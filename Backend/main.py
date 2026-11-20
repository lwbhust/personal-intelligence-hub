"""PIH Sidecar entry point (Phase 0).

Startup order follows `Docs/API_CONTRACT.md` §2.4 exactly:
validate env -> initialize database (failure never blocks startup) -> bind
127.0.0.1:PIH_PORT -> ASGI startup -> one-line handshake on stdout.

stdout carries the handshake only; every log line goes to stderr as JSON.
Designed to be started by the macOS App, which owns the process lifecycle.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import time

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import uvicorn  # noqa: E402

import database  # noqa: E402
from api.app import create_app  # noqa: E402
from core.config import ConfigError, load_config  # noqa: E402
from core.logging import configure_logging, log_event  # noqa: E402
from core.version import SERVICE_NAME, VERSION  # noqa: E402

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_BIND_FAILED = 3
EXIT_FATAL = 4

HANDSHAKE_PREFIX = "PIH_SIDECAR_READY"
HANDSHAKE_MAX_BYTES = 4096

SIGTERM_GRACE_SECONDS = 3.0
PARENT_CHECK_INTERVAL_SECONDS = 2.0
PARENT_GRACE_SECONDS = 1.0

_server: "SidecarServer | None" = None
_stop_logged = False
_force_exit_started = False
_lifecycle_lock = threading.Lock()


# --------------------------------------------------------------------------
# stdout handshake
# --------------------------------------------------------------------------


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _write_handshake(port: int) -> None:
    """Write the single allowed stdout line and flush it immediately."""

    payload = {
        "port": int(port),
        "pid": os.getpid(),
        "service": SERVICE_NAME,
        "version": VERSION,
    }
    line = HANDSHAKE_PREFIX + " " + json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
    data = line.encode("utf-8")
    if len(data) > HANDSHAKE_MAX_BYTES:
        raise RuntimeError("handshake line exceeds protocol limit")
    # os.write is unbuffered: no flush can be forgotten.
    _write_all(1, data)


# --------------------------------------------------------------------------
# lifecycle helpers
# --------------------------------------------------------------------------


def _signal_reason(signum: int) -> str:
    try:
        return signal.Signals(signum).name.lower()
    except ValueError:  # pragma: no cover - defensive
        return f"signal_{signum}"


def _log_stopping(reason: str) -> None:
    global _stop_logged
    with _lifecycle_lock:
        if _stop_logged:
            return
        _stop_logged = True
    log_event("sidecar_stopping", reason=reason, pid=os.getpid())


def _schedule_force_exit(grace_seconds: float) -> None:
    """Hard upper bound for graceful shutdown (contract §8.1/§9.1)."""

    global _force_exit_started
    with _lifecycle_lock:
        if _force_exit_started:
            return
        _force_exit_started = True

    def _force() -> None:
        time.sleep(max(0.0, grace_seconds))
        os._exit(EXIT_OK)

    threading.Thread(target=_force, name="pih-force-exit", daemon=True).start()


def _stop_server(reason: str, grace_seconds: float) -> None:
    _log_stopping(reason)
    server = _server
    if server is not None:
        server.should_exit = True
    _schedule_force_exit(grace_seconds)


def _handle_signal(signum: int, frame: object) -> None:
    # During `serve()` uvicorn installs its own handler, so this runs only
    # before startup or when uvicorn re-raises the captured signal on exit
    # (which must not kill the process: contract requires exit code 0).
    _stop_server(_signal_reason(signum), SIGTERM_GRACE_SECONDS)


def _install_signal_handlers() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handle_signal)


def _start_parent_watchdog(parent_pid: int) -> None:
    """Exit gracefully when the App (parent) disappears (contract §9.2)."""

    def watch() -> None:
        # If the parent already vanished before this thread started, getppid()
        # is 1 (launchd) and the comparison below would never fire: exit now.
        if parent_pid <= 1:
            log_event("parent_lost", level="warn", pid=os.getpid())
            _stop_server("parent_lost", PARENT_GRACE_SECONDS)
            return
        while True:
            time.sleep(PARENT_CHECK_INTERVAL_SECONDS)
            if os.getppid() != parent_pid or os.getppid() == 1:
                log_event("parent_lost", level="warn", pid=os.getpid())
                _stop_server("parent_lost", PARENT_GRACE_SECONDS)
                return

    threading.Thread(target=watch, name="pih-parent-watchdog", daemon=True).start()


# --------------------------------------------------------------------------
# socket + server
# --------------------------------------------------------------------------


def _bind_loopback(port: int) -> socket.socket:
    """Bind (do not listen) 127.0.0.1:port so the real port is race-free."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        raise
    return sock


class SidecarServer(uvicorn.Server):
    """uvicorn server that emits the handshake after ASGI startup completes."""

    def __init__(self, config: uvicorn.Config, port: int) -> None:
        super().__init__(config)
        self._pih_port = port
        self._handshake_written = False

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if not self.started or self._handshake_written:
            return
        self._handshake_written = True
        _write_handshake(self._pih_port)
        log_event("sidecar_ready", pid=os.getpid(), port=self._pih_port)

    def handle_exit(self, sig: int, frame: object) -> None:
        _log_stopping(_signal_reason(sig))
        super().handle_exit(sig, frame)  # type: ignore[arg-type]
        _schedule_force_exit(SIGTERM_GRACE_SECONDS)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    global _server

    # Baseline §2.3: private files only for this user.
    os.umask(0o077)

    configure_logging()
    # Keep stdout reserved for the handshake; stray library prints go to stderr.
    sys.stdout = sys.stderr

    log_event("sidecar_starting", pid=os.getpid())

    try:
        config = load_config()
    except ConfigError as exc:
        log_event("startup_failed", level="error", error_code=exc.code)
        return EXIT_CONFIG_ERROR

    # Contract §2.3: drop the token from the environment once captured.
    os.environ.pop("PIH_SIDECAR_TOKEN", None)

    _install_signal_handlers()
    _start_parent_watchdog(os.getppid())

    db_status = database.initialize()
    if db_status.status == "ok":
        log_event(
            "database_ready",
            schema_version=db_status.schema_version,
            path_kind=db_status.path_kind,
        )
    else:
        log_event(
            "database_error",
            level="error",
            error_code=db_status.code,
            path_kind=db_status.path_kind,
        )

    try:
        sock = _bind_loopback(config.port)
    except OSError as exc:
        log_event(
            "startup_failed",
            level="error",
            error_code="port_bind_failed",
            exc_type=type(exc).__name__,
        )
        return EXIT_BIND_FAILED

    port = int(sock.getsockname()[1])
    app = create_app(config.token)
    uvicorn_config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
        lifespan="on",
        timeout_graceful_shutdown=int(SIGTERM_GRACE_SECONDS),
        server_header=False,
        date_header=False,
    )
    server = SidecarServer(uvicorn_config, port)
    _server = server

    try:
        server.run(sockets=[sock])
    except SystemExit as exc:  # uvicorn lifespan/startup failure
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        log_event(
            "startup_failed",
            level="error",
            error_code="server_startup_failed",
            exit_code=code,
        )
        return code or EXIT_FATAL
    except Exception as exc:  # noqa: BLE001 - report, never hide
        log_event(
            "startup_failed",
            level="error",
            error_code="server_fatal",
            exc_type=type(exc).__name__,
        )
        return EXIT_FATAL
    finally:
        try:
            sock.close()
        except OSError:
            pass

    # The data layer opens one short-lived connection per operation
    # (DATABASE_BASELINE.md §3.1), so there is no long-lived handle to close.
    _log_stopping("shutdown")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
