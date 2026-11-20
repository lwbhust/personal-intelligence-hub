"""Feed parsing / normalisation regression tests (fixed local samples)."""

from __future__ import annotations

import pytest

from collectors.feed_parser import FeedParseError, PLACEHOLDER_TITLE, html_to_text, parse_feed
from collectors.normalize import canonicalize_url, content_fingerprint

RSS2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Example Feed</title>
    <item>
      <title><![CDATA[Hello &amp; World]]></title>
      <link>https://example.com/post/1?utm_source=rss&amp;b=2&amp;a=1</link>
      <guid isPermaLink="false">guid-1</guid>
      <author>alice@example.com (Alice)</author>
      <description><![CDATA[<p>Short <b>summary</b></p>]]></description>
      <content:encoded><![CDATA[<div><p>Full <b>body</b></p><script>alert(1)</script></div>]]></content:encoded>
      <pubDate>Mon, 16 Nov 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Summary only</title>
      <link>https://example.com/post/2</link>
      <guid>guid-2</guid>
      <description>Just a summary</description>
    </item>
    <item>
      <link>https://example.com/post/3</link>
      <guid>guid-3</guid>
      <description></description>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom entry</title>
    <link href="https://example.org/a/1"/>
    <id>tag:example.org,2026:1</id>
    <updated>2026-11-16T09:30:00Z</updated>
    <author><name>Bob</name></author>
    <content type="html">&lt;p&gt;Atom body&lt;/p&gt;</content>
    <summary>Atom summary</summary>
  </entry>
</feed>
"""


def test_entry_title_is_plain_text() -> None:
    feed = parse_feed(
        b"<?xml version='1.0'?><rss version='2.0'><channel><title>T</title>"
        b"<item><title>&lt;script&gt;alert(1)&lt;/script&gt;Real title</title>"
        b"<link>javascript:alert(1)</link><guid>id-1</guid></item>"
        b"</channel></rss>"
    )
    title = feed.entries[0].title
    assert title == "Real title"
    assert "<" not in title


def test_rss2_maps_fields_and_extracts_text() -> None:
    feed = parse_feed(RSS2)
    assert feed.feed_type == "rss"
    assert feed.title == "Example Feed"
    assert len(feed.entries) == 3

    first = feed.entries[0]
    assert first.title == "Hello & World"
    assert first.external_id == "guid-1"
    assert first.content_state == "full"
    assert first.content is not None and "Full body" in first.content
    assert "script" not in first.content.lower()
    assert first.summary == "Short summary"
    assert first.published_at == "2026-11-16T08:00:00.000Z"
    assert first.author == "alice@example.com (Alice)"

    second = feed.entries[1]
    assert second.content_state == "summary_only"
    assert second.content is not None and "Just a summary" in second.content

    third = feed.entries[2]
    assert third.title == PLACEHOLDER_TITLE
    assert third.content_state == "unavailable"


def test_atom_maps_fields() -> None:
    feed = parse_feed(ATOM)
    assert feed.feed_type == "atom"
    entry = feed.entries[0]
    assert entry.title == "Atom entry"
    assert entry.link == "https://example.org/a/1"
    assert entry.external_id == "tag:example.org,2026:1"
    assert entry.author == "Bob"
    assert entry.content_state == "full"
    assert entry.content == "Atom body"
    assert entry.source_updated_at == "2026-11-16T09:30:00.000Z"


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>",
        b"not xml at all",
    ],
)
def test_unusable_payloads_raise(payload: bytes) -> None:
    with pytest.raises(FeedParseError):
        parse_feed(payload)


def test_malformed_xml_is_tolerated_only_when_entries_exist() -> None:
    """feedparser may recover real-world malformed feeds; it must never crash."""

    feed = parse_feed(
        b"<?xml version='1.0'?><rss><channel><item><title>x</title></channel></rss>"
    )
    assert feed.entries[0].title == "x"


@pytest.mark.parametrize(
    "payload",
    [
        b"""<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <rss version="2.0"><channel><title>&xxe;</title></channel></rss>""",
        b"""<?xml version="1.0"?><!ENTITY boom "x">""",
    ],
)
def test_dtd_and_entities_are_rejected(payload: bytes) -> None:
    with pytest.raises(FeedParseError) as error:
        parse_feed(payload)
    assert error.value.code == "xml_parse_error"


def test_oversized_feed_is_rejected() -> None:
    with pytest.raises(FeedParseError) as error:
        parse_feed(b"<rss>" + b"x" * (3 * 1024 * 1024) + b"</rss>")
    assert error.value.code == "response_too_large"


def test_html_to_text_removes_scripts() -> None:
    assert html_to_text("<p>a</p><script>evil()</script><p>b</p>") == "a\nb"
    assert html_to_text("plain  text") == "plain text"
    assert html_to_text(None) is None


def test_duplicate_entries_are_kept_for_dedup_layer() -> None:
    feed = parse_feed(RSS2)
    assert len([e for e in feed.entries if e.external_id == "guid-1"]) == 1
    # Parser must not silently merge; dedup belongs to the service layer.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443/Post/?utm_source=x&b=2&a=1#frag", "https://example.com/Post?a=1&b=2"),
        ("http://example.com:80", "http://example.com/"),
        ("http://example.com/a//b///", "http://example.com/a/b"),
        ("http://example.com/x?fbclid=1&gclid=2", "http://example.com/x"),
        ("ftp://example.com/x", None),
        ("javascript:alert(1)", None),
        ("http://user:pw@example.com/x", None),
        ("", None),
        (None, None),
    ],
)
def test_canonicalize_url(raw: str | None, expected: str | None) -> None:
    assert canonicalize_url(raw) == expected


def test_fingerprint_is_stable_across_whitespace() -> None:
    first = content_fingerprint(title="Title", body="a  b\n c", published_at="2026-01-01T00:00:00.000Z")
    second = content_fingerprint(title="Title", body="a b c", published_at="2026-01-01T00:00:00.000Z")
    assert first == second
    assert len(first) == 64
    third = content_fingerprint(title="Title", body="different", published_at=None)
    assert third != first
