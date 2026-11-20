"""Phase 7.6 cross-source event aggregation (`event-aggregate-v1`).

The service is deliberately separate from `EventClusteringService`:

- clustering puts an *unassigned* article into a new/existing event;
- aggregation decides whether two *existing* structures (an unassigned article
  or a whole event) describe the same real-world event and should be merged.

Only a Dry Run is automatic. Applying is an explicit, backed-up, audited and
bounded operation; manual events are never touched and original articles are
never deleted.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import database
from core.logging import log_event
from core.timeutil import utc_timestamp
from database import backup
from database.repositories import event_aggregation_repository as agg_repo
from database.repositories import event_audit_repository as audit_repo
from database.repositories import event_relation_repository as relation_repo
from database.repositories import event_repository as event_repo
from database.repositories import personalization_repository as personalization_repo
from event_intelligence.aggregation import (
    ALGORITHM_VERSION,
    MAX_GAP_HOURS,
    MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    AggregationScore,
    ArticleSignal,
    EventSignal,
    RepresentativeCandidate,
    choose_representative,
    headline_text,
    score_article_event,
)
from event_intelligence.lifecycle import next_status, transition_reason
from event_intelligence.taxonomy import event_domain_name
from event_intelligence.text import hours_between, title_similarity, tokens
from services.classification_service import refresh_event_category
from services.errors import conflict, not_found, validation
from services.event_aggregation import (
    rebuild_event_entities,
    recompute_event_aggregates,
    refresh_event_summary,
)
from services.event_scoring_service import score_event_in_conn

MAX_DRY_RUN_EVENTS = 200
MAX_DRY_RUN_ARTICLES = 800
MAX_APPLY_PAIRS = 50
DEFAULT_DAYS = 30
TOKEN_PREFILTER = 0.18
ARTICLE_TOKEN_PREFILTER = 0.35
TERMINAL = {"merged", "archived", "closed"}


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item.strip().lower()[:50] for item in parsed if isinstance(item, str) and item.strip()]


def _cutoff(days: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _article_signal(conn, row) -> ArticleSignal:
    entity_ids, entity_keys, event_entity_ids, event_entity_keys = (
        event_repo.article_entity_keys(conn, str(row["id"]))
    )
    ai_summary = row["ai_summary"]
    summary = ai_summary or row["summary"]
    return ArticleSignal(
        id=str(row["id"]),
        title=str(row["title"]),
        summary=summary,
        published_at=row["published_at"] or row["fetched_at"],
        source_id=str(row["source_id"]),
        source_name=row["source_name"],
        category=event_domain_name(row["ai_category"] or row["source_category"]),
        keywords=frozenset(_json_list(row["ai_keywords"])),
        entity_ids=frozenset(entity_ids),
        entity_keys=frozenset(entity_keys),
        event_entity_ids=frozenset(event_entity_ids),
        event_entity_keys=frozenset(event_entity_keys),
        content_state=str(row["content_state"] or "unavailable"),
        credibility=row["credibility_score"],
        canonical_url=row["canonical_url"],
        original_url=row["original_url"],
        has_ai_summary=bool(ai_summary),
        summary_length=len(summary or ""),
    )


def _member_row_to_signal(conn, row) -> ArticleSignal:
    entity_ids, entity_keys, event_entity_ids, event_entity_keys = (
        event_repo.article_entity_keys(conn, str(row["article_id"]))
    )
    ai_summary = row["ai_summary"]
    summary = ai_summary or row["summary"]
    return ArticleSignal(
        id=str(row["article_id"]),
        title=str(row["title"]),
        summary=summary,
        published_at=row["published_at"] or row["fetched_at"],
        source_id=str(row["source_id"]),
        source_name=row["source_name"],
        category=event_domain_name(row["ai_category"] or row["source_category"]),
        keywords=frozenset(_json_list(row["ai_keywords"])),
        entity_ids=frozenset(entity_ids),
        entity_keys=frozenset(entity_keys),
        event_entity_ids=frozenset(event_entity_ids),
        event_entity_keys=frozenset(event_entity_keys),
        content_state=str(row["content_state"] or "unavailable"),
        credibility=row["credibility_score"],
        canonical_url=row["canonical_url"],
        original_url=row["original_url"],
        has_ai_summary=bool(ai_summary),
        summary_length=len(summary or ""),
    )


def _event_signal(row, members: list[ArticleSignal]) -> EventSignal:
    entity_ids: set[str] = set()
    entity_keys: set[str] = set()
    event_entity_ids: set[str] = set()
    event_entity_keys: set[str] = set()
    keywords: set[str] = set()
    for member in members:
        entity_ids |= member.entity_ids
        entity_keys |= member.entity_keys
        event_entity_ids |= member.event_entity_ids
        event_entity_keys |= member.event_entity_keys
        keywords |= member.keywords
    return EventSignal(
        id=str(row["id"]),
        title=str(row["title"]),
        summary=row["summary"],
        category=event_domain_name(row["category"]),
        status=str(row["status"]),
        is_manual=bool(int(row["is_manual"])),
        members=tuple(members),
        entity_ids=frozenset(entity_ids),
        entity_keys=frozenset(entity_keys),
        event_entity_ids=frozenset(event_entity_ids),
        event_entity_keys=frozenset(event_entity_keys),
        keywords=frozenset(keywords),
        source_ids=frozenset(member.source_id for member in members),
        first_published_at=row["first_published_at"],
        last_published_at=row["last_published_at"] or row["last_seen_at"],
    )


def _load_events(conn, *, cutoff: str, limit: int) -> dict[str, EventSignal]:
    rows = agg_repo.recent_events(conn, cutoff=cutoff, limit=limit)
    grouped = agg_repo.event_members(conn, [str(row["id"]) for row in rows])
    events: dict[str, EventSignal] = {}
    for row in rows:
        event_id = str(row["id"])
        members = [
            _member_row_to_signal(conn, member)
            for member in grouped.get(event_id, [])
        ]
        if members:
            events[event_id] = _event_signal(row, members)
    return events


def _load_article_signals(conn, *, cutoff: str, limit: int) -> list[ArticleSignal]:
    return [
        _article_signal(conn, row)
        for row in agg_repo.unassigned_articles(conn, since=cutoff, limit=limit)
    ]


def _title_tokens(signal: ArticleSignal | EventSignal) -> frozenset[str]:
    value = tokens(headline_text(signal.title))
    if isinstance(signal, EventSignal):
        for member in signal.members[:5]:
            value = value | tokens(headline_text(member.title))
    return value


def _prefilter_article_event(article: ArticleSignal, event: EventSignal) -> bool:
    if article.source_id in event.source_ids:
        return False
    gap = hours_between(event.last_published_at, article.published_at)
    if gap is not None and abs(gap) > MAX_GAP_HOURS:
        return False
    if article.entity_ids and event.entity_ids:
        return True
    if article.entity_keys and event.entity_keys:
        return True
    if article.keywords and event.keywords:
        return True
    left = _title_tokens(article)
    right = _title_tokens(event)
    if not left or not right:
        return True
    overlap = len(left & right) / max(1, min(len(left), len(right)))
    return overlap >= TOKEN_PREFILTER


def _article_as_event(article: ArticleSignal) -> EventSignal:
    """Synthetic one-report event used to compare two unassigned articles."""

    return EventSignal(
        id=f"synthetic:{article.id}",
        title=article.title,
        summary=article.summary,
        category=article.category,
        status="candidate",
        is_manual=False,
        members=(article,),
        entity_ids=article.entity_ids,
        entity_keys=article.entity_keys,
        event_entity_ids=article.event_entity_ids,
        event_entity_keys=article.event_entity_keys,
        keywords=article.keywords,
        source_ids=frozenset({article.source_id}),
        first_published_at=article.published_at,
        last_published_at=article.published_at,
    )


def _prefilter_article_pair(left: ArticleSignal, right: ArticleSignal) -> bool:
    if left.source_id == right.source_id:
        return False
    gap = hours_between(left.published_at, right.published_at)
    if gap is not None and abs(gap) > MAX_GAP_HOURS:
        return False
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    return overlap >= ARTICLE_TOKEN_PREFILTER


def _candidate_payload(
    *,
    kind: str,
    score: AggregationScore,
    article: ArticleSignal | None = None,
    source_event: EventSignal | None = None,
    target_event: EventSignal,
    counterpart: ArticleSignal | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "decision": score.decision,
        "score": score.total,
        "guard_count": len(score.guards),
        "guards": list(score.guards),
        "reasons": list(score.reasons),
        "components": {
            "title": score.title,
            "summary": score.summary,
            "entity": score.entity,
            "keyword": score.keyword,
            "time": score.time,
            "category": score.category,
        },
        "target_event": {
            "id": target_event.id,
            "title": target_event.title,
            "category": target_event.category,
            "article_count": target_event.article_count,
            "source_count": target_event.source_count,
            "last_published_at": target_event.last_published_at,
        },
    }
    if article is not None:
        payload["article"] = {
            "id": article.id,
            "title": article.title,
            "source_id": article.source_id,
            "source_name": article.source_name,
            "published_at": article.published_at,
        }
    if source_event is not None:
        representative = choose_representative(
            [
                RepresentativeCandidate(
                    article_id=member.id,
                    title=member.title,
                    source_id=member.source_id,
                    source_name=member.source_name,
                    published_at=member.published_at,
                    credibility=member.credibility,
                    content_state=member.content_state,
                    has_ai_summary=member.has_ai_summary,
                    summary_length=member.summary_length,
                )
                for member in source_event.members
            ]
        )
        payload["source_event"] = {
            "id": source_event.id,
            "title": source_event.title,
            "category": source_event.category,
            "article_count": source_event.article_count,
            "source_count": source_event.source_count,
            "first_published_at": source_event.first_published_at,
            "last_published_at": source_event.last_published_at,
            "representative": (
                None
                if representative is None
                else {
                    "article_id": representative.article_id,
                    "title": representative.title,
                    "source_name": representative.source_name,
                    "published_at": representative.published_at,
                }
            ),
        }
    return payload


def _article_pair_payload(
    left: ArticleSignal, right: ArticleSignal, score: AggregationScore
) -> dict[str, object]:
    return {
        "kind": "article_group",
        "decision": score.decision,
        "score": score.total,
        "guard_count": len(score.guards),
        "guards": list(score.guards),
        "reasons": list(score.reasons),
        "components": {
            "title": score.title,
            "summary": score.summary,
            "entity": score.entity,
            "keyword": score.keyword,
            "time": score.time,
            "category": score.category,
        },
        "articles": [
            {
                "id": article.id,
                "title": article.title,
                "source_id": article.source_id,
                "source_name": article.source_name,
                "published_at": article.published_at,
                "url": article.canonical_url or article.original_url,
            }
            for article in (left, right)
        ],
    }


def _best_member_pair(    source: EventSignal, target: EventSignal
) -> tuple[AggregationScore, ArticleSignal] | None:
    best: tuple[AggregationScore, ArticleSignal] | None = None
    for member in source.members[:8]:
        if member.source_id in target.source_ids:
            continue
        score = score_article_event(member, target)
        if score.decision == "separate":
            continue
        if best is None or (score.decision == "merge", score.total) > (
            best[0].decision == "merge",
            best[0].total,
        ):
            best = (score, member)
    return best


class EventAggregationService:
    def status(self) -> dict[str, object]:
        cutoff = _cutoff(DEFAULT_DAYS)
        with database.read_session() as conn:
            events = conn.execute(
                "SELECT COUNT(*) FROM events WHERE status NOT IN ('merged','archived') "
                "AND last_seen_at >= ?",
                (cutoff,),
            ).fetchone()
            unassigned = conn.execute(
                "SELECT COUNT(*) FROM articles a WHERE a.deleted_at IS NULL "
                "AND a.status = 'active' AND COALESCE(a.published_at, a.fetched_at) >= ? "
                "AND NOT EXISTS (SELECT 1 FROM event_articles ea WHERE ea.article_id = a.id)",
                (cutoff,),
            ).fetchone()
            multi_source = conn.execute(
                "SELECT COUNT(*) FROM events WHERE status NOT IN ('merged','archived') "
                "AND source_count > 1",
            ).fetchone()
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "window_days": DEFAULT_DAYS,
            "recent_events": int(events[0]) if events else 0,
            "unassigned_articles": int(unassigned[0]) if unassigned else 0,
            "multi_source_events": int(multi_source[0]) if multi_source else 0,
            "auto_apply_enabled": os.getenv("PIH_EVENT_AGGREGATION_AUTO", "0") == "1",
            "merge_threshold": MERGE_THRESHOLD,
            "review_threshold": REVIEW_THRESHOLD,
        }

    def dry_run(
        self,
        *,
        days: int = DEFAULT_DAYS,
        event_limit: int = MAX_DRY_RUN_EVENTS,
        article_limit: int = MAX_DRY_RUN_ARTICLES,
    ) -> dict[str, object]:
        days = max(1, min(int(days), 90))
        event_limit = max(1, min(int(event_limit), MAX_DRY_RUN_EVENTS))
        article_limit = max(0, min(int(article_limit), MAX_DRY_RUN_ARTICLES))
        cutoff = _cutoff(days)
        with database.read_session() as conn:
            events = _load_events(conn, cutoff=cutoff, limit=event_limit)
            articles = _load_article_signals(conn, cutoff=cutoff, limit=article_limit)

        candidates: list[dict[str, object]] = []
        for article in articles:
            best: dict[str, object] | None = None
            for event in events.values():
                if not _prefilter_article_event(article, event):
                    continue
                score = score_article_event(article, event)
                if score.decision == "separate":
                    continue
                payload = _candidate_payload(
                    kind="article_attach", score=score, article=article, target_event=event
                )
                if best is None or (
                    payload["decision"] == "merge",
                    payload["score"],
                ) > (best["decision"] == "merge", best["score"]):
                    best = payload
            if best is not None:
                candidates.append(best)

        # Unassigned article pairs: the same story may already be reported by
        # two sources before either of them has formed an event.
        article_pairs: list[dict[str, object]] = []
        for index, left in enumerate(articles):
            for right in articles[index + 1 :]:
                if not _prefilter_article_pair(left, right):
                    continue
                forward = score_article_event(left, _article_as_event(right))
                backward = score_article_event(right, _article_as_event(left))
                score = forward if forward.total >= backward.total else backward
                if score.decision == "separate":
                    continue
                article_pairs.append(_article_pair_payload(left, right, score))
        article_pairs.sort(key=lambda item: float(item["score"]), reverse=True)

        event_pairs: list[dict[str, object]] = []
        ordered = list(events.values())
        for index, source in enumerate(ordered):
            for target in ordered[index + 1 :]:
                if source.is_manual or target.is_manual:
                    continue
                if source.category != target.category:
                    continue
                if source.source_ids == target.source_ids:
                    continue
                gap = hours_between(source.last_published_at, target.last_published_at)
                if gap is not None and abs(gap) > MAX_GAP_HOURS:
                    continue
                left_tokens = _title_tokens(source)
                right_tokens = _title_tokens(target)
                overlap = (
                    len(left_tokens & right_tokens)
                    / max(1, min(len(left_tokens), len(right_tokens)))
                    if left_tokens and right_tokens
                    else 0.0
                )
                shared_signal = bool(
                    (source.entity_ids & target.entity_ids)
                    or (source.entity_keys & target.entity_keys)
                    or (source.keywords & target.keywords)
                )
                if not shared_signal and overlap < 0.30:
                    continue
                forward = _best_member_pair(source, target)
                backward = _best_member_pair(target, source)
                if forward is None or backward is None:
                    continue
                score, member = (
                    (forward[0], forward[1])
                    if forward[0].total >= backward[0].total
                    else (backward[0], backward[1])
                )
                if score.decision == "separate":
                    continue
                # The pair below threshold from both directions is still useful
                # for review, so keep it with the lower of the two scores.
                if score.total < REVIEW_THRESHOLD:
                    continue
                event_pairs.append(
                    _candidate_payload(
                        kind="event_merge",
                        score=score,
                        source_event=source,
                        target_event=target,
                        counterpart=member,
                    )
                )

        groups = self._merge_groups(event_pairs, events)
        article_groups = self._article_groups(article_pairs, articles)
        summary = {
            "events_scanned": len(events),
            "articles_scanned": len(articles),
            "article_candidates": sum(1 for item in candidates if item["decision"] == "merge"),
            "article_review": sum(1 for item in candidates if item["decision"] == "review"),
            "event_candidates": sum(1 for item in event_pairs if item["decision"] == "merge"),
            "event_review": sum(1 for item in event_pairs if item["decision"] == "review"),
            "article_group_candidates": sum(
                1 for item in article_pairs if item["decision"] == "merge"
            ),
            "article_group_review": sum(
                1 for item in article_pairs if item["decision"] == "review"
            ),
            "article_groups": len(article_groups),
            "merge_groups": len(groups),
            "articles_in_groups": sum(
                int(group["article_count"]) for group in article_groups
            ),
        }
        log_event(
            "event_aggregation_dry_run",
            events=len(events),
            articles=len(articles),
            candidates=len(candidates) + len(event_pairs) + len(article_pairs),
            groups=len(groups) + len(article_groups),
        )
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "generated_at": utc_timestamp(),
            "window_days": days,
            "dry_run": True,
            "summary": summary,
            "article_candidates": candidates,
            "article_pairs": article_pairs,
            "event_candidates": event_pairs,
            "groups": groups,
            "article_groups": article_groups,
        }

    def _merge_groups(
        self, pairs: list[dict[str, object]], events: dict[str, EventSignal]
    ) -> list[dict[str, object]]:
        parent: dict[str, str] = {}

        def find(value: str) -> str:
            parent.setdefault(value, value)
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        merge_pairs = [
            item for item in pairs if item["decision"] == "merge"
        ]
        for item in merge_pairs:
            source_id = str(item["source_event"]["id"])
            target_id = str(item["target_event"]["id"])
            union(source_id, target_id)

        members: dict[str, list[str]] = {}
        for event_id in list(parent):
            members.setdefault(find(event_id), []).append(event_id)

        groups: list[dict[str, object]] = []
        for root, event_ids in members.items():
            if len(event_ids) < 2:
                continue
            ordered = sorted(
                (events[event_id] for event_id in event_ids),
                key=lambda event: (
                    event.article_count,
                    event.source_count,
                    -(_timestamp_value(event.first_published_at)),
                ),
                reverse=True,
            )
            target = ordered[0]
            article_count = sum(event.article_count for event in ordered)
            source_ids: set[str] = set()
            for event in ordered:
                source_ids |= set(event.source_ids)
            rationale = [
                {
                    "source_event_id": item["source_event"]["id"],
                    "target_event_id": item["target_event"]["id"],
                    "score": item["score"],
                    "reasons": item["reasons"],
                }
                for item in merge_pairs
                if str(item["source_event"]["id"]) in event_ids
                and str(item["target_event"]["id"]) in event_ids
            ]
            groups.append(
                {
                    "group_id": f"group-{root}",
                    "target_event_id": target.id,
                    "target_title": target.title,
                    "target_category": target.category,
                    "event_ids": event_ids,
                    "article_count": article_count,
                    "source_count": len(source_ids),
                    "first_published_at": min(
                        (event.first_published_at for event in ordered if event.first_published_at),
                        default=None,
                    ),
                    "last_published_at": max(
                        (event.last_published_at for event in ordered if event.last_published_at),
                        default=None,
                    ),
                    "pairs": rationale,
                }
            )
        groups.sort(key=lambda item: int(item["article_count"]), reverse=True)
        return groups

    def _article_groups(
        self, pairs: list[dict[str, object]], articles: list[ArticleSignal]
    ) -> list[dict[str, object]]:
        by_id = {article.id: article for article in articles}
        parent: dict[str, str] = {}

        def find(value: str) -> str:
            parent.setdefault(value, value)
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        merge_pairs = [item for item in pairs if item["decision"] == "merge"]
        for item in merge_pairs:
            first, second = item["articles"]
            union(str(first["id"]), str(second["id"]))

        members: dict[str, list[str]] = {}
        for article_id in list(parent):
            members.setdefault(find(article_id), []).append(article_id)

        groups: list[dict[str, object]] = []
        for root, article_ids in members.items():
            if len(article_ids) < 2:
                continue
            signals = [by_id[article_id] for article_id in article_ids if article_id in by_id]
            if len(signals) < 2:
                continue
            representative = choose_representative(
                [
                    RepresentativeCandidate(
                        article_id=item.id,
                        title=item.title,
                        source_id=item.source_id,
                        source_name=item.source_name,
                        published_at=item.published_at,
                        credibility=item.credibility,
                        content_state=item.content_state,
                        has_ai_summary=item.has_ai_summary,
                        summary_length=item.summary_length,
                    )
                    for item in signals
                ]
            )
            groups.append(
                {
                    "group_id": f"articles-{root}",
                    "article_ids": [item.id for item in signals],
                    "article_count": len(signals),
                    "source_count": len({item.source_id for item in signals}),
                    "representative": (
                        None
                        if representative is None
                        else {
                            "article_id": representative.article_id,
                            "title": representative.title,
                            "source_name": representative.source_name,
                            "published_at": representative.published_at,
                            "score": representative.score,
                            "reasons": list(representative.reasons),
                        }
                    ),
                    "articles": [
                        {
                            "id": item.id,
                            "title": item.title,
                            "source_name": item.source_name,
                            "published_at": item.published_at,
                            "url": item.canonical_url or item.original_url,
                        }
                        for item in signals
                    ],
                    "pairs": [
                        item
                        for item in merge_pairs
                        if {str(part["id"]) for part in item["articles"]} <= set(article_ids)
                    ],
                }
            )
        groups.sort(key=lambda item: int(item["article_count"]), reverse=True)
        return groups

    def apply(
        self, pairs: list[dict[str, object]], *, confirm: bool, create_backup: bool = True
    ) -> dict[str, object]:
        if confirm is not True:
            raise validation("confirm", "required", "必须显式确认后才能执行聚合合并")
        if not pairs:
            raise validation("pairs", "required", "至少提供一个合并关系")
        if len(pairs) > MAX_APPLY_PAIRS:
            raise validation("pairs", "too_many", f"单次最多应用 {MAX_APPLY_PAIRS} 个合并")
        if os.getenv("PIH_EVENT_AGGREGATION_ENABLED", "1") != "1":
            raise conflict("aggregation_disabled", "事件聚合已被配置关闭")

        backup_payload: dict[str, object] | None = None
        if create_backup:
            try:
                backup_payload = backup.create_backup("phase76-agg")
            except Exception as exc:  # noqa: BLE001 - never merge without a backup
                raise conflict(
                    "aggregation_backup_failed",
                    f"合并前备份失败：{type(exc).__name__}",
                ) from exc

        applied: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        affected_events: set[str] = set()
        for pair in pairs:
            kind = str(pair.get("kind") or pair.get("type") or "")
            try:
                if kind == "event_merge":
                    result = self._apply_event_merge(
                        source_event_id=str(pair.get("source_event_id") or ""),
                        target_event_id=str(pair.get("target_event_id") or ""),
                    )
                elif kind == "article_group":
                    result = self._apply_article_group(
                        article_ids=[
                            str(item) for item in (pair.get("article_ids") or [])
                        ]
                    )
                elif kind == "article_attach":
                    result = self._apply_article_attach(
                        article_id=str(pair.get("article_id") or ""),
                        event_id=str(pair.get("event_id") or ""),
                    )
                else:
                    raise validation("kind", "invalid", "合并类型必须是 event_merge 或 article_attach")
                applied.append(result)
                affected_events.add(str(result["target_event_id"]))
            except Exception as exc:  # noqa: BLE001 - report each rejection
                rejected.append(
                    {
                        "pair": pair,
                        "code": getattr(exc, "code", "aggregation_rejected"),
                        "message": str(getattr(exc, "message", exc))[:300],
                    }
                )

        for event_id in affected_events:
            try:
                from services import personalization_service

                personalization_service.refresh_event(event_id)
            except Exception:  # noqa: BLE001 - recommendations must not block
                log_event("event_aggregation_recommendation_refresh_failed", event_id=event_id, level="warn")

        return {
            "algorithm_version": ALGORITHM_VERSION,
            "applied": applied,
            "rejected": rejected,
            "backup": backup_payload,
            "applied_count": len(applied),
            "rejected_count": len(rejected),
        }

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def _apply_article_group(self, *, article_ids: list[str]) -> dict[str, object]:
        ids = list(dict.fromkeys(article_ids))
        if len(ids) < 2:
            raise validation("article_ids", "too_few", "至少选择两篇不同来源的文章")
        if len(ids) > 20:
            raise validation("article_ids", "too_many", "单次最多聚合 20 篇文章")
        now = utc_timestamp()
        with database.session() as conn:
            rows = [agg_repo.article_row_by_id(conn, article_id) for article_id in ids]
            if any(row is None for row in rows):
                raise not_found("aggregation_article_unavailable", "文章不存在或不可用")
            for article_id in ids:
                if event_repo.get_article_membership(conn, article_id) is not None:
                    raise conflict("aggregation_article_assigned", "文章已属于其他事件")
            signals = [
                _article_signal(conn, row) for row in rows if row is not None
            ]
            # Same-source, same-headline variants are feed duplicates, not
            # independent reports. They are still attached to the event later,
            # but must not be used to verify cross-source equivalence.
            unique: list[ArticleSignal] = []
            seen_keys: set[tuple[str, str]] = set()
            for signal in signals:
                key = (signal.source_id, headline_text(signal.title).lower())
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                unique.append(signal)
            if len({signal.source_id for signal in unique}) < 2:
                raise conflict("aggregation_same_source", "至少需要两个不同来源")
            signals.sort(key=lambda item: (item.published_at is None, item.published_at or ""))
            representative = choose_representative(
                [
                    RepresentativeCandidate(
                        article_id=item.id,
                        title=item.title,
                        source_id=item.source_id,
                        source_name=item.source_name,
                        published_at=item.published_at,
                        credibility=item.credibility,
                        content_state=item.content_state,
                        has_ai_summary=item.has_ai_summary,
                        summary_length=item.summary_length,
                    )
                    for item in unique
                ]
            )
            if representative is None:
                raise conflict("aggregation_empty_group", "没有可用的代表文章")
            lead = next(item for item in unique if item.id == representative.article_id)
            accepted: list[tuple[ArticleSignal, float]] = [(lead, 1.0)]
            same_source_duplicates: list[ArticleSignal] = []
            target = _article_as_event(lead)
            accepted_sources = {lead.source_id}
            for candidate in unique:
                if candidate.id == lead.id:
                    continue
                score = score_article_event(candidate, target)
                if score.decision == "merge":
                    accepted.append((candidate, score.total))
                    accepted_sources.add(candidate.source_id)
                    continue
                # A near-identical headline from a source already represented in
                # the group is a feed duplicate, not a conflicting event.
                if (
                    candidate.source_id in accepted_sources
                    and title_similarity(
                        headline_text(candidate.title), headline_text(lead.title)
                    )
                    >= 0.90
                ):
                    same_source_duplicates.append(candidate)
                    continue
                raise conflict(
                    "aggregation_not_confirmed",
                    f"文章「{candidate.title[:40]}」重新计算为 {score.decision}"
                    f"（{score.total:.3f}），守卫 {','.join(score.guards) or '无'}，整组拒绝聚合",
                )

            first_published = min(
                (item.published_at for item in signals if item.published_at), default=None
            )
            last_published = max(
                (item.published_at for item in signals if item.published_at), default=None
            )
            category = event_domain_name(lead.category)
            event_id = str(uuid.uuid4())
            event_repo.insert_event(
                conn,
                {
                    "id": event_id,
                    "title": (lead.title or "未命名事件")[:300],
                    "summary": (lead.summary or lead.title or "")[:2000],
                    "category": category,
                    "status": "candidate",
                    "status_reason": "跨来源聚合创建的事件候选",
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "first_published_at": first_published,
                    "last_published_at": last_published,
                    "occurred_at": None,
                    "article_count": 0,
                    "source_count": 0,
                    "is_manual": 0,
                    "merged_into_event_id": None,
                    "algorithm_version": ALGORITHM_VERSION,
                    "title_source": "auto",
                    "summary_source": "auto",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            for index, (article, similarity) in enumerate(accepted):
                duplicate = bool(
                    article.content_hash and article.content_hash == lead.content_hash
                )
                role = "duplicate" if duplicate else ("report" if index == 0 else "follow_up")
                event_repo.insert_event_article(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "event_id": event_id,
                        "article_id": article.id,
                        "role": role,
                        "similarity": None if index == 0 else similarity,
                        "match_reasons_json": json.dumps(
                            {
                                "algorithm": ALGORITHM_VERSION,
                                "aggregated": True,
                                "representative": lead.id,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "is_manual": 0,
                        "added_at": now,
                        "created_at": now,
                    },
                )
                event_repo.insert_timeline_item(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "event_id": event_id,
                        "article_id": article.id,
                        "kind": "first_report" if index == 0 else "follow_up",
                        "title": article.title[:300],
                        "description": (article.summary or "")[:2000] or None,
                        "occurred_at": None,
                        "published_at": article.published_at,
                        "recognized_at": now,
                        "confidence": None if index == 0 else similarity,
                        "is_key": 1,
                        "evidence_json": json.dumps(
                            {
                                "algorithm": ALGORITHM_VERSION,
                                "aggregated": True,
                                "source_name": article.source_name,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )[:4000],
                        "created_at": now,
                    },
                )
            accepted_ids = {article.id for article, _ in accepted}
            duplicate_ids = {article.id for article in same_source_duplicates}
            extras = [
                signal
                for signal in signals
                if signal.id not in accepted_ids and signal.id not in duplicate_ids
            ]
            extras.extend(same_source_duplicates)
            for extra in extras:
                event_repo.insert_event_article(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "event_id": event_id,
                        "article_id": extra.id,
                        "role": "duplicate",
                        "similarity": None,
                        "match_reasons_json": json.dumps(
                            {
                                "algorithm": ALGORITHM_VERSION,
                                "aggregated": True,
                                "duplicate_of": lead.id,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "is_manual": 0,
                        "added_at": now,
                        "created_at": now,
                    },
                )
            recompute_event_aggregates(conn, event_id, now)
            rebuild_event_entities(conn, event_id, now)
            refresh_event_summary(conn, event_id)
            refresh_event_category(conn, event_id, now=now)
            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=event_id,
                entity_id=None,
                action="create_event",
                actor="algorithm",
                detail={
                    "article_ids": [signal.id for signal in signals],
                    "algorithm_version": ALGORITHM_VERSION,
                    "representative_article_id": lead.id,
                    "duplicate_article_ids": [signal.id for signal in extras],
                    "scores": {item.id: score for item, score in accepted[1:]},
                },
                created_at=now,
            )
            score_event_in_conn(conn, event_id, now=now)
            personalization_repo.deactivate_excluded_results(conn, now=now)

        log_event(
            "event_aggregation_group_created",
            event_id=event_id,
            articles=len(signals),
            independent_articles=len(accepted),
        )
        return {
            "kind": "article_group",
            "target_event_id": event_id,
            "article_ids": [signal.id for signal in signals],
            "article_count": len(signals),
            "independent_article_count": len(accepted),
            "representative_article_id": lead.id,
            "target": self._event_snapshot(event_id),
        }

    def _apply_event_merge(self, *, source_event_id: str, target_event_id: str) -> dict[str, object]:
        if not source_event_id or not target_event_id:
            raise validation("event_id", "required", "必须提供来源事件与目标事件")
        if source_event_id == target_event_id:
            raise validation("event_id", "same", "不能合并到自身")
        now = utc_timestamp()
        with database.session() as conn:
            rows = agg_repo.event_rows_by_ids(conn, [source_event_id, target_event_id])
            source_row = rows.get(source_event_id)
            target_row = rows.get(target_event_id)
            if source_row is None or target_row is None:
                raise not_found("event_not_found", "事件不存在")
            if bool(int(source_row["is_manual"])) or bool(int(target_row["is_manual"])):
                raise conflict("aggregation_manual_event", "人工事件不参与自动合并")
            if str(source_row["status"]) in TERMINAL:
                raise conflict("aggregation_event_closed", "来源事件已合并、归档或关闭")
            if str(target_row["status"]) in {"merged", "archived"}:
                raise conflict("aggregation_target_closed", "目标事件已合并或归档")
            members = agg_repo.event_members(conn, [source_event_id, target_event_id])
            source_members = [
                _member_row_to_signal(conn, row) for row in members.get(source_event_id, [])
            ]
            target_members = [
                _member_row_to_signal(conn, row) for row in members.get(target_event_id, [])
            ]
            if not source_members or not target_members:
                raise conflict("aggregation_empty_event", "事件没有可用文章")
            source = _event_signal(source_row, source_members)
            target = _event_signal(target_row, target_members)
            score = self._verify_pair(source, target)
            if score.decision != "merge":
                raise conflict(
                    "aggregation_not_confirmed",
                    f"当前数据重新计算为 {score.decision}（{score.total:.3f}），拒绝合并",
                )

            moved, duplicates = event_repo.move_articles(
                conn, source_event_id=source_event_id, target_event_id=target_event_id
            )
            moved_timeline = event_repo.move_timeline_all(
                conn, source_event_id=source_event_id, target_event_id=target_event_id
            )
            relation_repo.merge_event_relations(
                conn,
                source_event_id=source_event_id,
                target_event_id=target_event_id,
                updated_at=now,
            )
            event_repo.delete_event_entities(conn, source_event_id)
            event_repo.update_event(
                conn,
                source_event_id,
                {
                    "status": "merged",
                    "merged_into_event_id": target_event_id,
                    "status_reason": f"跨来源聚合合并（{ALGORITHM_VERSION}）",
                    "updated_at": now,
                },
            )
            recompute_event_aggregates(conn, target_event_id, now)
            recompute_event_aggregates(conn, source_event_id, now)
            rebuild_event_entities(conn, target_event_id, now)
            refresh_event_summary(conn, target_event_id)
            refresh_event_category(conn, target_event_id, now=now)
            event_repo.insert_timeline_item(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "event_id": target_event_id,
                    "article_id": None,
                    "kind": "merge",
                    "title": f"聚合合并：{source.title}"[:300],
                    "description": f"并入 {moved} 篇文章、{moved_timeline} 个时间线节点",
                    "occurred_at": None,
                    "published_at": None,
                    "recognized_at": now,
                    "confidence": score.total,
                    "is_key": 1,
                    "evidence_json": json.dumps(
                        {
                            "algorithm": ALGORITHM_VERSION,
                            "source_event_id": source_event_id,
                            "score": score.total,
                            "reasons": list(score.reasons),
                            "guards": list(score.guards),
                            "moved_articles": moved,
                            "duplicate_articles": duplicates,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )[:4000],
                    "created_at": now,
                },
            )
            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=target_event_id,
                entity_id=None,
                action="merge_events",
                actor="algorithm",
                detail={
                    "source_event_id": source_event_id,
                    "target_event_id": target_event_id,
                    "algorithm_version": ALGORITHM_VERSION,
                    "score": score.total,
                    "reasons": list(score.reasons),
                    "moved_articles": moved,
                    "duplicate_articles": duplicates,
                    "moved_timeline_items": moved_timeline,
                },
                created_at=now,
            )
            personalization_repo.deactivate_event_result(conn, source_event_id, now=now)
            score_event_in_conn(conn, target_event_id, now=now)

        updated = self._event_snapshot(target_event_id)
        log_event(
            "event_aggregation_merged",
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            moved=moved,
            score=score.total,
        )
        return {
            "kind": "event_merge",
            "target_event_id": target_event_id,
            "source_event_id": source_event_id,
            "moved_articles": moved,
            "duplicate_articles": duplicates,
            "moved_timeline_items": moved_timeline,
            "score": score.total,
            "reasons": list(score.reasons),
            "target": updated,
        }

    def _apply_article_attach(self, *, article_id: str, event_id: str) -> dict[str, object]:
        if not article_id or not event_id:
            raise validation("article_id", "required", "必须提供文章与目标事件")
        now = utc_timestamp()
        with database.session() as conn:
            if event_repo.get_article_membership(conn, article_id) is not None:
                raise conflict("aggregation_article_assigned", "文章已属于其他事件")
            rows = agg_repo.event_rows_by_ids(conn, [event_id])
            event_row = rows.get(event_id)
            if event_row is None:
                raise not_found("event_not_found", "事件不存在")
            if bool(int(event_row["is_manual"])):
                raise conflict("aggregation_manual_event", "人工事件不参与自动合并")
            if str(event_row["status"]) in TERMINAL:
                raise conflict("aggregation_event_closed", "目标事件已合并、归档或关闭")
            articles = agg_repo.article_row_by_id(conn, article_id)
            if articles is None:
                raise conflict("aggregation_article_unavailable", "文章不存在、不可用或已归属事件")
            article_row = articles
            members = agg_repo.event_members(conn, [event_id]).get(event_id, [])
            if not members:
                raise conflict("aggregation_empty_event", "目标事件没有可用文章")
            article = _article_signal(conn, article_row)
            target = _event_signal(
                event_row, [_member_row_to_signal(conn, row) for row in members]
            )
            score = score_article_event(article, target)
            if score.decision != "merge":
                raise conflict(
                    "aggregation_not_confirmed",
                    f"当前数据重新计算为 {score.decision}（{score.total:.3f}），拒绝合并",
                )
            duplicate = any(
                member.content_hash and member.content_hash == article.content_hash
                for member in target.members
            )
            role = "duplicate" if duplicate else "follow_up"
            event_repo.insert_event_article(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "event_id": event_id,
                    "article_id": article_id,
                    "role": role,
                    "similarity": score.total,
                    "match_reasons_json": json.dumps(
                        {
                            "algorithm": ALGORITHM_VERSION,
                            "reasons": list(score.reasons),
                            "guards": list(score.guards),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )[:4000],
                    "is_manual": 0,
                    "added_at": now,
                    "created_at": now,
                },
            )
            previous_status = str(event_row["status"])
            stats = recompute_event_aggregates(conn, event_id, now)
            rebuild_event_entities(conn, event_id, now)
            refresh_event_summary(conn, event_id)
            refresh_event_category(conn, event_id, now=now)
            event_repo.insert_timeline_item(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "event_id": event_id,
                    "article_id": article_id,
                    "kind": "follow_up",
                    "title": article.title[:300],
                    "description": (article.summary or "")[:2000] or None,
                    "occurred_at": None,
                    "published_at": article.published_at,
                    "recognized_at": now,
                    "confidence": score.total,
                    "is_key": 1,
                    "evidence_json": json.dumps(
                        {
                            "algorithm": ALGORITHM_VERSION,
                            "source_name": article.source_name,
                            "reasons": list(score.reasons),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )[:4000],
                    "created_at": now,
                },
            )
            new_status = next_status(
                previous_status,
                article_count=int(stats["article_count"]),
                first_seen_at=str(event_row["first_seen_at"]),
                last_published_at=stats["last_published_at"],
                now=None,
                new_article=True,
            )
            if new_status != previous_status:
                reason = transition_reason(previous_status, new_status)
                event_repo.update_event(
                    conn,
                    event_id,
                    {
                        "status": new_status,
                        "status_reason": reason[:500] or None,
                        "updated_at": now,
                    },
                )
                audit_repo.insert(
                    conn,
                    audit_id=str(uuid.uuid4()),
                    event_id=event_id,
                    entity_id=None,
                    action="change_status",
                    actor="algorithm",
                    detail={
                        "previous": previous_status,
                        "current": new_status,
                        "reason": reason,
                        "automatic": True,
                    },
                    created_at=now,
                )
            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=event_id,
                entity_id=None,
                action="attach_article",
                actor="algorithm",
                detail={
                    "article_id": article_id,
                    "algorithm_version": ALGORITHM_VERSION,
                    "score": score.total,
                    "role": role,
                    "reasons": list(score.reasons),
                },
                created_at=now,
            )
            score_event_in_conn(conn, event_id, now=now)

        log_event(
            "event_aggregation_attached",
            event_id=event_id,
            article_id=article_id,
            score=score.total,
            role=role,
        )
        return {
            "kind": "article_attach",
            "target_event_id": event_id,
            "article_id": article_id,
            "role": role,
            "score": score.total,
            "reasons": list(score.reasons),
            "target": self._event_snapshot(event_id),
        }

    # ------------------------------------------------------------------

    def _verify_pair(self, source: EventSignal, target: EventSignal) -> AggregationScore:
        best = _best_member_pair(source, target)
        if best is not None:
            return best[0]
        # Fall back to the event-level text so a pair of one-article events can
        # still be verified deterministically.
        representative = source.members[0]
        return score_article_event(representative, target)

    def _event_snapshot(self, event_id: str) -> dict[str, object] | None:
        with database.read_session() as conn:
            event = event_repo.get(conn, event_id)
            members = agg_repo.event_members(conn, [event_id]).get(event_id, [])
        if event is None:
            return None
        signals = [
            RepresentativeCandidate(
                article_id=str(row["article_id"]),
                title=str(row["title"]),
                source_id=str(row["source_id"]),
                source_name=row["source_name"],
                published_at=row["published_at"],
                credibility=row["credibility_score"],
                content_state=str(row["content_state"] or "unavailable"),
                has_ai_summary=bool(row["ai_summary"]),
                summary_length=len(str(row["ai_summary"] or row["summary"] or "")),
            )
            for row in members
        ]
        representative = choose_representative(signals)
        return {
            "id": event.id,
            "title": event.title,
            "category": event_domain_name(event.category),
            "status": event.status,
            "article_count": event.article_count,
            "source_count": event.source_count,
            "first_published_at": event.first_published_at,
            "last_published_at": event.last_published_at,
            "representative": (
                None
                if representative is None
                else {
                    "article_id": representative.article_id,
                    "title": representative.title,
                    "source_name": representative.source_name,
                    "published_at": representative.published_at,
                    "score": representative.score,
                    "reasons": list(representative.reasons),
                }
            ),
        }


def _timestamp_value(value: str | None) -> float:
    from event_intelligence.text import parse_timestamp

    parsed = parse_timestamp(value)
    return 0.0 if parsed is None else parsed.timestamp()


_aggregation_service: EventAggregationService | None = None


def get_event_aggregation_service() -> EventAggregationService:
    global _aggregation_service
    if _aggregation_service is None:
        _aggregation_service = EventAggregationService()
    return _aggregation_service
