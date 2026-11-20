"""Deterministic evidence building for Phase 7.1 intelligence reports.

Every number and every reference in a report comes from these functions.
The local model only writes interpretation over this evidence; it can never
invent statistics, and its citations are validated against the IDs collected
here.

Statistics version: `intelligence-stats-v1`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone

from database.repositories import intelligence_repository as intel_repo

STATS_VERSION = "intelligence-stats-v1"
KEY_EVENT_LIMIT = 8
EVIDENCE_PER_EVENT = 4
SUMMARY_CHARS = 300
RISING_LIMIT = 10
ENTITY_LIMIT = 10
TOPIC_LIMIT = 10

NOTES = (
    "统计口径：文章按 COALESCE(published_at, fetched_at) 归入 UTC 日期区间；",
    "事件按 COALESCE(last_published_at, last_seen_at) 归入区间；",
    "分类与关键词来自既有本地 AI 分析结果，未分析文章单独计入“未分析”；",
    "关键词变化为当前区间与等长上一区间的真实计数对比。",
)


def _ts(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def period_for(report_type: str, *, today: date | None = None) -> tuple[date, date]:
    """Data range: today for daily, a rolling 7-day window for weekly."""

    if report_type == "daily":
        current = today or today_utc()
        return current, current
    if report_type == "weekly":
        current = today or today_utc()
        return current - timedelta(days=6), current
    raise ValueError(f"unknown report type: {report_type}")


def period_key_for(report_type: str, *, today: date | None = None) -> str:
    """Dedupe anchor: the day for daily, the ISO week start for weekly."""

    current = today or today_utc()
    if report_type == "daily":
        return current.isoformat()
    if report_type == "weekly":
        return (current - timedelta(days=current.weekday())).isoformat()
    raise ValueError(f"unknown report type: {report_type}")


def _bounds(start: date, end: date) -> tuple[str, str]:
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return _ts(start_at), _ts(end_at)


def _previous_bounds(start: date, end: date) -> tuple[str, str]:
    span = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=span - 1)
    return _bounds(previous_start, previous_end)


def _clean(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _keywords(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip()[:30])
    return out


def _keyword_stats(
    rows: list[sqlite3.Row],
) -> dict[str, dict[str, object]]:
    """keyword -> {count, sources, article_ids} for one window."""

    result: dict[str, dict[str, object]] = {}
    for row in rows:
        source_name = str(row["source_name"] or "")
        for keyword in _keywords(row["keywords_json"]):
            entry = result.setdefault(
                keyword,
                {"keyword": keyword, "count": 0, "sources": set(), "article_ids": []},
            )
            entry["count"] = int(entry["count"]) + 1
            sources = entry["sources"]
            assert isinstance(sources, set)
            if source_name:
                sources.add(source_name)
            article_ids = entry["article_ids"]
            assert isinstance(article_ids, list)
            if len(article_ids) < 5:
                article_ids.append(str(row["article_id"]))
    return result


def _serialise_keyword(entry: dict[str, object]) -> dict[str, object]:
    sources = entry.get("sources") or set()
    return {
        "keyword": entry["keyword"],
        "count": entry["count"],
        "sources": sorted(str(item) for item in sources),
        "article_ids": list(entry.get("article_ids") or []),
    }


def build_stats(
    conn: sqlite3.Connection,
    *,
    report_type: str,
    period_start: date,
    period_end: date,
) -> dict[str, object]:
    start_ts, end_ts = _bounds(period_start, period_end)
    prev_start_ts, prev_end_ts = _previous_bounds(period_start, period_end)

    current = intel_repo.article_window_stats(conn, start_ts, end_ts)
    previous = intel_repo.article_window_stats(conn, prev_start_ts, prev_end_ts)
    categories_now = intel_repo.category_window_counts(conn, start_ts, end_ts)
    categories_before = intel_repo.category_window_counts(conn, prev_start_ts, prev_end_ts)

    events_now = intel_repo.count_events_in_window(conn, start_ts, end_ts)
    new_events = intel_repo.count_events_in_window(conn, start_ts, end_ts, new_only=True)
    unclustered_total, unclustered = intel_repo.unclustered_articles(
        conn, start_ts, end_ts, limit=6
    )

    key_rows = intel_repo.events_in_window(conn, start_ts, end_ts, limit=KEY_EVENT_LIMIT)
    event_ids = [str(row["id"]) for row in key_rows]
    entities_by_event = intel_repo.event_entities_for(conn, event_ids)
    articles_by_event = intel_repo.event_evidence_articles(
        conn, event_ids, per_event=EVIDENCE_PER_EVENT
    )

    key_events: list[dict[str, object]] = []
    for row in key_rows:
        event_id = str(row["id"])
        entities = [
            {
                "name": _clean(item["canonical_name"], 60),
                "type": str(item["entity_type"]),
                "role": str(item["role"]),
                "article_count": int(item["article_count"]),
            }
            for item in entities_by_event.get(event_id, [])[:6]
        ]
        evidence = [
            {
                "article_id": str(item["article_id"]),
                "title": _clean(item["title"], 200),
                "source_name": _clean(item["source_name"], 100),
                "url": item["canonical_url"] or item["original_url"],
                "summary": _clean(item["ai_summary"] or item["summary"] or "", 160),
                "published_at": item["at"],
            }
            for item in articles_by_event.get(event_id, [])
        ]
        key_events.append(
            {
                "event_id": event_id,
                "title": _clean(row["title"], 200),
                "summary": _clean(row["summary"] or "", SUMMARY_CHARS),
                "category": str(row["category"]),
                "status": str(row["status"]),
                "article_count": int(row["article_count"]),
                "source_count": int(row["source_count"]),
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "scores": {
                    "importance": float(row["importance_score"] or 0),
                    "heat": float(row["heat_score"] or 0),
                    "freshness": float(row["freshness_score"] or 0),
                    "coverage": float(row["coverage_score"] or 0),
                    "confidence": float(row["confidence_score"] or 0),
                    "total": float(row["total_score"] or 0),
                    "algorithm_version": row["algorithm_version"],
                },
                "entities": entities,
                "evidence": evidence,
            }
        )

    keywords_now = _keyword_stats(intel_repo.keyword_rows(conn, start_ts, end_ts))
    keywords_before = _keyword_stats(
        intel_repo.keyword_rows(conn, prev_start_ts, prev_end_ts)
    )

    rising: list[dict[str, object]] = []
    for keyword, entry in keywords_now.items():
        count = int(entry["count"])
        before = int(keywords_before.get(keyword, {}).get("count", 0))
        if count < 2:
            continue
        if before > 0 and count < before * 1.5:
            continue
        rising.append(
            {
                "keyword": keyword,
                "count": count,
                "previous": before,
                "delta": count - before,
                "sources": sorted(str(item) for item in (entry.get("sources") or set())),
            }
        )
    rising.sort(key=lambda item: (-int(item["delta"]), -int(item["count"])))
    rising = rising[:RISING_LIMIT]

    cross_source: list[dict[str, object]] = []
    for entry in keywords_now.values():
        sources = entry.get("sources") or set()
        assert isinstance(sources, set)
        if len(sources) >= 2:
            cross_source.append(_serialise_keyword(entry) | {"source_count": len(sources)})
    cross_source.sort(key=lambda item: (-int(item["source_count"]), -int(item["count"])))
    cross_source = cross_source[:TOPIC_LIMIT]

    new_entities = intel_repo.new_entities(conn, start_ts, end_ts, limit=ENTITY_LIMIT)
    top_entities = intel_repo.entity_mentions_in_window(
        conn, start_ts, end_ts, limit=ENTITY_LIMIT
    )
    relations = intel_repo.relations_between(conn, event_ids)

    data_from = current.get("first_at") or (key_events[0]["last_seen_at"] if key_events else None)
    data_to = current.get("last_at") or (key_events[0]["last_seen_at"] if key_events else None)

    return {
        "version": STATS_VERSION,
        "period": {
            "report_type": report_type,
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "from_at": start_ts,
            "to_at": end_ts,
            "previous_start": prev_start_ts,
            "previous_end": prev_end_ts,
        },
        "totals": {
            "articles": int(current["articles"]),
            "sources": int(current["sources"]),
            "previous_articles": int(previous["articles"]),
            "events": events_now,
            "new_events": new_events,
            "unclustered_articles": unclustered_total,
        },
        "data_range": {"from_at": data_from, "to_at": data_to},
        "categories": [
            {
                "name": name,
                "articles": int(categories_now.get(name, 0)),
                "previous": int(categories_before.get(name, 0)),
                "delta": int(categories_now.get(name, 0)) - int(categories_before.get(name, 0)),
            }
            for name in sorted(set(categories_now) | set(categories_before))
        ],
        "key_events": key_events,
        "rising_keywords": rising,
        "cross_source_topics": cross_source,
        "new_entities": new_entities,
        "top_entities": top_entities,
        "relations": relations,
        "unclustered_samples": unclustered,
        "notes": list(NOTES),
    }


def available_evidence_ids(stats: dict[str, object]) -> tuple[dict[str, set[str]], set[str], set[str]]:
    """Allowed IDs for citation validation: per-event articles, events, entities."""

    articles: dict[str, set[str]] = {}
    events: set[str] = set()
    entities: set[str] = set()
    for event in stats.get("key_events") or []:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        events.add(event_id)
        articles[event_id] = {
            str(item.get("article_id"))
            for item in (event.get("evidence") or [])
            if isinstance(item, dict) and item.get("article_id")
        }
        for entity in event.get("entities") or []:
            if isinstance(entity, dict) and entity.get("name"):
                entities.add(str(entity["name"]))
    return articles, events, entities


def evidence_article_index(stats: dict[str, object]) -> dict[str, dict[str, object]]:
    """article_id -> {title, source_name, url} for citation rows."""

    index: dict[str, dict[str, object]] = {}
    for event in stats.get("key_events") or []:
        if not isinstance(event, dict):
            continue
        for item in event.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            article_id = str(item.get("article_id") or "")
            if article_id and article_id not in index:
                index[article_id] = {
                    "title": item.get("title"),
                    "source_name": item.get("source_name"),
                    "url": item.get("url"),
                }
    return index
