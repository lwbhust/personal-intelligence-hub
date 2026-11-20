"""Event/article classification consistency (Phase 7.2, taxonomy-v1).

Reads are cheap and side-effect free. Writes only happen in `apply()` or in the
single-event `refresh_event_category()` used after an event gains a new article.
A `manual` classification is never overwritten by automation.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from database.repositories import event_audit_repository as audit_repo
from database.repositories import event_repository as event_repo
from core.timeutil import utc_timestamp
from event_intelligence.taxonomy import (
    TAXONOMY_VERSION,
    derive_event_domain,
    domain_key_of,
    resolve_category,
    taxonomy_document,
)
from services.errors import ServiceError

MANUAL_AUDIT_ACTION = "recategorize_event"
# The audit table's action CHECK is frozen in migration 0006, so automated
# changes reuse the same action and are distinguished by `actor='algorithm'`.
AUTO_AUDIT_ACTION = "recategorize_event"
AUTO_ACTOR = "algorithm"


@dataclass(frozen=True, slots=True)
class MemberCategory:
    article_id: str
    ai_category: str | None
    is_primary: bool


@dataclass(frozen=True, slots=True)
class CategorySuggestion:
    event_id: str
    title: str | None
    current_category: str
    current_source: str
    suggested_category: str
    resolved: bool
    confidence: float
    reason: str
    member_count: int
    analyzed_members: int
    unknown_members: int
    protected: bool
    protected_reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "current_category": self.current_category,
            "current_source": self.current_source,
            "suggested_category": self.suggested_category,
            "changed": self.suggested_category != self.current_category,
            "resolved": self.resolved,
            "confidence": self.confidence,
            "reason": self.reason,
            "member_count": self.member_count,
            "analyzed_members": self.analyzed_members,
            "unknown_members": self.unknown_members,
            "protected": self.protected,
            "protected_reason": self.protected_reason,
        }


def _member_categories(
    conn: sqlite3.Connection, event_ids: list[str]
) -> dict[str, list[MemberCategory]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT ea.event_id, ea.article_id, ea.role,
               x.category AS ai_category
        FROM event_articles AS ea
        JOIN articles AS a ON a.id = ea.article_id AND a.deleted_at IS NULL
        LEFT JOIN article_ai_analysis AS x ON x.id = (
            SELECT x2.id FROM article_ai_analysis AS x2
            WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE ea.event_id IN ({placeholders})
        ORDER BY ea.event_id, ea.added_at ASC, ea.id ASC
        """,
        tuple(event_ids),
    ).fetchall()
    grouped: dict[str, list[MemberCategory]] = {}
    for row in rows:
        grouped.setdefault(str(row["event_id"]), []).append(
            MemberCategory(
                article_id=str(row["article_id"]),
                ai_category=None if row["ai_category"] is None else str(row["ai_category"]),
                is_primary=str(row["role"]) == "report",
            )
        )
    return grouped


def _manual_reason(
    conn: sqlite3.Connection, event_id: str, category_source: str
) -> str | None:
    if category_source == "manual":
        return "人工分类保护（category_source=manual）"
    row = conn.execute(
        "SELECT 1 FROM event_audit_log "
        "WHERE event_id = ? AND action = ? AND actor <> ? LIMIT 1",
        (event_id, MANUAL_AUDIT_ACTION, AUTO_ACTOR),
    ).fetchone()
    if row is not None:
        return "人工分类保护（历史人工修改记录）"
    return None


def suggest_for_events(
    conn: sqlite3.Connection,
    *,
    limit: int = 200,
    offset: int = 0,
    only_unresolved: bool = False,
) -> tuple[list[CategorySuggestion], int]:
    """Return read-only suggestions for events, newest first."""

    clauses = ["e.status NOT IN ('merged','archived')"]
    if only_unresolved:
        clauses.append("e.category_source = 'unresolved'")
    where = " AND ".join(clauses)
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM events AS e WHERE {where}"
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    rows = conn.execute(
        f"SELECT e.id, e.title, e.category, e.category_source FROM events AS e "
        f"WHERE {where} ORDER BY e.created_at DESC, e.id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    ids = [str(row["id"]) for row in rows]
    members = _member_categories(conn, ids)

    suggestions: list[CategorySuggestion] = []
    for row in rows:
        event_id = str(row["id"])
        items = members.get(event_id, [])
        decision = derive_event_domain(
            [(item.ai_category, item.is_primary) for item in items]
        )
        protected_reason = _manual_reason(
            conn, event_id, str(row["category_source"])
        )
        suggestions.append(
            CategorySuggestion(
                event_id=event_id,
                title=row["title"],
                current_category=str(row["category"]),
                current_source=str(row["category_source"]),
                suggested_category=decision.domain_name,
                resolved=decision.resolved,
                confidence=decision.confidence,
                reason=decision.reason,
                member_count=len(items),
                analyzed_members=sum(1 for item in items if item.ai_category),
                unknown_members=decision.unknown_members,
                protected=protected_reason is not None,
                protected_reason=protected_reason,
            )
        )
    return suggestions, total


def refresh_event_category(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    now: str,
    force: bool = False,
) -> CategorySuggestion | None:
    """Re-evaluate one event's domain from all members and persist it.

    - manual categories are never touched unless `force=True` (never used by the
      orchestrator; reserved for an explicit, audited admin action);
    - an event without usable AI categories is marked `unresolved` and keeps its
      current value instead of being forced into `其他`.
    """

    event = event_repo.get(conn, event_id)
    if event is None:
        return None
    if not force and event.category_source == "manual":
        return None
    if not force and _manual_reason(conn, event_id, event.category_source) is not None:
        return None

    members = _member_categories(conn, [event_id]).get(event_id, [])
    decision = derive_event_domain(
        [(item.ai_category, item.is_primary) for item in members]
    )

    if not decision.resolved:
        if event.category_source != "unresolved":
            event_repo.update_event(
                conn,
                event_id,
                {
                    "category_source": "unresolved",
                    "category_reason": decision.reason[:500],
                    "category_updated_at": now,
                    "updated_at": now,
                },
            )
        return CategorySuggestion(
            event_id=event_id,
            title=event.title,
            current_category=event.category,
            current_source=event.category_source,
            suggested_category=decision.domain_name,
            resolved=False,
            confidence=decision.confidence,
            reason=decision.reason,
            member_count=len(members),
            analyzed_members=sum(1 for item in members if item.ai_category),
            unknown_members=decision.unknown_members,
            protected=False,
            protected_reason=None,
        )

    changed = decision.domain_name != event.category
    fields: dict[str, object] = {
        "category_source": "auto",
        "category_reason": decision.reason[:500],
        "category_updated_at": now,
        "updated_at": now,
    }
    if changed:
        fields["category"] = decision.domain_name
    event_repo.update_event(conn, event_id, fields)
    if changed:
        audit_repo.insert(
            conn,
            audit_id=str(uuid.uuid4()),
            event_id=event_id,
            entity_id=None,
            action=AUTO_AUDIT_ACTION,
            actor=AUTO_ACTOR,
            detail={
                "previous_category": event.category,
                "current_category": decision.domain_name,
                "taxonomy_version": TAXONOMY_VERSION,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "member_count": len(members),
                "analyzed_members": sum(1 for item in members if item.ai_category),
            },
            created_at=now,
        )

    return CategorySuggestion(
        event_id=event_id,
        title=event.title,
        current_category=event.category,
        current_source=event.category_source,
        suggested_category=decision.domain_name,
        resolved=True,
        confidence=decision.confidence,
        reason=decision.reason,
        member_count=len(members),
        analyzed_members=sum(1 for item in members if item.ai_category),
        unknown_members=decision.unknown_members,
        protected=False,
        protected_reason=None,
    )


def apply_suggestions(
    conn: sqlite3.Connection,
    *,
    event_ids: list[str] | None,
    limit: int,
    now: str,
) -> dict[str, object]:
    """Apply re-evaluation inside the caller's transaction.

    `event_ids=None` scans all non-terminal events up to `limit`.
    """

    if event_ids is None:
        rows = conn.execute(
            "SELECT id FROM events WHERE status NOT IN ('merged','archived') "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        targets = [str(row[0]) for row in rows]
    else:
        targets = list(dict.fromkeys(event_ids))[:limit]

    changed = 0
    resolved = 0
    unresolved = 0
    protected = 0
    details: list[dict[str, object]] = []
    for event_id in targets:
        event = event_repo.get(conn, event_id)
        if event is None:
            continue
        if event.category_source == "manual" or _manual_reason(
            conn, event_id, event.category_source
        ) is not None:
            protected += 1
            continue
        before = event.category
        suggestion = refresh_event_category(conn, event_id, now=now)
        if suggestion is None:
            protected += 1
            continue
        if suggestion.resolved:
            resolved += 1
        else:
            unresolved += 1
        if suggestion.suggested_category != before and suggestion.resolved:
            changed += 1
            details.append(
                {
                    "event_id": event_id,
                    "before": before,
                    "after": suggestion.suggested_category,
                    "confidence": suggestion.confidence,
                }
            )

    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "scanned_events": len(targets),
        "changed_events": changed,
        "resolved_events": resolved,
        "unresolved_events": unresolved,
        "protected_events": protected,
        "changes": details[:200],
    }


def article_category_mapping(conn: sqlite3.Connection) -> dict[str, object]:
    """Summarise how stored article categories map into the dictionary."""

    rows = conn.execute(
        "SELECT category, COUNT(*) AS n FROM article_ai_analysis "
        "GROUP BY category ORDER BY n DESC"
    ).fetchall()
    items: list[dict[str, object]] = []
    unmapped = 0
    for row in rows:
        category = str(row["category"])
        resolution = resolve_category(category)
        if not resolution.known:
            unmapped += int(row["n"])
        items.append(
            {
                "category": category,
                "count": int(row["n"]),
                "topic_key": resolution.topic_key,
                "domain_key": resolution.domain_key,
                "domain_name": resolution.domain_name,
                "known": resolution.known,
                "detail": resolution.detail,
            }
        )
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "items": items,
        "unmapped_articles": unmapped,
    }


def classification_distribution(conn: sqlite3.Connection) -> dict[str, object]:
    """Current event category distribution plus source provenance counts."""

    rows = conn.execute(
        "SELECT category, category_source, COUNT(*) AS n FROM events "
        "GROUP BY category, category_source ORDER BY n DESC"
    ).fetchall()
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "items": [
            {
                "category": str(row["category"]),
                "category_source": str(row["category_source"]),
                "domain_key": domain_key_of(str(row["category"])),
                "count": int(row["n"]),
            }
            for row in rows
        ],
    }


def taxonomy_snapshot() -> dict[str, object]:
    return taxonomy_document()


def apply_classification(*, limit: int) -> dict[str, object]:
    """Create a verified backup, then apply the re-evaluation in one transaction."""

    import database
    from database import backup

    try:
        backup_payload = backup.create_backup("classification-fix")
    except backup.BackupError as exc:
        raise ServiceError(
            "backup_failed",
            409,
            f"备份失败，已取消分类修复：{exc.message}",
        ) from exc

    with database.session() as conn:
        result = apply_suggestions(
            conn, event_ids=None, limit=limit, now=utc_timestamp()
        )
    result["backup"] = backup_payload
    return result
