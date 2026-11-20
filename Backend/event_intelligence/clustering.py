"""Deterministic article-to-event scoring and guards (`event-cluster-v1`)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import (
    hours_between,
    jaccard,
    normalize_text,
    time_decay,
    title_similarity,
)

ATTACH_THRESHOLD = 0.70
AMBIGUOUS_THRESHOLD = 0.55
MAX_EVENT_GAP_HOURS = 24 * 30
# Two explicit but different event entities ("第三季度财报" vs "第四季度财报")
# are strong negative evidence, so the pair must not attach on title/keyword
# similarity alone.
DISJOINT_EVENT_ENTITY_FACTOR = 0.6

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Explicit, mutually exclusive markers. When two titles carry different values
# of the same marker family they describe different events even if the wording
# is otherwise almost identical (e.g. "第三季度财报" vs "第四季度财报").
_QUARTER_PATTERNS = (
    re.compile(r"(?:^|[^a-z0-9])q([1-4])(?:[^0-9]|$)", re.IGNORECASE),
    re.compile(r"([1-4])q(?:[^a-z0-9]|$)", re.IGNORECASE),
    re.compile(r"第?([一二三四1234])季度"),
    re.compile(r"(?:上半年|half\s*1|h1)", re.IGNORECASE),
    re.compile(r"(?:下半年|half\s*2|h2)", re.IGNORECASE),
)
_CN_DIGITS = {"一": "1", "二": "2", "三": "3", "四": "4", "1": "1", "2": "2", "3": "3", "4": "4"}
_CONFLICTING_WORDS = (
    ("裁员", "招聘"),
    ("收购", "出售"),
    ("盈利", "亏损"),
    ("涨价", "降价"),
    ("上市", "退市"),
    ("合作", "诉讼"),
    ("发布", "召回"),
    ("开源", "闭源"),
    ("增持", "减持"),
)


def _period_markers(value: str | None) -> set[str]:
    text = value or ""
    found: set[str] = set()
    for index, pattern in enumerate(_QUARTER_PATTERNS):
        for match in pattern.finditer(text):
            token = match.group(1) if match.lastindex else None
            if index >= 3:
                found.add("h1" if index == 3 else "h2")
            elif token:
                found.add(_CN_DIGITS.get(token, token))
    return found


def conflicting_event_markers(left: str | None, right: str | None) -> bool:
    """True when two titles carry contradictory period or event markers."""

    left_periods = _period_markers(left)
    right_periods = _period_markers(right)
    if left_periods and right_periods and left_periods.isdisjoint(right_periods):
        return True
    left_text = left or ""
    right_text = right or ""
    for first, second in _CONFLICTING_WORDS:
        if (first in left_text and second in right_text) or (
            second in left_text and first in right_text
        ):
            return True
    return False


def _language(value: str | None) -> str:
    text = value or ""
    has_cjk = bool(_CJK_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_cjk and not has_latin:
        return "zh"
    if has_latin and not has_cjk:
        return "en"
    return "mixed"


def _cross_language(left: str | None, right: str | None) -> bool:
    return {_language(left), _language(right)} == {"zh", "en"}

WEIGHTS = {
    "entity": 0.30,
    "keyword": 0.20,
    "title": 0.22,
    "summary": 0.08,
    "time": 0.08,
    "category": 0.07,
    "source": 0.05,
}


@dataclass(frozen=True, slots=True)
class ArticleFeatures:
    id: str
    title: str
    summary: str | None
    published_at: str | None
    source_id: str
    category: str | None
    keywords: frozenset[str] = field(default_factory=frozenset)
    entity_ids: frozenset[str] = field(default_factory=frozenset)
    entity_keys: frozenset[str] = field(default_factory=frozenset)
    event_entity_ids: frozenset[str] = field(default_factory=frozenset)
    event_entity_keys: frozenset[str] = field(default_factory=frozenset)
    content_hash: str = ""


@dataclass(frozen=True, slots=True)
class EventFeatures:
    id: str
    title: str
    summary: str | None
    category: str | None
    entity_ids: frozenset[str] = field(default_factory=frozenset)
    entity_keys: frozenset[str] = field(default_factory=frozenset)
    event_entity_ids: frozenset[str] = field(default_factory=frozenset)
    event_entity_keys: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)
    member_article_ids: tuple[str, ...] = ()
    member_titles: tuple[str, ...] = ()
    member_summaries: tuple[str, ...] = ()
    member_content_hashes: tuple[str, ...] = ()
    source_ids: frozenset[str] = field(default_factory=frozenset)
    first_published_at: str | None = None
    last_published_at: str | None = None
    article_count: int = 0
    is_manual: bool = False


@dataclass(frozen=True, slots=True)
class PairScore:
    total: float
    entity: float
    keyword: float
    title: float
    summary: float
    time: float
    category: float
    source: float
    decision: str
    reasons: tuple[str, ...] = ()
    strong: float = 0.0
    shared_event_entity: bool = False

    def components(self) -> dict[str, float]:
        return {
            "entity": self.entity,
            "keyword": self.keyword,
            "title": self.title,
            "summary": self.summary,
            "time": self.time,
            "category": self.category,
            "source": self.source,
            "strong": self.strong,
        }


def _max_similarity(value: str | None, candidates: tuple[str, ...]) -> float:
    best = 0.0
    for candidate in candidates:
        if not candidate:
            continue
        best = max(best, title_similarity(value, candidate))
    return round(best, 4)


def _summary_similarity(article: ArticleFeatures, event: EventFeatures) -> float:
    if not article.summary:
        return 0.0
    candidates = list(event.member_summaries)
    if event.summary:
        candidates.insert(0, event.summary)
    return _max_similarity(article.summary, tuple(candidates[:3]))


def _entity_score(article: ArticleFeatures, event: EventFeatures) -> float:
    if article.entity_ids and event.entity_ids:
        return jaccard(article.entity_ids, event.entity_ids)
    return jaccard(article.entity_keys, event.entity_keys)


def decide(
    *,
    total: float,
    entity: float,
    keyword: float,
    title: float,
    category_same: bool,
    gap_hours: float | None,
    already_member: bool = False,
    exact_content: bool = False,
    shared_event_entity: bool = False,
) -> str:
    if already_member:
        return "skipped"
    if exact_content:
        return "attach"
    if gap_hours is not None and gap_hours > MAX_EVENT_GAP_HOURS:
        return "separate"
    if entity < 0.20 and title < 0.70:
        return "separate"
    if (
        entity >= 0.50
        and title < 0.35
        and keyword < 0.25
        and not shared_event_entity
    ):
        return "separate"
    if not category_same and title < 0.60:
        return "separate"
    if total >= ATTACH_THRESHOLD:
        return "attach"
    if total >= AMBIGUOUS_THRESHOLD:
        return "ambiguous"
    return "separate"


def score_article_against_event(
    article: ArticleFeatures, event: EventFeatures
) -> PairScore:
    already_member = article.id in event.member_article_ids
    exact_content = bool(
        article.content_hash and article.content_hash in event.member_content_hashes
    )

    entity = 0.0 if exact_content else _entity_score(article, event)
    keyword = 0.0 if exact_content else jaccard(article.keywords, event.keywords)
    shared_event_ids = article.event_entity_ids & event.event_entity_ids
    shared_event_keys = article.event_entity_keys & event.event_entity_keys
    shared_event_entity = bool(shared_event_ids or shared_event_keys)
    strong = 1.0 if shared_event_ids else (0.5 if shared_event_keys else 0.0)
    titles = (event.title, *event.member_titles[:3])
    title = 1.0 if exact_content else _max_similarity(article.title, titles)
    summary = 0.0 if exact_content else _summary_similarity(article, event)
    time_score = (
        1.0
        if exact_content
        else time_decay(article.published_at, event.last_published_at)
    )
    category_same = bool(article.category and event.category and article.category == event.category)
    category = 1.0 if category_same else 0.25
    source = 1.0 if article.source_id not in event.source_ids else 0.4
    gap = hours_between(event.last_published_at, article.published_at)
    gap_hours = None if gap is None else abs(gap)

    total = round(
        WEIGHTS["entity"] * entity
        + WEIGHTS["keyword"] * keyword
        + WEIGHTS["title"] * title
        + WEIGHTS["summary"] * summary
        + WEIGHTS["time"] * time_score
        + WEIGHTS["category"] * category
        + WEIGHTS["source"] * source,
        4,
    )
    has_event_entity = bool(
        article.event_entity_ids
        or article.event_entity_keys
        or event.event_entity_ids
        or event.event_entity_keys
    )
    disjoint_event_entities = (
        not exact_content
        and has_event_entity
        and not shared_event_entity
        and bool(article.event_entity_ids or article.event_entity_keys)
        and bool(event.event_entity_ids or event.event_entity_keys)
    )
    if disjoint_event_entities:
        total = round(total * DISJOINT_EVENT_ENTITY_FACTOR, 4)
    # A shared event-type entity ("第三季度财报") is much more specific than a
    # shared company/person. It may lift a pair over the attach threshold, but
    # only when other signals agree and the time window holds.
    strong_boost = (
        not exact_content
        and shared_event_entity
        and entity >= 0.5
        and keyword >= 0.10
        and title >= 0.10
        and category_same
        and (gap_hours is None or gap_hours <= MAX_EVENT_GAP_HOURS)
    )
    if strong_boost:
        total = max(total, ATTACH_THRESHOLD)
    decision = decide(
        total=total,
        entity=entity,
        keyword=keyword,
        title=title,
        category_same=category_same,
        gap_hours=gap_hours,
        already_member=already_member,
        exact_content=exact_content,
        shared_event_entity=shared_event_entity,
    )
    # Deterministic signals cannot bridge scripts. When a Chinese and a Latin
    # report share a canonical entity on the same topic, surface the pair for
    # human/LLM review instead of silently splitting or falsely merging.
    cross_language = (
        not exact_content
        and decision == "separate"
        and entity >= 0.20
        and _cross_language(article.title, event.title)
    )
    if cross_language:
        decision = "ambiguous"
    # If entity extraction failed for one report, textual agreement must not
    # silently create a duplicate event: route it to review instead.
    missing_entity_review = (
        not cross_language
        and not exact_content
        and decision == "separate"
        and not (article.entity_ids or article.entity_keys)
        and bool(event.entity_ids or event.entity_keys)
        and keyword >= 0.50
        and title >= 0.40
        and (gap_hours is None or gap_hours <= 72)
    )
    if missing_entity_review:
        decision = "ambiguous"

    # Without a shared event-type entity, contradictory period/antonym markers
    # ("Q3" vs "Q4", "裁员" vs "招聘") are decisive: never merge them silently.
    marker_conflict = (
        not exact_content
        and not shared_event_entity
        and conflicting_event_markers(article.title, event.title)
    )
    if marker_conflict and decision in {"attach", "ambiguous"}:
        decision = "separate"

    reasons = [
        f"entity={entity:.3f}",
        f"keyword={keyword:.3f}",
        f"title={title:.3f}",
        f"summary={summary:.3f}",
        f"time={time_score:.2f}",
        f"category={'same' if category_same else 'different'}",
        f"source={'new' if source == 1.0 else 'existing'}",
        f"total={total:.3f}",
    ]
    if exact_content:
        reasons.insert(0, "exact_content_hash")
    if strong_boost:
        reasons.append("strong_event_entity_boost")
    if disjoint_event_entities:
        reasons.append("guard=disjoint_event_entities")
    if cross_language:
        reasons.append("guard=cross_language_review")
    if missing_entity_review:
        reasons.append("guard=missing_entity_review")
    if marker_conflict:
        reasons.append("guard=conflicting_event_marker")
    if decision == "separate" and gap_hours is not None and gap_hours > MAX_EVENT_GAP_HOURS:
        reasons.append("guard=time_window_exceeded")
    elif decision == "separate" and (
        entity >= 0.50 and title < 0.35 and keyword < 0.25 and not shared_event_entity
    ):
        reasons.append("guard=same_subject_different_event")
    elif decision == "separate" and not category_same and title < 0.60:
        reasons.append("guard=category_mismatch")
    return PairScore(
        total=total,
        entity=round(entity, 4),
        keyword=round(keyword, 4),
        title=round(title, 4),
        summary=round(summary, 4),
        time=round(time_score, 4),
        category=round(category, 4),
        source=round(source, 4),
        decision=decision,
        reasons=tuple(reasons),
        strong=round(strong, 4),
        shared_event_entity=shared_event_entity,
    )


def normalized_title(value: str | None) -> str:
    return normalize_text(value).lower()
