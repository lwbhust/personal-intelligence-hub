"""Independent SSRF / resource-limit tests for `collectors.net_guard`.

All HTTP behaviour is exercised against a real local server. Loopback is only
allowed through the explicit test policy; product defaults are asserted to
reject it.
"""

from __future__ import annotations

import gzip
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from collectors.net_guard import (
    NetGuard,
    NetGuardError,
    NetPolicy,
    resolve_validated,
    validate_ip_address,
    validate_target,
)

FEED = b"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title></channel></rss>"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, ctype: str = "application/rss+xml", **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: C901 - a tiny dispatch table
        if self.path == "/ok":
            self._send(200, FEED)
        elif self.path == "/robots.txt":
            self._send(404, b"not found", "text/plain")
        elif self.path == "/robots-deny.txt":
            self._send(200, b"User-agent: *\nDisallow: /feed\n", "text/plain")
        elif self.path == "/feed-denied":
            self._send(200, FEED)
        elif self.path == "/html":
            self._send(200, b"<html></html>", "text/html")
        elif self.path == "/500":
            self._send(500, b"boom", "text/plain")
        elif self.path == "/oversize":
            self._send(200, b"x" * 5000)
        elif self.path == "/chunked-oversize":
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(40):
                chunk = b"x" * 1024
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        elif self.path == "/gzip-bomb":
            payload = gzip.compress(b"\0" * (4 * 1024 * 1024))
            self._send(200, payload, "application/rss+xml", Content_Encoding="gzip")
        elif self.path == "/slow":
            time.sleep(1.5)
            self._send(200, FEED)
        elif self.path == "/redirect-internal":
            self._send(302, b"", "text/plain", Location="http://169.254.169.254/latest/meta-data/")
        elif self.path == "/redirect-file":
            self._send(302, b"", "text/plain", Location="file:///etc/passwd")
        elif self.path == "/redirect-downgrade":
            self._send(302, b"", "text/plain", Location="http://example.com/")
        elif self.path == "/redirect-local":
            self._send(302, b"", "text/plain", Location="/ok")
        elif self.path == "/redirect-loop":
            self._send(302, b"", "text/plain", Location="/redirect-loop")
        else:
            self._send(404, b"missing", "text/plain")

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture()
def server() -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()


def _guard(**overrides: object) -> NetGuard:
    defaults = {
        "allowed_ports": None,
        "allow_loopback_for_tests": True,
        "robots_enabled": False,
        "total_timeout": 5.0,
        "connect_timeout": 1.0,
        "read_timeout": 2.0,
    }
    defaults.update(overrides)
    return NetGuard(NetPolicy(**defaults))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Static SSRF policy (production defaults)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/feed",
        "http://127.0.0.1:8080/feed",
        "http://[::1]/feed",
        "http://10.1.2.3/feed",
        "http://172.16.0.1/feed",
        "http://172.31.255.255/feed",
        "http://192.168.1.1/feed",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.100.100.200/latest/meta-data/",
        "http://100.64.0.1/feed",
        "http://[::ffff:100.64.0.1]/feed",
        "http://198.18.0.1/feed",
        "http://192.0.2.1/feed",
        "http://[fe80::1]/feed",
        "http://[fc00::1]/feed",
        "http://[::ffff:127.0.0.1]/feed",
        "http://0.0.0.0/feed",
        "http://224.0.0.1/feed",
        "http://localhost/feed",
        "http://foo.local/feed",
        "http://foo.internal/feed",
        "http://2130706433/feed",
        "http://0x7f000001/feed",
        "http://0177.0.0.1/feed",
        "http://127.1/feed",
        "http://user:pw@example.com/feed",
        "file:///etc/passwd",
        "ftp://example.com/feed",
        "gopher://example.com/",
        "http://example.com:22/feed",
        "http://example.com:6379/feed",
        "not-a-url",
        "http:///feed",
        "http://example.com/" + "a" * 2050,
        "http://exa mple.com/feed",
    ],
)
def test_static_targets_are_rejected(url: str) -> None:
    with pytest.raises(NetGuardError):
        validate_target(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/feed",
        "https://Example.COM:443/feed",
        "https://example.com:8443/feed",
    ],
)
def test_public_https_is_allowed_only_when_port_is_allowed(url: str) -> None:
    policy = NetPolicy(allowed_ports=frozenset({80, 443}))
    if ":8443" in url:
        with pytest.raises(NetGuardError):
            validate_target(url, policy)
    else:
        target = validate_target(url, policy)
        assert target.host == "example.com"


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.1", "172.16.0.1", "192.168.0.1", "169.254.1.1", "127.0.0.1", "::1", "fe80::1", "fc00::1", "0.0.0.0"],
)
def test_forbidden_address_classes(ip: str) -> None:
    with pytest.raises(NetGuardError):
        validate_ip_address(ip)


def test_metadata_ipv6_is_rejected() -> None:
    with pytest.raises(NetGuardError):
        validate_ip_address("fd00:ec2::254")


def test_dns_answers_are_all_checked() -> None:
    policy = NetPolicy()
    target = validate_target("http://feeds.example.com/feed")

    def resolver(_host: str, _port: int) -> list[tuple[int, str]]:
        return [(2, "93.184.216.34"), (2, "10.0.0.7")]

    with pytest.raises(NetGuardError) as error:
        resolve_validated(target, policy=policy, resolver=resolver)
    assert error.value.code == "blocked_target"


def test_dns_rebinding_is_prevented_by_pinning() -> None:
    """The resolver is consulted once and the connection uses that exact IP."""

    calls: list[str] = []

    def resolver(host: str, _port: int) -> list[tuple[int, str]]:
        calls.append(host)
        # First answer public, later answers would be internal: a rebinding DNS.
        return [(2, "127.0.0.1")] if len(calls) == 1 else [(2, "10.0.0.1")]

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        policy = NetPolicy(
            allowed_ports=None,
            allow_loopback_for_tests=True,
            robots_enabled=False,
        )
        guard = NetGuard(policy, resolver=resolver)
        port = httpd.server_address[1]
        result = guard.fetch(f"http://pinned.example.com:{port}/ok")
        assert result.status_code == 200
        assert calls == ["pinned.example.com"]
    finally:
        httpd.shutdown()
        httpd.server_close()


# --------------------------------------------------------------------------
# HTTP behaviour and resource limits
# --------------------------------------------------------------------------

def test_fetch_success(server: str) -> None:
    result = _guard().fetch(server + "/ok")
    assert result.status_code == 200
    assert result.body.startswith(b"<?xml")
    assert result.content_type == "application/rss+xml"


def test_redirect_to_metadata_is_blocked(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard().fetch(server + "/redirect-internal")
    assert error.value.code == "blocked_target"


def test_redirect_to_file_scheme_is_blocked(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard().fetch(server + "/redirect-file")
    assert error.value.code == "redirect_rejected"


def test_https_downgrade_is_blocked(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard().fetch(server.replace("http://", "https://") + "/redirect-downgrade")
    assert error.value.code in {"redirect_rejected", "network_unreachable", "tls_error"}


def test_relative_redirect_is_followed(server: str) -> None:
    result = _guard().fetch(server + "/redirect-local")
    assert result.status_code == 200
    assert result.final_url.endswith("/ok")


def test_redirect_limit(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard().fetch(server + "/redirect-loop")
    assert error.value.code == "redirect_rejected"


def test_unsupported_content_type(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard().fetch(server + "/html")
    assert error.value.code == "unsupported_content_type"


def test_http_500_is_retryable(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard().fetch(server + "/500")
    assert error.value.code == "http_server_error"
    assert error.value.retryable is True


def test_content_length_over_cap(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard(max_response_bytes=1024).fetch(server + "/oversize")
    assert error.value.code == "response_too_large"


def test_streaming_chunked_over_cap(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard(max_response_bytes=4096).fetch(server + "/chunked-oversize")
    assert error.value.code == "response_too_large"


def test_gzip_bomb_is_bounded(server: str) -> None:
    started = time.monotonic()
    with pytest.raises(NetGuardError) as error:
        _guard(max_response_bytes=64 * 1024).fetch(server + "/gzip-bomb")
    assert error.value.code == "response_too_large"
    assert time.monotonic() - started < 3.0


def test_read_timeout(server: str) -> None:
    with pytest.raises(NetGuardError) as error:
        _guard(read_timeout=0.2, total_timeout=1.0).fetch(server + "/slow")
    assert error.value.code == "network_timeout"


def test_robots_disallow_blocks_feed() -> None:
    class RobotsHandler(_Handler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/robots.txt":
                self._send(200, b"User-agent: *\nDisallow: /feed\n", "text/plain")
            else:
                self._send(200, FEED)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RobotsHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        guard = _guard(robots_enabled=True)
        with pytest.raises(NetGuardError) as error:
            guard.fetch(f"http://127.0.0.1:{httpd.server_address[1]}/feed")
        assert error.value.code == "robots_disallowed"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_etag_conditional_request(server: str) -> None:
    """A server returning 304 must surface `not_modified` without a body."""

    class ConditionalHandler(_Handler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("If-None-Match") == '"v1"':
                self.send_response(304)
                self.send_header("ETag", '"v1"')
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send(200, FEED, ETag='"v1"')

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ConditionalHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        result = _guard().fetch(
            f"http://127.0.0.1:{httpd.server_address[1]}/ok", etag='"v1"'
        )
        assert result.status_code == 304
        assert result.not_modified is True
        assert result.body == b""
    finally:
        httpd.shutdown()
        httpd.server_close()
