"""Static URL validation for source configuration (no DNS, no network).

Phase 1 only stores source URLs; it never fetches them. This module rejects
statically-detectable unsafe targets (loopback, private, link-local, metadata,
numeric/hex hosts, userinfo, single-label hosts) and normalises the URL so the
partial unique index is stable. DNS resolution checks belong to Phase 2.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048

_LOCAL_NAMES = {"localhost", "localhost.localdomain"}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal")
_NUMERIC_HOST_RE = re.compile(r"^[0-9.]+$")


def _is_strict_ipv4(host: str) -> bool:
    """Accept only canonical dotted-quad IPv4 (no shorthand, no octal)."""

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


class URLValidationError(ValueError):
    """Carries a stable machine reason plus a fixed Chinese message."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def _reject(reason: str, message: str) -> None:
    raise URLValidationError(reason, message)


def _reject_ip(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        _reject("url_host", "不允许使用本机、内网或保留地址")


def normalize_http_url(
    raw: str, *, allowed_ports: frozenset[int] | None = None
) -> str:
    """Return a normalised http(s) URL or raise `URLValidationError`."""

    value = raw.strip()
    if not value:
        _reject("url_required", "URL 不能为空")
    if len(value) > MAX_URL_LENGTH:
        _reject("url_too_long", f"URL 长度不能超过 {MAX_URL_LENGTH}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        _reject("url_invalid", "URL 含非法控制字符")
    if " " in value:
        _reject("url_invalid", "URL 不能包含空格，请使用百分号编码")

    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        _reject("url_scheme", "仅支持 http 或 https")

    if "@" in parts.netloc:
        _reject("url_userinfo", "URL 不能包含用户名或密码")

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        _reject("url_host", "URL 端口非法")

    if not hostname:
        _reject("url_host", "URL 缺少主机名")

    host = hostname.lower().rstrip(".")
    if not host:
        _reject("url_host", "URL 缺少主机名")
    if host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES):
        _reject("url_host", "不允许使用本机或内网主机名")

    # Decimal/hex IPv4 literals are interpreted by some resolvers.
    if host.isdigit() or host.startswith("0x"):
        _reject("url_host", "不允许使用数字或十六进制形式的主机地址")
    if any(label.startswith("0x") for label in host.split(".")):
        _reject("url_host", "不允许使用十六进制形式的主机地址")
    if _NUMERIC_HOST_RE.fullmatch(host) and not _is_strict_ipv4(host):
        # Catches shorthand (127.1), octal (0177.0.0.1) and out-of-range forms.
        _reject("url_host", "不允许使用非标准 IPv4 写法")

    _reject_ip(host)

    try:
        is_ip = ipaddress.ip_address(host) is not None
    except ValueError:
        is_ip = False
    if not is_ip and "." not in host:
        _reject("url_host", "主机名必须是完整域名或 IP 地址")

    if port == 0:
        _reject("url_host", "URL 端口非法")
    if allowed_ports is not None:
        effective_port = (80 if scheme == "http" else 443) if port is None else port
        if effective_port not in allowed_ports:
            _reject("url_port", "仅支持 80 或 443 端口")

    default_port = 80 if scheme == "http" else 443
    netloc_host = f"[{host}]" if ":" in host else host
    netloc = netloc_host if port in (None, default_port) else f"{netloc_host}:{port}"

    path = parts.path or ""
    if path == "/":
        path = ""
    elif path.endswith("/"):
        # Treat a trailing slash as the same source identity to avoid duplicates.
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))
