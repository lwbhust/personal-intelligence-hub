"""Dashboard trend/overview use publication dates and expose zero days."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import database
from core.timeutil import utc_timestamp
from services.dashboard_service import articles_trend, overview


def _ts(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _day(days_ago: int, *, hour: int = 9) -> str:
    day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return _ts(datetime.combine(day, time(hour=hour), tzinfo=timezone.utc))


def _seed_articles(specs: list[tuple[str | None, str]]) -> None:
    """Insert (published_at, fetched_at) pairs under one real source."""

    now = utc_timestamp()
    with database.session() as conn:
        source_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO sources (
                id, category_id, name, source_type, url, homepage_url, description,
                language, country, priority, credibility_score,
                fetch_interval_minutes, enabled, health_status, created_at, updated_at
            ) VALUES (?, NULL, '趋势来源', 'rss', ?, NULL, NULL, 'zh', NULL, 10,
                      NULL, 60, 1, 'unknown', ?, ?)
            """,
            (source_id, f"https://{source_id[:8]}.example.com/feed.xml", now, now),
        )
        for index, (published, fetched) in enumerate(specs):
            article_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO articles (
                    id, source_id, external_id, canonical_url, original_url, title,
                    author, summary, content_text, content_state, published_at,
                    source_updated_at, fetched_at, content_hash, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, 'summary_only',
                          ?, NULL, ?, ?, 'active', ?, ?)
                """,
                (
                    article_id,
                    source_id,
                    f"ext-{index}-{article_id[:8]}",
                    f"趋势测试文章 {index}",
                    published,
                    fetched,
                    uuid.uuid4().hex * 2,
                    now,
                    now,
                ),
            )


def test_trend_uses_publish_date_and_fills_zero_days(ready):
    _seed_articles(
        [
            (_day(0), _day(0, hour=3)),
            (_day(1), _day(1, hour=3)),
            (_day(1, hour=10), _day(1, hour=11)),
            (_day(5), _day(5, hour=4)),
            # No published_at: the fetch date must be the fallback.
            (None, _day(2, hour=4)),
        ]
    )
    with database.read_session() as conn:
        points = articles_trend(conn, days=14)

    assert len(points) == 14
    days = [point["day"] for point in points]
    assert days == sorted(days)
    today = datetime.now(timezone.utc).date()
    assert days[-1] == today.isoformat()
    assert days[0] == (today - timedelta(days=13)).isoformat()

    counts = {point["day"]: point["count"] for point in points}
    assert counts[today.isoformat()] == 1
    assert counts[(today - timedelta(days=1)).isoformat()] == 2
    assert counts[(today - timedelta(days=2)).isoformat()] == 1
    assert counts[(today - timedelta(days=5)).isoformat()] == 1
    # Empty days are present with real zeros, not omitted.
    assert counts[(today - timedelta(days=3)).isoformat()] == 0
    assert sum(counts.values()) == 5


def test_overview_counts_follow_publish_date(ready):
    _seed_articles(
        [
            (_day(0), _day(0)),
            (None, _day(0)),
            (_day(1), _day(1)),
            (_day(8), _day(8)),
        ]
    )
    with database.read_session() as conn:
        data = overview(conn)

    articles = data["articles"]
    assert articles["total"] == 4
    assert articles["today"] == 2
    assert articles["last_7_days"] == 3
