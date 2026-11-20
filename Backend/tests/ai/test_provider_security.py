"""Provider security tests: endpoint, cloud blocking, proxies, num_ctx."""

from __future__ import annotations

import http.server
import json
import socket
import threading
from collections.abc import Mapping

import pytest

from ai_engine.errors import AIError
from ai_engine.provider import (
    ALLOWED_PORT,
    MAX_RESPONSE_BYTES,
    OllamaLocalProvider,
    UrllibTransport,
)

TAGS = {
    "models": [
        {
            "name": "qwen3.5:4b-mlx",
            "digest": "d" * 64,
            "size": 3973305013,
            "details": {"parameter_size": "4.5B", "quantization_level": "nvfp4"},
        },
        {
            "name": "gpt-oss:20b-cloud",
            "digest": "c" * 64,
            "size": 381,
            "remote_host": "https://ollama.com:443",
            "details": {"parameter_size": "20.9B"},
        },
    ]
}


def chat_response(text: str = '{"ok":true}', *, done_reason: str = "stop") -> dict:
    return {
        "model": "qwen3.5:4b-mlx",
        "message": {"role": "assistant", "content": text},
        "done_reason": done_reason,
        "total_duration": 2_500_000_000,
        "load_duration": 100_000_000,
        "prompt_eval_count": 120,
        "prompt_eval_duration": 300_000_000,
        "eval_count": 50,
        "eval_duration": 1_000_000_000,
    }


class StubTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, Mapping[str, object] | None, float]] = []

    def request(self, method, url, payload, timeout):
        self.calls.append((method, url, payload, timeout))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _body(data: object) -> tuple[int, bytes]:
    return 200, json.dumps(data).encode()


def _provider(responses: list[object]) -> tuple[OllamaLocalProvider, StubTransport]:
    transport = StubTransport(responses)
    return OllamaLocalProvider(transport=transport), transport


@pytest.mark.parametrize(
    "base_url",
    [
        "http://0.0.0.0:11434",
        "http://localhost:11434",
        "http://192.168.1.10:11434",
        "https://127.0.0.1:11434",
        "http://127.0.0.1:11435",
        "http://127.0.0.1:11434/path",
        "http://user:pass@127.0.0.1:11434",
    ],
)
def test_endpoint_must_be_loopback_fixed_port(base_url: str) -> None:
    with pytest.raises(AIError) as excinfo:
        OllamaLocalProvider(base_url=base_url)
    assert excinfo.value.code == "provider_endpoint_rejected"


def test_cloud_model_name_is_blocked_without_network_call() -> None:
    provider, transport = _provider([])
    with pytest.raises(AIError) as excinfo:
        provider.generate(
            model="gpt-oss:20b-cloud",
            messages=[{"role": "user", "content": "hi"}],
            num_ctx=4096,
            temperature=0.1,
            num_predict=16,
            allowed_models={"gpt-oss:20b-cloud"},
        )
    assert excinfo.value.code == "cloud_model_blocked"
    assert transport.calls == []


def test_model_outside_whitelist_is_rejected() -> None:
    provider, transport = _provider([_body(TAGS)])
    with pytest.raises(AIError) as excinfo:
        provider.generate(
            model="qwen3.5:4b-mlx",
            messages=[{"role": "user", "content": "hi"}],
            num_ctx=4096,
            temperature=0.1,
            num_predict=16,
            allowed_models=set(),
        )
    assert excinfo.value.code == "model_not_allowed"
    assert transport.calls == []


def test_remote_tag_entry_is_blocked_even_if_enabled() -> None:
    provider, transport = _provider([_body(TAGS)])
    with pytest.raises(AIError) as excinfo:
        provider.generate(
            model="gpt-oss:20b-cloud",
            messages=[{"role": "user", "content": "hi"}],
            num_ctx=4096,
            temperature=0.1,
            num_predict=16,
            allowed_models={"gpt-oss:20b-cloud"},
        )
    assert excinfo.value.code == "cloud_model_blocked"
    assert transport.calls == []


def test_remote_host_in_tags_blocks_plain_model_name() -> None:
    tags = {
        "models": [
            {
                "name": "sneaky:4b",
                "digest": "e" * 64,
                "size": 1,
                "remote_host": "https://ollama.com:443",
            }
        ]
    }
    provider, _ = _provider([_body(tags)])
    with pytest.raises(AIError) as excinfo:
        provider.generate(
            model="sneaky:4b",
            messages=[{"role": "user", "content": "hi"}],
            num_ctx=4096,
            temperature=0.1,
            num_predict=16,
            allowed_models={"sneaky:4b"},
        )
    assert excinfo.value.code == "cloud_model_blocked"


def test_missing_model_is_model_unavailable() -> None:
    provider, _ = _provider([_body(TAGS)])
    with pytest.raises(AIError) as excinfo:
        provider.generate(
            model="qwen3:1.7b",
            messages=[{"role": "user", "content": "hi"}],
            num_ctx=4096,
            temperature=0.1,
            num_predict=16,
            allowed_models={"qwen3:1.7b"},
        )
    assert excinfo.value.code == "model_unavailable"
    assert excinfo.value.retryable is True


def test_num_ctx_and_metrics_are_explicit() -> None:
    provider, transport = _provider(
        [_body(TAGS), _body(chat_response("hello"))]
    )
    result = provider.generate(
        model="qwen3.5:4b-mlx",
        messages=[{"role": "user", "content": "hi"}],
        num_ctx=2048,
        temperature=0.2,
        num_predict=32,
        allowed_models={"qwen3.5:4b-mlx"},
    )
    payload = transport.calls[1][2]
    assert payload is not None
    assert payload["options"]["num_ctx"] == 2048
    assert payload["stream"] is False
    assert payload["think"] is False
    assert result.text == "hello"
    assert result.model_digest == "d" * 64
    assert result.tok_per_s == 50.0
    assert result.total_duration_ms == 2500
    assert result.truncated is False


def test_structured_mode_sets_json_format() -> None:
    provider, transport = _provider([_body(TAGS), _body(chat_response())])
    provider.generate_structured(
        model="qwen3.5:4b-mlx",
        messages=[{"role": "user", "content": "hi"}],
        num_ctx=4096,
        temperature=0.1,
        num_predict=16,
        allowed_models={"qwen3.5:4b-mlx"},
    )
    assert transport.calls[1][2]["format"] == "json"


def test_truncated_output_is_reported() -> None:
    provider, _ = _provider(
        [_body(TAGS), _body(chat_response("partial", done_reason="length"))]
    )
    result = provider.generate_structured(
        model="qwen3.5:4b-mlx",
        messages=[{"role": "user", "content": "hi"}],
        num_ctx=4096,
        temperature=0.1,
        num_predict=16,
        allowed_models={"qwen3.5:4b-mlx"},
    )
    assert result.truncated is True


def test_health_check_reports_unavailable_on_connection_error() -> None:
    provider, _ = _provider([AIError("provider_unreachable", "down", retryable=True)])
    health = provider.health_check()
    assert health.available is False
    assert health.error_code == "provider_unreachable"
    assert health.models == ()


def test_response_over_limit_is_rejected() -> None:
    class _BigHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib signature
            body = b"{" + b" " * (MAX_RESPONSE_BYTES + 10) + b"}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _BigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        transport = UrllibTransport()
        with pytest.raises(AIError) as excinfo:
            transport.request("GET", f"http://127.0.0.1:{port}/big", None, 2.0)
        assert excinfo.value.code == "response_too_large"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# UrllibTransport proxy isolation (real socket, no mocking)
# ---------------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib signature
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        return


def test_urllib_transport_ignores_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
        monkeypatch.setenv("https_proxy", "http://127.0.0.1:1")
        monkeypatch.setenv("all_proxy", "http://127.0.0.1:1")
        transport = UrllibTransport()
        status, body = transport.request(
            "GET", f"http://127.0.0.1:{port}/anything", None, 2.0
        )
        assert status == 200
        assert json.loads(body) == {"ok": True}
    finally:
        server.shutdown()
        server.server_close()


def test_urllib_transport_reports_timeout() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        transport = UrllibTransport()
        with pytest.raises(AIError) as excinfo:
            transport.request("GET", f"http://127.0.0.1:{port}/slow", None, 0.2)
        assert excinfo.value.code in ("provider_timeout", "provider_unreachable")
    finally:
        listener.close()


def test_allowlisted_port_constant() -> None:
    assert ALLOWED_PORT == 11434
    assert str(ALLOWED_PORT) in "http://127.0.0.1:11434"
