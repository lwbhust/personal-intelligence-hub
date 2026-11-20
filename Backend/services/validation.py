"""Field validation shared by both Phase 1 services."""

from __future__ import annotations

import re
import unicodedata

from core.url_guard import URLValidationError, normalize_http_url

from .errors import ErrorDetail, validation

SOURCE_TYPES = ("rss", "atom", "website", "official_announcement", "api")

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")


def normalize_text(
    raw: str,
    *,
    field: str,
    max_length: int,
    required: bool = False,
) -> str | None:
    value = unicodedata.normalize("NFKC", raw)
    value = " ".join(value.split())
    if required and not value:
        raise validation(field, "required", "不能为空")
    if not value:
        return None
    if len(value) > max_length:
        raise validation(field, "too_long", f"长度不能超过 {max_length}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise validation(field, "invalid", "包含非法控制字符")
    return value


def normalize_url(
    raw: str, *, field: str, allowed_ports: frozenset[int] | None = None
) -> str:
    try:
        return normalize_http_url(raw, allowed_ports=allowed_ports)
    except URLValidationError as exc:
        raise validation(field, exc.reason, exc.message) from exc


def normalize_language(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if not _LANGUAGE_RE.fullmatch(value):
        raise validation("language", "format", "语言格式应如 zh-CN 或 en")
    return value


def normalize_country(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if not _COUNTRY_RE.fullmatch(value):
        raise validation("country", "format", "国家代码应为两个字母")
    return value.upper()


def normalize_source_type(raw: str) -> str:
    value = raw.strip().lower()
    if value not in SOURCE_TYPES:
        raise validation("source_type", "enum", "不支持的信息源类型")
    return value


def ensure_range(
    value: int, *, field: str, minimum: int, maximum: int
) -> int:
    if value < minimum or value > maximum:
        raise validation(field, "range", f"必须在 {minimum}–{maximum} 之间")
    return value


def optional_credibility(raw: int | None) -> int | None:
    if raw is None:
        return None
    return ensure_range(raw, field="credibility_score", minimum=0, maximum=100)


def details(*items: ErrorDetail) -> list[ErrorDetail]:
    return list(items)
