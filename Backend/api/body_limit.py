"""Reject oversized request bodies before they reach the application.

Phase 1 accepts JSON bodies only; 64 KiB is far above any legitimate source
payload and prevents memory abuse. Authentication runs in the outer
`RequestMiddleware`, so unauthenticated requests still get 401 first.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from starlette.datastructures import Headers

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

MAX_BODY_BYTES = 64 * 1024
_METHODS = {"POST", "PUT", "PATCH"}


class BodyLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                await self._reject(scope, send, 422, "invalid_request", "请求体长度非法")
                return
            if length > self.max_bytes:
                await self._reject(scope, send, 413, "payload_too_large", "请求体过大")
                return

        buffered = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if chunk:
                buffered.extend(chunk)
                if len(buffered) > self.max_bytes:
                    await self._reject(scope, send, 413, "payload_too_large", "请求体过大")
                    return
            more_body = bool(message.get("more_body", False))

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(buffered), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    async def _reject(
        self, scope: Scope, send: Send, status: int, code: str, message: str
    ) -> None:
        request_id = str(scope.get("state", {}).get("request_id", "-"))
        payload = {"error": {"code": code, "message": message}}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"x-request-id", request_id.encode("ascii")),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
