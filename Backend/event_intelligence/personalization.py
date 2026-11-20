"""Explainable personal recommendation algorithm (`personal-reco-v1`).

Pure functions only: no database, no network, no model calls. The service layer
loads real rows, calls these functions, and persists the result so the API can
always return the same explanation it scored with.

Design rules:
- Every dimension is independent and bounded 0–100.
- Missing evidence is neutral (50) plus an explicit warning, never a fake 0/100.
- Keyword hits alone never produce a high score (domain/entity signals weigh more).
- Major events can bypass a low interest match through an explicit fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .taxonomy import resolve_category

ALGORITHM_VERSION = "personal-reco-v1"

LEVELS = ("must_read", "recommended", "watch", "low", "not_recommended")

DEFAULT_LEVEL_WEIGHTS: dict[str, float] = {
    "core": 1.0,
    "extended": 0.65,
    "general": 0.3,
    "muted": 0.0,
}

DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    "interest": 0.35,
    "importance": 0.25,
    "novelty": 0.15,
    "source_quality": 0.15,
    "recency": 0.10,
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "must_read": 85.0,
    "recommended": 70.0,
    "watch": 50.0,
    "low": 30.0,
}

DEFAULT_CONFIG: dict[str, object] = {
    "dimension_weights": DEFAULT_DIMENSION_WEIGHTS,
    "thresholds": DEFAULT_THRESHOLDS,
    "major_event_importance": 55.0,
    "major_event_min_score": 70.0,
    "neutral_no_evidence": 50.0,
    "unmatched_interest_score": 15.0,
}

# Signal strengths per interest type. Entity and domain are the strongest
# because they are backed by structured data, keywords are weaker, and a source
# match is only a hint about the user's reading habit.
SIGNAL_STRENGTH: dict[str, float] = {
    "domain": 1.0,
    "topic": 0.9,
    "entity": 1.0,
    "keyword": 0.8,
    "source": 0.6,
    "event": 0.0,
}

FEEDBACK_DELTA: dict[str, float] = {
    "interested": 8.0,
    "important": 12.0,
    "not_interested": -25.0,
    "source_disliked": -20.0,
    "duplicate": 0.0,
    "later": 0.0,
}

# Reading behaviour is a weaker signal than an explicit feedback: a favorite is
# a light positive nudge, and an already-read article is only mildly demoted so
# it does not compete with fresh material when "show read" is requested.
# "later" is deliberately neutral: saving for later is not a taste judgement.
BEHAVIOR_FAVORITE_BOOST = 6.0
BEHAVIOR_READ_PENALTY = -8.0
BEHAVIOR_LATER_DELTA = 0.0


@dataclass(frozen=True, slots=True)
class InterestSignal:
    id: str
    name: str
    interest_type: str
    level: str
    weight: float
    domain_key: str | None = None
    keywords: tuple[str, ...] = ()
    exclusion_keywords: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class MatchInput:
    title: str
    summary: str
    category: str | None
    source_id: str
    source_name: str | None
    entity_ids: tuple[str, ...]
    entity_names: tuple[str, ...]
    interest_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchResult:
    score: float
    matched_interests: tuple[str, ...]
    matched_entity_names: tuple[str, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    best_level: str | None = None
    matched_interest_ids: tuple[str, ...] = field(default=())


def _normalise(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
    )


def _is_word_char(char: str) -> bool:
    """Latin/digit word characters; CJK characters act as boundaries."""

    return char.isalnum() and not _is_cjk(char)


def keyword_hit(text: str, keyword: str) -> bool:
    """Case-insensitive substring match with a Latin word-boundary guard.

    Chinese has no spaces, so substring matching is correct there. For Latin
    keywords we require a boundary so "AI" does not match "said", while
    mixed Chinese text such as "大厂AI动态" still matches "AI".
    """

    needle = _normalise(keyword)
    if not needle:
        return False
    haystack = _normalise(text)
    if not haystack:
        return False
    if needle.isascii() and needle.replace("-", "").replace(" ", "").isalnum():
        start = 0
        while True:
            index = haystack.find(needle, start)
            if index < 0:
                return False
            before = haystack[index - 1] if index > 0 else " "
            after_index = index + len(needle)
            after = haystack[after_index] if after_index < len(haystack) else " "
            if not _is_word_char(before) and not _is_word_char(after):
                return True
            start = index + 1
    return needle in haystack


def domain_of(category: str | None) -> str | None:
    if not category:
        return None
    resolution = resolve_category(category)
    if resolution.known:
        return resolution.domain_key
    return None


def match_interests(
    signals: list[InterestSignal],
    item: MatchInput,
) -> MatchResult:
    """Match one article or event against the enabled interests."""

    enabled = [signal for signal in signals if signal.enabled and signal.weight > 0]
    if not enabled:
        return MatchResult(
            score=float(DEFAULT_CONFIG["neutral_no_evidence"]),
            matched_interests=(),
            matched_entity_names=(),
            reason_codes=(),
            warnings=("NO_INTERESTS_CONFIGURED",),
            best_level=None,
        )

    text = f"{item.title}\n{item.summary}"
    domain_key = domain_of(item.category)
    entity_ids = set(item.entity_ids)
    entity_name_by_id = dict(zip(item.entity_ids, item.entity_names))
    matched: list[tuple[InterestSignal, float]] = []
    matched_entities: list[str] = []
    warnings: set[str] = set()

    for signal in enabled:
        if signal.level == "muted":
            hit_exclusion = any(keyword_hit(text, word) for word in signal.exclusion_keywords)
            if hit_exclusion:
                warnings.add("EXCLUDED_KEYWORD")
            continue
        if any(keyword_hit(text, word) for word in signal.exclusion_keywords):
            warnings.add("EXCLUDED_KEYWORD")
            continue

        strength = 0.0
        if signal.interest_type in {"domain", "topic"} and signal.domain_key:
            if domain_key and signal.domain_key == domain_key:
                strength = max(strength, SIGNAL_STRENGTH[signal.interest_type])
        if signal.interest_type in {"keyword", "topic", "domain"}:
            if any(keyword_hit(text, word) for word in signal.keywords):
                strength = max(strength, SIGNAL_STRENGTH["keyword"])
        if signal.entity_ids and entity_ids.intersection(signal.entity_ids):
            strength = max(strength, SIGNAL_STRENGTH["entity"])
            for entity_id in signal.entity_ids:
                name = entity_name_by_id.get(entity_id)
                if name and name not in matched_entities:
                    matched_entities.append(name)
        if signal.source_ids and item.source_id in signal.source_ids:
            strength = max(strength, SIGNAL_STRENGTH["source"])

        if strength > 0:
            matched.append((signal, strength))

    if not matched:
        return MatchResult(
            score=float(DEFAULT_CONFIG["unmatched_interest_score"]),
            matched_interests=(),
            matched_entity_names=tuple(matched_entities[:5]),
            reason_codes=(),
            warnings=tuple(sorted(warnings)),
            best_level=None,
        )

    def effective(signal: InterestSignal) -> float:
        return min(1.0, max(0.0, signal.weight)) * strength_of(signal)

    def strength_of(signal: InterestSignal) -> float:
        for candidate, strength in matched:
            if candidate.id == signal.id:
                return strength
        return 0.0

    ranked = sorted(matched, key=lambda pair: effective(pair[0]), reverse=True)
    best_signal, best_strength = ranked[0]
    best = min(1.0, max(0.0, best_signal.weight)) * best_strength
    score = 100.0 * best + min(24.0, 8.0 * (len(ranked) - 1))
    score = max(0.0, min(100.0, round(score, 2)))

    reasons: list[str] = []
    if best >= 0.85:
        reasons.append("CORE_INTEREST_MATCH")
    else:
        reasons.append("INTEREST_MATCH")
    if len(ranked) >= 2:
        reasons.append("MULTI_INTEREST_MATCH")
    if any(signal.interest_type == "entity" for signal, _ in ranked):
        reasons.append("TRACKED_ENTITY")
    if any(signal.interest_type == "source" for signal, _ in ranked):
        reasons.append("TRUSTED_SOURCE_HABIT")
    if len(ranked) > 1:
        warnings.add("MULTIPLE_WEAK_MATCHES")
    if best_strength <= SIGNAL_STRENGTH["keyword"] and best_signal.interest_type != "entity":
        warnings.add("KEYWORD_ONLY_MATCH")

    return MatchResult(
        score=score,
        matched_interests=tuple(signal.name for signal, _ in ranked[:6]),
        matched_entity_names=tuple(matched_entities[:5]),
        reason_codes=tuple(reasons),
        warnings=tuple(sorted(warnings)),
        best_level=best_signal.level,
        matched_interest_ids=tuple(signal.id for signal, _ in ranked[:6]),
    )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def recency_score(published_at: str | None, *, now: datetime) -> float:
    published = parse_timestamp(published_at)
    if published is None:
        return 50.0
    hours = max(0.0, (now - published).total_seconds() / 3600.0)
    if hours < 12:
        return 100.0
    if hours < 24:
        return 95.0
    if hours < 48:
        return 85.0
    if hours < 72:
        return 75.0
    if hours < 24 * 7:
        return 55.0
    if hours < 24 * 30:
        return 35.0
    return 20.0


def novelty_score(
    *,
    is_event: bool,
    is_newest_in_event: bool,
    event_freshness_hours: float | None,
    has_duplicate_feedback: bool,
    standalone_default: float = 90.0,
) -> float:
    """Novelty uses existing event membership as the similarity baseline."""

    if has_duplicate_feedback:
        return 20.0
    if not is_event:
        return standalone_default
    score = 90.0 if is_newest_in_event else 70.0
    if event_freshness_hours is not None and event_freshness_hours <= 24:
        score = min(95.0, score + 5.0)
    return score


def source_quality_score(credibility: float | None) -> tuple[float, tuple[str, ...]]:
    if credibility is None:
        return float(DEFAULT_CONFIG["neutral_no_evidence"]), ("SOURCE_QUALITY_UNKNOWN",)
    value = float(credibility)
    if value <= 1.0:
        value *= 100.0
    return max(0.0, min(100.0, value)), ()


def importance_score(event_total: float | None) -> tuple[float, tuple[str, ...]]:
    if event_total is None:
        return float(DEFAULT_CONFIG["neutral_no_evidence"]), ("EVENT_IMPORTANCE_UNKNOWN",)
    return max(0.0, min(100.0, float(event_total))), ()


def merge_weights(override: dict[str, object] | None) -> dict[str, float]:
    weights = dict(DEFAULT_DIMENSION_WEIGHTS)
    if isinstance(override, dict):
        for key in weights:
            raw = override.get(key)
            if isinstance(raw, (int, float)):
                weights[key] = max(0.0, min(1.0, float(raw)))
    total = sum(weights.values())
    if total > 0:
        weights = {key: value / total for key, value in weights.items()}
    return weights


def merge_thresholds(override: dict[str, object] | None) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if isinstance(override, dict):
        for key in thresholds:
            raw = override.get(key)
            if isinstance(raw, (int, float)):
                thresholds[key] = float(raw)
    # Keep a strictly descending ladder even if the caller sends odd numbers.
    order = ("must_read", "recommended", "watch", "low")
    for previous, current in zip(order, order[1:]):
        if thresholds[current] >= thresholds[previous]:
            thresholds[current] = thresholds[previous] - 1.0
    return thresholds


def level_for(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds["must_read"]:
        return "must_read"
    if score >= thresholds["recommended"]:
        return "recommended"
    if score >= thresholds["watch"]:
        return "watch"
    if score >= thresholds["low"]:
        return "low"
    return "not_recommended"


def reading_signal(
    *, reading_status: str | None, is_favorite: bool
) -> tuple[float, tuple[str, ...]]:
    """Translate reading state into a small, explainable score adjustment."""

    delta = 0.0
    reasons: list[str] = []
    if is_favorite:
        delta += BEHAVIOR_FAVORITE_BOOST
        reasons.append("FAVORITE_BOOST")
    if reading_status == "read":
        delta += BEHAVIOR_READ_PENALTY
        reasons.append("ALREADY_READ")
    elif reading_status == "later":
        delta += BEHAVIOR_LATER_DELTA
        reasons.append("SAVED_FOR_LATER")
    return delta, tuple(reasons)


@dataclass(frozen=True, slots=True)
class ScoredRecommendation:
    score: float
    level: str
    interest_score: float
    importance_score: float
    novelty_score: float
    source_quality_score: float
    recency_score: float
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    is_fallback: bool
    breakdown: dict[str, float]

    def as_explanation(self) -> dict[str, object]:
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "score_breakdown": dict(self.breakdown),
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "is_fallback": self.is_fallback,
        }


def score_item(
    *,
    match: MatchResult,
    importance: float,
    novelty: float,
    credibility: float | None,
    published_at: str | None,
    now: datetime,
    weights: dict[str, float],
    thresholds: dict[str, float],
    feedback: str | None,
    is_event: bool,
    config: dict[str, object] | None = None,
    behavior_delta: float = 0.0,
    behavior_reasons: tuple[str, ...] = (),
) -> ScoredRecommendation:
    quality, quality_warnings = source_quality_score(credibility)
    recency = recency_score(published_at, now=now)
    warnings = list(dict.fromkeys((*match.warnings, *quality_warnings)))
    reasons = list(match.reason_codes)

    total = (
        weights["interest"] * match.score
        + weights["importance"] * importance
        + weights["novelty"] * novelty
        + weights["source_quality"] * quality
        + weights["recency"] * recency
    )

    if feedback in FEEDBACK_DELTA:
        total += FEEDBACK_DELTA[feedback]
        if feedback == "interested":
            reasons.append("FEEDBACK_INTERESTED")
        elif feedback == "important":
            reasons.append("FEEDBACK_IMPORTANT")
        elif feedback == "not_interested":
            reasons.append("FEEDBACK_NOT_INTERESTED")
            warnings.append("LOWERED_BY_FEEDBACK")
        elif feedback == "source_disliked":
            reasons.append("FEEDBACK_SOURCE_DISLIKED")
            warnings.append("LOWERED_BY_FEEDBACK")
        elif feedback == "duplicate":
            reasons.append("FEEDBACK_DUPLICATE")
            warnings.append("DUPLICATE_SUPPRESSED")
        elif feedback == "later":
            reasons.append("FEEDBACK_LATER")

    if behavior_delta:
        total += behavior_delta
    reasons.extend(behavior_reasons)

    if importance >= 60:
        reasons.append("HIGH_EVENT_IMPORTANCE")
    if novelty >= 85:
        reasons.append("NEW_INFORMATION")
    if recency >= 90:
        reasons.append("FRESH")
    if quality >= 80:
        reasons.append("TRUSTED_SOURCE")

    is_fallback = False
    cfg = config or DEFAULT_CONFIG
    if is_event:
        major_threshold = float(cfg.get("major_event_importance", 55.0))
        min_score = float(cfg.get("major_event_min_score", 70.0))
        if importance >= major_threshold and match.score < 50.0:
            total = max(total, min_score)
            reasons.append("MAJOR_EVENT_FALLBACK")
            is_fallback = True
        elif importance >= major_threshold:
            reasons.append("MAJOR_EVENT")

    total = round(max(0.0, min(100.0, total)), 2)
    level = level_for(total, thresholds)

    return ScoredRecommendation(
        score=total,
        level=level,
        interest_score=round(match.score, 2),
        importance_score=round(importance, 2),
        novelty_score=round(novelty, 2),
        source_quality_score=round(quality, 2),
        recency_score=round(recency, 2),
        reason_codes=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        is_fallback=is_fallback,
        breakdown={
            "interest": round(match.score, 2),
            "importance": round(importance, 2),
            "novelty": round(novelty, 2),
            "source_quality": round(quality, 2),
            "recency": round(recency, 2),
        },
    )
