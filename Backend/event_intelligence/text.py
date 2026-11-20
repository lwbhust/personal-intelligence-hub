"""Deterministic text normalisation and similarity helpers.

Chinese text is represented by character bigrams (single characters for
one-character runs), Latin text by lower-cased word tokens. No tokenizer
dependency and no FTS5: Phase 4 must work without the Phase 5 search stack.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*", re.IGNORECASE)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "it", "its", "will", "has", "have",
    "had", "not", "but", "than", "then", "so", "we", "they", "he", "she",
    "的", "了", "和", "与", "在", "是", "为", "对", "从", "到", "将",
    "并", "及", "等", "中", "上", "下", "这", "那", "其", "也", "都",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _SPACE_RE.sub(" ", text).strip()


def tokens(value: str | None) -> frozenset[str]:
    """Return normalized token set used by every similarity signal."""

    text = normalize_text(value).lower()
    if not text:
        return frozenset()

    result: set[str] = set()
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            if run not in _STOPWORDS:
                result.add(run)
            continue
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            if bigram not in _STOPWORDS:
                result.add(bigram)
    for word in _WORD_RE.findall(text):
        word = word.strip("._+-")
        if len(word) >= 2 and word not in _STOPWORDS and not _CJK_RE.search(word):
            result.add(word)
    return frozenset(result)


def jaccard(left: frozenset[str] | set[str], right: frozenset[str] | set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return round(len(left & right) / len(union), 4)


def title_similarity(left: str | None, right: str | None) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    token_score = jaccard(left_tokens, right_tokens)

    left_text = normalize_text(left).lower()
    right_text = normalize_text(right).lower()
    if not left_text or not right_text:
        return round(token_score, 4)

    # SequenceMatcher is quadratic; cap the inputs so a malformed 20k title
    # cannot stall the single clustering worker.
    left_text = left_text[:500]
    right_text = right_text[:500]
    import difflib

    ratio = difflib.SequenceMatcher(None, left_text, right_text).ratio()
    return round(0.6 * token_score + 0.4 * ratio, 4)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def hours_between(earlier: str | None, later: str | None) -> float | None:
    left = parse_timestamp(earlier)
    right = parse_timestamp(later)
    if left is None or right is None:
        return None
    return (right - left).total_seconds() / 3600.0


def time_decay(article_published_at: str | None, event_published_at: str | None) -> float:
    """Time proximity between an article and an event's latest article."""

    hours = hours_between(event_published_at, article_published_at)
    if hours is None:
        return 0.5
    hours = abs(hours)
    if hours <= 72:
        return 1.0
    if hours <= 24 * 7:
        return 0.6
    if hours <= 24 * 30:
        return 0.3
    return 0.1


def content_family_key(content_hash: str | None, title: str | None) -> str:
    """Stable de-duplication key for heat/coverage.

    Prefer the content hash; fall back to the normalized title so reposts with
    an empty hash still collapse.
    """

    if content_hash:
        return "h:" + content_hash
    normalized = "".join(ch for ch in normalize_text(title).lower() if ch.isalnum())
    return "t:" + normalized[:200]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def log2p(value: float) -> float:
    return math.log2(max(0.0, value) + 1.0)
