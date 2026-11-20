"""Entity normalisation, alias management, merge and unmerge (Phase 4)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import replace

import database
from core.timeutil import utc_timestamp
from database.repositories import entity_repository as entity_repo
from database.repositories import event_repository as event_repo
from database.repositories.models import EntityRecord
from event_intelligence.entities import (
    alias_variants,
    clean_entity_name,
    entity_type_of,
    mention_confidence,
    normalized_key,
)
from services.errors import conflict, not_found, validation
from services.event_aggregation import rebuild_event_entities

MAX_SYNC_ARTICLES = 500
DEFAULT_SYNC_LIMIT = 200
DETAIL_ARTICLES = 50


def _json_entities(value: object) -> list[dict[str, str]]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [
        {"name": str(item.get("name", "")), "type": str(item.get("type", "other"))}
        for item in parsed
        if isinstance(item, dict) and item.get("name")
    ]


def _seen_bounds(article_time: str | None, now: str) -> tuple[str, str]:
    value = article_time or now
    return (value, value)


def sync_article(
    conn: sqlite3.Connection,
    article_id: str,
    *,
    now: str,
    stats: dict[str, int],
) -> None:
    article = event_repo.article_feature_row(conn, article_id)
    if article is None or article["analysis_id"] is None:
        return
    analysis = entity_repo.get_analysis(conn, str(article["analysis_id"]))
    if analysis is None:
        return
    entities = _json_entities(analysis["entities_json"])
    if not entities:
        return
    analysis_confidence = float(analysis["confidence"])
    article_time = article["published_at"] or article["fetched_at"]

    for item in entities:
        raw_name = item["name"]
        raw_type = item["type"]
        cleaned = clean_entity_name(raw_name)
        if not cleaned:
            continue
        entity_type, type_group = entity_type_of(raw_type, cleaned)
        canonical_key = normalized_key(cleaned, type_group)

        direct = entity_repo.find_active_by_key(
            conn, normalized_key=canonical_key, type_group=type_group
        )
        if direct is not None:
            _link(
                conn,
                article_id=article_id,
                analysis_id=str(article["analysis_id"]),
                entity=direct,
                cleaned=cleaned,
                raw_type=raw_type,
                method="canonical",
                analysis_confidence=analysis_confidence,
                article_time=article_time,
                now=now,
                stats=stats,
            )
            continue

        variants = alias_variants(cleaned, entity_type)
        candidates: dict[str, EntityRecord] = {}
        for alias, _language in variants:
            key = normalized_key(alias, type_group)
            for candidate in entity_repo.find_active_by_alias(
                conn, alias_key=key, type_group=type_group
            ):
                candidates[candidate.id] = candidate

        if len(candidates) == 1:
            entity = next(iter(candidates.values()))
            _link(
                conn,
                article_id=article_id,
                analysis_id=str(article["analysis_id"]),
                entity=entity,
                cleaned=cleaned,
                raw_type=raw_type,
                method="alias",
                analysis_confidence=analysis_confidence,
                article_time=article_time,
                now=now,
                stats=stats,
                variants=variants,
            )
            continue

        if len(candidates) > 1:
            if not entity_repo.ambiguous_exists(
                conn, article_id=article_id, raw_name=cleaned
            ):
                entity_repo.insert_article_entity(
                    conn,
                    {
                        "id": str(uuid.uuid4()),
                        "article_id": article_id,
                        "entity_id": None,
                        "analysis_id": str(article["analysis_id"]),
                        "raw_name": cleaned[:200],
                        "raw_type": raw_type[:32],
                        "match_method": "ambiguous",
                        "status": "ambiguous",
                        "confidence": 0.4,
                        "merged_from_entity_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                stats["ambiguous_mentions"] = stats.get("ambiguous_mentions", 0) + 1
            continue

        entity_id = str(uuid.uuid4())
        first_seen, last_seen = _seen_bounds(article_time, now)
        confidence = mention_confidence(analysis_confidence, "canonical")
        entity_repo.insert_entity(
            conn,
            {
                "id": entity_id,
                "canonical_name": cleaned,
                "entity_type": entity_type,
                "type_group": type_group,
                "normalized_key": canonical_key,
                "status": "active",
                "confidence": confidence,
                "normalization_basis": "ai_extraction",
                "merged_into_entity_id": None,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "created_at": now,
                "updated_at": now,
            },
        )
        stats["created_entities"] = stats.get("created_entities", 0) + 1
        entity_repo.insert_alias(
            conn,
            {
                "id": str(uuid.uuid4()),
                "entity_id": entity_id,
                "alias": cleaned,
                "alias_key": canonical_key,
                "language": alias_variants(cleaned, entity_type)[0][1],
                "source": "canonical",
                "confidence": 1.0,
                "merged_from_entity_id": None,
                "created_at": now,
            },
        )
        for alias, language in variants:
            key = normalized_key(alias, type_group)
            if key == canonical_key:
                continue
            entity_repo.insert_alias(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "entity_id": entity_id,
                    "alias": alias,
                    "alias_key": key,
                    "language": language,
                    "source": "ai_extraction",
                    "confidence": 0.8,
                    "merged_from_entity_id": None,
                    "created_at": now,
                },
            )
        entity = entity_repo.get(conn, entity_id)
        if entity is not None:
            _link(
                conn,
                article_id=article_id,
                analysis_id=str(article["analysis_id"]),
                entity=entity,
                cleaned=cleaned,
                raw_type=raw_type,
                method="canonical",
                analysis_confidence=analysis_confidence,
                article_time=article_time,
                now=now,
                stats=stats,
            )


def _link(
    conn: sqlite3.Connection,
    *,
    article_id: str,
    analysis_id: str,
    entity: EntityRecord,
    cleaned: str,
    raw_type: str,
    method: str,
    analysis_confidence: float,
    article_time: str | None,
    now: str,
    stats: dict[str, int],
    variants: list[tuple[str, str]] | None = None,
) -> None:
    if entity_repo.article_entity_exists(conn, article_id=article_id, entity_id=entity.id):
        return
    confidence = mention_confidence(analysis_confidence, method)
    entity_repo.insert_article_entity(
        conn,
        {
            "id": str(uuid.uuid4()),
            "article_id": article_id,
            "entity_id": entity.id,
            "analysis_id": analysis_id,
            "raw_name": cleaned[:200],
            "raw_type": raw_type[:32],
            "match_method": method,
            "status": "resolved",
            "confidence": confidence,
            "merged_from_entity_id": None,
            "created_at": now,
            "updated_at": now,
        },
    )
    stats["linked_mentions"] = stats.get("linked_mentions", 0) + 1

    first_seen, last_seen = _seen_bounds(article_time, now)
    current_first = entity.first_seen_at or first_seen
    current_last = entity.last_seen_at or last_seen
    entity_repo.update_entity(
        conn,
        entity.id,
        {
            "first_seen_at": min(current_first, first_seen),
            "last_seen_at": max(current_last, last_seen),
            "confidence": max(entity.confidence, confidence),
            "updated_at": now,
        },
    )
    stats["updated_entities"] = stats.get("updated_entities", 0) + 1

    for alias, language in variants or []:
        key = normalized_key(alias, entity.type_group)
        entity_repo.insert_alias(
            conn,
            {
                "id": str(uuid.uuid4()),
                "entity_id": entity.id,
                "alias": alias,
                "alias_key": key,
                "language": language,
                "source": "ai_extraction",
                "confidence": 0.8,
                "merged_from_entity_id": None,
                "created_at": now,
            },
        )


def sync_entities(*, limit: int = DEFAULT_SYNC_LIMIT) -> dict[str, object]:
    bounded = max(1, min(int(limit), MAX_SYNC_ARTICLES))
    now = utc_timestamp()
    stats: dict[str, int] = {
        "processed_articles": 0,
        "created_entities": 0,
        "linked_mentions": 0,
        "ambiguous_mentions": 0,
        "updated_entities": 0,
    }
    started = time.monotonic()
    with database.session() as conn:
        rows = entity_repo.articles_with_analysis(conn, limit=bounded)
        for row in rows:
            sync_article(conn, str(row[0]), now=now, stats=stats)
            stats["processed_articles"] += 1
    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    return stats


class EntityService:
    def list(
        self,
        *,
        limit: int,
        offset: int,
        entity_type: str | None,
        keyword: str | None,
        order: str,
        direction: str,
    ) -> tuple[list[EntityRecord], int]:
        with database.read_session() as conn:
            return entity_repo.list_entities(
                conn,
                limit=limit,
                offset=offset,
                entity_type=entity_type,
                keyword=keyword,
                order=order,
                direction=direction,
            )

    def detail(self, entity_id: str) -> EntityRecord:
        with database.read_session() as conn:
            record = entity_repo.get(conn, entity_id)
            if record is None:
                raise not_found("entity_not_found", "实体不存在")
            aliases = tuple(entity_repo.list_aliases(conn, entity_id))
            articles = tuple(
                entity_repo.list_article_entities(conn, entity_id, limit=DETAIL_ARTICLES)
            )
            merged_from = tuple(
                (item.id, item.canonical_name)
                for item in entity_repo.list_merged_from(conn, entity_id)
            )
            return replace(
                record, aliases=aliases, articles=articles, merged_from=merged_from
            )

    def merge_candidates(self, *, limit: int) -> list[tuple[EntityRecord, EntityRecord, str]]:
        with database.read_session() as conn:
            return entity_repo.list_merge_candidates(conn, limit)

    def merge(self, source_id: str, target_id: str, reason: str | None) -> EntityRecord:
        if source_id == target_id:
            raise conflict("entity_merge_conflict", "不能合并到自身")
        now = utc_timestamp()
        with database.session() as conn:
            source = entity_repo.get(conn, source_id)
            target = entity_repo.get(conn, target_id)
            if source is None or target is None:
                raise not_found("entity_not_found", "实体不存在")
            if source.status != "active" or target.status != "active":
                raise conflict("entity_merge_conflict", "只有活跃实体可以合并")
            if source.type_group != target.type_group:
                raise conflict("entity_merge_conflict", "实体类型不兼容，不能合并")
            affected = _events_for_entities(conn, [source_id, target_id])
            entity_repo.move_aliases(conn, source_id=source_id, target_id=target_id)
            entity_repo.move_article_links(conn, source_id=source_id, target_id=target_id)
            entity_repo.update_entity(
                conn,
                source_id,
                {
                    "status": "merged",
                    "merged_into_entity_id": target_id,
                    "normalization_basis": "merge",
                    "updated_at": now,
                },
            )
            entity_repo.update_entity(
                conn,
                target_id,
                {
                    "confidence": max(source.confidence, target.confidence),
                    "last_seen_at": max(
                        source.last_seen_at or target.last_seen_at or now,
                        target.last_seen_at or source.last_seen_at or now,
                    ),
                    "updated_at": now,
                },
            )
            for event_id in affected:
                rebuild_event_entities(conn, event_id, now)
            from database.repositories import event_audit_repository as audit_repo

            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=None,
                entity_id=target_id,
                action="merge_entities",
                actor="user",
                detail={
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "source_name": source.canonical_name,
                    "target_name": target.canonical_name,
                    "reason": (reason or "")[:500],
                },
                created_at=now,
            )
            merged = entity_repo.get(conn, target_id)
            if merged is None:
                raise not_found("entity_not_found", "实体不存在")
            return merged

    def unmerge(self, target_id: str) -> EntityRecord:
        now = utc_timestamp()
        with database.session() as conn:
            target = entity_repo.get(conn, target_id)
            if target is None:
                raise not_found("entity_not_found", "实体不存在")
            merged = entity_repo.list_merged_from(conn, target_id)
            if not merged:
                raise conflict("entity_not_merged", "该实体没有可撤销的合并记录")
            source = merged[0]
            affected = _events_for_entities(conn, [source.id, target_id])
            restored_links = entity_repo.restore_article_links(conn, source.id)
            restored_aliases = entity_repo.restore_aliases(conn, source.id)
            entity_repo.update_entity(
                conn,
                source.id,
                {
                    "status": "active",
                    "merged_into_entity_id": None,
                    "normalization_basis": "manual",
                    "updated_at": now,
                },
            )
            for event_id in affected:
                rebuild_event_entities(conn, event_id, now)
            from database.repositories import event_audit_repository as audit_repo

            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=None,
                entity_id=source.id,
                action="unmerge_entities",
                actor="user",
                detail={
                    "source_entity_id": source.id,
                    "target_entity_id": target_id,
                    "restored_article_links": restored_links,
                    "restored_aliases": restored_aliases,
                },
                created_at=now,
            )
            record = entity_repo.get(conn, source.id)
            if record is None:
                raise not_found("entity_not_found", "实体不存在")
            return record

    def add_alias(self, entity_id: str, alias: str, language: str | None) -> EntityRecord:
        cleaned = clean_entity_name(alias)
        if not cleaned:
            raise validation("alias", "empty", "别名不能为空")
        now = utc_timestamp()
        with database.session() as conn:
            entity = entity_repo.get(conn, entity_id)
            if entity is None or entity.status != "active":
                raise not_found("entity_not_found", "实体不存在")
            key = normalized_key(cleaned, entity.type_group)
            other = entity_repo.alias_owned_by_other(
                conn,
                alias_key=key,
                type_group=entity.type_group,
                entity_id=entity_id,
            )
            if other is not None:
                raise conflict("entity_alias_conflict", "该别名已属于同类型的其他实体")
            from event_intelligence.entities import guess_language

            entity_repo.insert_alias(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "entity_id": entity_id,
                    "alias": cleaned,
                    "alias_key": key,
                    "language": language or guess_language(cleaned),
                    "source": "manual",
                    "confidence": 1.0,
                    "merged_from_entity_id": None,
                    "created_at": now,
                },
            )
            entity_repo.update_entity(conn, entity_id, {"updated_at": now})
            from database.repositories import event_audit_repository as audit_repo

            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=None,
                entity_id=entity_id,
                action="entity_metadata",
                actor="user",
                detail={
                    "operation": "add_alias",
                    "alias": cleaned[:200],
                    "alias_key": key,
                    "language": language or guess_language(cleaned),
                },
                created_at=now,
            )
            record = entity_repo.get(conn, entity_id)
            if record is None:
                raise not_found("entity_not_found", "实体不存在")
            return record

    def delete_alias(self, entity_id: str, alias_id: str) -> None:
        with database.session() as conn:
            alias = entity_repo.get_alias(conn, alias_id)
            if alias is None or alias.entity_id != entity_id:
                raise not_found("entity_alias_not_found", "别名不存在")
            if alias.source == "canonical":
                raise conflict("entity_alias_protected", "规范名别名不可删除")
            entity_repo.delete_alias(conn, alias_id)
            from database.repositories import event_audit_repository as audit_repo

            audit_repo.insert(
                conn,
                audit_id=str(uuid.uuid4()),
                event_id=None,
                entity_id=entity_id,
                action="entity_metadata",
                actor="user",
                detail={
                    "operation": "delete_alias",
                    "alias_id": alias_id,
                    "alias": str(alias.alias)[:200],
                    "source": str(alias.source),
                },
                created_at=utc_timestamp(),
            )


def _events_for_entities(conn: sqlite3.Connection, entity_ids: list[str]) -> list[str]:
    if not entity_ids:
        return []
    placeholders = ", ".join("?" for _ in entity_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT event_id FROM event_entities
        WHERE entity_id IN ({placeholders})
        UNION
        SELECT DISTINCT ea.event_id
        FROM event_articles AS ea
        JOIN article_entities AS ae ON ae.article_id = ea.article_id
        WHERE ae.entity_id IN ({placeholders})
        """,
        (*entity_ids, *entity_ids),
    ).fetchall()
    return [str(row[0]) for row in rows]


_entity_service: EntityService | None = None


def get_entity_service() -> EntityService:
    global _entity_service
    if _entity_service is None:
        _entity_service = EntityService()
    return _entity_service
