"""Personal interest matching, explainable recommendations and daily digests.

Phase 7.3.1. This service only orchestrates existing data:

- article AI category/keywords/entities (Phase 3/4)
- events, membership and current event scores (Phase 4)
- sources credibility (Phase 1)
- FTS/keyword statistics are not duplicated: emerging topics reuse
  `services.intelligence_stats.build_stats`.

No model call is made here. Every score is a deterministic rule result stored in
`recommendation_results`, so the UI can always explain it and tests can assert it.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import database
from core.timeutil import utc_timestamp
from database.repositories import event_aggregation_repository as aggregation_repo
from database.repositories import personalization_repository as repo
from event_intelligence import personalization as algo
from event_intelligence.aggregation import (
    RepresentativeCandidate,
    choose_representative,
)
from event_intelligence.taxonomy import event_domain_name
from services import intelligence_stats
from services.errors import conflict, not_found, validation

LEVEL_WEIGHTS = dict(algo.DEFAULT_LEVEL_WEIGHTS)
LEVEL_RANK = {"core": 0, "extended": 1, "general": 2, "muted": 3}
FEEDBACK_VALUES = {
    "interested",
    "not_interested",
    "important",
    "duplicate",
    "source_disliked",
    "later",
}
INTEREST_TYPES = {"domain", "topic", "keyword", "entity", "source", "event"}
FEED_WINDOW_DAYS = 14
EVENT_WINDOW_DAYS = 30
CANDIDATE_EVENT_LIMIT = 400
CANDIDATE_ARTICLE_LIMIT = 400
MIN_FEED_SCORE = 30.0
DIGEST_VERSION = "digest-v1"
MINUTES_PER_ITEM = 4


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _local_today(profile) -> date:
    return datetime.now(_local_zone(profile.timezone)).date()


def _day_start_utc(profile, day: date) -> str:
    zone = _local_zone(profile.timezone)
    moment = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _window_start(days: int) -> str:
    moment = _now() - timedelta(days=days)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _level_weight(level: str) -> float:
    return LEVEL_WEIGHTS.get(level, 0.3)


def _profile_payload(profile) -> dict[str, object]:
    return {
        "display_name": profile.display_name,
        "digest_time": profile.digest_time,
        "timezone": profile.timezone,
        "daily_item_limit": profile.daily_item_limit,
        "daily_minutes": profile.daily_minutes,
        "exploration_ratio": profile.exploration_ratio,
        "auto_adjust_enabled": profile.auto_adjust_enabled,
        "onboarding_done": profile.onboarding_done,
        "scoring_config": profile.scoring_config,
        "updated_at": profile.updated_at,
    }


def profile_payload() -> dict[str, object]:
    with database.read_session() as conn:
        profile = repo.get_profile(conn)
        interests = repo.list_interests(conn)
    return {
        "profile": _profile_payload(profile),
        "interest_count": len(interests),
        "enabled_interest_count": sum(1 for item in interests if item.enabled),
        "has_core_interest": any(item.enabled and item.level == "core" for item in interests),
        "blocked_source_count": len(_blocked_sources()),
    }


def _blocked_sources() -> list[dict[str, object]]:
    with database.read_session() as conn:
        return repo.list_blocked_sources(conn)


def update_profile(fields: dict[str, object]) -> dict[str, object]:
    allowed = {
        "display_name",
        "digest_time",
        "timezone",
        "daily_item_limit",
        "daily_minutes",
        "exploration_ratio",
        "auto_adjust_enabled",
        "onboarding_done",
        "scoring_config",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise validation(sorted(unknown)[0], "unknown", "存在未知的画像设置字段")

    payload: dict[str, object] = {}
    if "display_name" in fields:
        value = str(fields["display_name"]).strip()
        if not 1 <= len(value) <= 60:
            raise validation("display_name", "range", "名称长度必须在 1–60 之间")
        payload["display_name"] = value
    if "digest_time" in fields:
        value = str(fields["digest_time"]).strip()
        try:
            hour, minute = value.split(":")
            assert 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
        except (ValueError, AssertionError):
            raise validation("digest_time", "format", "时间必须是 HH:MM") from None
        payload["digest_time"] = f"{int(hour):02d}:{int(minute):02d}"
    if "timezone" in fields:
        value = str(fields["timezone"]).strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise validation("timezone", "unknown", "未知的时区标识") from None
        payload["timezone"] = value
    if "daily_item_limit" in fields:
        value = fields["daily_item_limit"]
        if value is not None:
            value = int(value)  # type: ignore[arg-type]
            if not 1 <= value <= 100:
                raise validation("daily_item_limit", "range", "每日条数必须在 1–100 之间")
        payload["daily_item_limit"] = value
    if "daily_minutes" in fields:
        value = fields["daily_minutes"]
        if value is not None:
            value = int(value)  # type: ignore[arg-type]
            if not 1 <= value <= 600:
                raise validation("daily_minutes", "range", "每日分钟数必须在 1–600 之间")
        payload["daily_minutes"] = value
    if "exploration_ratio" in fields:
        value = float(fields["exploration_ratio"])  # type: ignore[arg-type]
        if not 0.0 <= value <= 0.5:
            raise validation("exploration_ratio", "range", "探索比例必须在 0–0.5 之间")
        payload["exploration_ratio"] = value
    if "auto_adjust_enabled" in fields:
        payload["auto_adjust_enabled"] = 1 if bool(fields["auto_adjust_enabled"]) else 0
    if "onboarding_done" in fields:
        payload["onboarding_done"] = 1 if bool(fields["onboarding_done"]) else 0
    if "scoring_config" in fields:
        value = fields["scoring_config"]
        if not isinstance(value, dict):
            raise validation("scoring_config", "type", "scoring_config 必须是对象")
        encoded = _json(value)
        if len(encoded) > 4000:
            raise validation("scoring_config", "size", "scoring_config 过大")
        payload["scoring_config_json"] = encoded

    now = utc_timestamp()
    with database.session() as conn:
        profile = repo.update_profile(conn, payload, updated_at=now)
    return _profile_payload(profile)


# ---------------------------------------------------------------------------
# interests
# ---------------------------------------------------------------------------


def _interest_payload(record) -> dict[str, object]:
    return {
        "id": record.id,
        "name": record.name,
        "interest_type": record.interest_type,
        "level": record.level,
        "weight": round(record.weight, 3),
        "domain_key": record.domain_key,
        "enabled": record.enabled,
        "notes": record.notes,
        "keywords": list(record.keywords),
        "exclusion_keywords": list(record.exclusion_keywords),
        "entity_ids": list(record.entity_ids),
        "entity_names": list(record.entity_names),
        "source_ids": list(record.source_ids),
        "source_names": list(record.source_names),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def interests_payload() -> dict[str, object]:
    with database.read_session() as conn:
        records = repo.list_interests(conn)
    return {
        "items": [_interest_payload(record) for record in records],
        "total": len(records),
        "levels": {key: _level_weight(key) for key in LEVEL_WEIGHTS},
    }


def _resolve_domain_key(interest_type: str, raw: object) -> str | None:
    if interest_type not in {"domain", "topic"}:
        return None if raw in (None, "") else str(raw)
    if raw in (None, ""):
        raise validation("domain_key", "required", "领域/主题兴趣必须提供 domain_key")
    from event_intelligence.taxonomy import DOMAIN_BY_KEY, TOPIC_BY_KEY

    key = str(raw).strip().lower()
    if key not in DOMAIN_BY_KEY and key not in TOPIC_BY_KEY:
        raise validation("domain_key", "unknown", "domain_key 必须来自 taxonomy-v1")
    return key


def create_interest(payload: dict[str, object]) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    if not 1 <= len(name) <= 80:
        raise validation("name", "range", "兴趣名称长度必须在 1–80 之间")
    interest_type = str(payload.get("interest_type", "topic"))
    if interest_type not in INTEREST_TYPES:
        raise validation("interest_type", "unknown", "不支持的关注类型")
    level = str(payload.get("level", "general"))
    if level not in LEVEL_WEIGHTS:
        raise validation("level", "unknown", "关注等级必须是 core/extended/general/muted")
    weight = payload.get("weight")
    weight_value = _level_weight(level) if weight is None else float(weight)  # type: ignore[arg-type]
    if not 0.0 <= weight_value <= 1.0:
        raise validation("weight", "range", "权重必须在 0–1 之间")
    domain_key = _resolve_domain_key(interest_type, payload.get("domain_key"))
    notes = payload.get("notes")
    if notes is not None and len(str(notes)) > 500:
        raise validation("notes", "size", "备注最多 500 字符")

    now = utc_timestamp()
    interest_id = str(uuid.uuid4())
    with database.session() as conn:
        if repo.find_interest_by_name(conn, name) is not None:
            raise conflict("interest_exists", "已存在同名兴趣")
        repo.insert_interest(
            conn,
            {
                "id": interest_id,
                "name": name,
                "interest_type": interest_type,
                "level": level,
                "weight": weight_value,
                "domain_key": domain_key,
                "enabled": 0 if payload.get("enabled") is False else 1,
                "notes": None if notes is None else str(notes),
                "created_at": now,
                "updated_at": now,
            },
        )
        repo.replace_keywords(
            conn,
            interest_id,
            keywords=[str(item) for item in payload.get("keywords") or []],
            exclusions=[str(item) for item in payload.get("exclusion_keywords") or []],
            created_at=now,
            make_id=lambda: uuid.uuid4(),
        )
        record = repo.get_interest(conn, interest_id)
    assert record is not None
    return _interest_payload(record)


def update_interest(interest_id: str, fields: dict[str, object]) -> dict[str, object]:
    allowed = {
        "name",
        "interest_type",
        "level",
        "weight",
        "domain_key",
        "enabled",
        "notes",
        "keywords",
        "exclusion_keywords",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise validation(sorted(unknown)[0], "unknown", "存在未知的兴趣字段")
    now = utc_timestamp()
    with database.session() as conn:
        record = repo.get_interest(conn, interest_id)
        if record is None:
            raise not_found("interest_not_found", "兴趣不存在")

        payload: dict[str, object] = {}
        if "name" in fields:
            name = str(fields["name"]).strip()
            if not 1 <= len(name) <= 80:
                raise validation("name", "range", "兴趣名称长度必须在 1–80 之间")
            existing = repo.find_interest_by_name(conn, name)
            if existing is not None and existing.id != interest_id:
                raise conflict("interest_exists", "已存在同名兴趣")
            payload["name"] = name
        if "interest_type" in fields:
            value = str(fields["interest_type"])
            if value not in INTEREST_TYPES:
                raise validation("interest_type", "unknown", "不支持的关注类型")
            payload["interest_type"] = value
        if "level" in fields:
            value = str(fields["level"])
            if value not in LEVEL_WEIGHTS:
                raise validation("level", "unknown", "关注等级必须是 core/extended/general/muted")
            payload["level"] = value
        if "weight" in fields:
            value = float(fields["weight"])  # type: ignore[arg-type]
            if not 0.0 <= value <= 1.0:
                raise validation("weight", "range", "权重必须在 0–1 之间")
            payload["weight"] = value
        if "domain_key" in fields:
            interest_type = str(payload.get("interest_type", record.interest_type))
            payload["domain_key"] = _resolve_domain_key(interest_type, fields["domain_key"])
        if "enabled" in fields:
            payload["enabled"] = 1 if bool(fields["enabled"]) else 0
        if "notes" in fields:
            notes = fields["notes"]
            if notes is not None and len(str(notes)) > 500:
                raise validation("notes", "size", "备注最多 500 字符")
            payload["notes"] = None if notes is None else str(notes)
        payload["updated_at"] = now
        repo.update_interest(conn, interest_id, payload)

        if "keywords" in fields or "exclusion_keywords" in fields:
            repo.replace_keywords(
                conn,
                interest_id,
                keywords=[str(item) for item in fields.get("keywords", record.keywords) or []],
                exclusions=[
                    str(item)
                    for item in fields.get("exclusion_keywords", record.exclusion_keywords) or []
                ],
                created_at=now,
                make_id=lambda: uuid.uuid4(),
            )
        updated = repo.get_interest(conn, interest_id)
    assert updated is not None
    return _interest_payload(updated)


def delete_interest(interest_id: str) -> dict[str, object]:
    with database.session() as conn:
        removed = repo.delete_interest(conn, interest_id)
    if removed == 0:
        raise not_found("interest_not_found", "兴趣不存在")
    return {"deleted": True, "interest_id": interest_id}


def link_interest_entity(interest_id: str, entity_id: str) -> dict[str, object]:
    now = utc_timestamp()
    with database.session() as conn:
        if repo.get_interest(conn, interest_id) is None:
            raise not_found("interest_not_found", "兴趣不存在")
        if not repo.entity_exists(conn, entity_id):
            raise not_found("entity_not_found", "实体不存在")
        created = repo.link_entity(
            conn,
            link_id=str(uuid.uuid4()),
            interest_id=interest_id,
            entity_id=entity_id,
            created_at=now,
        )
        if not created:
            raise conflict("interest_entity_exists", "该实体已关联到此兴趣")
        record = repo.get_interest(conn, interest_id)
    assert record is not None
    return _interest_payload(record)


def unlink_interest_entity(interest_id: str, entity_id: str) -> dict[str, object]:
    with database.session() as conn:
        removed = repo.unlink_entity(conn, interest_id=interest_id, entity_id=entity_id)
        record = repo.get_interest(conn, interest_id)
    if record is None:
        raise not_found("interest_not_found", "兴趣不存在")
    if removed == 0:
        raise not_found("interest_entity_not_found", "该实体未关联到此兴趣")
    return _interest_payload(record)


def link_interest_source(interest_id: str, source_id: str) -> dict[str, object]:
    now = utc_timestamp()
    with database.session() as conn:
        if repo.get_interest(conn, interest_id) is None:
            raise not_found("interest_not_found", "兴趣不存在")
        if not repo.source_exists(conn, source_id):
            raise not_found("source_not_found", "信息源不存在")
        created = repo.link_source(
            conn,
            link_id=str(uuid.uuid4()),
            interest_id=interest_id,
            source_id=source_id,
            created_at=now,
        )
        if not created:
            raise conflict("interest_source_exists", "该信息源已关联到此兴趣")
        record = repo.get_interest(conn, interest_id)
    assert record is not None
    return _interest_payload(record)


def unlink_interest_source(interest_id: str, source_id: str) -> dict[str, object]:
    with database.session() as conn:
        removed = repo.unlink_source(conn, interest_id=interest_id, source_id=source_id)
        record = repo.get_interest(conn, interest_id)
    if record is None:
        raise not_found("interest_not_found", "兴趣不存在")
    if removed == 0:
        raise not_found("interest_source_not_found", "该信息源未关联到此兴趣")
    return _interest_payload(record)


def block_source(source_id: str, reason: str | None) -> dict[str, object]:
    with database.session() as conn:
        if not repo.source_exists(conn, source_id):
            raise not_found("source_not_found", "信息源不存在")
        repo.block_source(
            conn,
            source_id=source_id,
            reason=None if reason is None else str(reason)[:200],
            created_at=utc_timestamp(),
        )
        items = repo.list_blocked_sources(conn)
    return {"items": items, "total": len(items)}


def unblock_source(source_id: str) -> dict[str, object]:
    with database.session() as conn:
        removed = repo.unblock_source(conn, source_id)
        items = repo.list_blocked_sources(conn)
    if removed == 0:
        raise not_found("blocked_source_not_found", "该信息源未被屏蔽")
    return {"items": items, "total": len(items)}


def blocked_sources_payload() -> dict[str, object]:
    items = _blocked_sources()
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def _signals(conn: sqlite3.Connection) -> list[algo.InterestSignal]:
    signals: list[algo.InterestSignal] = []
    for record in repo.list_interests(conn):
        if not record.enabled:
            continue
        signals.append(
            algo.InterestSignal(
                id=record.id,
                name=record.name,
                interest_type=record.interest_type,
                level=record.level,
                weight=record.weight,
                domain_key=record.domain_key,
                keywords=record.keywords,
                exclusion_keywords=record.exclusion_keywords,
                entity_ids=record.entity_ids,
                source_ids=record.source_ids,
                enabled=record.enabled,
            )
        )
    return signals


def _weights_and_thresholds(profile):
    config = profile.scoring_config or {}
    return (
        algo.merge_weights(config.get("dimension_weights")),
        algo.merge_thresholds(config.get("thresholds")),
        config,
    )


def _match_input(
    *,
    title: str | None,
    summary: str | None,
    category: str | None,
    source_id: str,
    source_name: str | None,
    entities: list[tuple[str, str]],
) -> algo.MatchInput:
    return algo.MatchInput(
        title=title or "",
        summary=summary or "",
        category=category,
        source_id=source_id,
        source_name=source_name,
        entity_ids=tuple(item[0] for item in entities),
        entity_names=tuple(item[1] for item in entities),
    )


def _article_match_input(row: sqlite3.Row, entities: list[tuple[str, str]]) -> algo.MatchInput:
    return _match_input(
        title=row["title"],
        summary=row["ai_summary"] or row["summary"],
        category=row["ai_category"],
        source_id=str(row["source_id"]),
        source_name=row["source_name"],
        entities=entities,
    )


def _event_match_input(row: sqlite3.Row, entities: list[tuple[str, str]]) -> algo.MatchInput:
    return _match_input(
        title=row["title"],
        summary=row["summary"],
        category=row["category"],
        source_id="",
        source_name=None,
        entities=entities,
    )


def _upsert(
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
    scored: algo.ScoredRecommendation,
    match: algo.MatchResult,
    inputs_version: str,
    now: str,
    is_event: bool,
) -> None:
    result_id = str(uuid.uuid4())
    repo.upsert_result(
        conn,
        {
            "id": result_id,
            "target_type": target_type,
            "target_id": target_id,
            "score": scored.score,
            "level": scored.level,
            "interest_score": scored.interest_score,
            "importance_score": scored.importance_score,
            "novelty_score": scored.novelty_score,
            "source_quality_score": scored.source_quality_score,
            "recency_score": scored.recency_score,
            "matched_interests_json": _json(list(match.matched_interests)),
            "matched_entities_json": _json(list(match.matched_entity_names)),
            "reason_codes_json": _json(list(scored.reason_codes)),
            "warnings_json": _json(list(scored.warnings)),
            "explanation_json": _json(
                {
                    **scored.as_explanation(),
                    "is_event": is_event,
                    "matched_interests": list(match.matched_interests),
                    "matched_entities": list(match.matched_entity_names),
                }
            ),
            "algorithm_version": algo.ALGORITHM_VERSION,
            "inputs_version": inputs_version,
            "is_fallback": 1 if scored.is_fallback else 0,
            "is_current": 1,
            "computed_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )


def recompute(
    *,
    article_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    inputs: str | None = None,
) -> dict[str, object]:
    """Recompute recommendations for explicit ids or for the recent window."""

    now_dt = _now()
    now = utc_timestamp()
    with database.session() as conn:
        profile = repo.get_profile(conn)
        inputs_version = inputs or repo.inputs_version(conn)
        signals = _signals(conn)
        weights, thresholds, config = _weights_and_thresholds(profile)
        blocked = repo.blocked_source_ids(conn)
        feedback_articles = repo.active_feedback_map(conn, "article")
        feedback_events = repo.active_feedback_map(conn, "event")

        if event_ids is not None:
            event_rows = repo.events_by_ids(conn, event_ids)
        else:
            event_rows = repo.candidate_events(
                conn, since=_window_start(EVENT_WINDOW_DAYS), limit=CANDIDATE_EVENT_LIMIT
            )
        if article_ids is not None:
            article_rows = repo.articles_by_ids(conn, article_ids)
        else:
            article_rows = repo.candidate_articles(
                conn, since=_window_start(FEED_WINDOW_DAYS), limit=CANDIDATE_ARTICLE_LIMIT
            )

        article_rows = [row for row in article_rows if str(row["source_id"]) not in blocked]
        event_ids_list = [str(row["id"]) for row in event_rows]
        article_ids_list = [str(row["id"]) for row in article_rows]
        article_entities = repo.article_entity_rows(conn, article_ids_list)
        event_entities = repo.event_entity_rows(conn, event_ids_list)
        event_members = repo.event_members(conn, event_ids_list)

        scored_events = 0
        for row in event_rows:
            event_id = str(row["id"])
            members = event_members.get(event_id, [])
            if not members:
                continue
            if all(str(member["source_id"]) in blocked for member in members):
                continue
            entities = [
                (str(item["entity_id"]), str(item["canonical_name"]))
                for item in event_entities.get(event_id, [])
            ]
            event_match = algo.match_interests(signals, _event_match_input(row, entities))

            best_member_match: algo.MatchResult | None = None
            for member in members:
                member_entities = [
                    (str(item["entity_id"]), str(item["canonical_name"]))
                    for item in article_entities.get(str(member["article_id"]), [])
                ]
                candidate = algo.match_interests(
                    signals, _article_match_input(member, member_entities)
                )
                if best_member_match is None or candidate.score > best_member_match.score:
                    best_member_match = candidate

            match = event_match
            if best_member_match is not None and best_member_match.score > event_match.score:
                merged_interests = tuple(
                    dict.fromkeys(
                        (*best_member_match.matched_interests, *event_match.matched_interests)
                    )
                )[:6]
                merged_entities = tuple(
                    dict.fromkeys(
                        (*event_match.matched_entity_names, *best_member_match.matched_entity_names)
                    )
                )[:5]
                match = algo.MatchResult(
                    score=best_member_match.score,
                    matched_interests=merged_interests,
                    matched_entity_names=merged_entities,
                    reason_codes=tuple(
                        dict.fromkeys(
                            (*event_match.reason_codes, *best_member_match.reason_codes)
                        )
                    ),
                    warnings=tuple(
                        dict.fromkeys((*event_match.warnings, *best_member_match.warnings))
                    ),
                    best_level=best_member_match.best_level,
                    matched_interest_ids=best_member_match.matched_interest_ids,
                )

            importances, importance_warnings = algo.importance_score(
                None if row["total_score"] is None else float(row["total_score"])
            )
            warnings = list(match.warnings) + list(importance_warnings)
            published = row["last_published_at"] or row["last_seen_at"]
            freshness = algo.parse_timestamp(row["last_seen_at"])
            freshness_hours = (
                None if freshness is None else (_now() - freshness).total_seconds() / 3600
            )
            credibility_values = [
                float(member["credibility_score"])
                for member in members
                if member["credibility_score"] is not None
            ]
            credibility = (
                sum(credibility_values) / len(credibility_values)
                if credibility_values
                else None
            )
            novelty = algo.novelty_score(
                is_event=True,
                is_newest_in_event=True,
                event_freshness_hours=freshness_hours,
                has_duplicate_feedback=feedback_events.get(event_id) == "duplicate",
            )
            matched = algo.MatchResult(
                score=match.score,
                matched_interests=match.matched_interests,
                matched_entity_names=match.matched_entity_names,
                reason_codes=match.reason_codes,
                warnings=tuple(dict.fromkeys(warnings)),
                best_level=match.best_level,
                matched_interest_ids=match.matched_interest_ids,
            )
            scored = algo.score_item(
                match=matched,
                importance=importances,
                novelty=novelty,
                credibility=credibility,
                published_at=published,
                now=now_dt,
                weights=weights,
                thresholds=thresholds,
                feedback=feedback_events.get(event_id),
                is_event=True,
                config=config,
            )
            _upsert(
                conn,
                target_type="event",
                target_id=event_id,
                scored=scored,
                match=matched,
                inputs_version=inputs_version,
                now=now,
                is_event=True,
            )
            scored_events += 1

        scored_articles = 0
        for row in article_rows:
            article_id = str(row["id"])
            entities = [
                (str(item["entity_id"]), str(item["canonical_name"]))
                for item in article_entities.get(article_id, [])
            ]
            match = algo.match_interests(signals, _article_match_input(row, entities))
            importance, importance_warnings = algo.importance_score(None)
            novelty = algo.novelty_score(
                is_event=False,
                is_newest_in_event=True,
                event_freshness_hours=None,
                has_duplicate_feedback=feedback_articles.get(article_id) == "duplicate",
            )
            behavior_delta, behavior_reasons = algo.reading_signal(
                reading_status=str(row["reading_status"] or "unread"),
                is_favorite=bool(row["is_favorite"]),
            )
            scored = algo.score_item(
                match=match,
                importance=importance,
                novelty=novelty,
                credibility=row["credibility_score"],
                published_at=row["published_at"] or row["fetched_at"],
                now=now_dt,
                weights=weights,
                thresholds=thresholds,
                feedback=feedback_articles.get(article_id),
                is_event=False,
                config=config,
                behavior_delta=behavior_delta,
                behavior_reasons=behavior_reasons,
            )
            merged_warnings = tuple(dict.fromkeys((*scored.warnings, *importance_warnings)))
            scored = algo.ScoredRecommendation(
                score=scored.score,
                level=scored.level,
                interest_score=scored.interest_score,
                importance_score=scored.importance_score,
                novelty_score=scored.novelty_score,
                source_quality_score=scored.source_quality_score,
                recency_score=scored.recency_score,
                reason_codes=scored.reason_codes,
                warnings=merged_warnings,
                is_fallback=scored.is_fallback,
                breakdown=scored.breakdown,
            )
            _upsert(
                conn,
                target_type="article",
                target_id=article_id,
                scored=scored,
                match=match,
                inputs_version=inputs_version,
                now=now,
                is_event=False,
            )
            scored_articles += 1

        repo.deactivate_excluded_results(conn, now=now)

    return {
        "events_scored": scored_events,
        "articles_scored": scored_articles,
        "algorithm_version": algo.ALGORITHM_VERSION,
        "inputs_version": inputs_version,
    }


def ensure_fresh() -> dict[str, object]:
    """Recompute when profile/interests/feedback or source data moved."""

    with database.read_session() as conn:
        current = repo.inputs_version(conn)
        rows = conn.execute(
            "SELECT COUNT(*) FROM recommendation_results WHERE is_current = 1"
        ).fetchone()
        stale_row = conn.execute(
            "SELECT COUNT(*) FROM recommendation_results WHERE is_current = 1 "
            "AND inputs_version <> ?",
            (current,),
        ).fetchone()
        total = int(rows[0]) if rows else 0
        stale = int(stale_row[0]) if stale_row else 0
    if total == 0 or stale > 0:
        return {"recomputed": True, **recompute(inputs=current)}
    return {"recomputed": False, "inputs_version": current}


def refresh_event(event_id: str) -> None:
    """Pipeline hook: refresh one event without touching the whole feed."""

    try:
        recompute(event_ids=[event_id])
    except Exception:  # noqa: BLE001 - recommendations must never break the pipeline
        return


# ---------------------------------------------------------------------------
# feed
# ---------------------------------------------------------------------------


def result_payload(record, *, core_names: set[str]) -> dict[str, object]:
    return {
        "target_type": record.target_type,
        "target_id": record.target_id,
        "title": record.title,
        "summary": record.summary,
        "source_name": record.source_name,
        "category": record.category,
        "published_at": record.published_at,
        "event_id": record.event_id,
        "article_count": record.article_count,
        "source_count": record.source_count,
        "is_read": record.is_read,
        "is_favorite": record.is_favorite,
        "score": round(record.score, 1),
        "level": record.level,
        "is_fallback": record.is_fallback,
        "matched_interests": list(record.matched_interests),
        "matched_entities": list(record.matched_entities),
        "reason_codes": list(record.reason_codes),
        "warnings": list(record.warnings),
        "score_breakdown": {
            "interest": round(record.interest_score, 1),
            "importance": round(record.importance_score, 1),
            "novelty": round(record.novelty_score, 1),
            "source_quality": round(record.source_quality_score, 1),
            "recency": round(record.recency_score, 1),
        },
        "has_core_interest": any(name in core_names for name in record.matched_interests),
        "computed_at": record.computed_at,
    }


def _budget(profile) -> int:
    limits: list[int] = []
    if profile.daily_item_limit:
        limits.append(int(profile.daily_item_limit))
    if profile.daily_minutes:
        limits.append(max(1, int(profile.daily_minutes) // MINUTES_PER_ITEM))
    return min(limits) if limits else 10


def feed(
    *,
    limit: int | None = None,
    include_low: bool = False,
    include_read: bool = False,
) -> dict[str, object]:
    ensure_fresh()
    with database.read_session() as conn:
        profile = repo.get_profile(conn)
        interests = repo.list_interests(conn)
        results = repo.list_current_results(
            conn, limit=2000, min_score=0.0, exclude_read=not include_read
        )
        feedback_articles = repo.active_feedback_map(conn, "article")
        feedback_events = repo.active_feedback_map(conn, "event")
        today = _local_today(profile)
        counts = repo.counts_today(conn, since=_day_start_utc(profile, today))
        emerging = _emerging_topics(conn, today)

    core_names = {item.name for item in interests if item.enabled and item.level == "core"}
    extended_names = {
        item.name for item in interests if item.enabled and item.level == "extended"
    }
    budget = min(limit, 50) if limit else _budget(profile)
    ranked = [record for record in results if record.score >= MIN_FEED_SCORE]
    if not include_low:
        ranked = [record for record in ranked if record.level != "not_recommended"]

    # 用户明确表达「不感兴趣 / 不喜欢来源」后，该对象直接从今日流移除；
    # 撤销反馈后会重新出现，不修改任何评分或历史结果。
    dismissive = {"not_interested", "source_disliked"}
    ranked = [
        record
        for record in ranked
        if not (
            (
                record.target_type == "article"
                and feedback_articles.get(record.target_id) in dismissive
            )
            or (
                record.target_type == "event"
                and feedback_events.get(record.target_id) in dismissive
            )
        )
    ]

    seen: set[tuple[str, str]] = set()

    def take(records, cap: int) -> list:
        picked = []
        for record in records:
            key = (record.target_type, record.target_id)
            if key in seen:
                continue
            seen.add(key)
            picked.append(record)
            if len(picked) >= cap:
                break
        return picked

    events = [record for record in ranked if record.target_type == "event"]
    articles = [record for record in ranked if record.target_type == "article"]

    must_read = take([record for record in ranked if record.level == "must_read"], 8)
    event_highlights = take(
        [
            record
            for record in events
            if record.is_fallback or record.importance_score >= 55.0
        ],
        6,
    )
    core_updates = take(
        [
            record
            for record in ranked
            if any(name in core_names for name in record.matched_interests)
        ],
        8,
    )
    leads = take(
        [record for record in articles if record.score >= 50.0 and not record.event_id],
        6,
    )
    watch = take([record for record in ranked if record.level in {"watch", "low"}], 12)
    others = take(ranked, 40)

    # Reading budget limits the first-screen list (spec F3). Overflow is not
    # deleted: it moves into the collapsed "watch" bucket.
    primary_order = must_read + event_highlights + core_updates + leads
    primary = primary_order[:budget]
    overflow = primary_order[budget:]
    keep = {(item.target_type, item.target_id) for item in primary}

    def only_kept(items):
        return [item for item in items if (item.target_type, item.target_id) in keep]

    must_read = only_kept(must_read)
    event_highlights = only_kept(event_highlights)
    core_updates = only_kept(core_updates)
    leads = only_kept(leads)
    if overflow:
        overflow_keys = {(item.target_type, item.target_id) for item in overflow}
        watch = watch + [
            item for item in overflow if (item.target_type, item.target_id) in overflow_keys
        ]

    exploration_cap = max(1, round(budget * profile.exploration_ratio))

    def exploration_count(items) -> int:
        return sum(
            1
            for record in items
            if record.interest_score < 50.0
            and not record.is_fallback
        )

    exploration_total = exploration_count(must_read + event_highlights + core_updates + leads)
    if exploration_total > exploration_cap:
        # Soft guard: trim exploration items from the watch bucket first.
        keep: list = []
        dropped = 0
        for record in watch:
            if (
                record.interest_score < 50.0
                and not record.is_fallback
                and exploration_total - dropped > exploration_cap
            ):
                dropped += 1
                others.append(record)
                continue
            keep.append(record)
        watch = keep

    payload = {
        "generated_at": utc_timestamp(),
        "algorithm_version": algo.ALGORITHM_VERSION,
        "budget": {
            "items": budget,
            "daily_item_limit": profile.daily_item_limit,
            "daily_minutes": profile.daily_minutes,
            "exploration_ratio": profile.exploration_ratio,
            "exploration_cap": exploration_cap,
        },
        "metrics": {
            "today_articles": counts["articles"],
            "today_events": counts["events"],
            "recommended_total": len(ranked),
            "must_read": sum(1 for record in ranked if record.level == "must_read"),
            "event_count": len(events),
            "standalone_count": len(articles),
        },
        "sections": {
            "must_read": [result_payload(item, core_names=core_names) for item in must_read],
            "event_highlights": [
                result_payload(item, core_names=core_names) for item in event_highlights
            ],
            "core_interest": [
                result_payload(item, core_names=core_names) for item in core_updates
            ],
            "emerging": emerging,
            "leads": [result_payload(item, core_names=core_names) for item in leads],
            "watch": [result_payload(item, core_names=core_names) for item in watch],
            "others": [result_payload(item, core_names=core_names) for item in others],
        },
        "has_interests": bool(interests),
        "has_core_interest": bool(core_names),
        "onboarding_done": profile.onboarding_done,
    }
    return payload


def _emerging_topics(conn: sqlite3.Connection, today: date) -> list[dict[str, object]]:
    try:
        stats = intelligence_stats.build_stats(
            conn,
            report_type="daily",
            period_start=today,
            period_end=today,
        )
    except Exception:  # noqa: BLE001 - feed must degrade instead of failing
        return []
    items: list[dict[str, object]] = []
    for entry in list(stats.get("rising_keywords") or [])[:6]:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "target_type": "topic",
                "target_id": str(entry.get("keyword") or ""),
                "title": str(entry.get("keyword") or ""),
                "count": int(entry.get("count") or 0),
                "previous": int(entry.get("previous") or 0),
                "delta": int(entry.get("delta") or 0),
                "sources": list(entry.get("sources") or []),
                "reason": "近 24 小时出现频率上升",
            }
        )
    return items


# ---------------------------------------------------------------------------
# recommendation detail / feedback
# ---------------------------------------------------------------------------


def recommendation_detail(target_type: str, target_id: str) -> dict[str, object]:
    if target_type not in {"article", "event"}:
        raise validation("target_type", "unknown", "target_type 必须是 article 或 event")
    with database.read_session() as conn:
        if target_type == "article" and not repo.article_exists(conn, target_id):
            raise not_found("article_not_found", "文章不存在")
        if target_type == "event" and not repo.event_exists(conn, target_id):
            raise not_found("event_not_found", "事件不存在")
        result = repo.get_current_result(conn, target_type=target_type, target_id=target_id)
    if result is None:
        recompute(
            article_ids=[target_id] if target_type == "article" else None,
            event_ids=[target_id] if target_type == "event" else None,
        )
        with database.read_session() as conn:
            result = repo.get_current_result(conn, target_type=target_type, target_id=target_id)
    if result is None:
        raise not_found("recommendation_not_found", "该对象暂无推荐结果")
    with database.read_session() as conn:
        feedback = repo.active_feedback(conn, target_type=target_type, target_id=target_id)
    payload = result_payload(
        result,
        core_names={
            item.name
            for item in _interest_records()
            if item.enabled and item.level == "core"
        },
    )
    payload["feedback"] = None if feedback is None else _feedback_payload(feedback)
    payload["explanation"] = result.explanation
    return payload


def _interest_records():
    with database.read_session() as conn:
        return repo.list_interests(conn)


def _feedback_payload(record) -> dict[str, object]:
    return {
        "id": record.id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "feedback": record.feedback,
        "interest_id": record.interest_id,
        "note": record.note,
        "created_at": record.created_at,
        "revoked_at": record.revoked_at,
    }


def submit_feedback(
    *,
    target_type: str,
    target_id: str,
    feedback: str,
    interest_id: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    if target_type not in {"article", "event"}:
        raise validation("target_type", "unknown", "target_type 必须是 article 或 event")
    if feedback not in FEEDBACK_VALUES:
        raise validation("feedback", "unknown", "不支持的反馈类型")
    if note is not None and len(note) > 500:
        raise validation("note", "size", "反馈备注最多 500 字符")
    now = utc_timestamp()
    with database.session() as conn:
        if target_type == "article" and not repo.article_exists(conn, target_id):
            raise not_found("article_not_found", "文章不存在")
        if target_type == "event" and not repo.event_exists(conn, target_id):
            raise not_found("event_not_found", "事件不存在")
        if interest_id is not None and repo.get_interest(conn, interest_id) is None:
            raise not_found("interest_not_found", "兴趣不存在")
        existing = repo.active_feedback(conn, target_type=target_type, target_id=target_id)
        if existing is not None:
            repo.revoke_feedback(conn, existing.id, revoked_at=now)
        feedback_id = str(uuid.uuid4())
        repo.insert_feedback(
            conn,
            {
                "id": feedback_id,
                "target_type": target_type,
                "target_id": target_id,
                "feedback": feedback,
                "interest_id": interest_id,
                "note": None if note is None else note.strip(),
                "created_at": now,
                "revoked_at": None,
            },
        )
        record = repo.get_feedback(conn, feedback_id)

    recompute(
        article_ids=[target_id] if target_type == "article" else None,
        event_ids=[target_id] if target_type == "event" else None,
    )
    try:
        result: dict[str, object] | None = recommendation_detail(target_type, target_id)
    except Exception as exc:  # noqa: BLE001 - feedback must survive a missing rec
        # Phase 8.0: event-member articles are not recommended individually, so
        # a valid "not interested" on them has no article-level result. The
        # feedback is already stored; return it instead of a misleading 404.
        if getattr(exc, "code", None) != "recommendation_not_found":
            raise
        result = None
    assert record is not None
    return {"feedback": _feedback_payload(record), "recommendation": result}


def revoke_feedback(feedback_id: str) -> dict[str, object]:
    now = utc_timestamp()
    with database.session() as conn:
        record = repo.get_feedback(conn, feedback_id)
        if record is None:
            raise not_found("feedback_not_found", "反馈不存在")
        if record.revoked_at is not None:
            raise conflict("feedback_already_revoked", "该反馈已撤销")
        repo.revoke_feedback(conn, feedback_id, revoked_at=now)
        target_type = record.target_type
        target_id = record.target_id
    recompute(
        article_ids=[target_id] if target_type == "article" else None,
        event_ids=[target_id] if target_type == "event" else None,
    )
    return {"revoked": True, "feedback_id": feedback_id}


def revoke_feedback_for_target(target_type: str, target_id: str) -> dict[str, object]:
    with database.session() as conn:
        record = repo.active_feedback(conn, target_type=target_type, target_id=target_id)
    if record is None:
        raise not_found("feedback_not_found", "该对象没有有效反馈")
    return revoke_feedback(record.id)


def feedback_payloads(*, limit: int, offset: int) -> dict[str, object]:
    with database.read_session() as conn:
        records, total = repo.list_feedback(
            conn, limit=limit, offset=offset, include_revoked=True
        )
        items = []
        for record in records:
            payload = _feedback_payload(record)
            result = repo.get_current_result(
                conn, target_type=record.target_type, target_id=record.target_id
            )
            payload["target_title"] = None if result is None else result.title
            items.append(payload)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# interest adjustment suggestions
# ---------------------------------------------------------------------------


def suggestions() -> dict[str, object]:
    positive = {"interested", "important"}
    negative = {"not_interested", "source_disliked"}
    with database.read_session() as conn:
        profile = repo.get_profile(conn)
        interests = repo.list_interests(conn)
        records, _ = repo.list_feedback(conn, limit=500, offset=0, include_revoked=False)
        result_cache: dict[tuple[str, str], tuple[str, ...]] = {}
        for record in records:
            key = (record.target_type, record.target_id)
            if key not in result_cache:
                result = repo.get_current_result(
                    conn, target_type=record.target_type, target_id=record.target_id
                )
                result_cache[key] = () if result is None else result.matched_interests

    name_to_id = {item.name: item for item in interests}
    tally: dict[str, dict[str, int]] = {}
    evidence: dict[str, list[str]] = {}
    for record in records:
        targets: set[str] = set()
        if record.interest_id and record.interest_id in {item.id for item in interests}:
            targets.add(record.interest_id)
        else:
            for name in result_cache.get((record.target_type, record.target_id), ()):
                interest = name_to_id.get(name)
                if interest is not None:
                    targets.add(interest.id)
        for interest_id in targets:
            bucket = tally.setdefault(interest_id, {"positive": 0, "negative": 0})
            if record.feedback in positive:
                bucket["positive"] += 1
            elif record.feedback in negative:
                bucket["negative"] += 1
            if record.feedback in positive | negative:
                evidence.setdefault(interest_id, []).append(record.id)

    by_id = {item.id: item for item in interests}
    items: list[dict[str, object]] = []
    for interest_id, counts in tally.items():
        interest = by_id.get(interest_id)
        if interest is None:
            continue
        pos = counts["positive"]
        neg = counts["negative"]
        if max(pos, neg) < 3:
            continue
        if pos >= neg * 2 and pos >= 3:
            suggested_level = _promote(interest.level)
            direction = "increase"
            delta = min(0.1, round(1.0 - interest.weight, 2))
        elif neg >= pos * 2 and neg >= 3:
            suggested_level = _demote(interest.level)
            direction = "decrease"
            delta = -min(0.1, round(interest.weight, 2))
        else:
            continue
        if suggested_level == interest.level and abs(delta) < 0.05:
            continue
        items.append(
            {
                "interest_id": interest.id,
                "interest_name": interest.name,
                "current_level": interest.level,
                "current_weight": round(interest.weight, 3),
                "suggested_level": suggested_level,
                "suggested_weight": round(max(0.0, min(1.0, interest.weight + delta)), 3),
                "direction": direction,
                "positive_feedback": pos,
                "negative_feedback": neg,
                "evidence_feedback_ids": evidence.get(interest_id, [])[:5],
                "reason": "近期的主动反馈与当前关注等级不一致，可考虑调整（不会自动修改）。",
            }
        )

    items.sort(key=lambda entry: -(int(entry["positive_feedback"]) + int(entry["negative_feedback"])))
    return {
        "items": items,
        "total": len(items),
        "auto_adjust_enabled": profile.auto_adjust_enabled,
        "note": "建议只做提示，不会自动修改兴趣权重；是否应用由用户决定。",
    }


def _promote(level: str) -> str:
    return {"general": "extended", "extended": "core", "core": "core", "muted": "general"}.get(
        level, level
    )


def _demote(level: str) -> str:
    return {"core": "extended", "extended": "general", "general": "general", "muted": "muted"}.get(
        level, level
    )


# ---------------------------------------------------------------------------
# daily digest
# ---------------------------------------------------------------------------


def _event_digest_detail(conn: sqlite3.Connection, event_id: str) -> dict[str, object] | None:
    """Event-level digest detail: representative report, other sources, progress."""

    rows = aggregation_repo.event_members(conn, [event_id]).get(event_id, [])
    if not rows:
        return None
    event_row = aggregation_repo.event_rows_by_ids(conn, [event_id]).get(event_id)
    if event_row is None:
        return None
    candidates = [
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
        for row in rows
    ]
    representative = choose_representative(candidates)
    ordered = sorted(
        rows,
        key=lambda row: (row["published_at"] is None, row["published_at"] or ""),
    )
    latest = ordered[-1]
    others = [
        row
        for row in reversed(ordered)
        if representative is None or str(row["article_id"]) != representative.article_id
    ][:5]

    def _article(row) -> dict[str, object]:
        return {
            "article_id": str(row["article_id"]),
            "title": str(row["title"]),
            "source_id": str(row["source_id"]),
            "source_name": row["source_name"],
            "published_at": row["published_at"],
            "url": row["canonical_url"] or row["original_url"],
        }

    score_row = conn.execute(
        "SELECT total_score, importance_score FROM event_score_snapshots "
        "WHERE event_id = ? AND is_current = 1",
        (event_id,),
    ).fetchone()
    source_names = list(
        dict.fromkeys(str(row["source_name"]) for row in ordered if row["source_name"])
    )
    return {
        "event_id": event_id,
        "category": event_domain_name(event_row["category"]),
        "status": str(event_row["status"]),
        "first_published_at": event_row["first_published_at"],
        "last_published_at": event_row["last_published_at"],
        "article_count": len(rows),
        "source_count": len(source_names),
        "sources": source_names[:8],
        "importance": None if score_row is None else round(float(score_row["total_score"]), 1),
        "representative": (
            None
            if representative is None
            else {
                **_article(
                    next(
                        row
                        for row in rows
                        if str(row["article_id"]) == representative.article_id
                    )
                ),
                "reason": "；".join(representative.reasons),
            }
        ),
        "other_reports": [_article(row) for row in others],
        "latest_progress": {
            **_article(latest),
            "is_representative": bool(
                representative is not None
                and str(latest["article_id"]) == representative.article_id
            ),
        },
        "information_increment": {
            "follow_up_count": max(0, len(rows) - 1),
            "distinct_sources": len(source_names),
            "has_multiple_sources": len(source_names) > 1,
        },
    }


def _digest_with_details(record) -> dict[str, object]:
    event_ids = [
        item.target_id
        for item in record.items
        if item.target_type == "event" and item.target_id
    ]
    details: dict[str, dict[str, object]] = {}
    if event_ids:
        with database.read_session() as conn:
            for event_id in dict.fromkeys(event_ids):
                detail = _event_digest_detail(conn, str(event_id))
                if detail is not None:
                    details[str(event_id)] = detail
    return _digest_payload(record, event_details=details)


def _digest_payload(record, *, event_details: dict[str, dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "id": record.id,
        "digest_date": record.digest_date,
        "timezone": record.timezone,
        "status": record.status,
        "ai_status": record.ai_status,
        "headline": record.headline,
        "overview": record.overview,
        "stats": record.stats,
        "model_name": record.model_name,
        "prompt_version": record.prompt_version,
        "digest_version": record.digest_version,
        "generated_at": record.generated_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "items": [
            {
                "id": item.id,
                "section": item.section,
                "rank": item.rank,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "title": item.title,
                "reason": item.reason,
                "matched_interests": list(item.matched_interests),
                "score": item.score,
                "event_detail": (
                    (event_details or {}).get(str(item.target_id))
                    if item.target_type == "event" and item.target_id
                    else None
                ),
            }
            for item in record.items
        ],
    }


def digest_today(*, generate: bool = True, force: bool = False) -> dict[str, object]:
    with database.read_session() as conn:
        profile = repo.get_profile(conn)
    today = _local_today(profile)
    return digest_for_date(today.isoformat(), generate=generate, force=force)


def digest_for_date(
    digest_date: str, *, generate: bool = True, force: bool = False
) -> dict[str, object]:
    try:
        parsed = date.fromisoformat(digest_date)
    except ValueError:
        raise validation("date", "format", "日期必须是 YYYY-MM-DD") from None
    with database.read_session() as conn:
        profile = repo.get_profile(conn)
        existing = repo.get_digest(conn, digest_date=parsed.isoformat(), timezone=profile.timezone)
    if existing is not None and not force:
        return _digest_with_details(existing)
    if not generate:
        raise not_found("digest_not_found", "该日期没有生成日报")
    return _generate_digest(profile, parsed, force=force)


def _generate_digest(profile, day: date, *, force: bool) -> dict[str, object]:
    ensure_fresh()
    now = utc_timestamp()
    day_start = _day_start_utc(profile, day)
    with database.read_session() as conn:
        interests = repo.list_interests(conn)
        results = repo.list_current_results(conn, limit=2000, min_score=0.0)
        stats = intelligence_stats.build_stats(
            conn, report_type="daily", period_start=day, period_end=day
        )
        counts = repo.counts_today(conn, since=day_start)
        recent_events = repo.candidate_events(
            conn, since=day_start, limit=10
        )
        event_results = {
            record.target_id: record for record in results if record.target_type == "event"
        }
    core_names = {item.name for item in interests if item.enabled and item.level == "core"}
    ranked = [record for record in results if record.score >= MIN_FEED_SCORE]

    sections: dict[str, list[dict[str, object]]] = {
        "must_not_miss": [],
        "highlights": [],
        "core_interest": [],
        "event_changes": [],
        "emerging": [],
        "leads": [],
    }
    seen: set[tuple[str, str]] = set()

    def add(section: str, record, reason: str | None = None) -> None:
        key = (record.target_type, record.target_id)
        if key in seen:
            return
        seen.add(key)
        sections[section].append(
            {
                "target_type": record.target_type,
                "target_id": record.target_id,
                "title": record.title or "（无标题）",
                "reason": reason
                or _digest_reason(record),
                "matched_interests": list(record.matched_interests),
                "score": round(record.score, 1),
            }
        )

    # Event-level digest: reserve up to two of the daily slots for the most
    # important events so merged multi-source stories are visible, then fill
    # with the highest-scoring articles/leads. One event still occupies one slot.
    top_events = [record for record in ranked if record.target_type == "event"][:2]
    top_others = [record for record in ranked if record.target_type != "event"][:3]
    for record in (*top_events, *top_others):
        add("must_not_miss", record)
    for record in ranked[:8]:
        if record.score >= 70 or record.level in {"must_read", "recommended"}:
            add("highlights", record)
    for record in ranked:
        if any(name in core_names for name in record.matched_interests):
            add("core_interest", record)
            if len(sections["core_interest"]) >= 8:
                break
    for row in recent_events:
        record = event_results.get(str(row["id"]))
        if record is None:
            continue
        add(
            "event_changes",
            record,
            "今日有更新的事件" if row["updated_at"] >= day_start else "今日新增/活跃事件",
        )
        if len(sections["event_changes"]) >= 6:
            break
    for entry in list(stats.get("rising_keywords") or [])[:5]:
        if not isinstance(entry, dict):
            continue
        keyword = str(entry.get("keyword") or "").strip()
        if not keyword:
            continue
        sections["emerging"].append(
            {
                "target_type": "topic",
                "target_id": keyword,
                "title": keyword,
                "reason": f"今日 {int(entry.get('count') or 0)} 次，此前 {int(entry.get('previous') or 0)} 次",
                "matched_interests": [],
                "score": None,
            }
        )
    for record in ranked:
        if record.target_type == "article" and record.score >= 50 and not record.event_id:
            add("leads", record)
            if len(sections["leads"]) >= 6:
                break

    # Daily budget limits the digest's recommendation cards; emerging topics are
    # thematic context and do not consume a reading slot.
    digest_budget = _budget(profile)
    order = ["must_not_miss", "highlights", "core_interest", "event_changes", "leads"]
    remaining = digest_budget
    for section in order:
        items = sections[section]
        if remaining <= 0:
            sections[section] = []
            continue
        if len(items) > remaining:
            sections[section] = items[:remaining]
            remaining = 0
        else:
            remaining -= len(items)

    total_items = sum(len(items) for items in sections.values())
    level_counts = {}
    for record in ranked:
        level_counts[record.level] = level_counts.get(record.level, 0) + 1
    digest_stats = {
        "totals": {
            "articles_today": counts["articles"],
            "events_today": counts["events"],
            "recommended_total": len(ranked),
            "digest_items": total_items,
        },
        "by_level": level_counts,
        "by_target_type": {
            "events": sum(1 for record in ranked if record.target_type == "event"),
            "articles": sum(1 for record in ranked if record.target_type == "article"),
        },
        "intelligence": {
            "articles": int((stats.get("totals") or {}).get("articles") or 0),
            "events": int((stats.get("totals") or {}).get("events") or 0),
            "new_events": int((stats.get("totals") or {}).get("new_events") or 0),
            "rising_keywords": len(stats.get("rising_keywords") or []),
        },
        "algorithm_version": algo.ALGORITHM_VERSION,
        "taxonomy_version": "taxonomy-v1",
        "ai_status": "skipped",
        "ai_note": "本版本日报为规则生成，不调用模型；AI 概览为后续增强项。",
    }
    headline = (
        f"{day.isoformat()} 今日精选：{total_items} 条"
        if total_items
        else f"{day.isoformat()}：今天没有达到推荐阈值的更新"
    )
    top_titles = [item["title"] for item in sections["must_not_miss"][:3]]
    overview_parts = [
        f"今天共采集 {counts['articles']} 篇文章、{counts['events']} 个活跃事件，"
        f"其中 {len(ranked)} 条进入推荐候选。"
    ]
    if top_titles:
        overview_parts.append("今日重点：" + "；".join(top_titles) + "。")
    if sections["emerging"]:
        overview_parts.append(
            "上升主题：" + "、".join(item["title"] for item in sections["emerging"][:3]) + "。"
        )
    if not ranked:
        overview_parts.append("当前兴趣画像可能还未配置，或今天没有匹配的新内容。")
    overview = "".join(overview_parts)

    digest_id = str(uuid.uuid4())
    try:
        with database.session() as conn:
            if force:
                repo.supersede_digests(
                    conn,
                    digest_date=day.isoformat(),
                    timezone=profile.timezone,
                    superseded_at=now,
                )
            repo.insert_digest(
                conn,
                {
                    "id": digest_id,
                    "digest_date": day.isoformat(),
                    "timezone": profile.timezone,
                    "status": "generating",
                    "ai_status": "skipped",
                    "headline": headline,
                    "overview": overview,
                    "stats_json": _json(digest_stats),
                    "model_name": None,
                    "model_digest": None,
                    "prompt_version": None,
                    "digest_version": DIGEST_VERSION,
                    "generated_at": None,
                    "superseded_at": None,
                    "error_code": None,
                    "error_message": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            for section, items in sections.items():
                for rank, item in enumerate(items):
                    repo.insert_digest_item(
                        conn,
                        {
                            "id": str(uuid.uuid4()),
                            "digest_id": digest_id,
                            "section": section,
                            "rank": rank,
                            "target_type": item["target_type"],
                            "target_id": item.get("target_id"),
                            "title": str(item["title"])[:300],
                            "reason": item.get("reason"),
                            "matched_interests_json": _json(item.get("matched_interests") or []),
                            "score": item.get("score"),
                            "created_at": now,
                        },
                    )
            repo.update_digest(
                conn,
                digest_id,
                {
                    "status": "succeeded",
                    "generated_at": now,
                    "updated_at": now,
                },
            )
            record = repo.get_digest_by_id(conn, digest_id)
    except sqlite3.IntegrityError as exc:
        raise conflict("digest_exists", "该日期已存在有效日报，请使用 force 重新生成") from exc
    if record is None:
        raise conflict("digest_failed", "日报生成失败")
    return _digest_with_details(record)


def _digest_reason(record) -> str:
    reasons: list[str] = []
    if record.is_fallback:
        reasons.append("重大事件兜底")
    if record.matched_interests:
        reasons.append("匹配兴趣：" + "、".join(record.matched_interests[:3]))
    if record.importance_score >= 60:
        reasons.append("事件重要性较高")
    if record.novelty_score >= 85:
        reasons.append("包含新信息")
    if record.recency_score >= 90:
        reasons.append("刚刚发布")
    if record.reason_codes and not reasons:
        reasons.append("、".join(record.reason_codes[:3]))
    return "；".join(reasons) or "综合推荐分数较高"


def digest_history(*, limit: int, offset: int) -> dict[str, object]:
    with database.read_session() as conn:
        records, total = repo.list_digests(conn, limit=limit, offset=offset)
    return {
        "items": [_digest_with_details(record) for record in records],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def stats_payload() -> dict[str, object]:
    with database.read_session() as conn:
        profile = repo.get_profile(conn)
        interests = repo.list_interests(conn)
        result = repo.result_stats(conn)
        feedback_total = conn.execute(
            "SELECT COUNT(*) FROM recommendation_feedback WHERE revoked_at IS NULL"
        ).fetchone()
        digests = conn.execute(
            "SELECT COUNT(*) FROM daily_digests WHERE status = 'succeeded'"
        ).fetchone()
        today = _local_today(profile)
        counts = repo.counts_today(conn, since=_day_start_utc(profile, today))
    return {
        "recommendations": result,
        "interests": {
            "total": len(interests),
            "enabled": sum(1 for item in interests if item.enabled),
            "by_level": {
                level: sum(1 for item in interests if item.level == level and item.enabled)
                for level in LEVEL_WEIGHTS
            },
        },
        "feedback": {"active": int(feedback_total[0]) if feedback_total else 0},
        "digests": {"total": int(digests[0]) if digests else 0},
        "today": counts,
        "algorithm_version": algo.ALGORITHM_VERSION,
        "profile_updated_at": profile.updated_at,
    }


def reset_personalization(
    *, clear_interests: bool = False, clear_feedback: bool = False, clear_digests: bool = False
) -> dict[str, object]:
    """User-initiated reset. Never touches articles, events or analyses."""

    removed: dict[str, int] = {}
    with database.session() as conn:
        if clear_interests:
            removed["interests"] = int(
                conn.execute("DELETE FROM interests").rowcount or 0
            )
        if clear_feedback:
            removed["feedback"] = int(
                conn.execute("DELETE FROM recommendation_feedback").rowcount or 0
            )
        if clear_digests:
            removed["digests"] = int(conn.execute("DELETE FROM daily_digests").rowcount or 0)
        removed["recommendations"] = int(
            conn.execute("DELETE FROM recommendation_results").rowcount or 0
        )
    return {"reset": True, "removed": removed}
