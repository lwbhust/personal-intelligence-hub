"""Single-line JSON logging to stderr.

Contract: `Docs/API_CONTRACT.md` §10.
- stdout carries the handshake line only; every log line goes to stderr.
- Every line is one JSON object with `ts`, `level`, `event`, `request_id`.
- Tokens, Authorization headers, request bodies and absolute paths are never
  logged. Sensitive-looking field names are dropped defensively.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from core.timeutil import utc_timestamp

_SENSITIVE_FRAGMENTS = ("token", "authorization", "secret", "password", "cookie")

_LEVEL_NAMES = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _emit(payload: dict[str, Any]) -> None:
    """Write one compact JSON line to stderr, flushing immediately."""

    line = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    stream = sys.stderr
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(line.encode("utf-8"))
        buffer.flush()
        return
    stream.write(line)
    stream.flush()


def log_event(event: str, *, level: str = "info", request_id: str = "-", **fields: Any) -> None:
    """Emit a structured event. Field names containing secrets are dropped."""

    payload: dict[str, Any] = {
        "ts": utc_timestamp(),
        "level": level,
        "event": event,
        "request_id": request_id or "-",
    }
    for key, value in fields.items():
        if key in payload or _is_sensitive(key):
            continue
        payload[key] = _json_safe(value)

    try:
        _emit(payload)
    except Exception:  # noqa: BLE001 - logging must never break requests
        pass


class _LibraryFormatter(logging.Formatter):
    """Project third-party (uvicorn) log records into the same JSON shape."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": utc_timestamp(),
            "level": _LEVEL_NAMES.get(record.levelno, "info"),
            "event": "library_log",
            "request_id": "-",
            "logger": record.name,
        }
        try:
            payload["message"] = record.getMessage()
        except Exception:  # noqa: BLE001
            payload["message"] = "<unformattable>"
        if record.exc_info and record.exc_info[1] is not None:
            payload["exc_type"] = type(record.exc_info[1]).__name__
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Route the root logger to stderr with JSON lines (idempotent)."""

    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED:
        root.setLevel(level)
        return

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_LibraryFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True
