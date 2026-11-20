"""Home-page aggregation for the "今日" screen.

This service only reads existing derived data (recommendation results, events,
pipeline counters). It never triggers AI, clustering or collection work, so
opening the home page is always cheap.
"""

from __future__ import annotations

import database
from core.timeutil import utc_timestamp
from database.repositories import pipeline_repository as pipeline_repo
from services import personalization_service as personalization


def _flatten_primary(feed: dict[str, object]) -> list[dict[str, object]]:
    sections = feed.get("sections") or {}
    if not isinstance(sections, dict):
        return []
    ordered: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for key in ("must_read", "event_highlights", "core_interest", "leads"):
        for item in sections.get(key) or []:
            if not isinstance(item, dict):
                continue
            identity = (str(item.get("target_type")), str(item.get("target_id")))
            if identity in seen:
                continue
            seen.add(identity)
            ordered.append(item)
    return ordered


def _recent_reads(conn, limit: int = 6) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT a.id, a.title, s.name AS source_name, a.last_read_at, a.published_at
        FROM articles AS a
        JOIN sources AS s ON s.id = a.source_id AND s.deleted_at IS NULL
        WHERE a.deleted_at IS NULL AND a.reading_status = 'read'
        ORDER BY a.last_read_at DESC, a.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "source_name": row["source_name"],
            "last_read_at": row["last_read_at"],
            "published_at": row["published_at"],
        }
        for row in rows
    ]


def _multi_report(item: dict[str, object]) -> bool:
    """A single article is not an event worth surfacing on the home page."""

    if str(item.get("target_type")) != "event":
        return True
    return int(item.get("article_count") or 0) >= 2


def overview(*, pick_limit: int = 5, todo_limit: int = 10) -> dict[str, object]:
    # Ask for a wider window than the visible budget: single-article events are
    # filtered out below, so a narrow limit would otherwise leave the home page
    # without enough real articles.
    feed = personalization.feed(limit=50, include_low=False)
    primary = [item for item in _flatten_primary(feed) if _multi_report(item)]

    sections = feed.get("sections") or {}
    all_events: list[dict[str, object]] = []
    seen_events: set[str] = set()
    if isinstance(sections, dict):
        for key in ("must_read", "event_highlights", "core_interest"):
            for item in sections.get(key) or []:
                if not isinstance(item, dict) or not _multi_report(item):
                    continue
                if str(item.get("target_type")) != "event":
                    continue
                target_id = str(item.get("target_id"))
                if target_id in seen_events:
                    continue
                seen_events.add(target_id)
                all_events.append(item)

    picks = primary[:pick_limit]
    picks_ids = {
        (str(item.get("target_type")), str(item.get("target_id"))) for item in picks
    }
    todo = [
        item
        for item in primary
        if (str(item.get("target_type")), str(item.get("target_id"))) not in picks_ids
        and item.get("target_type") == "article"
    ][:todo_limit]

    # The same event must not appear twice on the home page: events already
    # shown in today's picks are removed from the dedicated events section.
    events = [
        item
        for item in all_events
        if (str(item.get("target_type")), str(item.get("target_id"))) not in picks_ids
    ][:5]
    metrics = feed.get("metrics") or {}

    with database.read_session() as conn:
        settings = pipeline_repo.get_settings(conn)
        activity = pipeline_repo.recent_activity(conn)
        counts = pipeline_repo.count_by_status(conn)
        today = pipeline_repo.today_counts(conn, since=_today_start())
        recent_reads = _recent_reads(conn)
        new_today = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL "
            "AND COALESCE(published_at, fetched_at) >= ?",
            (_today_start(),),
        ).fetchone()

    return {
        "generated_at": utc_timestamp(),
        "metrics": {
            "today_articles": int(new_today[0]) if new_today else 0,
            "recommended_total": metrics.get("recommended_total", 0),
            "must_read": metrics.get("must_read", 0),
            "event_count": metrics.get("event_count", 0),
            "multi_report_events": len(all_events),
            "unread_picks": len(primary),
        },
        "picks": picks,
        "events": events,
        "todo": todo,
        "recent_reads": recent_reads,
        "automation": {
            "enabled": settings.automation_enabled,
            "paused": settings.paused,
            "ai_enabled": settings.ai_enabled,
            "event_enabled": settings.event_enabled,
            "pending": (
                counts.get("pending", 0)
                + counts.get("ready", 0)
                + counts.get("retry_wait", 0)
            ),
            "running": counts.get("running", 0),
            "failed": counts.get("failed", 0),
            "today_succeeded": today.get("succeeded", 0),
            "today_failed": today.get("failed", 0),
            "today_skipped": today.get("skipped", 0),
            "last_completed_at": activity.get("last_completed_at"),
            "last_succeeded_at": activity.get("last_succeeded_at"),
        },
        "has_interests": feed.get("has_interests", False),
        "has_core_interest": feed.get("has_core_interest", False),
        "onboarding_done": feed.get("onboarding_done", False),
    }


def _today_start() -> str:
    from datetime import datetime, timezone

    moment = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
