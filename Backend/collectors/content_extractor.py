"""Readable main-text extraction for on-demand article body retrieval.

The extractor is deliberately conservative: it never fabricates body text. When
the page has too little prose it returns `None` and the caller keeps the RSS
summary and marks the article as `summary_only`.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

MIN_CONTENT_CHARS = 200
MAX_CONTENT_CHARS = 200_000

_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?\s*([a-zA-Z0-9_\-]+)", re.I)
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([a-zA-Z0-9_\-]+)", re.I)


class _TextParser(HTMLParser):
    _VOID = {"br", "img", "hr", "input", "meta", "link", "source", "area", "base"}
    _SKIP = {
        "script", "style", "noscript", "iframe", "svg", "math",
        "nav", "header", "footer", "aside", "form", "button", "select",
    }
    _BLOCK = {
        "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "section", "article", "td", "br",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_charset: str | None = None
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "meta":
            values = {key.lower(): (value or "") for key, value in attrs}
            charset = values.get("charset")
            if charset and self.meta_charset is None:
                self.meta_charset = charset
            return
        if lowered in self._VOID:
            if lowered == "br":
                self._parts.append("\n")
            return
        if lowered in self._SKIP:
            self._skip_depth += 1
            return
        if lowered in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._VOID:
            return
        if lowered in self._SKIP:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if lowered in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts).replace("\u3000", " ")
        paragraphs: list[str] = []
        for block in raw.split("\n"):
            line = " ".join(block.split())
            if len(line) >= 2:
                paragraphs.append(line)
        return "\n\n".join(paragraphs).strip()


def _decode(body: bytes, content_type: str | None, parser: _TextParser) -> str:
    charset = None
    if content_type:
        match = _CHARSET_RE.search(content_type)
        if match:
            charset = match.group(1)
    if charset is None and parser.meta_charset:
        charset = parser.meta_charset
    if charset is None:
        match = _META_CHARSET_RE.search(body[:4096])
        if match:
            charset = match.group(1).decode("ascii", errors="ignore")
    candidates = [charset, "utf-8", "gb18030"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return body.decode(candidate, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def extract_main_text(body: bytes, content_type: str | None = None) -> str | None:
    """Return cleaned main prose or `None` when the page has too little text."""

    if not body:
        return None
    if content_type:
        lowered = content_type.lower()
        if lowered and "html" not in lowered and "xml" not in lowered:
            return None
    parser = _TextParser()
    try:
        parser.feed(_decode(body, content_type, parser))
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML must not break the request
        return None
    text = parser.text()
    if len(text) < MIN_CONTENT_CHARS:
        return None
    return text[:MAX_CONTENT_CHARS]
