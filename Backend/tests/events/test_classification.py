"""Event classification consistency: dry run, apply, audits and manual protection."""

from __future__ import annotations

import uuid

import sqlite3

import database
from core.timeutil import utc_timestamp
from database import session as write_session
from services.classification_service import (
    apply_suggestions,
    article_category_mapping,
    refresh_event_category,
    suggest_for_events,
)

from event_support import create_analysis, create_article, create_source


def _insert_event(*, category: str, category_source: str = "legacy") -> str:
    event_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO events (
                id, title, summary, category, status, status_reason, first_seen_at,
                last_seen_at, first_published_at, last_published_at, occurred_at,
                article_count, source_count, is_manual, merged_into_event_id,
                algorithm_version, title_source, summary_source, created_at, updated_at,
                category_source
            ) VALUES (?, '测试事件', '事件摘要', ?, 'candidate', '测试', ?, ?, NULL,
                      NULL, NULL, 0, 0, 0, NULL, 'event-cluster-v1', 'auto', 'auto', ?, ?, ?)
            """,
            (event_id, category, now, now, now, now, category_source),
        )
    return event_id


def _attach(event_id: str, article_id: str, *, role: str = "report") -> None:
    now = utc_timestamp()
    with write_session() as conn:
        conn.execute(
            """
            INSERT INTO event_articles (
                id, event_id, article_id, role, similarity, match_reasons_json,
                is_manual, added_at, created_at
            ) VALUES (?, ?, ?, ?, NULL, '[]', 0, ?, ?)
            """,
            (str(uuid.uuid4()), event_id, article_id, role, now, now),
        )


def _event(event_id: str) -> sqlite3.Row:
    with database.read_session() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row is not None
    return row


def _make_article(category: str) -> str:
    source_id = create_source("分类测试源")
    article_id = create_article(
        source_id=source_id, title=f"文章-{uuid.uuid4().hex[:6]}", summary="足够长的摘要内容用于分类测试。"
    )
    create_analysis(
        article_id=article_id,
        category=category,
        summary="分类测试摘要",
        keywords=["分类", "测试", "事件"],
        entities=[("测试机构", "organization")],
    )
    return article_id


def test_legacy_stale_event_is_corrected_with_audit(ready) -> None:
    event_id = _insert_event(category="其他")
    _attach(event_id, _make_article("科技"))

    with database.read_session() as conn:
        suggestions, total = suggest_for_events(conn, limit=10, offset=0)
    match = next(item for item in suggestions if item.event_id == event_id)
    assert match.suggested_category == "科技"
    assert total >= 1

    with database.session() as conn:
        result = apply_suggestions(conn, event_ids=[event_id], limit=10, now=utc_timestamp())
    assert result["changed_events"] == 1

    row = _event(event_id)
    assert row["category"] == "科技"
    assert row["category_source"] == "auto"
    assert row["category_reason"]
    with database.read_session() as conn:
        audit = conn.execute(
            "SELECT action, detail_json FROM event_audit_log WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert audit is not None
    assert audit["action"] == "recategorize_event"


def test_manual_category_is_never_overwritten(ready) -> None:
    event_id = _insert_event(category="文化", category_source="manual")
    _attach(event_id, _make_article("科技"))

    with database.session() as conn:
        result = apply_suggestions(conn, event_ids=[event_id], limit=10, now=utc_timestamp())

    assert result["protected_events"] == 1
    assert result["changed_events"] == 0
    row = _event(event_id)
    assert row["category"] == "文化"
    assert row["category_source"] == "manual"


def test_event_without_analysis_stays_unresolved(ready) -> None:
    event_id = _insert_event(category="其他")
    source_id = create_source("无分析来源")
    article_id = create_article(
        source_id=source_id, title="未分析文章", summary="摘要足够长但没有 AI 分析结果。"
    )
    _attach(event_id, article_id)

    with database.session() as conn:
        refresh_event_category(conn, event_id, now=utc_timestamp())

    row = _event(event_id)
    assert row["category"] == "其他"
    assert row["category_source"] == "unresolved"
    assert "待确认" in str(row["category_reason"])


def test_article_mapping_covers_all_stored_categories(ready) -> None:
    source_id = create_source("映射来源")
    article_id = create_article(
        source_id=source_id,
        title="映射文章",
        summary="足够长的摘要内容，用于验证分类映射统计。",
    )
    create_analysis(
        article_id=article_id,
        category="科技",
        summary="映射测试摘要",
        keywords=["映射", "测试", "分类"],
        entities=[("映射机构", "organization")],
    )
    with database.read_session() as conn:
        mapping = article_category_mapping(conn)
    assert mapping["taxonomy_version"] == "taxonomy-v1"
    assert mapping["unmapped_articles"] == 0
    assert mapping["items"]
    assert all(item["known"] is True for item in mapping["items"])
