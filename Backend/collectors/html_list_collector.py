"""HTML list-page collector for official sources without RSS.

The collector only performs HTTP GETs through `NetGuard` (robots, SSRF and
size limits apply). It extracts candidate article links from one or more list
pages, then reads each detail page for title, publish date and body text.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from math import ceil
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from collectors.feed_parser import ParsedEntry
from collectors.net_guard import NetGuard, NetGuardError

HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_SUMMARY = 1200
MAX_CONTENT = 200_000

_DATE_RE = re.compile(
    r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
_CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class AdapterFetchResult:
    entries: tuple[ParsedEntry, ...]
    http_status: int | None
    errors: tuple[str, ...]


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): (value or "") for key, value in attrs}
        if values.get("href"):
            self._href = values["href"]
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._parts).split())
            self.anchors.append((self._href, text))
            self._href = None
            self._parts = []


class _DetailParser(HTMLParser):
    """Extract meta/title/h1/body and the most likely article container."""

    _VOID = {"br", "img", "hr", "input", "meta", "link", "source", "area", "base"}
    _SKIP = {
        "script", "style", "noscript", "iframe", "svg", "math",
        "nav", "header", "footer", "aside", "form",
    }
    _HINT = re.compile(r"(article|content|main|detail|text|zoom|body|post|news)", re.I)
    _BAD = re.compile(
        r"(nav|menu|footer|header|side|share|comment|related|recommend|advert|breadcrumb)",
        re.I,
    )
    _BLOCK = {
        "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "section", "article", "td",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.h1 = ""
        self._in_title = False
        self._in_h1 = False
        self._skip_depth = 0
        self._stack: list[dict[str, object]] = []
        self._candidates: list[str] = []
        self._body: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        values = {key.lower(): (value or "") for key, value in attrs}
        if lowered == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and values.get("content"):
                self.meta.setdefault(key, values["content"])
            return
        if lowered in self._VOID:
            return
        if lowered in self._SKIP:
            self._skip_depth += 1
            return
        if lowered == "title":
            self._in_title = True
        if lowered == "h1":
            self._in_h1 = True
        if lowered in self._BLOCK:
            self._body.append("\n")
        identity = f"{values.get('id', '')} {values.get('class', '')}"
        candidate = bool(self._HINT.search(identity)) and not bool(
            self._BAD.search(identity)
        )
        self._stack.append(
            {
                "tag": lowered,
                "candidate": candidate,
                "parts": [],
                "length": 0,
            }
        )

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.h1 += data
        if data.strip():
            self._body.append(data)
        for frame in self._stack:
            if frame["candidate"]:
                frame["parts"].append(data)  # type: ignore[union-attr]
                frame["length"] = int(frame["length"]) + len(data.strip())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._VOID:
            return
        if lowered in self._SKIP:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if lowered == "title":
            self._in_title = False
        if lowered == "h1":
            self._in_h1 = False
        if lowered in self._BLOCK:
            self._body.append("\n")
        if not self._stack:
            return
        frame = self._stack.pop()
        if frame["candidate"] and int(frame["length"]) > 200:
            self._candidates.append("".join(frame["parts"]))  # type: ignore[arg-type]

    def content(self) -> str:
        if self._candidates:
            best = max(self._candidates, key=len)
            if len(best.strip()) > 200:
                return _clean(best)
        return _clean("".join(self._body))


def _clean(value: str) -> str:
    return " ".join(value.replace("\u3000", " ").split()).strip()


def _normalise_date(raw: str | None) -> str | None:
    if not raw:
        return None
    match = _DATE_RE.search(raw)
    if match is None:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        if hour is None:
            moment = datetime(
                int(year), int(month), int(day), tzinfo=_CN_TZ
            )
        else:
            # Chinese sources publish in Asia/Shanghai; store UTC.
            moment = datetime(
                int(year), int(month), int(day),
                int(hour), int(minute or 0), int(second or 0),
                tzinfo=_CN_TZ,
            )
        return (
            moment.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    except ValueError:
        return None


def _title_from_html(parser: _DetailParser) -> str:
    candidates = [
        parser.meta.get("og:title"),
        parser.h1,
        parser.title,
    ]
    for value in candidates:
        text = _clean(value or "")
        if not text:
            continue
        for separator in ("---", "--", "——", " - ", "_", "|"):
            if separator in text:
                head = text.split(separator, 1)[0].strip()
                if len(head) >= 6:
                    text = head
                    break
        return text[:500]
    return ""


class HtmlListCollector:
    def __init__(self, guard: NetGuard) -> None:
        self.guard = guard

    def collect(
        self,
        *,
        list_urls: list[str],
        link_pattern: str,
        max_entries: int,
        rate_limit_seconds: int,
        fetch_full_text: bool,
        max_pages: int = 1,
    ) -> AdapterFetchResult:
        try:
            pattern = re.compile(link_pattern)
        except re.error as exc:
            raise NetGuardError(
                "invalid_pattern", f"link_pattern 无效：{exc}"
            ) from exc

        errors: list[str] = []
        candidates: list[str] = []
        last_status: int | None = None
        quota = max(1, ceil(max_entries / max(1, len(list_urls))))

        for index, list_url in enumerate(list_urls):
            if index:
                time.sleep(rate_limit_seconds)
            page_url = list_url
            visited: set[str] = set()
            collected_for_list = 0
            page_no = 0
            while (
                page_url
                and page_no < max(1, max_pages)
                and page_url not in visited
                and collected_for_list < quota
            ):
                visited.add(page_url)
                if page_no:
                    time.sleep(rate_limit_seconds)
                try:
                    response = self.guard.fetch(
                        page_url,
                        allowed_content_types=HTML_CONTENT_TYPES,
                        max_bytes=MAX_HTML_BYTES,
                    )
                    last_status = response.status_code
                    links = self._extract_links(
                        response.body, response.final_url, pattern
                    )
                    if not links and page_no == 0:
                        errors.append(f"{list_url}: 列表页未匹配到文章链接")
                    for link in links:
                        if link not in candidates:
                            candidates.append(link)
                            collected_for_list += 1
                        if collected_for_list >= quota:
                            break
                    page_url = self._find_next_page(
                        response.body, response.final_url, visited
                    )
                except NetGuardError as exc:
                    errors.append(f"{page_url}: {exc.code}: {exc.message}"[:300])
                    break
                except Exception as exc:  # noqa: BLE001 - per-list isolation
                    errors.append(f"{page_url}: {type(exc).__name__}"[:300])
                    break
                page_no += 1

        entries: list[ParsedEntry] = []
        for index, url in enumerate(candidates[: max_entries * 2]):
            if len(entries) >= max_entries:
                break
            if index:
                time.sleep(rate_limit_seconds)
            try:
                response = self.guard.fetch(
                    url,
                    allowed_content_types=HTML_CONTENT_TYPES,
                    max_bytes=MAX_HTML_BYTES,
                )
                last_status = response.status_code
                entry = self._parse_entry(
                    response.body,
                    response.final_url or url,
                    fetch_full_text=fetch_full_text,
                )
                if entry is not None:
                    entries.append(entry)
            except NetGuardError as exc:
                errors.append(f"{url}: {exc.code}: {exc.message}"[:300])
            except Exception as exc:  # noqa: BLE001 - per-article isolation
                errors.append(f"{url}: {type(exc).__name__}"[:300])

        entries.sort(key=lambda item: item.published_at or "", reverse=True)
        return AdapterFetchResult(
            entries=tuple(entries[:max_entries]),
            http_status=last_status,
            errors=tuple(errors[:30]),
        )

    @staticmethod
    def _find_next_page(body: bytes, base_url: str, visited: set[str]) -> str | None:
        html = body.decode("utf-8", errors="ignore")
        if "�" in html:
            html = body.decode("gb18030", errors="ignore")
        parser = _AnchorParser()
        parser.feed(html)
        host = urlsplit(base_url).hostname
        current = HtmlListCollector._page_number(base_url)
        best: tuple[int, str] | None = None
        for href, text in parser.anchors:
            absolute = urljoin(base_url, href.strip())
            parts = urlsplit(absolute)
            if parts.scheme not in ("http", "https") or parts.hostname != host:
                continue
            if absolute in visited:
                continue
            label = text.strip().lower()
            if label in {"下一页", "下页", "next", "next page", ">", "›", "»"}:
                return absolute
            if text.strip().isdigit() and HtmlListCollector._is_pagination_href(absolute):
                number = int(text.strip())
                if number > current and (best is None or number < best[0]):
                    best = (number, absolute)
        return None if best is None else best[1]

    @staticmethod
    def _is_pagination_href(url: str) -> bool:
        return bool(
            re.search(r"(index_\d+|-\d+\.html|page=\d+|/page/\d+)", url, re.I)
        )

    @staticmethod
    def _page_number(url: str) -> int:
        match = re.search(r"index_(\d+)", url, re.I)
        if match:
            return int(match.group(1)) + 1
        match = re.search(r"(?:-|page=|/page/)(\d+)", url, re.I)
        if match:
            return int(match.group(1))
        return 1

    @staticmethod
    def _extract_links(body: bytes, base_url: str, pattern: re.Pattern[str]) -> list[str]:
        html = body.decode("utf-8", errors="ignore")
        if "�" in html:
            html = body.decode("gb18030", errors="ignore")
        parser = _AnchorParser()
        parser.feed(html)
        host = urlsplit(base_url).hostname
        seen: set[str] = set()
        links: list[str] = []
        for href, text in parser.anchors:
            if len(text) < 6:
                continue
            absolute = urljoin(base_url, href.strip())
            parts = urlsplit(absolute)
            if parts.scheme not in ("http", "https") or parts.hostname != host:
                continue
            if not pattern.search(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return links

    @staticmethod
    def _parse_entry(
        body: bytes,
        url: str,
        *,
        fetch_full_text: bool,
    ) -> ParsedEntry | None:
        html = body.decode("utf-8", errors="ignore")
        if "�" in html:
            html = body.decode("gb18030", errors="ignore")
        parser = _DetailParser()
        parser.feed(html)
        title = _title_from_html(parser)
        if not title:
            return None
        content = parser.content()[:MAX_CONTENT]
        date_raw = (
            parser.meta.get("article:published_time")
            or parser.meta.get("pubdate")
            or parser.meta.get("publishdate")
            or parser.meta.get("date")
        )
        published_at = _normalise_date(date_raw)
        if published_at is None:
            match = _DATE_RE.search(html[:20000])
            if match is not None:
                published_at = _normalise_date(match.group(0))
        summary = content[:MAX_SUMMARY] if content else None
        full = content if fetch_full_text and content else None
        if full:
            state = "full"
        elif summary:
            state = "summary_only"
        else:
            state = "unavailable"
        return ParsedEntry(
            external_id=None,
            link=url,
            title=title,
            author=None,
            summary=summary,
            content=full,
            content_state=state,
            published_at=published_at,
            source_updated_at=None,
            truncated=False,
        )
