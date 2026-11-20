"""net_guard — the only outbound HTTP path for Phase 2 collection.

Threat model
------------
Feed URLs are user-configured but still untrusted, and every redirect target is
attacker-controlled data. This module therefore:

* accepts only http/https with an allow-listed port;
* rejects loopback, private, link-local, multicast, reserved, unspecified and
  IPv4-mapped addresses, plus cloud metadata endpoints;
* resolves DNS once, validates **every** A/AAAA answer, and connects to a
  validated IP directly (TLS SNI/verification still uses the hostname). The
  validated address and the connected address are the same value, which closes
  the DNS-rebinding / TOCTOU gap;
* re-runs the full URL + DNS + IP validation on every redirect hop;
* enforces connect/read/total timeouts, redirect limits, compressed and
  decompressed byte caps, Content-Type and Content-Encoding whitelists;
* never sends credentials and never executes response content.

`allow_loopback_for_tests` exists only so the security tests can point the
guard at a local HTTP server. It is never enabled from the environment and must
never be used by product code.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit

USER_AGENT = "PIH/0.3 (+local)"
MAX_URL_LENGTH = 2048
MAX_DNS_RESULTS = 16
MAX_REDIRECTS = 3
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 15.0
DEFAULT_TOTAL_TIMEOUT = 30.0

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
XML_CONTENT_TYPES = frozenset(
    {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
        "application/rdf+xml",
        "text/rss+xml",
        "application/xhtml+xml",
        # Real-world feeds are frequently served with generic types. The body
        # still has to pass XML/DTD validation in `feed_parser` before use.
        "application/octet-stream",
        "text/plain",
    }
)

_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_NUMERIC_HOST_RE = "^[0-9.]+$"


class NetGuardError(Exception):
    """A stable collection error code plus a short, non-reflective message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class NetPolicy:
    allowed_ports: frozenset[int] | None = frozenset({80, 443})
    allow_loopback_for_tests: bool = False
    max_redirects: int = MAX_REDIRECTS
    max_response_bytes: int = DEFAULT_MAX_BYTES
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT
    user_agent: str = USER_AGENT
    robots_enabled: bool = True


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    url: str
    scheme: str
    host: str
    port: int
    path_query: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    status_code: int
    headers: dict[str, str]
    body: bytes
    final_url: str
    content_type: str
    duration_ms: int
    not_modified: bool = False


Resolver = Callable[[str, int], list[tuple[int, str]]]


def _default_resolver(host: str, port: int) -> list[tuple[int, str]]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    results: list[tuple[int, str]] = []
    seen: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        ip = str(sockaddr[0]).split("%", 1)[0]
        if ip in seen:
            continue
        seen.add(ip)
        results.append((family, ip))
    return results


def _strict_ipv4(host: str) -> bool:
    parts = host.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3:
            return False
        if len(part) > 1 and part[0] == "0":
            return False
        if int(part) > 255:
            return False
    return True


def validate_ip_address(ip: str, *, allow_loopback: bool = False) -> None:
    """Reject every address class that must never be fetched."""

    try:
        address = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise NetGuardError("blocked_target", "目标地址无法解析") from exc

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped

    if address.is_loopback:
        if allow_loopback:
            return
        raise NetGuardError("blocked_target", "不允许访问本机地址")
    if address.is_private:
        raise NetGuardError("blocked_target", "不允许访问内网地址")
    if address.is_link_local:
        raise NetGuardError("blocked_target", "不允许访问链路本地地址")
    if address.is_multicast:
        raise NetGuardError("blocked_target", "不允许访问组播地址")
    if address.is_reserved:
        raise NetGuardError("blocked_target", "不允许访问保留地址")
    if address.is_unspecified:
        raise NetGuardError("blocked_target", "不允许访问未指定地址")
    # RFC 6598 CGNAT, benchmarking, documentation and other special-purpose
    # ranges are not globally routable even though `ipaddress` does not flag
    # all of them as private/reserved.
    if not address.is_global:
        raise NetGuardError("blocked_target", "不允许访问非公网地址")

    # Explicit metadata services (IPv4 covered by link-local, IPv6 by ULA).
    if str(address) in {"169.254.169.254", "fd00:ec2::254"}:
        raise NetGuardError("blocked_target", "不允许访问云元数据服务")


def validate_target(raw: str, policy: NetPolicy | None = None) -> ValidatedTarget:
    """Static URL validation; no DNS and no network."""

    active = NetPolicy() if policy is None else policy
    value = (raw or "").strip()
    if not value:
        raise NetGuardError("invalid_url", "URL 不能为空")
    if len(value) > MAX_URL_LENGTH:
        raise NetGuardError("invalid_url", f"URL 长度不能超过 {MAX_URL_LENGTH}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise NetGuardError("invalid_url", "URL 含非法控制字符")
    if " " in value:
        raise NetGuardError("invalid_url", "URL 不能包含空格")

    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise NetGuardError("invalid_url", "URL 格式非法") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise NetGuardError("unsupported_scheme", "仅支持 http 或 https")
    if "@" in parts.netloc:
        raise NetGuardError("invalid_url", "URL 不能包含用户名或密码")

    try:
        hostname = parts.hostname
        explicit_port = parts.port
    except ValueError as exc:
        raise NetGuardError("invalid_url", "URL 端口非法") from exc
    if not hostname:
        raise NetGuardError("invalid_url", "URL 缺少主机名")

    host = hostname.lower().rstrip(".")
    if not host:
        raise NetGuardError("invalid_url", "URL 缺少主机名")
    if not active.allow_loopback_for_tests:
        if host in ("localhost", "localhost.localdomain") or host.endswith(_LOCAL_SUFFIXES):
            raise NetGuardError("blocked_target", "不允许使用本机或内网域名")
        if host.isdigit() or host.startswith("0x") or any(
            label.startswith("0x") for label in host.split(".")
        ):
            raise NetGuardError("blocked_target", "不允许使用数字或十六进制主机")
        if re.fullmatch(_NUMERIC_HOST_RE, host) and not _strict_ipv4(host):
            raise NetGuardError("blocked_target", "不允许使用非标准 IPv4 写法")

    is_ip = True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        is_ip = False
    if not is_ip and "." not in host:
        raise NetGuardError("invalid_url", "主机名必须是完整域名或 IP 地址")
    if is_ip:
        validate_ip_address(host, allow_loopback=active.allow_loopback_for_tests)

    default_port = 80 if scheme == "http" else 443
    port = default_port if explicit_port is None else int(explicit_port)
    if port <= 0 or port > 65535:
        raise NetGuardError("invalid_url", "URL 端口非法")
    if active.allowed_ports is not None and port not in active.allowed_ports:
        raise NetGuardError("blocked_target", "目标端口不在允许范围")

    path = parts.path or "/"
    path_query = path + (f"?{parts.query}" if parts.query else "")

    netloc_host = f"[{host}]" if ":" in host else host
    netloc = netloc_host if port == default_port else f"{netloc_host}:{port}"
    normalised = f"{scheme}://{netloc}{path}" + (f"?{parts.query}" if parts.query else "")
    return ValidatedTarget(
        url=normalised,
        scheme=scheme,
        host=host,
        port=port,
        path_query=path_query,
    )


def resolve_validated(
    target: ValidatedTarget,
    *,
    policy: NetPolicy,
    resolver: Resolver | None = None,
) -> list[tuple[int, str]]:
    """Resolve once and validate every answer before any connection is made."""

    try:
        ipaddress.ip_address(target.host)
        literal = True
    except ValueError:
        literal = False

    if literal:
        validate_ip_address(target.host, allow_loopback=policy.allow_loopback_for_tests)
        family = socket.AF_INET6 if ":" in target.host else socket.AF_INET
        return [(family, target.host)]

    resolve = resolver or _default_resolver
    try:
        answers = resolve(target.host, target.port)
    except NetGuardError:
        raise
    except (socket.gaierror, OSError) as exc:
        raise NetGuardError("dns_failure", "域名解析失败", retryable=True) from exc

    if not answers:
        raise NetGuardError("dns_failure", "域名解析没有返回地址", retryable=True)
    if len(answers) > MAX_DNS_RESULTS:
        raise NetGuardError("blocked_target", "域名解析返回地址过多")
    for _family, ip in answers:
        validate_ip_address(ip, allow_loopback=policy.allow_loopback_for_tests)
    return list(answers)


def _same_ip(left: str, right: str) -> bool:
    try:
        return ipaddress.ip_address(left) == ipaddress.ip_address(right)
    except ValueError:
        return left == right


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, pinned_ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # noqa: D401 - http.client hook
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        peer = str(sock.getpeername()[0]).split("%", 1)[0]
        if not _same_ip(peer, self._pinned_ip):
            sock.close()
            raise NetGuardError("blocked_target", "连接目标与校验地址不一致")
        self.sock = sock


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        pinned_ip: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # noqa: D401 - http.client hook
        raw = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        tls = self._context.wrap_socket(raw, server_hostname=self.host)
        peer = str(tls.getpeername()[0]).split("%", 1)[0]
        if not _same_ip(peer, self._pinned_ip):
            tls.close()
            raise NetGuardError("blocked_target", "连接目标与校验地址不一致")
        self.sock = tls


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class RobotsCache:
    """Small in-memory robots.txt cache with a 24h TTL.

    Fetch failures never bypass net_guard: the robots file itself is fetched
    through the same guard (with robots checking disabled to break recursion).
    If robots.txt cannot be retrieved, standard crawler behaviour is to allow
    the request.
    """

    TTL_SECONDS = 24 * 60 * 60
    MAX_BYTES = 64 * 1024
    MAX_ENTRIES = 256

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, list[str] | None]] = {}

    def allowed(self, guard: "NetGuard", url: str) -> bool:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        now = time.monotonic()
        with self._lock:
            cached = self._entries.get(key)
        if cached is not None and now - cached[0] < self.TTL_SECONDS:
            rules = cached[1]
        else:
            rules = self._load(guard, key)
            with self._lock:
                self._entries[key] = (now, rules)
                if len(self._entries) > self.MAX_ENTRIES:
                    self._evict_locked(now)
        if not rules:
            return True
        path = parts.path or "/"
        best_len = -1
        allowed = True
        for rule in rules:
            if rule and path.startswith(rule):
                if len(rule) > best_len:
                    best_len = len(rule)
                    allowed = False
        return allowed

    def _evict_locked(self, now: float) -> None:
        """Drop expired entries, then the oldest ones, to bound memory."""

        for key, (stamp, _rules) in list(self._entries.items()):
            if now - stamp >= self.TTL_SECONDS:
                self._entries.pop(key, None)
        while len(self._entries) > self.MAX_ENTRIES:
            self._entries.pop(next(iter(self._entries)), None)

    def _load(self, guard: "NetGuard", base: str) -> list[str] | None:
        try:
            result = guard.fetch(
                base + "/robots.txt",
                check_robots=False,
                max_bytes=self.MAX_BYTES,
                allowed_content_types=None,
            )
        except NetGuardError:
            return None
        if result.status_code >= 400 or not result.body:
            return None
        return _parse_robots(result.body.decode("utf-8", errors="replace"))


def _parse_robots(text: str) -> list[str]:
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    disallow: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if disallow:
                groups.append((agents, disallow))
                agents, disallow = [], []
            agents.append(value.lower())
        elif field == "disallow":
            disallow.append(value)
    if agents or disallow:
        groups.append((agents, disallow))

    chosen: list[str] = []
    wildcard: list[str] | None = None
    for group_agents, rules in groups:
        for agent in group_agents:
            if agent in ("pih", "pih/0.3"):
                chosen = rules
        if "*" in group_agents and wildcard is None:
            wildcard = rules
    active = chosen if chosen else (wildcard or [])
    return [rule for rule in active if rule]


class NetGuard:
    def __init__(
        self,
        policy: NetPolicy | None = None,
        *,
        resolver: Resolver | None = None,
        robots: RobotsCache | None = None,
    ) -> None:
        self.policy = NetPolicy() if policy is None else policy
        self._resolver = resolver
        self.robots = robots if robots is not None else RobotsCache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        check_robots: bool | None = None,
        max_bytes: int | None = None,
        allowed_content_types: Iterable[str] | None = XML_CONTENT_TYPES,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        started = time.monotonic()
        deadline = started + self.policy.total_timeout
        byte_cap = max(1, int(max_bytes or self.policy.max_response_bytes))
        current = validate_target(url, self.policy).url
        use_robots = self.policy.robots_enabled if check_robots is None else check_robots

        redirects = 0
        while True:
            if time.monotonic() > deadline:
                raise NetGuardError("network_timeout", "请求总时长超出上限", retryable=True)

            if use_robots and not self.robots.allowed(self, current):
                raise NetGuardError("robots_disallowed", "目标站点 robots.txt 不允许采集")

            target = validate_target(current, self.policy)
            addresses = resolve_validated(
                target, policy=self.policy, resolver=self._resolver
            )

            connection, status, response, ip = self._connect(
                target,
                addresses,
                deadline=deadline,
                etag=etag,
                last_modified=last_modified,
                extra_headers=extra_headers,
            )
            try:
                if status in REDIRECT_STATUSES:
                    location = response.getheader("Location")
                    response.read(8192)
                    if not location:
                        raise NetGuardError(
                            "redirect_rejected", "重定向缺少 Location", status_code=status
                        )
                    redirects += 1
                    if redirects > self.policy.max_redirects:
                        raise NetGuardError(
                            "redirect_rejected", "重定向次数超出上限", status_code=status
                        )
                    next_url = urljoin(current, location.strip())
                    next_parts = urlsplit(next_url)
                    if next_parts.scheme.lower() not in ("http", "https"):
                        raise NetGuardError(
                            "redirect_rejected", "重定向协议不被允许", status_code=status
                        )
                    if (
                        urlsplit(current).scheme.lower() == "https"
                        and next_parts.scheme.lower() == "http"
                    ):
                        raise NetGuardError(
                            "redirect_rejected", "不允许 HTTPS 降级到 HTTP", status_code=status
                        )
                    current = next_url
                    continue

                if status == 304:
                    return FetchResult(
                        status_code=304,
                        headers=self._headers(response),
                        body=b"",
                        final_url=current,
                        content_type=self._content_type(response),
                        duration_ms=int((time.monotonic() - started) * 1000),
                        not_modified=True,
                    )

                content_type = self._content_type(response)
                if allowed_content_types is not None and status < 400:
                    if content_type not in set(allowed_content_types):
                        raise NetGuardError(
                            "unsupported_content_type",
                            "响应类型不在允许范围",
                            status_code=status,
                        )

                if status >= 500:
                    raise NetGuardError(
                        "http_server_error",
                        f"目标服务返回 {status}",
                        status_code=status,
                        retryable=True,
                    )
                if status >= 400:
                    raise NetGuardError(
                        "http_client_error",
                        f"目标资源返回 {status}",
                        status_code=status,
                    )

                body = self._read_body(
                    response, deadline=deadline, byte_cap=byte_cap
                )
                return FetchResult(
                    status_code=status,
                    headers=self._headers(response),
                    body=body,
                    final_url=current,
                    content_type=content_type,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            finally:
                try:
                    response.close()
                except Exception:  # noqa: BLE001 - best-effort close
                    pass
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - best-effort close
                    pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _connect(
        self,
        target: ValidatedTarget,
        addresses: list[tuple[int, str]],
        *,
        deadline: float,
        etag: str | None,
        last_modified: str | None,
        extra_headers: dict[str, str] | None,
    ) -> tuple[http.client.HTTPConnection, int, http.client.HTTPResponse, str]:
        headers = {
            "User-Agent": self.policy.user_agent,
            "Accept": (
                "application/rss+xml, application/atom+xml, application/xml, "
                "text/xml;q=0.9, */*;q=0.1"
            ),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if extra_headers:
            headers.update(extra_headers)

        last_error: Exception | None = None
        for _family, ip in addresses[:2]:
            remaining = max(0.5, deadline - time.monotonic())
            connect_timeout = min(self.policy.connect_timeout, remaining)
            try:
                if target.scheme == "https":
                    connection: http.client.HTTPConnection = _PinnedHTTPSConnection(
                        target.host,
                        target.port,
                        pinned_ip=ip,
                        timeout=connect_timeout,
                        context=_ssl_context(),
                    )
                else:
                    connection = _PinnedHTTPConnection(
                        target.host,
                        target.port,
                        pinned_ip=ip,
                        timeout=connect_timeout,
                    )
                connection.connect()
                if connection.sock is not None:
                    connection.sock.settimeout(
                        min(self.policy.read_timeout, max(0.5, deadline - time.monotonic()))
                    )
                connection.putrequest(
                    "GET", target.path_query, skip_accept_encoding=True
                )
                for name, value in headers.items():
                    connection.putheader(name, value)
                connection.endheaders()
                response = connection.getresponse()
                return connection, int(response.status), response, ip
            except NetGuardError:
                raise
            except ssl.SSLError as exc:
                last_error = NetGuardError("tls_error", "TLS 握手或证书校验失败", retryable=False)
                last_error.__cause__ = exc
            except (socket.timeout, TimeoutError) as exc:
                last_error = NetGuardError("network_timeout", "连接或读取超时", retryable=True)
                last_error.__cause__ = exc
            except (ConnectionError, OSError) as exc:
                last_error = NetGuardError("network_unreachable", "无法建立连接", retryable=True)
                last_error.__cause__ = exc
            except http.client.HTTPException as exc:
                last_error = NetGuardError("network_unreachable", "HTTP 协议错误", retryable=True)
                last_error.__cause__ = exc

        assert last_error is not None
        raise last_error

    def _read_body(
        self,
        response: http.client.HTTPResponse,
        *,
        deadline: float,
        byte_cap: int,
    ) -> bytes:
        length_header = response.getheader("Content-Length")
        if length_header is not None:
            try:
                if int(length_header) > byte_cap:
                    raise NetGuardError("response_too_large", "响应体超出大小上限")
            except ValueError:
                pass

        encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if encoding in ("",):
            encoding = "identity"
        if encoding not in ("identity", "gzip", "deflate"):
            raise NetGuardError("unsupported_content_encoding", "不支持的压缩编码")

        decompressor = None
        if encoding == "gzip":
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            decompressor = zlib.decompressobj()

        body = bytearray()
        compressed = 0
        while True:
            if time.monotonic() > deadline:
                raise NetGuardError("network_timeout", "读取响应超时", retryable=True)
            try:
                chunk = response.read(65536)
            except (socket.timeout, TimeoutError) as exc:
                raise NetGuardError("network_timeout", "读取响应超时", retryable=True) from exc
            except (ConnectionError, OSError, http.client.HTTPException) as exc:
                raise NetGuardError("network_unreachable", "读取响应失败", retryable=True) from exc
            if not chunk:
                break
            compressed += len(chunk)
            if compressed > byte_cap:
                raise NetGuardError("response_too_large", "压缩响应体超出大小上限")

            if decompressor is None:
                body.extend(chunk)
                if len(body) > byte_cap:
                    raise NetGuardError("response_too_large", "响应体超出大小上限")
                continue

            data = chunk
            while data:
                room = byte_cap + 1 - len(body)
                if room <= 0:
                    raise NetGuardError("response_too_large", "解压后响应超出大小上限")
                try:
                    piece = decompressor.decompress(data, room)
                except zlib.error as exc:
                    raise NetGuardError("unsupported_content_encoding", "响应解压失败") from exc
                body.extend(piece)
                if len(body) > byte_cap:
                    raise NetGuardError("response_too_large", "解压后响应超出大小上限")
                data = decompressor.unconsumed_tail
                if not data:
                    break

        if decompressor is not None:
            try:
                tail = decompressor.flush()
            except zlib.error as exc:
                raise NetGuardError("unsupported_content_encoding", "响应解压失败") from exc
            body.extend(tail)
            if len(body) > byte_cap:
                raise NetGuardError("response_too_large", "解压后响应超出大小上限")
        return bytes(body)

    @staticmethod
    def _headers(response: http.client.HTTPResponse) -> dict[str, str]:
        lowered: dict[str, str] = {}
        for name, value in response.getheaders():
            lowered.setdefault(name.lower(), value)
        return lowered

    @staticmethod
    def _content_type(response: http.client.HTTPResponse) -> str:
        raw = response.getheader("Content-Type") or ""
        return raw.split(";", 1)[0].strip().lower()
