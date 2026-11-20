"""Local-only Ollama provider (Phase 3).

Security contract (`Docs/AI_PROVIDER_SECURITY_POLICY.md` P1–P6):
* the endpoint is fixed to http://127.0.0.1:11434 and re-validated per call;
* any model containing ``-cloud`` or exposing a non-empty ``remote_host`` is
  refused before a request is sent;
* environment proxies are disabled, so local calls can never be relayed;
* ``num_ctx`` is always explicit;
* every result carries the real model digest and timing metrics.

Business code never hard-codes model names: callers pass the enabled set from
``ai_model_registry``.
"""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

from core.timeutil import utc_timestamp

from .errors import (
    AIError,
    CLOUD_MODEL_BLOCKED,
    EMBEDDING_MODEL_UNAVAILABLE,
    INVALID_RESPONSE,
    MODEL_NOT_ALLOWED,
    MODEL_UNAVAILABLE,
    PROVIDER_ENDPOINT_REJECTED,
    PROVIDER_HTTP_ERROR,
    PROVIDER_TIMEOUT,
    PROVIDER_UNREACHABLE,
    RESPONSE_TOO_LARGE,
)

BASE_URL = "http://127.0.0.1:11434"
ALLOWED_HOST = "127.0.0.1"
ALLOWED_PORT = 11434
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MODELS_CACHE_SECONDS = 30.0
DEFAULT_HEALTH_TIMEOUT = 3.0
DEFAULT_GENERATE_TIMEOUT = 120.0
DEFAULT_EMBED_TIMEOUT = 30.0
DEFAULT_KEEP_ALIVE = "5m"


@dataclass(frozen=True, slots=True)
class RemoteModel:
    name: str
    digest: str
    size_bytes: int
    parameter_size: str
    quantization: str
    remote_host: str | None

    @property
    def is_remote(self) -> bool:
        return bool(self.remote_host)


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    available: bool
    version: str | None
    models: tuple[RemoteModel, ...]
    error_code: str | None
    checked_at: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    model_name: str
    model_digest: str | None
    total_duration_ms: int
    load_duration_ms: int
    prompt_eval_count: int
    eval_count: int
    eval_duration_ms: int
    tok_per_s: float
    truncated: bool


class Transport(Protocol):
    """Minimal HTTP transport so tests can inject a local stub."""

    def request(
        self,
        method: str,
        url: str,
        payload: Mapping[str, object] | None,
        timeout: float,
    ) -> tuple[int, bytes]: ...


class UrllibTransport:
    """stdlib transport with all proxy handling disabled."""

    def __init__(self) -> None:
        # An empty ProxyHandler ignores http_proxy/https_proxy/all_proxy.
        self._opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))

    def request(
        self,
        method: str,
        url: str,
        payload: Mapping[str, object] | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urlrequest.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise AIError(RESPONSE_TOO_LARGE, "响应体超过 2 MiB 上限")
                return int(response.status), body
        except urlerror.HTTPError as exc:
            try:
                body = exc.read(MAX_RESPONSE_BYTES)
            except Exception:  # noqa: BLE001 - body is best-effort
                body = b""
            return int(exc.code), body
        except urlerror.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise AIError(
                    PROVIDER_TIMEOUT, "本地模型请求超时", retryable=True
                ) from exc
            raise AIError(
                PROVIDER_UNREACHABLE, "无法连接本地 Ollama", retryable=True
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AIError(PROVIDER_TIMEOUT, "本地模型请求超时", retryable=True) from exc
        except OSError as exc:
            raise AIError(
                PROVIDER_UNREACHABLE, "无法连接本地 Ollama", retryable=True
            ) from exc


def is_remote_model_name(model_name: str) -> bool:
    return "-cloud" in model_name.strip().lower()


def _validate_base_url(base_url: str) -> None:
    # Exact-match allowlist: rejects whitespace, case variants, leading-zero
    # ports, trailing slashes and every non-loopback host.
    if base_url != BASE_URL:
        raise AIError(
            PROVIDER_ENDPOINT_REJECTED,
            "Provider 只允许 http://127.0.0.1:11434",
        )
    parts = urlsplit(base_url)
    if (
        parts.scheme != "http"
        or parts.hostname != ALLOWED_HOST
        or parts.port != ALLOWED_PORT
    ):
        raise AIError(
            PROVIDER_ENDPOINT_REJECTED,
            "Provider 只允许 http://127.0.0.1:11434",
        )


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


class OllamaLocalProvider:
    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        transport: Transport | None = None,
        clock=time.monotonic,
        health_timeout: float = DEFAULT_HEALTH_TIMEOUT,
        generate_timeout: float = DEFAULT_GENERATE_TIMEOUT,
        embed_timeout: float = DEFAULT_EMBED_TIMEOUT,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
    ) -> None:
        _validate_base_url(base_url)
        self.base_url = base_url
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._health_timeout = health_timeout
        self._generate_timeout = generate_timeout
        self._embed_timeout = embed_timeout
        self._keep_alive = keep_alive
        self._models_cache: tuple[float, tuple[RemoteModel, ...]] | None = None

    # ------------------------------------------------------------------
    # transport helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        _validate_base_url(self.base_url)
        return self.base_url + path

    def _json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
        timeout: float,
    ) -> tuple[int, Any]:
        status, body = self._transport.request(method, self._url(path), payload, timeout)
        if status != 200:
            return status, None
        try:
            return status, json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIError(INVALID_RESPONSE, "Ollama 返回了无法解析的响应") from exc

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------

    def list_models(self, *, force: bool = False) -> tuple[RemoteModel, ...]:
        now = self._clock()
        if not force and self._models_cache is not None:
            cached_at, models = self._models_cache
            if now - cached_at <= MODELS_CACHE_SECONDS:
                return models

        status, data = self._json("GET", "/api/tags", None, self._health_timeout)
        if status != 200 or not isinstance(data, dict):
            raise AIError(PROVIDER_UNREACHABLE, "无法读取本地模型列表", retryable=True)
        raw_models = data.get("models")
        if not isinstance(raw_models, list):
            raise AIError(INVALID_RESPONSE, "模型列表格式不正确")

        models: list[RemoteModel] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if not isinstance(name, str) or not name.strip():
                continue
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            remote = item.get("remote_host")
            models.append(
                RemoteModel(
                    name=name.strip(),
                    digest=str(item.get("digest") or ""),
                    size_bytes=_int_or_zero(item.get("size")),
                    parameter_size=str(details.get("parameter_size") or ""),
                    quantization=str(details.get("quantization_level") or ""),
                    remote_host=str(remote) if remote else None,
                )
            )
        result = tuple(models)
        self._models_cache = (now, result)
        return result

    def health_check(self) -> ProviderHealth:
        checked_at = utc_timestamp()
        try:
            status, data = self._json("GET", "/api/version", None, self._health_timeout)
            if status != 200 or not isinstance(data, dict):
                return ProviderHealth(
                    available=False,
                    version=None,
                    models=(),
                    error_code=MODEL_UNAVAILABLE,
                    checked_at=checked_at,
                )
            version = data.get("version")
            models = self.list_models(force=True)
            return ProviderHealth(
                available=True,
                version=str(version) if version else None,
                models=models,
                error_code=None,
                checked_at=checked_at,
            )
        except AIError as exc:
            code = exc.code
            if code not in (PROVIDER_TIMEOUT, PROVIDER_UNREACHABLE):
                code = MODEL_UNAVAILABLE if code == MODEL_UNAVAILABLE else code
            return ProviderHealth(
                available=False,
                version=None,
                models=(),
                error_code=code,
                checked_at=checked_at,
            )

    # ------------------------------------------------------------------
    # whitelist
    # ------------------------------------------------------------------

    def ensure_model(
        self,
        model: str,
        allowed_models: Iterable[str],
    ) -> RemoteModel:
        name = (model or "").strip()
        if not name:
            raise AIError(MODEL_NOT_ALLOWED, "未指定模型")
        if is_remote_model_name(name):
            raise AIError(CLOUD_MODEL_BLOCKED, "云端模型被禁止调用")
        allowed = {item.strip() for item in allowed_models if item and item.strip()}
        if name not in allowed:
            raise AIError(MODEL_NOT_ALLOWED, "模型不在本地白名单内")

        models = self.list_models()
        for item in models:
            if item.name != name:
                continue
            if item.is_remote:
                raise AIError(CLOUD_MODEL_BLOCKED, "该模型为云端代理，禁止调用")
            return item
        raise AIError(MODEL_UNAVAILABLE, "本地模型未安装或不可用", retryable=True)

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------

    def generate(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        num_ctx: int,
        temperature: float,
        num_predict: int,
        allowed_models: Iterable[str],
        timeout: float | None = None,
        json_mode: bool = False,
    ) -> GenerationResult:
        remote = self.ensure_model(model, allowed_models)
        if not 1024 <= int(num_ctx) <= 32768:
            raise AIError(INVALID_RESPONSE, "num_ctx 超出允许范围")
        if not messages:
            raise AIError(INVALID_RESPONSE, "messages 不能为空")

        payload: dict[str, object] = {
            "model": remote.name,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self._keep_alive,
            "options": {
                "num_ctx": int(num_ctx),
                "temperature": float(temperature),
                "num_predict": int(num_predict),
            },
        }
        if json_mode:
            payload["format"] = "json"

        status, data = self._json(
            "POST",
            "/api/chat",
            payload,
            self._generate_timeout if timeout is None else timeout,
        )
        if status == 404:
            raise AIError(MODEL_UNAVAILABLE, "本地模型未安装或不可用", retryable=True)
        if status != 200:
            raise AIError(
                PROVIDER_HTTP_ERROR,
                f"本地模型返回 HTTP {status}",
                retryable=status >= 500,
            )
        if not isinstance(data, dict):
            raise AIError(INVALID_RESPONSE, "模型响应格式不正确")
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise AIError(INVALID_RESPONSE, "模型响应缺少内容")

        eval_count = _int_or_zero(data.get("eval_count"))
        eval_duration = _int_or_zero(data.get("eval_duration"))
        tok_per_s = 0.0
        if eval_duration > 0:
            tok_per_s = round(eval_count / (eval_duration / 1_000_000_000), 2)

        return GenerationResult(
            text=content,
            model_name=str(data.get("model") or remote.name),
            model_digest=remote.digest or None,
            total_duration_ms=_int_or_zero(data.get("total_duration")) // 1_000_000,
            load_duration_ms=_int_or_zero(data.get("load_duration")) // 1_000_000,
            prompt_eval_count=_int_or_zero(data.get("prompt_eval_count")),
            eval_count=eval_count,
            eval_duration_ms=eval_duration // 1_000_000,
            tok_per_s=tok_per_s,
            truncated=str(data.get("done_reason") or "") == "length",
        )

    def generate_structured(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        num_ctx: int,
        temperature: float,
        num_predict: int,
        allowed_models: Iterable[str],
        timeout: float | None = None,
    ) -> GenerationResult:
        return self.generate(
            model=model,
            messages=messages,
            num_ctx=num_ctx,
            temperature=temperature,
            num_predict=num_predict,
            allowed_models=allowed_models,
            timeout=timeout,
            json_mode=True,
        )

    # ------------------------------------------------------------------
    # embeddings (gated by AI-01)
    # ------------------------------------------------------------------

    def embed(
        self,
        *,
        model: str,
        text: str,
        allowed_models: Iterable[str],
        timeout: float | None = None,
    ) -> list[float]:
        remote = self.ensure_model(model, allowed_models)
        status, data = self._json(
            "POST",
            "/api/embed",
            {"model": remote.name, "input": text},
            self._embed_timeout if timeout is None else timeout,
        )
        if status == 404:
            raise AIError(
                EMBEDDING_MODEL_UNAVAILABLE, "Embedding 模型未安装或未获授权"
            )
        if status != 200 or not isinstance(data, dict):
            raise AIError(
                PROVIDER_HTTP_ERROR, f"Embedding 请求失败（HTTP {status}）"
            )
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            raise AIError(INVALID_RESPONSE, "Embedding 响应格式不正确")
        vector = embeddings[0]
        if not isinstance(vector, list) or not vector:
            raise AIError(INVALID_RESPONSE, "Embedding 向量为空")
        return [float(value) for value in vector]
