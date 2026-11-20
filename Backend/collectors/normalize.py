"""URL canonicalisation and content fingerprints for Phase 2 dedup.

Identity normalisation only: these URLs are never fetched directly. Any
outbound request still goes through `net_guard`.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

MAX_URL_LENGTH = 2048
_DEFAULT_PORTS = {"http": 80, "https": 443}
_TRACKING_EXACT = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "yclid",
    "spm",
    "_hsenc",
    "_hsmi",
    "vero_id",
    "wickedid",
    "ref",
    "source",
}
_TRACKING_PREFIXES = ("utm_",)
_SLASHES = re.compile(r"/{2,}")
_TITLE_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_title(value: str | None) -> str:
    """Collapse a title to a comparison key (Chinese punctuation preserved as separators)."""

    return _TITLE_NOISE.sub("", (value or "").lower())


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in _TRACKING_EXACT or lowered.startswith(_TRACKING_PREFIXES)


def canonicalize_url(raw: str | None) -> str | None:
    """Return a stable identity URL, or None when the value is unusable."""

    if raw is None:
        return None
    value = raw.strip()
    if not value or len(value) > MAX_URL_LENGTH:
        return None
    if " " in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if "@" in parts.netloc:
        return None
    try:
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return None
    if not host:
        return None

    default_port = _DEFAULT_PORTS[scheme]
    host_part = f"[{host}]" if ":" in host else host
    netloc = host_part if port in (None, default_port) else f"{host_part}:{port}"

    path = _SLASHES.sub("/", parts.path or "/")
    if not path.startswith("/"):
        path = "/" + path
    if path != "/":
        path = path.rstrip("/")

    pairs = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(key)
    ]
    pairs.sort()
    query = urlencode(pairs, doseq=True, quote_via=quote, safe="")
    canonical = f"{scheme}://{netloc}{path}"
    if query:
        canonical += "?" + query
    if len(canonical) > MAX_URL_LENGTH:
        return None
    return canonical


def content_fingerprint(
    *,
    title: str,
    body: str | None,
    published_at: str | None = None,
) -> str:
    """SHA-256 over the stable fields used for third-level dedup."""

    normalised_body = " ".join((body or "").split())
    normalised_title = " ".join(title.split())
    material = "\n".join(
        [
            normalised_title,
            published_at or "",
            normalised_body,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
