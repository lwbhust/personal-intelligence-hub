"""Safe RSS 2.0 / Atom parsing.

Defence in depth:
* no `<!DOCTYPE` / `<!ENTITY` (XXE and entity expansion are rejected up front);
* a defusedxml well-formedness gate with DTD/entity protection;
* feedparser is used only for tolerant field mapping, never for fetching;
* entries are capped, all strings are length-limited, and HTML is converted to
  plain text before it can reach the UI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

import feedparser
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 100
MAX_TITLE = 500
MAX_SUMMARY = 8000
MAX_CONTENT = 200_000
MAX_AUTHOR = 200
MAX_EXTERNAL_ID = 512
PLACEHOLDER_TITLE = "(无标题)"


class FeedParseError(Exception):
    """Stable collection error code for unusable feed payloads."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    external_id: str | None
    link: str | None
    title: str
    author: str | None
    summary: str | None
    content: str | None
    content_state: str
    published_at: str | None
    source_updated_at: str | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    title: str | None
    feed_type: str
    entries: tuple[ParsedEntry, ...]
    entry_count: int
    truncated: bool


class _TextExtractor(HTMLParser):
    """Convert untrusted HTML into plain text without executing anything."""

    _SKIP = {"script", "style", "noscript", "iframe", "object", "embed", "svg", "math"}
    _BREAK = {
        "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "section", "article", "header", "footer",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP:
            self._skip_depth += 1
        elif lowered in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif lowered in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(value: str | None, *, limit: int = MAX_CONTENT) -> str | None:
    """Strip tags/scripts and collapse whitespace; never raise on bad HTML."""

    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "<" not in raw and ">" not in raw:
        return _clean_whitespace(unescape(raw))[:limit] or None
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = parser.text()
    except Exception:  # noqa: BLE001 - malformed markup must not break collection
        text = raw
    cleaned = _clean_whitespace(text)
    return cleaned[:limit] or None


def _clean_whitespace(value: str) -> str:
    lines = []
    for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        collapsed = " ".join(line.split())
        if collapsed:
            lines.append(collapsed)
    return "\n".join(lines)


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = _clean_whitespace(unescape(value))
    if not cleaned:
        return None
    return cleaned[:limit]


def _iso_utc(struct_time: time.struct_time | None) -> str | None:
    if struct_time is None:
        return None
    try:
        moment = datetime(
            struct_time.tm_year,
            struct_time.tm_mon,
            struct_time.tm_mday,
            struct_time.tm_hour,
            struct_time.tm_min,
            struct_time.tm_sec,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _select_content(entry: dict) -> tuple[str | None, str]:
    """Return (content_text, content_state) using feed-provided values only."""

    blocks = entry.get("content") or []
    best: str | None = None
    for block in blocks:
        value = block.get("value") if isinstance(block, dict) else None
        if not value:
            continue
        text = html_to_text(str(value))
        if text and (best is None or len(text) > len(best)):
            best = text
    if best:
        return best[:MAX_CONTENT], "full"
    summary = entry.get("summary")
    summary_text = html_to_text(str(summary)) if summary else None
    if summary_text:
        return summary_text[:MAX_CONTENT], "summary_only"
    return None, "unavailable"


def parse_feed(body: bytes) -> ParsedFeed:
    if not body:
        raise FeedParseError("feed_empty", "Feed 内容为空")
    if len(body) > MAX_FEED_BYTES:
        raise FeedParseError("response_too_large", "Feed 超出大小上限")

    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FeedParseError("xml_parse_error", "Feed 含不允许的 DTD 或实体声明")
    if not body.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        raise FeedParseError("xml_parse_error", "Feed 响应不是 XML 文档")

    try:
        DefusedET.fromstring(body)
    except DefusedXmlException as exc:
        raise FeedParseError("xml_parse_error", "Feed 含不允许的 XML 构造") from exc
    except Exception:  # noqa: BLE001 - feedparser may still recover; checked below
        pass

    parsed = feedparser.parse(body)
    feed_type = "atom" if parsed.get("version", "").startswith("atom") else "rss"
    raw_entries = list(parsed.get("entries") or [])
    if parsed.get("bozo") and not raw_entries:
        raise FeedParseError("xml_parse_error", "Feed XML 无法解析")
    if not raw_entries:
        raise FeedParseError("feed_empty", "Feed 没有可用条目")

    entries: list[ParsedEntry] = []
    for entry in raw_entries[:MAX_ENTRIES]:
        external_id = entry.get("id") or entry.get("guid")
        title_raw = entry.get("title")
        title = html_to_text(str(title_raw), limit=MAX_TITLE) if title_raw else None
        author_raw = entry.get("author")
        if not author_raw:
            detail = entry.get("author_detail")
            if isinstance(detail, dict):
                author_raw = detail.get("name")
        content_text, content_state = _select_content(entry)
        summary_raw = entry.get("summary")
        summary = html_to_text(str(summary_raw), limit=MAX_SUMMARY) if summary_raw else None
        if summary is None and content_text is not None:
            summary = html_to_text(content_text, limit=MAX_SUMMARY)

        entries.append(
            ParsedEntry(
                external_id=_clip(str(external_id), MAX_EXTERNAL_ID) if external_id else None,
                link=(str(entry.get("link")).strip()[:2048] if entry.get("link") else None),
                title=title or PLACEHOLDER_TITLE,
                author=_clip(str(author_raw), MAX_AUTHOR) if author_raw else None,
                summary=summary[:MAX_SUMMARY] if summary else None,
                content=content_text,
                content_state=content_state,
                published_at=_iso_utc(entry.get("published_parsed")),
                source_updated_at=_iso_utc(entry.get("updated_parsed")),
                truncated=len(raw_entries) > MAX_ENTRIES,
            )
        )

    return ParsedFeed(
        title=_clip(str(parsed.get("feed", {}).get("title") or "") or None, 200),
        feed_type=feed_type,
        entries=tuple(entries),
        entry_count=len(raw_entries),
        truncated=len(raw_entries) > MAX_ENTRIES,
    )
