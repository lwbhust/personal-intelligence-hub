"""Parameterised SQL for Phase 7.3.1 personalization.

Every write goes through a caller-owned `database.session()` transaction. Read
helpers join only what the recommendation service needs (article features,
event membership, current event score).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace

from .models import (
    DigestItemRecord,
    DigestRecord,
    FeedbackRecord,
    InterestProfileRecord,
    InterestRecord,
    RecommendationRecord,
)

INTEREST_COLUMNS = (
    "id",
    "name",
    "interest_type",
    "level",
    "weight",
    "domain_key",
    "enabled",
    "notes",
    "created_at",
    "updated_at",
)

FEEDBACK_COLUMNS = (
    "id",
    "target_type",
    "target_id",
    "feedback",
    "interest_id",
    "note",
    "created_at",
    "revoked_at",
)

RESULT_COLUMNS = (
    "id",
    "target_type",
    "target_id",
    "score",
    "level",
    "interest_score",
    "importance_score",
    "novelty_score",
    "source_quality_score",
    "recency_score",
    "matched_interests_json",
    "matched_entities_json",
    "reason_codes_json",
    "warnings_json",
    "explanation_json",
    "algorithm_version",
    "inputs_version",
    "is_fallback",
    "is_current",
    "computed_at",
    "created_at",
    "updated_at",
)

DIGEST_COLUMNS = (
    "id",
    "digest_date",
    "timezone",
    "status",
    "ai_status",
    "headline",
    "overview",
    "stats_json",
    "model_name",
    "model_digest",
    "prompt_version",
    "digest_version",
    "generated_at",
    "superseded_at",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
)

DIGEST_ITEM_COLUMNS = (
    "id",
    "digest_id",
    "section",
    "rank",
    "target_type",
    "target_id",
    "title",
    "reason",
    "matched_interests_json",
    "score",
    "created_at",
)


def _json_list(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def get_profile(conn: sqlite3.Connection) -> InterestProfileRecord:
    row = conn.execute("SELECT * FROM interest_profiles WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("interest_profiles row is missing")
    return InterestProfileRecord(
        display_name=str(row["display_name"]),
        digest_time=str(row["digest_time"]),
        timezone=str(row["timezone"]),
        daily_item_limit=None if row["daily_item_limit"] is None else int(row["daily_item_limit"]),
        daily_minutes=None if row["daily_minutes"] is None else int(row["daily_minutes"]),
        exploration_ratio=float(row["exploration_ratio"]),
        auto_adjust_enabled=bool(int(row["auto_adjust_enabled"])),
        onboarding_done=bool(int(row["onboarding_done"])),
        scoring_config=_json_object(row["scoring_config_json"]),
        updated_at=str(row["updated_at"]),
    )


def update_profile(
    conn: sqlite3.Connection, fields: Mapping[str, object], *, updated_at: str
) -> InterestProfileRecord:
    allowed = {
        "display_name",
        "digest_time",
        "timezone",
        "daily_item_limit",
        "daily_minutes",
        "exploration_ratio",
        "auto_adjust_enabled",
        "onboarding_done",
        "scoring_config_json",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown profile fields: {sorted(unknown)}")
    values = dict(fields)
    values["updated_at"] = updated_at
    assignments = ", ".join(f"{key} = ?" for key in values)
    conn.execute(
        f"UPDATE interest_profiles SET {assignments} WHERE id = 1",
        tuple(values.values()),
    )
    return get_profile(conn)


# ---------------------------------------------------------------------------
# Interests
# ---------------------------------------------------------------------------


def _interest_rows(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> list[InterestRecord]:
    rows = conn.execute(
        f"SELECT * FROM interests {where} ORDER BY "
        "CASE level WHEN 'core' THEN 0 WHEN 'extended' THEN 1 WHEN 'general' THEN 2 ELSE 3 END, "
        "updated_at DESC, name ASC",
        params,
    ).fetchall()
    records: list[InterestRecord] = []
    for row in rows:
        interest_id = str(row["id"])
        keywords = conn.execute(
            "SELECT keyword, is_exclusion FROM interest_keywords WHERE interest_id = ? "
            "ORDER BY created_at, keyword",
            (interest_id,),
        ).fetchall()
        entities = conn.execute(
            "SELECT l.entity_id, e.canonical_name FROM interest_entity_links l "
            "JOIN entities e ON e.id = l.entity_id WHERE l.interest_id = ? "
            "ORDER BY e.canonical_name",
            (interest_id,),
        ).fetchall()
        sources = conn.execute(
            "SELECT l.source_id, s.name FROM interest_source_links l "
            "JOIN sources s ON s.id = l.source_id WHERE l.interest_id = ? "
            "ORDER BY s.name",
            (interest_id,),
        ).fetchall()
        records.append(
            InterestRecord(
                id=interest_id,
                name=str(row["name"]),
                interest_type=str(row["interest_type"]),
                level=str(row["level"]),
                weight=float(row["weight"]),
                domain_key=row["domain_key"],
                enabled=bool(int(row["enabled"])),
                notes=row["notes"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                keywords=tuple(str(item["keyword"]) for item in keywords if not int(item["is_exclusion"])),
                exclusion_keywords=tuple(
                    str(item["keyword"]) for item in keywords if int(item["is_exclusion"])
                ),
                entity_ids=tuple(str(item["entity_id"]) for item in entities),
                entity_names=tuple(str(item["canonical_name"]) for item in entities),
                source_ids=tuple(str(item["source_id"]) for item in sources),
                source_names=tuple(str(item["name"]) for item in sources),
            )
        )
    return records


def list_interests(conn: sqlite3.Connection) -> list[InterestRecord]:
    return _interest_rows(conn)


def get_interest(conn: sqlite3.Connection, interest_id: str) -> InterestRecord | None:
    rows = _interest_rows(conn, "WHERE id = ?", (interest_id,))
    return rows[0] if rows else None


def find_interest_by_name(conn: sqlite3.Connection, name: str) -> InterestRecord | None:
    rows = _interest_rows(conn, "WHERE name = ?", (name,))
    return rows[0] if rows else None


def insert_interest(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(INTEREST_COLUMNS)
    placeholders = ", ".join("?" for _ in INTEREST_COLUMNS)
    conn.execute(
        f"INSERT INTO interests ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in INTEREST_COLUMNS),
    )


def update_interest(
    conn: sqlite3.Connection, interest_id: str, fields: Mapping[str, object]
) -> None:
    allowed = set(INTEREST_COLUMNS) - {"id", "created_at"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown interest fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE interests SET {assignments} WHERE id = ?",
        tuple(fields.values()) + (interest_id,),
    )


def delete_interest(conn: sqlite3.Connection, interest_id: str) -> int:
    cursor = conn.execute("DELETE FROM interests WHERE id = ?", (interest_id,))
    return int(cursor.rowcount or 0)


def replace_keywords(
    conn: sqlite3.Connection,
    interest_id: str,
    *,
    keywords: Sequence[str],
    exclusions: Sequence[str],
    created_at: str,
    make_id,
) -> None:
    conn.execute("DELETE FROM interest_keywords WHERE interest_id = ?", (interest_id,))
    seen: set[tuple[str, int]] = set()
    for keyword in keywords:
        cleaned = keyword.strip()
        if not cleaned or (cleaned, 0) in seen:
            continue
        seen.add((cleaned, 0))
        conn.execute(
            "INSERT INTO interest_keywords (id, interest_id, keyword, is_exclusion, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (str(make_id()), interest_id, cleaned, created_at),
        )
    for keyword in exclusions:
        cleaned = keyword.strip()
        if not cleaned or (cleaned, 1) in seen:
            continue
        seen.add((cleaned, 1))
        conn.execute(
            "INSERT INTO interest_keywords (id, interest_id, keyword, is_exclusion, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (str(make_id()), interest_id, cleaned, created_at),
        )


def link_entity(
    conn: sqlite3.Connection, *, link_id: str, interest_id: str, entity_id: str, created_at: str
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO interest_entity_links (id, interest_id, entity_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (link_id, interest_id, entity_id, created_at),
    )
    return cursor.rowcount == 1


def unlink_entity(conn: sqlite3.Connection, *, interest_id: str, entity_id: str) -> int:
    cursor = conn.execute(
        "DELETE FROM interest_entity_links WHERE interest_id = ? AND entity_id = ?",
        (interest_id, entity_id),
    )
    return int(cursor.rowcount or 0)


def link_source(
    conn: sqlite3.Connection, *, link_id: str, interest_id: str, source_id: str, created_at: str
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO interest_source_links (id, interest_id, source_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (link_id, interest_id, source_id, created_at),
    )
    return cursor.rowcount == 1


def unlink_source(conn: sqlite3.Connection, *, interest_id: str, source_id: str) -> int:
    cursor = conn.execute(
        "DELETE FROM interest_source_links WHERE interest_id = ? AND source_id = ?",
        (interest_id, source_id),
    )
    return int(cursor.rowcount or 0)


def list_blocked_sources(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        "SELECT b.source_id, s.name, b.reason, b.created_at FROM blocked_sources b "
        "JOIN sources s ON s.id = b.source_id ORDER BY b.created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def block_source(
    conn: sqlite3.Connection, *, source_id: str, reason: str | None, created_at: str
) -> None:
    conn.execute(
        "INSERT INTO blocked_sources (source_id, reason, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(source_id) DO UPDATE SET reason = excluded.reason, created_at = excluded.created_at",
        (source_id, reason, created_at),
    )


def unblock_source(conn: sqlite3.Connection, source_id: str) -> int:
    cursor = conn.execute("DELETE FROM blocked_sources WHERE source_id = ?", (source_id,))
    return int(cursor.rowcount or 0)


def blocked_source_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT source_id FROM blocked_sources").fetchall()
    return {str(row[0]) for row in rows}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def _feedback_from_row(row: sqlite3.Row) -> FeedbackRecord:
    return FeedbackRecord(
        id=str(row["id"]),
        target_type=str(row["target_type"]),
        target_id=str(row["target_id"]),
        feedback=str(row["feedback"]),
        interest_id=row["interest_id"],
        note=row["note"],
        created_at=str(row["created_at"]),
        revoked_at=row["revoked_at"],
    )


def insert_feedback(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(FEEDBACK_COLUMNS)
    placeholders = ", ".join("?" for _ in FEEDBACK_COLUMNS)
    conn.execute(
        f"INSERT INTO recommendation_feedback ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in FEEDBACK_COLUMNS),
    )


def active_feedback(
    conn: sqlite3.Connection, *, target_type: str, target_id: str
) -> FeedbackRecord | None:
    row = conn.execute(
        "SELECT * FROM recommendation_feedback WHERE target_type = ? AND target_id = ? "
        "AND revoked_at IS NULL",
        (target_type, target_id),
    ).fetchone()
    return None if row is None else _feedback_from_row(row)


def revoke_feedback(conn: sqlite3.Connection, feedback_id: str, *, revoked_at: str) -> int:
    cursor = conn.execute(
        "UPDATE recommendation_feedback SET revoked_at = ? "
        "WHERE id = ? AND revoked_at IS NULL",
        (revoked_at, feedback_id),
    )
    return int(cursor.rowcount or 0)


def list_feedback(
    conn: sqlite3.Connection, *, limit: int, offset: int, include_revoked: bool
) -> tuple[list[FeedbackRecord], int]:
    where = "" if include_revoked else "WHERE revoked_at IS NULL"
    rows = conn.execute(
        f"SELECT * FROM recommendation_feedback {where} "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM recommendation_feedback {where}"
    ).fetchone()
    return (
        [_feedback_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def active_feedback_map(
    conn: sqlite3.Connection, target_type: str
) -> dict[str, str]:
    rows = conn.execute(
        "SELECT target_id, feedback FROM recommendation_feedback "
        "WHERE target_type = ? AND revoked_at IS NULL",
        (target_type,),
    ).fetchall()
    return {str(row["target_id"]): str(row["feedback"]) for row in rows}


def feedback_max_timestamp(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MAX(COALESCE(revoked_at, created_at)) FROM recommendation_feedback"
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def feedback_counts_by_interest(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT f.interest_id, f.feedback, COUNT(*) AS n
        FROM recommendation_feedback f
        WHERE f.revoked_at IS NULL AND f.interest_id IS NOT NULL
        GROUP BY f.interest_id, f.feedback
        ORDER BY n DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Recommendation results
# ---------------------------------------------------------------------------


def _result_from_row(row: sqlite3.Row) -> RecommendationRecord:
    keys = set(row.keys())
    return RecommendationRecord(
        id=str(row["id"]),
        target_type=str(row["target_type"]),
        target_id=str(row["target_id"]),
        score=float(row["score"]),
        level=str(row["level"]),
        interest_score=float(row["interest_score"]),
        importance_score=float(row["importance_score"]),
        novelty_score=float(row["novelty_score"]),
        source_quality_score=float(row["source_quality_score"]),
        recency_score=float(row["recency_score"]),
        matched_interests=_json_list(row["matched_interests_json"]),
        matched_entities=_json_list(row["matched_entities_json"]),
        reason_codes=_json_list(row["reason_codes_json"]),
        warnings=_json_list(row["warnings_json"]),
        explanation=_json_object(row["explanation_json"]),
        algorithm_version=str(row["algorithm_version"]),
        inputs_version=str(row["inputs_version"]),
        is_fallback=bool(int(row["is_fallback"])),
        computed_at=str(row["computed_at"]),
        title=row["title"] if "title" in keys else None,
        summary=row["summary"] if "summary" in keys else None,
        source_name=row["source_name"] if "source_name" in keys else None,
        category=row["category"] if "category" in keys else None,
        published_at=row["published_at"] if "published_at" in keys else None,
        event_id=row["event_id"] if "event_id" in keys else None,
        article_count=int(row["article_count"] or 0) if "article_count" in keys else 0,
        source_count=int(row["source_count"] or 0) if "source_count" in keys else 0,
        is_read=bool(int(row["is_read"])) if "is_read" in keys else False,
        is_favorite=bool(int(row["is_favorite"])) if "is_favorite" in keys else False,
    )


_RESULT_JOIN = """
    SELECT r.*,
           CASE WHEN r.target_type = 'article' THEN a.title ELSE e.title END AS title,
           CASE WHEN r.target_type = 'article'
                THEN substr(COALESCE(NULLIF(x.summary, ''), a.summary), 1, 400)
                ELSE substr(e.summary, 1, 400) END AS summary,
           s.name AS source_name,
           CASE WHEN r.target_type = 'article' THEN x.category ELSE e.category END AS category,
           CASE WHEN r.target_type = 'article' THEN a.published_at ELSE e.last_published_at END AS published_at,
           CASE WHEN r.target_type = 'article' THEN ea.event_id ELSE e.id END AS event_id,
           CASE WHEN r.target_type = 'event' THEN e.article_count ELSE 0 END AS article_count,
           CASE WHEN r.target_type = 'event' THEN e.source_count ELSE 0 END AS source_count,
           CASE WHEN r.target_type = 'article' THEN a.reading_status = 'read' ELSE 0 END AS is_read,
           CASE WHEN r.target_type = 'article' THEN a.is_favorite ELSE 0 END AS is_favorite
    FROM recommendation_results AS r
    LEFT JOIN articles AS a ON r.target_type = 'article' AND a.id = r.target_id
    LEFT JOIN sources AS s ON s.id = a.source_id
    LEFT JOIN article_ai_analysis AS x ON x.id = (
        SELECT x2.id FROM article_ai_analysis x2 WHERE x2.article_id = a.id
        ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
    )
    LEFT JOIN event_articles AS ea ON r.target_type = 'article' AND ea.article_id = a.id
    LEFT JOIN events AS e ON e.id = r.target_id AND r.target_type = 'event'
"""


def get_current_result(
    conn: sqlite3.Connection, *, target_type: str, target_id: str
) -> RecommendationRecord | None:
    row = conn.execute(
        _RESULT_JOIN + " WHERE r.is_current = 1 AND r.target_type = ? AND r.target_id = ?",
        (target_type, target_id),
    ).fetchone()
    return None if row is None else _result_from_row(row)


def upsert_result(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    """Replace the current result for a target, preserving the row id."""

    target_type = str(values["target_type"])
    target_id = str(values["target_id"])
    row = conn.execute(
        "SELECT id FROM recommendation_results WHERE is_current = 1 "
        "AND target_type = ? AND target_id = ?",
        (target_type, target_id),
    ).fetchone()
    if row is None:
        columns = ", ".join(RESULT_COLUMNS)
        placeholders = ", ".join("?" for _ in RESULT_COLUMNS)
        conn.execute(
            f"INSERT INTO recommendation_results ({columns}) VALUES ({placeholders})",
            tuple(values[key] for key in RESULT_COLUMNS),
        )
        return
    payload = {key: values[key] for key in RESULT_COLUMNS if key not in {"id", "created_at"}}
    assignments = ", ".join(f"{key} = ?" for key in payload)
    conn.execute(
        f"UPDATE recommendation_results SET {assignments} WHERE id = ?",
        tuple(payload.values()) + (str(row["id"]),),
    )


def list_current_results(
    conn: sqlite3.Connection,
    *,
    limit: int,
    min_score: float = 0.0,
    target_type: str | None = None,
    exclude_read: bool = False,
) -> list[RecommendationRecord]:
    clause = "r.is_current = 1 AND r.score >= ?"
    params: list[object] = [min_score]
    if target_type:
        clause += " AND r.target_type = ?"
        params.append(target_type)
    if exclude_read:
        # 「稍后阅读」与「已读」都表示用户已经处理过，默认从今日流中移出。
        clause += " AND NOT (r.target_type = 'article' AND a.reading_status IN ('read','later'))"
    rows = conn.execute(
        _RESULT_JOIN + f" WHERE {clause} ORDER BY r.score DESC, r.updated_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [_result_from_row(row) for row in rows]


def list_results_for_explanation(
    conn: sqlite3.Connection, *, limit: int, offset: int
) -> tuple[list[RecommendationRecord], int]:
    rows = conn.execute(
        _RESULT_JOIN + " WHERE r.is_current = 1 ORDER BY r.score DESC, r.updated_at DESC "
        "LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) FROM recommendation_results WHERE is_current = 1"
    ).fetchone()
    return (
        [_result_from_row(row) for row in rows],
        int(total_row[0]) if total_row is not None else 0,
    )


def result_stats(conn: sqlite3.Connection) -> dict[str, object]:
    levels = {
        str(row["level"]): int(row["n"])
        for row in conn.execute(
            "SELECT level, COUNT(*) AS n FROM recommendation_results WHERE is_current = 1 "
            "GROUP BY level"
        ).fetchall()
    }
    targets = {
        str(row["target_type"]): int(row["n"])
        for row in conn.execute(
            "SELECT target_type, COUNT(*) AS n FROM recommendation_results WHERE is_current = 1 "
            "GROUP BY target_type"
        ).fetchall()
    }
    avg_row = conn.execute(
        "SELECT AVG(score) FROM recommendation_results WHERE is_current = 1"
    ).fetchone()
    return {
        "total": sum(levels.values()),
        "by_level": levels,
        "by_target_type": targets,
        "average_score": None if avg_row is None or avg_row[0] is None else round(float(avg_row[0]), 2),
    }


def inputs_version(conn: sqlite3.Connection) -> str:
    """Fingerprint of everything that can change a recommendation."""

    profile = conn.execute("SELECT updated_at FROM interest_profiles WHERE id = 1").fetchone()
    interests = conn.execute(
        "SELECT MAX(updated_at), COUNT(*) FROM interests"
    ).fetchone()
    keywords = conn.execute("SELECT MAX(created_at), COUNT(*) FROM interest_keywords").fetchone()
    entity_links = conn.execute(
        "SELECT MAX(created_at), COUNT(*) FROM interest_entity_links"
    ).fetchone()
    source_links = conn.execute(
        "SELECT MAX(created_at), COUNT(*) FROM interest_source_links"
    ).fetchone()
    blocked = conn.execute(
        "SELECT MAX(created_at), COUNT(*) FROM blocked_sources"
    ).fetchone()
    feedback = conn.execute(
        "SELECT MAX(COALESCE(revoked_at, created_at)), COUNT(*) FROM recommendation_feedback"
    ).fetchone()
    reader = conn.execute(
        "SELECT MAX(updated_at), "
        "SUM(CASE WHEN reading_status <> 'unread' OR is_favorite = 1 THEN 1 ELSE 0 END) "
        "FROM articles WHERE deleted_at IS NULL"
    ).fetchone()
    parts = [
        f"p:{profile[0] if profile else ''}",
        f"i:{interests[0] or ''}:{interests[1] if interests else 0}",
        f"k:{keywords[0] or ''}:{keywords[1] if keywords else 0}",
        f"e:{entity_links[0] or ''}:{entity_links[1] if entity_links else 0}",
        f"s:{source_links[0] or ''}:{source_links[1] if source_links else 0}",
        f"b:{blocked[0] or ''}:{blocked[1] if blocked else 0}",
        f"f:{feedback[0] or ''}:{feedback[1] if feedback else 0}",
        f"r:{reader[0] or ''}:{(reader[1] or 0) if reader else 0}",
    ]
    return "|".join(parts)


# ---------------------------------------------------------------------------
# Candidate features
# ---------------------------------------------------------------------------


def candidate_events(conn: sqlite3.Connection, *, since: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT e.id, e.title, e.summary, e.category, e.status, e.article_count,
               e.source_count, e.last_seen_at, e.updated_at, e.last_published_at,
               s.total_score, s.importance_score, s.heat_score
        FROM events e
        LEFT JOIN event_score_snapshots s ON s.event_id = e.id AND s.is_current = 1
        WHERE e.status NOT IN ('merged','archived')
          AND e.last_seen_at >= ?
          AND EXISTS (SELECT 1 FROM event_articles ea WHERE ea.event_id = e.id)
        ORDER BY COALESCE(s.total_score, 0) DESC, e.last_seen_at DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()


def candidate_articles(conn: sqlite3.Connection, *, since: str, limit: int) -> list[sqlite3.Row]:
    """Articles that are not in any event (independent leads)."""

    return conn.execute(
        """
        SELECT a.id, a.title, a.summary, a.source_id, s.name AS source_name,
               s.credibility_score, a.published_at, a.fetched_at, a.updated_at,
               a.reading_status, a.is_favorite,
               x.category AS ai_category, x.summary AS ai_summary
        FROM articles a
        JOIN sources s ON s.id = a.source_id AND s.deleted_at IS NULL
        LEFT JOIN article_ai_analysis x ON x.id = (
            SELECT x2.id FROM article_ai_analysis x2 WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE a.deleted_at IS NULL AND a.status = 'active'
          AND a.content_state <> 'unavailable'
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND NOT EXISTS (SELECT 1 FROM event_articles ea WHERE ea.article_id = a.id)
        ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()


def article_entity_rows(conn: sqlite3.Connection, article_ids: Sequence[str]) -> dict[str, list[sqlite3.Row]]:
    if not article_ids:
        return {}
    placeholders = ", ".join("?" for _ in article_ids)
    rows = conn.execute(
        f"""
        SELECT ae.article_id, ae.entity_id, e.canonical_name
        FROM article_entities ae JOIN entities e ON e.id = ae.entity_id
        WHERE ae.article_id IN ({placeholders})
        ORDER BY ae.confidence DESC
        """,
        tuple(article_ids),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["article_id"]), []).append(row)
    return grouped


def event_entity_rows(conn: sqlite3.Connection, event_ids: Sequence[str]) -> dict[str, list[sqlite3.Row]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT ee.event_id, ee.entity_id, e.canonical_name
        FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        WHERE ee.event_id IN ({placeholders})
        ORDER BY ee.article_count DESC
        """,
        tuple(event_ids),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["event_id"]), []).append(row)
    return grouped


def event_members(conn: sqlite3.Connection, event_ids: Sequence[str]) -> dict[str, list[sqlite3.Row]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT ea.event_id, ea.article_id, a.title, a.summary, a.published_at, a.source_id,
               s.name AS source_name, s.credibility_score,
               x.category AS ai_category, x.summary AS ai_summary
        FROM event_articles ea
        JOIN articles a ON a.id = ea.article_id AND a.deleted_at IS NULL
        JOIN sources s ON s.id = a.source_id AND s.deleted_at IS NULL
        LEFT JOIN article_ai_analysis x ON x.id = (
            SELECT x2.id FROM article_ai_analysis x2 WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE ea.event_id IN ({placeholders})
        ORDER BY ea.added_at ASC, ea.id ASC
        """,
        tuple(event_ids),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["event_id"]), []).append(row)
    return grouped


def article_membership_rows(conn: sqlite3.Connection, article_ids: Sequence[str]) -> dict[str, str]:
    if not article_ids:
        return {}
    placeholders = ", ".join("?" for _ in article_ids)
    rows = conn.execute(
        f"SELECT article_id, event_id FROM event_articles WHERE article_id IN ({placeholders})",
        tuple(article_ids),
    ).fetchall()
    return {str(row["article_id"]): str(row["event_id"]) for row in rows}


def current_event_scores(conn: sqlite3.Connection, event_ids: Sequence[str]) -> dict[str, float]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"SELECT event_id, total_score FROM event_score_snapshots WHERE is_current = 1 "
        f"AND event_id IN ({placeholders})",
        tuple(event_ids),
    ).fetchall()
    return {str(row["event_id"]): float(row["total_score"]) for row in rows}


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


def _digest_from_row(row: sqlite3.Row) -> DigestRecord:
    return DigestRecord(
        id=str(row["id"]),
        digest_date=str(row["digest_date"]),
        timezone=str(row["timezone"]),
        status=str(row["status"]),
        ai_status=str(row["ai_status"]),
        headline=row["headline"],
        overview=row["overview"],
        stats=_json_object(row["stats_json"]),
        model_name=row["model_name"],
        model_digest=row["model_digest"],
        prompt_version=row["prompt_version"],
        digest_version=str(row["digest_version"]),
        generated_at=row["generated_at"],
        superseded_at=row["superseded_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _digest_item_from_row(row: sqlite3.Row) -> DigestItemRecord:
    return DigestItemRecord(
        id=str(row["id"]),
        digest_id=str(row["digest_id"]),
        section=str(row["section"]),
        rank=int(row["rank"]),
        target_type=str(row["target_type"]),
        target_id=row["target_id"],
        title=str(row["title"]),
        reason=row["reason"],
        matched_interests=_json_list(row["matched_interests_json"]),
        score=None if row["score"] is None else float(row["score"]),
        created_at=str(row["created_at"]),
    )


def get_digest(
    conn: sqlite3.Connection, *, digest_date: str, timezone: str
) -> DigestRecord | None:
    row = conn.execute(
        "SELECT * FROM daily_digests WHERE digest_date = ? AND timezone = ? "
        "AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1",
        (digest_date, timezone),
    ).fetchone()
    if row is None:
        return None
    items = conn.execute(
        "SELECT * FROM daily_digest_items WHERE digest_id = ? ORDER BY section, rank",
        (str(row["id"]),),
    ).fetchall()
    record = _digest_from_row(row)
    return replace(record, items=tuple(_digest_item_from_row(item) for item in items))


def get_digest_by_id(conn: sqlite3.Connection, digest_id: str) -> DigestRecord | None:
    row = conn.execute("SELECT * FROM daily_digests WHERE id = ?", (digest_id,)).fetchone()
    if row is None:
        return None
    items = conn.execute(
        "SELECT * FROM daily_digest_items WHERE digest_id = ? ORDER BY section, rank",
        (digest_id,),
    ).fetchall()
    record = _digest_from_row(row)
    return replace(record, items=tuple(_digest_item_from_row(item) for item in items))


def insert_digest(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(DIGEST_COLUMNS)
    placeholders = ", ".join("?" for _ in DIGEST_COLUMNS)
    conn.execute(
        f"INSERT INTO daily_digests ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in DIGEST_COLUMNS),
    )


def update_digest(
    conn: sqlite3.Connection, digest_id: str, fields: Mapping[str, object]
) -> None:
    allowed = set(DIGEST_COLUMNS) - {"id", "created_at"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown digest fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE daily_digests SET {assignments} WHERE id = ?",
        tuple(fields.values()) + (digest_id,),
    )


def supersede_digests(
    conn: sqlite3.Connection, *, digest_date: str, timezone: str, superseded_at: str
) -> int:
    cursor = conn.execute(
        "UPDATE daily_digests SET status = 'superseded', superseded_at = ?, updated_at = ? "
        "WHERE digest_date = ? AND timezone = ? AND status = 'succeeded'",
        (superseded_at, superseded_at, digest_date, timezone),
    )
    return int(cursor.rowcount or 0)


def insert_digest_item(conn: sqlite3.Connection, values: Mapping[str, object]) -> None:
    columns = ", ".join(DIGEST_ITEM_COLUMNS)
    placeholders = ", ".join("?" for _ in DIGEST_ITEM_COLUMNS)
    conn.execute(
        f"INSERT INTO daily_digest_items ({columns}) VALUES ({placeholders})",
        tuple(values[key] for key in DIGEST_ITEM_COLUMNS),
    )


def list_digests(
    conn: sqlite3.Connection, *, limit: int, offset: int
) -> tuple[list[DigestRecord], int]:
    rows = conn.execute(
        "SELECT * FROM daily_digests WHERE status = 'succeeded' "
        "ORDER BY digest_date DESC, created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) FROM daily_digests WHERE status = 'succeeded'"
    ).fetchone()
    return ([_digest_from_row(row) for row in rows], int(total_row[0]) if total_row is not None else 0)


__all__ = [
    "active_feedback",
    "active_feedback_map",
    "article_entity_rows",
    "article_membership_rows",
    "block_source",
    "blocked_source_ids",
    "candidate_articles",
    "candidate_events",
    "current_event_scores",
    "deactivate_event_result",
    "delete_interest",
    "event_entity_rows",
    "event_members",
    "feedback_counts_by_interest",
    "feedback_max_timestamp",
    "find_interest_by_name",
    "get_current_result",
    "get_digest",
    "get_digest_by_id",
    "get_interest",
    "get_profile",
    "inputs_version",
    "insert_digest",
    "insert_digest_item",
    "insert_feedback",
    "insert_interest",
    "link_entity",
    "link_source",
    "list_blocked_sources",
    "list_current_results",
    "list_digests",
    "list_feedback",
    "list_interests",
    "list_results_for_explanation",
    "replace_keywords",
    "result_stats",
    "revoke_feedback",
    "supersede_digests",
    "unblock_source",
    "unlink_entity",
    "unlink_source",
    "update_digest",
    "update_interest",
    "update_profile",
    "upsert_result",
]


def articles_by_ids(conn: sqlite3.Connection, article_ids: Sequence[str]) -> list[sqlite3.Row]:
    if not article_ids:
        return []
    placeholders = ", ".join("?" for _ in article_ids)
    return conn.execute(
        f"""
        SELECT a.id, a.title, a.summary, a.source_id, s.name AS source_name,
               s.credibility_score, a.published_at, a.fetched_at, a.updated_at,
               a.reading_status, a.is_favorite,
               x.category AS ai_category, x.summary AS ai_summary
        FROM articles a
        JOIN sources s ON s.id = a.source_id AND s.deleted_at IS NULL
        LEFT JOIN article_ai_analysis x ON x.id = (
            SELECT x2.id FROM article_ai_analysis x2 WHERE x2.article_id = a.id
            ORDER BY x2.created_at DESC, x2.id DESC LIMIT 1
        )
        WHERE a.deleted_at IS NULL AND a.status = 'active' AND a.id IN ({placeholders})
        """,
        tuple(article_ids),
    ).fetchall()


def events_by_ids(conn: sqlite3.Connection, event_ids: Sequence[str]) -> list[sqlite3.Row]:
    if not event_ids:
        return []
    placeholders = ", ".join("?" for _ in event_ids)
    return conn.execute(
        f"""
        SELECT e.id, e.title, e.summary, e.category, e.status, e.article_count,
               e.source_count, e.last_seen_at, e.updated_at, e.last_published_at,
               s.total_score, s.importance_score, s.heat_score
        FROM events e
        LEFT JOIN event_score_snapshots s ON s.event_id = e.id AND s.is_current = 1
        WHERE e.id IN ({placeholders})
        """,
        tuple(event_ids),
    ).fetchall()


def article_exists(conn: sqlite3.Connection, article_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM articles WHERE id = ? AND deleted_at IS NULL", (article_id,)
    ).fetchone()
    return row is not None


def event_exists(conn: sqlite3.Connection, event_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone()
    return row is not None


def entity_exists(conn: sqlite3.Connection, entity_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return row is not None


def source_exists(conn: sqlite3.Connection, source_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sources WHERE id = ? AND deleted_at IS NULL", (source_id,)
    ).fetchone()
    return row is not None


def counts_today(conn: sqlite3.Connection, *, since: str) -> dict[str, int]:
    articles = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL AND COALESCE(published_at, fetched_at) >= ?",
        (since,),
    ).fetchone()
    events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status NOT IN ('merged','archived') AND last_seen_at >= ?",
        (since,),
    ).fetchone()
    return {
        "articles": int(articles[0]) if articles else 0,
        "events": int(events[0]) if events else 0,
    }


def get_feedback(conn: sqlite3.Connection, feedback_id: str) -> FeedbackRecord | None:
    row = conn.execute(
        "SELECT * FROM recommendation_feedback WHERE id = ?", (feedback_id,)
    ).fetchone()
    return None if row is None else _feedback_from_row(row)


def deactivate_event_result(
    conn: sqlite3.Connection, event_id: str, *, now: str
) -> int:
    """Deactivate the current recommendation of an event that was merged away."""

    cursor = conn.execute(
        "UPDATE recommendation_results SET is_current = 0, updated_at = ? "
        "WHERE is_current = 1 AND target_type = 'event' AND target_id = ?",
        (now, event_id),
    )
    return int(cursor.rowcount or 0)


def deactivate_excluded_results(conn: sqlite3.Connection, *, now: str) -> int:
    """Drop current article results that must not appear in the feed anymore."""

    blocked = conn.execute(
        """
        UPDATE recommendation_results SET is_current = 0, updated_at = ?
        WHERE is_current = 1 AND target_type = 'article' AND target_id IN (
            SELECT a.id FROM articles a JOIN blocked_sources b ON b.source_id = a.source_id
        )
        """,
        (now,),
    ).rowcount
    joined = conn.execute(
        """
        UPDATE recommendation_results SET is_current = 0, updated_at = ?
        WHERE is_current = 1 AND target_type = 'article' AND target_id IN (
            SELECT article_id FROM event_articles
        )
        """,
        (now,),
    ).rowcount
    return int(blocked or 0) + int(joined or 0)
