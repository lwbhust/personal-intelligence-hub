"""Extractive, evidence-based event summaries.

No model call: the summary is assembled from member article summaries with
explicit source attribution. This cannot introduce facts that are absent from
the evidence. A manual summary may override it (stored separately).
"""

from __future__ import annotations

from .text import normalize_text

MAX_SUMMARY_CHARS = 2000
MAX_PIECE_CHARS = 600


def _piece(source: str | None, text: str) -> str:
    clean = normalize_text(text)[:MAX_PIECE_CHARS]
    if not clean:
        return ""
    source_name = normalize_text(source)[:80] or "未知来源"
    return f"据{source_name}报道：{clean}"


def build_event_summary(
    event_title: str,
    articles: list[tuple[str | None, str | None, str | None]],
) -> str:
    """Build a summary from ``(source_name, summary, title)`` evidence rows."""

    pieces: list[str] = []
    texts: set[str] = set()
    for source, summary, title in articles:
        candidate = summary or title
        if not candidate:
            continue
        key = normalize_text(candidate)
        if not key or key in texts:
            continue
        texts.add(key)
        piece = _piece(source, candidate)
        if piece:
            pieces.append(piece)
        if len(pieces) >= 2:
            break

    if not pieces:
        return normalize_text(event_title)[:MAX_SUMMARY_CHARS] or "暂无可用摘要"

    if len(articles) > 1:
        pieces.append(f"该事件共有 {len(articles)} 篇相关报道。")
    return normalize_text(" ".join(pieces))[:MAX_SUMMARY_CHARS]


def timeline_description(summary: str | None, title: str | None) -> str:
    text = normalize_text(summary) or normalize_text(title)
    return text[:2000]
