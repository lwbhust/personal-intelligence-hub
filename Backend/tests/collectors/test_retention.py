"""Article retention policy: soft delete, protections, dry run."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import database
from core.timeutil import utc_timestamp
from database.repositories import article_repository as article_repo
from database.repositories import source_repository as source_repo
from services.retention_service import prune_articles

SOURCE_START = "2026-11-16T08:00:00.000Z"


@pytest.fixture()
def data_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIH_ARTICLE_RETENTION_DAYS", "30")
    status = database.initialize()
    assert status.status == "ok"
    return tmp_path / "data"


def _iso(days_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _add_source() -> str:
    source_id = str(uuid.uuid4())
    with database.session() as conn:
        source_repo.insert(
            conn,
            {
                "id": source_id,
                "category_id": None,
                "name": "Retention Feed",
                "source_type": "rss",
                "url": "https://example.com/retention.xml",
                "homepage_url": None,
                "description": None,
                "language": "en",
                "country": None,
                "priority": 0,
                "credibility_score": None,
                "fetch_interval_minutes": 60,
                "max_entries_per_fetch": None,
                "enabled": 1,
                "health_status": "unknown",
                "created_at": SOURCE_START,
                "updated_at": SOURCE_START,
            },
        )
    return source_id


def _add_article(
    source_id: str,
    *,
    days_ago: float,
    favorite: bool = False,
    reading_status: str = "unread",
) -> str:
    article_id = str(uuid.uuid4())
    now = utc_timestamp()
    with database.session() as conn:
        article_repo.insert(
            conn,
            {
                "id": article_id,
                "source_id": source_id,
                "external_id": uuid.uuid4().hex,
                "canonical_url": f"https://example.com/{article_id}",
                "original_url": f"https://example.com/{article_id}",
                "title": f"Article {article_id[:8]}",
                "author": None,
                "summary": "summary",
                "content_text": "body",
                "content_state": "full",
                "published_at": _iso(days_ago),
                "source_updated_at": None,
                "fetched_at": now,
                "content_hash": uuid.uuid4().hex * 2,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            "UPDATE articles SET is_favorite = ?, reading_status = ? WHERE id = ?",
            (1 if favorite else 0, reading_status, article_id),
        )
    return article_id


def _attach_event(article_id: str) -> None:
    event_id = str(uuid.uuid4())
    now = utc_timestamp()
    with database.session() as conn:
        conn.execute(
            "INSERT INTO events (id, title, first_seen_at, last_seen_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, "Retention event", now, now, now, now),
        )
        conn.execute(
            "INSERT INTO event_articles (id, event_id, article_id, added_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), event_id, article_id, now, now),
        )


def _deleted(article_id: str) -> bool:
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT deleted_at FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
    return row is not None and row[0] is not None


def test_prune_keeps_fresh_and_protected_articles(data_env: Path) -> None:
    source_id = _add_source()
    stale = _add_article(source_id, days_ago=40)
    fresh = _add_article(source_id, days_ago=1)
    favorite = _add_article(source_id, days_ago=40, favorite=True)
    later = _add_article(source_id, days_ago=40, reading_status="later")
    evidence = _add_article(source_id, days_ago=40)
    _attach_event(evidence)

    report = prune_articles()

    assert report["candidates"] == 1
    assert report["deleted"] == 1
    assert _deleted(stale)
    assert not _deleted(fresh)
    assert not _deleted(favorite)
    assert not _deleted(later)
    assert not _deleted(evidence)


def test_dry_run_reports_candidates_without_writing(data_env: Path) -> None:
    source_id = _add_source()
    stale = _add_article(source_id, days_ago=40)

    report = prune_articles(dry_run=True)

    assert report["candidates"] == 1
    assert report["deleted"] == 0
    assert not _deleted(stale)
