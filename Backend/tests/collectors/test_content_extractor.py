"""Main-text extraction is conservative and never invents prose."""

from __future__ import annotations

from collectors.content_extractor import extract_main_text

_BODY = "这是一段关于电力系统智能调度的正文内容。" * 20


def test_extracts_paragraphs_and_skips_navigation() -> None:
    html = f"""
    <html><head><title>标题</title></head>
    <body>
      <nav>首页 新闻 关于我们</nav>
      <script>var tracking = 1;</script>
      <article>
        <h1>智能调度系统上线</h1>
        <p>{_BODY}</p>
        <p>第二段补充说明。</p>
      </article>
      <footer>版权所有</footer>
    </body></html>
    """.encode("utf-8")

    text = extract_main_text(html, "text/html; charset=utf-8")
    assert text is not None
    assert "智能调度系统上线" in text
    assert "首页 新闻" not in text
    assert "var tracking" not in text
    assert "版权所有" not in text


def test_returns_none_for_short_pages() -> None:
    html = b"<html><body><p>too short</p></body></html>"
    assert extract_main_text(html, "text/html") is None


def test_returns_none_for_non_html() -> None:
    assert extract_main_text(b"%PDF-1.7 ...", "application/pdf") is None


def test_decodes_gb18030_page() -> None:
    html = (
        "<html><head><meta charset='gb18030'></head><body><article><p>"
        + _BODY
        + "</p></article></body></html>"
    ).encode("gb18030")
    text = extract_main_text(html, "text/html")
    assert text is not None
    assert "电力系统" in text
