"""Evidence-backed event relation candidates (`event-relation-v1`).

Causality (`caused_by`), composition (`part_of`) and contradiction
(`contradicts`) are never generated automatically: chronology alone is not
causality. Those types are manual-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .clustering import EventFeatures
from .text import hours_between, jaccard, parse_timestamp, title_similarity


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    source_event_id: str
    target_event_id: str
    relation_type: str
    confidence: float
    rationale: str
    evidence_article_ids: tuple[str, ...] = ()


def _entity_overlap(left: EventFeatures, right: EventFeatures) -> tuple[set[str], float]:
    if left.entity_ids and right.entity_ids:
        shared = set(left.entity_ids) & set(right.entity_ids)
        if shared:
            return shared, 1.0
    shared_keys = set(left.entity_keys) & set(right.entity_keys)
    return set(), (1.0 if shared_keys else 0.0)


def _evidence(
    mentions: dict[str, dict[str, tuple[str, ...]]],
    event_id: str,
    shared: set[str],
) -> list[str]:
    result: list[str] = []
    for entity_id in shared:
        for article_id in mentions.get(event_id, {}).get(entity_id, ()):
            if article_id not in result:
                result.append(article_id)
    return result[:20]


def generate_relation_candidates(
    events: list[EventFeatures],
    *,
    mentions_by_event: dict[str, dict[str, tuple[str, ...]]] | None = None,
    limit: int = 200,
) -> list[RelationCandidate]:
    mentions = mentions_by_event or {}
    found: dict[tuple[str, str, str], RelationCandidate] = {}

    for index, left in enumerate(events):
        for right in events[index + 1 :]:
            shared_ids, shared_score = _entity_overlap(left, right)
            if shared_score <= 0:
                continue
            shared_count = len(shared_ids) if shared_ids else 1
            keyword_score = jaccard(left.keywords, right.keywords)
            title_score = title_similarity(left.title, right.title)

            if shared_count >= 2 or (shared_count >= 1 and keyword_score >= 0.30):
                key = tuple(sorted((left.id, right.id))) + ("same_topic",)
                confidence = 0.50 if shared_count >= 2 else 0.45
                found[key] = RelationCandidate(
                    source_event_id=key[0],
                    target_event_id=key[1],
                    relation_type="same_topic",
                    confidence=confidence,
                    rationale=(
                        f"共享 {shared_count} 个实体，关键词 Jaccard={keyword_score:.2f}；"
                        "属于同一主题下的不同事件"
                    ),
                    evidence_article_ids=tuple(
                        sorted(
                            set(_evidence(mentions, left.id, shared_ids))
                            | set(_evidence(mentions, right.id, shared_ids))
                        )
                    )[:20],
                )

            if left.category and right.category and left.category == right.category:
                key = tuple(sorted((left.id, right.id))) + ("related_to",)
                found.setdefault(
                    key,
                    RelationCandidate(
                        source_event_id=key[0],
                        target_event_id=key[1],
                        relation_type="related_to",
                        confidence=0.40,
                        rationale=f"共享 {shared_count} 个实体且分类相同（{left.category}）",
                        evidence_article_ids=tuple(
                            sorted(
                                set(_evidence(mentions, left.id, shared_ids))
                                | set(_evidence(mentions, right.id, shared_ids))
                            )
                        )[:20],
                    ),
                )

            # `follows` is directed: the earlier event is the source.
            earlier, later = left, right
            if (
                left.last_published_at
                and right.first_published_at
                and _starts_after(left, right)
            ):
                earlier, later = right, left
            gap = hours_between(earlier.last_published_at, later.first_published_at)
            if (
                gap is not None
                and 0 <= gap <= 24 * 14
                and title_score < 0.55
                and shared_count >= 1
            ):
                key = (earlier.id, later.id, "follows")
                found[key] = RelationCandidate(
                    source_event_id=earlier.id,
                    target_event_id=later.id,
                    relation_type="follows",
                    confidence=0.45,
                    rationale=(
                        f"共享 {shared_count} 个实体，后一事件在 {gap/24:.1f} 天后出现，"
                        f"标题相似度 {title_score:.2f}（<0.55），判断为后续进展而非同一事件"
                    ),
                    evidence_article_ids=tuple(
                        sorted(
                            set(_evidence(mentions, earlier.id, shared_ids))
                            | set(_evidence(mentions, later.id, shared_ids))
                        )
                    )[:20],
                )

    ordered = sorted(
        found.values(),
        key=lambda item: (-item.confidence, item.source_event_id, item.target_event_id),
    )
    return ordered[:limit]


def _starts_after(left: EventFeatures, right: EventFeatures) -> bool:
    left_start = parse_timestamp(left.first_published_at)
    right_start = parse_timestamp(right.first_published_at)
    if left_start is None or right_start is None:
        return False
    return left_start > right_start
