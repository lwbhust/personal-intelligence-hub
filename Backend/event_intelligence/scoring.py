"""Explainable event scoring (`event-score-v1`).

Every component is derived from stored evidence counts. The user's subjective
`credibility_score` is deliberately not an input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from .text import parse_timestamp
from .taxonomy import DOMAINS, NEUTRAL_SCORING_BASE, resolve_category, scoring_base_for

ALGORITHM_VERSION = "event-score-v1"

WEIGHTS = {
    "importance": 0.35,
    "heat": 0.25,
    "freshness": 0.15,
    "confidence": 0.15,
    "coverage": 0.10,
}

# Kept as the documented baseline table; the value actually used is resolved by
# `taxonomy.scoring_base_for`, which also accepts ASCII keys and extended
# topics. Unknown labels fall back to a neutral base instead of "其他".
CATEGORY_BASE = {item.name: item.scoring_base for item in DOMAINS}
SCORING_FALLBACK_BASE = NEUTRAL_SCORING_BASE

HEAT_WINDOW_HOURS = 72


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    category: str
    article_count: int = 0
    unique_content_count: int = 0
    unique_source_count: int = 0
    recent_72h_articles: int = 0
    recent_72h_sources: int = 0
    recent_24h_articles: int = 0
    previous_24h_articles: int = 0
    org_count: int = 0
    person_count: int = 0
    location_count: int = 0
    duration_days: float = 0.0
    avg_entity_confidence: float = 0.0
    ambiguity_ratio: float = 0.0
    is_manual: bool = False
    last_published_at: str | None = None
    last_seen_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "article_count": self.article_count,
            "unique_content_count": self.unique_content_count,
            "unique_source_count": self.unique_source_count,
            "recent_72h_articles": self.recent_72h_articles,
            "recent_72h_sources": self.recent_72h_sources,
            "recent_24h_articles": self.recent_24h_articles,
            "previous_24h_articles": self.previous_24h_articles,
            "org_count": self.org_count,
            "person_count": self.person_count,
            "location_count": self.location_count,
            "duration_days": round(self.duration_days, 2),
            "avg_entity_confidence": round(self.avg_entity_confidence, 4),
            "ambiguity_ratio": round(self.ambiguity_ratio, 4),
            "is_manual": self.is_manual,
            "last_published_at": self.last_published_at,
            "last_seen_at": self.last_seen_at,
        }


@dataclass(frozen=True, slots=True)
class ScoreResult:
    importance: float
    heat: float
    freshness: float
    coverage: float
    confidence: float
    total: float
    algorithm_version: str
    inputs: dict[str, object]
    explanation: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "importance_score": self.importance,
            "heat_score": self.heat,
            "freshness_score": self.freshness,
            "coverage_score": self.coverage,
            "confidence_score": self.confidence,
            "total_score": self.total,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _round(value: float) -> float:
    return round(_clamp(value), 2)


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def compute_scores(
    inputs: ScoreInputs,
    *,
    now: datetime | None = None,
    algorithm_version: str = ALGORITHM_VERSION,
) -> ScoreResult:
    moment = _now(now)

    base = scoring_base_for(inputs.category)
    resolution = resolve_category(inputs.category)
    base_note = "" if resolution.known else "（分类未识别，使用中性基准）"
    scale = min(18.0, 6.0 * math.log2(1 + max(0, inputs.unique_content_count)))
    sources = min(12.0, 4.0 * max(0, inputs.unique_source_count))
    orgs = min(6.0, 1.5 * max(0, inputs.org_count))
    persons = min(4.0, 2.0 * max(0, inputs.person_count))
    locations = min(3.0, 1.5 * max(0, inputs.location_count))
    actors = orgs + persons + locations
    duration = min(5.0, 0.5 * max(0.0, inputs.duration_days))
    manual_bonus = 6.0 if inputs.is_manual else 0.0
    importance = _round(base + scale + sources + actors + duration + manual_bonus)

    recent = max(0, inputs.recent_72h_articles)
    window_sources = max(0, inputs.recent_72h_sources)
    growth = (inputs.recent_24h_articles - inputs.previous_24h_articles) / max(
        1, inputs.previous_24h_articles
    )
    growth = max(-1.0, min(3.0, growth))
    article_component = min(45.0, 9.0 * math.log2(1 + recent))
    source_component = min(25.0, 5.0 * window_sources)
    growth_component = min(15.0, 7.5 * max(0.0, growth))
    reference = parse_timestamp(inputs.last_published_at or inputs.last_seen_at)
    hours = 100000.0
    if reference is not None:
        hours = max(0.0, (moment - reference).total_seconds() / 3600.0)
    recency_component = 15.0 * math.exp(-hours / HEAT_WINDOW_HOURS)
    heat = _round(article_component + source_component + growth_component + recency_component)

    freshness_reference = inputs.last_published_at or inputs.last_seen_at
    freshness_days = 0.0
    if freshness_reference:
        parsed = parse_timestamp(freshness_reference)
        if parsed is not None:
            freshness_days = max(0.0, (moment - parsed).total_seconds() / 86400.0)
    freshness = _round(100.0 * math.exp(-freshness_days / 7.0))

    coverage = _round(
        60.0 * (1.0 - math.exp(-max(0, inputs.unique_source_count) / 3.0))
        + 40.0 * (1.0 - math.exp(-max(0, inputs.unique_content_count) / 4.0))
    )

    evidence = min(30.0, 6.0 * max(0, inputs.unique_content_count))
    entity_quality = 20.0 * max(0.0, min(1.0, inputs.avg_entity_confidence))
    boundary = 20.0 * (1.0 - max(0.0, min(1.0, inputs.ambiguity_ratio)))
    manual_confidence = 15.0 if inputs.is_manual else 0.0
    diversity = min(15.0, 3.0 * max(0, inputs.unique_source_count))
    confidence = _round(
        evidence + entity_quality + boundary + manual_confidence + diversity
    )

    total = round(
        WEIGHTS["importance"] * importance
        + WEIGHTS["heat"] * heat
        + WEIGHTS["freshness"] * freshness
        + WEIGHTS["confidence"] * confidence
        + WEIGHTS["coverage"] * coverage,
        2,
    )

    components = [
        {
            "name": "importance",
            "weight": WEIGHTS["importance"],
            "value": importance,
            "contribution": round(WEIGHTS["importance"] * importance, 2),
            "reason": (
                f"分类基础值 {base:g}{base_note} + 规模 {scale:.2f} + 来源 {sources:.2f} + "
                f"主体 {actors:.2f} + 持续 {duration:.2f} + 人工 {manual_bonus:g}"
            ).replace(".00", ""),
        },
        {
            "name": "heat",
            "weight": WEIGHTS["heat"],
            "value": heat,
            "contribution": round(WEIGHTS["heat"] * heat, 2),
            "reason": (
                f"72h 去重文章 {recent}（{article_component:.2f}）+ 独立来源 "
                f"{window_sources}（{source_component:.2f}）+ 增长 {growth:.2f}"
                f"（{growth_component:.2f}）+ 最近更新衰减（{recency_component:.2f}）；"
                "仅基于报道节奏，不含阅读/传播数据"
            ),
        },
        {
            "name": "freshness",
            "weight": WEIGHTS["freshness"],
            "value": freshness,
            "contribution": round(WEIGHTS["freshness"] * freshness, 2),
            "reason": (
                f"距最近发布时间 {freshness_days:.2f} 天，按 exp(-days/7) 衰减"
                + ("" if inputs.last_published_at else "（无发布时间，使用识别时间）")
            ),
        },
        {
            "name": "confidence",
            "weight": WEIGHTS["confidence"],
            "value": confidence,
            "contribution": round(WEIGHTS["confidence"] * confidence, 2),
            "reason": (
                f"证据 {evidence:.2f} + 实体匹配 {entity_quality:.2f} + 边界稳定 "
                f"{boundary:.2f} + 人工确认 {manual_confidence:g} + 来源多样 "
                f"{diversity:.2f}；置信度不等于文章数"
            ),
        },
        {
            "name": "coverage",
            "weight": WEIGHTS["coverage"],
            "value": coverage,
            "contribution": round(WEIGHTS["coverage"] * coverage, 2),
            "reason": (
                f"独立来源 {inputs.unique_source_count}，去重内容 "
                f"{inputs.unique_content_count}；转载不重复计数"
            ),
        },
    ]

    return ScoreResult(
        importance=importance,
        heat=heat,
        freshness=freshness,
        coverage=coverage,
        confidence=confidence,
        total=total,
        algorithm_version=algorithm_version,
        inputs=inputs.as_dict(),
        explanation={
            "formula": (
                "0.35*importance+0.25*heat+0.15*freshness"
                "+0.15*confidence+0.10*coverage"
            ),
            "weights": dict(WEIGHTS),
            "components": components,
        },
    )
