"""Cross-source event aggregation (`event-aggregate-v1`).

Phase 7.6. Article de-duplication removes copies of the *same* feed item; this
module decides whether separate articles/events describe the *same real-world
event*. It is deterministic and explainable: every decision carries the signal
values and guard names so a Dry Run can be reviewed before anything is merged.

Design rules
------------
- Only different sources may be merged automatically. Same-source reposts are
  handled by the ingestion dedup layers, never here.
- Missing AI signals (category/keywords/entities) do not penalise a pair: the
  score is a weighted average over the signals that actually exist.
- Title similarity alone is never sufficient. Contradictory periods/antonyms,
  disjoint entity subjects and conflicting version numbers force `separate`.
- Cross-language pairs are capped at `review`: a Chinese and a Latin report of
  the same story need human/LLM confirmation before merging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .clustering import conflicting_event_markers
from .text import hours_between, jaccard, normalize_text, title_similarity

ALGORITHM_VERSION = "event-aggregate-v1"
MERGE_THRESHOLD = 0.75
REVIEW_THRESHOLD = 0.62
MAX_GAP_HOURS = 24 * 14
MAX_PAIR_ARTICLE_SCAN = 50

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_HEADLINE_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"[\[\(【（][^\]\)】）]{1,20}[\]\)】）]"
    r"|(?:新华图讯|新华视点|详讯|快讯|图集|视频|独家|观察|聚焦[A-Za-z\u4e00-\u9fff]{0,8})"
    r")\s*[丨|｜:：\-—]?\s*"
)
_VERSION_WORDS = (
    ("一代", "二代"),
    ("第一代", "第二代"),
    ("旧版", "新版"),
    ("上一代", "下一代"),
)


def headline_text(value: str | None) -> str:
    """Strip agency/column prefixes that differ between reports of one story.

    "新华图讯丨习近平会见普京" and "（深圳APEC）习近平会见李在明" keep their
    meaningful part; the prefix is presentation, not another event.
    """

    text = normalize_text(value)
    for _ in range(3):
        stripped = _HEADLINE_PREFIX_RE.sub("", text, count=1).strip()
        if stripped == text or not stripped:
            break
        text = stripped
    return text.rstrip("→ ").strip()


@dataclass(frozen=True, slots=True)
class ArticleSignal:
    id: str
    title: str
    summary: str | None
    published_at: str | None
    source_id: str
    source_name: str | None
    category: str | None
    keywords: frozenset[str] = field(default_factory=frozenset)
    entity_ids: frozenset[str] = field(default_factory=frozenset)
    entity_keys: frozenset[str] = field(default_factory=frozenset)
    event_entity_ids: frozenset[str] = field(default_factory=frozenset)
    event_entity_keys: frozenset[str] = field(default_factory=frozenset)
    content_hash: str = ""
    content_state: str = "unavailable"
    credibility: float | None = None
    canonical_url: str | None = None
    original_url: str | None = None
    has_ai_summary: bool = False
    summary_length: int = 0


@dataclass(frozen=True, slots=True)
class EventSignal:
    id: str
    title: str
    summary: str | None
    category: str | None
    status: str
    is_manual: bool
    members: tuple[ArticleSignal, ...] = ()
    entity_ids: frozenset[str] = field(default_factory=frozenset)
    entity_keys: frozenset[str] = field(default_factory=frozenset)
    event_entity_ids: frozenset[str] = field(default_factory=frozenset)
    event_entity_keys: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)
    source_ids: frozenset[str] = field(default_factory=frozenset)
    first_published_at: str | None = None
    last_published_at: str | None = None

    @property
    def article_count(self) -> int:
        return len(self.members)

    @property
    def source_count(self) -> int:
        return len(self.source_ids)

    @property
    def member_titles(self) -> tuple[str, ...]:
        return tuple(member.title for member in self.members if member.title)


@dataclass(frozen=True, slots=True)
class AggregationScore:
    total: float
    decision: str
    title: float
    summary: float
    entity: float | None
    keyword: float | None
    time: float
    category: float
    reasons: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepresentativeCandidate:
    article_id: str
    title: str
    source_id: str
    source_name: str | None
    published_at: str | None
    credibility: float | None
    content_state: str
    has_ai_summary: bool
    summary_length: int


@dataclass(frozen=True, slots=True)
class RepresentativeChoice:
    article_id: str
    title: str
    source_name: str | None
    published_at: str | None
    score: float
    reasons: tuple[str, ...] = ()


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
    """True when exactly one side contains CJK text.

    A mixed Chinese headline that contains "GPT-6.2" is still Chinese for this
    purpose, so mixed-vs-English pairs are correctly treated as cross-language.
    """

    left_cjk = bool(_CJK_RE.search(left or ""))
    right_cjk = bool(_CJK_RE.search(right or ""))
    return left_cjk != right_cjk


def _max_similarity(value: str | None, candidates: tuple[str, ...]) -> float:
    best = 0.0
    for candidate in candidates:
        if not candidate:
            continue
        best = max(best, title_similarity(value, candidate))
    return round(best, 4)


def _numbers(value: str | None) -> set[str]:
    return set(_NUMBER_RE.findall(normalize_text(value)))


def numeric_conflict(left: str | None, right: str | None, title_similarity_value: float) -> bool:
    """Different explicit versions/quantities (GPT-5 vs GPT-6, iPhone 17/18)."""

    left_numbers = _numbers(left)
    right_numbers = _numbers(right)
    if left_numbers and right_numbers and left_numbers.isdisjoint(right_numbers):
        return title_similarity_value < 0.90
    left_text = left or ""
    right_text = right or ""
    for first, second in _VERSION_WORDS:
        if (first in left_text and second in right_text) or (
            second in left_text and first in right_text
        ):
            return True
    return False


def _time_score(gap_hours: float | None) -> float:
    if gap_hours is None:
        return 0.5
    if gap_hours <= 72:
        return 1.0
    if gap_hours <= 24 * 7:
        return 0.7
    if gap_hours <= MAX_GAP_HOURS:
        return 0.4
    return 0.1


def score_article_event(article: ArticleSignal, event: EventSignal) -> AggregationScore:
    """Score whether one article reports the same event as an event cluster."""

    titles = tuple(
        headline_text(value)
        for value in (event.title, *event.member_titles[:5])
        if headline_text(value)
    )
    title = _max_similarity(headline_text(article.title), titles)
    summaries = tuple(
        item for item in (event.summary, *(member.summary for member in event.members[:3])) if item
    )
    summary = _max_similarity(article.summary, summaries) if article.summary else 0.0

    entity: float | None = None
    if article.entity_ids and event.entity_ids:
        entity = jaccard(article.entity_ids, event.entity_ids)
    elif article.entity_keys and event.entity_keys:
        entity = jaccard(article.entity_keys, event.entity_keys)

    keyword: float | None = None
    if article.keywords and event.keywords:
        keyword = jaccard(article.keywords, event.keywords)

    gap = hours_between(event.last_published_at, article.published_at)
    gap_hours = None if gap is None else abs(gap)
    time_component = _time_score(gap_hours)
    category_same = bool(
        article.category and event.category and article.category == event.category
    )
    category = 1.0 if category_same else 0.25

    weighted: list[tuple[float, float]] = [
        (0.36, title),
        (0.16, summary),
        (0.08, time_component),
        (0.06, category),
    ]
    if entity is not None:
        weighted.append((0.22, entity))
    if keyword is not None:
        weighted.append((0.12, keyword))
    available_weight = sum(weight for weight, _ in weighted)
    total = round(
        sum(weight * value for weight, value in weighted) / available_weight, 4
    ) if available_weight else 0.0

    guards: list[str] = []
    if article.source_id in event.source_ids:
        guards.append("same_source")
    if gap_hours is not None and gap_hours > MAX_GAP_HOURS:
        guards.append("time_window_exceeded")
    if conflicting_event_markers(article.title, event.title):
        guards.append("conflicting_event_marker")
    if numeric_conflict(article.title, event.title, title):
        guards.append("conflicting_version_marker")
    if (
        entity is not None
        and entity == 0.0
        and title < 0.55
        and categories_disjoint(article.category, event.category)
    ):
        guards.append("disjoint_subject")
    if not category_same and title < 0.60:
        guards.append("category_mismatch")
    if entity is None and keyword is None and title < 0.68:
        guards.append("unstructured_headline_mismatch")
    if title < 0.30 and summary < 0.15:
        guards.append("weak_text_similarity")

    shared_event_entity = bool(
        (article.event_entity_ids & event.event_entity_ids)
        or (article.event_entity_keys & event.event_entity_keys)
    )
    cross_language = _cross_language(article.title, event.title)
    decision = "separate"
    if not guards:
        strong_subject = (
            entity is not None and entity >= 0.60 and title >= 0.45 and (keyword or 0.0) >= 0.20
        )
        strong_event = (
            shared_event_entity
            and entity is not None
            and entity >= 0.50
            and (keyword or 0.0) >= 0.20
            and title >= 0.30
            and time_component >= 0.70
        )
        if strong_event and total >= REVIEW_THRESHOLD:
            decision = "merge"
        elif total >= MERGE_THRESHOLD and (title >= 0.60 or strong_subject):
            decision = "merge"
        elif total >= REVIEW_THRESHOLD:
            decision = "review"
    if cross_language and decision in {"merge", "review"}:
        # Deterministic signals cannot bridge scripts; require human/LLM review.
        guards.append("cross_language_review")
        decision = "review"

    reasons = [
        f"title={title:.3f}",
        f"summary={summary:.3f}",
        f"entity={'n/a' if entity is None else f'{entity:.3f}'}",
        f"keyword={'n/a' if keyword is None else f'{keyword:.3f}'}",
        f"time={time_component:.2f}",
        f"category={'same' if category_same else 'different'}",
        f"total={total:.3f}",
        f"decision={decision}",
    ]
    if shared_event_entity:
        reasons.append("shared_event_entity=yes")
    return AggregationScore(
        total=total,
        decision=decision,
        title=title,
        summary=summary,
        entity=entity,
        keyword=keyword,
        time=time_component,
        category=category,
        reasons=tuple(reasons),
        guards=tuple(guards),
    )


def categories_disjoint(left: str | None, right: str | None) -> bool:
    return bool(left and right and left != right)


def _completeness(content_state: str) -> float:
    return {"full": 1.0, "summary_only": 0.6}.get(content_state, 0.1)


def _richness(candidate: RepresentativeCandidate) -> float:
    if candidate.has_ai_summary:
        return 1.0
    if candidate.summary_length >= 120:
        return 0.7
    if candidate.summary_length >= 40:
        return 0.4
    return 0.1


def _is_better_representative(
    best_score: float,
    best_candidate: RepresentativeCandidate,
    score: float,
    candidate: RepresentativeCandidate,
) -> bool:
    if score != best_score:
        return score > best_score
    if candidate.published_at != best_candidate.published_at:
        if candidate.published_at is None:
            return False
        if best_candidate.published_at is None:
            return True
        return candidate.published_at < best_candidate.published_at
    return candidate.article_id < best_candidate.article_id


def choose_representative(
    candidates: list[RepresentativeCandidate],
) -> RepresentativeChoice | None:
    """Pick the most authoritative, complete and original report.

    Authority (source credibility) 40%, completeness 30%, first report 20%,
    information richness 10%. Ties break on earlier publication then id.
    """

    if not candidates:
        return None
    earliest = min(
        (item.published_at for item in candidates if item.published_at),
        default=None,
    )
    best: tuple[float, RepresentativeCandidate, list[str]] | None = None
    for candidate in candidates:
        credibility = candidate.credibility if candidate.credibility is not None else 0.5
        is_first = 1.0 if earliest and candidate.published_at == earliest else 0.0
        score = round(
            0.40 * max(0.0, min(1.0, credibility))
            + 0.30 * _completeness(candidate.content_state)
            + 0.20 * is_first
            + 0.10 * _richness(candidate),
            4,
        )
        reasons = [
            f"credibility={credibility:.2f}",
            f"completeness={_completeness(candidate.content_state):.2f}",
            f"first_report={'yes' if is_first else 'no'}",
            f"information={_richness(candidate):.2f}",
        ]
        if best is None or _is_better_representative(best[0], best[1], score, candidate):
            best = (score, candidate, reasons)
    if best is None:
        return None
    return RepresentativeChoice(
        article_id=best[1].article_id,
        title=best[1].title,
        source_name=best[1].source_name,
        published_at=best[1].published_at,
        score=best[0],
        reasons=tuple(best[2]),
    )
