"""Request middleware: authentication, request IDs, response headers, logs.

Contract: `Docs/API_CONTRACT.md` §5.3, §7.3, §7.4, §10.
- Authentication runs before routing, so unauthenticated requests to unknown
  paths are 401 rather than 404.
- Every response gets a server-generated UUIDv4 `X-Request-ID`,
  `Cache-Control: no-store` and `Content-Type: application/json; charset=utf-8`.
"""

from __future__ import annotations

import hmac
import json
import time
import uuid
from typing import Any, Awaitable, Callable

from starlette.datastructures import Headers, MutableHeaders

from api.errors import error_body
from core.logging import log_event

Scope = dict[str, Any]
Message = dict[str, Any]
Send = Callable[[Message], Awaitable[None]]

_JSON_CONTENT_TYPE = b"application/json; charset=utf-8"


async def _send_json(
    send: Send, status_code: int, payload: dict[str, Any], request_id: str
) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", _JSON_CONTENT_TYPE),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-request-id", request_id.encode("ascii")),
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class RequestMiddleware:
    """Pure ASGI middleware so auth precedes routing and headers are uniform."""

    def __init__(self, app: Callable[..., Awaitable[None]], token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _is_authorized(self, scope: Scope) -> bool:
        value = Headers(scope=scope).get("authorization")
        if value is None:
            return False
        parts = value.split(" ")
        if len(parts) != 2:
            return False
        scheme, candidate = parts
        if scheme.lower() != "bearer" or not candidate:
            return False
        return hmac.compare_digest(candidate.encode("utf-8"), self._token)

    async def __call__(self, scope: Scope, receive: Callable[..., Awaitable[Any]], send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                headers["cache-control"] = "no-store"
                if status_code != 204:
                    headers["content-type"] = _JSON_CONTENT_TYPE.decode("ascii")
            await send(message)

        try:
            if not self._is_authorized(scope):
                status_code = 401
                log_event(
                    "request_error",
                    level="warn",
                    request_id=request_id,
                    error_code="unauthorized",
                    status_code=401,
                )
                await _send_json(send, 401, error_body("unauthorized"), request_id)
                return

            await self.app(scope, receive, send_with_headers)
        except Exception as exc:  # noqa: BLE001 - last line of defense
            log_event(
                "request_error",
                level="error",
                request_id=request_id,
                error_code="internal_error",
                status_code=500,
                exc_type=type(exc).__name__,
            )
            if response_started:
                raise
            status_code = 500
            await _send_json(send, 500, error_body("internal_error"), request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log_event(
                "request_completed",
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
