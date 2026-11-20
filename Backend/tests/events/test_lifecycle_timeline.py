"""Stage 4.3 — lifecycle transitions and the event timeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import database
from event_intelligence.lifecycle import next_status, transition_reason
from services.event_service import EventService

from event_support import (
    create_article,
    create_source,
    event_row,
    list_events,
    run_clustering,
    seed_article,
    stamp,
    timeline,
)

CASE_ARTICLES = [
    dict(
        title="星河科技第三季度财报：营收同比增长两成",
        category="科技",
        summary="星河科技公布第三季度财报。",
        keywords=["财报", "营收"],
        entities=[("星河科技", "organization"), ("第三季度财报", "event")],
        source_name="财经日报",
    ),
    dict(
        title="星河科技发布三季度财报 净利润超预期",
        category="科技",
        summary="星河科技三季度财报净利润超出预期。",
        keywords=["财报", "营收"],
        entities=[("星河科技", "organization"), ("第三季度财报", "event")],
        source_name="科技观察",
    ),
    dict(
        title="星河科技 Q3 财报显示营收增长 20%",
        category="科技",
        summary="星河科技 Q3 财报营收增长。",
        keywords=["财报", "营收"],
        entities=[("星河科技", "organization"), ("第三季度财报", "event")],
        source_name="商业周刊",
    ),
]


def _seed_case(days: list[float] | None = None) -> list[str]:
    days = days or [0.3, 0.2, 0.1]
    return [
        seed_article(
            title=item["title"],
            category=item["category"],
            summary=item["summary"],
            keywords=item["keywords"],
            entities=item["entities"],
            source_name=item["source_name"],
            published_at=stamp(days[index]),
        ).article_id
        for index, item in enumerate(CASE_ARTICLES)
    ]


def test_candidate_becomes_active_with_second_article(ready) -> None:
    _seed_case()
    run_clustering(scope="incremental")
    events = list_events()
    assert len(events) == 1
    assert events[0]["status"] == "active"


def test_timeline_records_each_report_with_real_timestamps(ready) -> None:
    article_ids = _seed_case()
    run_clustering(scope="incremental")
    event = list_events()[0]
    items = timeline(str(event["id"]))

    assert items[0]["kind"] == "first_report"
    report_items = [item for item in items if item["article_id"] is not None]
    assert {item["article_id"] for item in report_items} == set(article_ids)
    for item in report_items:
        assert item["published_at"] is not None
        assert item["recognized_at"] is not None
        # Event occurrence time is never fabricated from publication time.
        assert item["occurred_at"] is None

    status_changes = [item for item in items if item["kind"] == "status_change"]
    assert status_changes
    assert any("candidate" in item["title"] and "active" in item["title"]
               for item in status_changes)


def test_key_development_detected_when_new_entities_appear(ready) -> None:
    _seed_case()
    seed_article(
        title="星河科技三季度财报电话会：新任 CFO 出席",
        category="科技",
        summary="新任首席财务官出席财报电话会。",
        keywords=["财报", "电话会"],
        entities=[
            ("星河科技", "organization"),
            ("第三季度财报", "event"),
            ("王敏", "person"),
        ],
        source_name="财经日报",
        published_at=stamp(0.05),
    )
    run_clustering(scope="incremental")
    event = list_events()[0]
    key_items = [item for item in timeline(str(event["id"])) if item["is_key"] == 1]
    assert any("王敏" not in (item["title"] or "") or item["kind"] == "follow_up"
               for item in key_items)
    latest = timeline(str(event["id"]))[-1]
    assert latest["is_key"] == 1


def test_manual_close_is_never_overridden_by_clustering(ready) -> None:
    _seed_case()
    run_clustering(scope="incremental")
    event = list_events()[0]
    service = EventService()
    service.patch(str(event["id"]), title=None, summary=None, category=None,
                  status="closed", status_reason="人工确认结束")

    seed_article(
        title="星河科技第三季度财报补充说明",
        category="科技",
        summary="补充说明。",
        keywords=["财报", "营收"],
        entities=[("星河科技", "organization"), ("第三季度财报", "event")],
        source_name="商业周刊",
        published_at=stamp(0.0),
    )
    run_clustering(scope="incremental")

    with database.read_session() as conn:
        row = conn.execute(
            "SELECT status FROM events WHERE id = ?", (str(event["id"]),)
        ).fetchone()
    assert row is not None and str(row[0]) == "closed"


def test_manual_note_appends_to_timeline(ready) -> None:
    _seed_case()
    run_clustering(scope="incremental")
    event = list_events()[0]
    occurred = stamp(1.0)
    EventService().add_note(
        str(event["id"]),
        title="记者会补充",
        description="管理层将在下周召开记者会。",
        occurred_at=occurred,
    )
    items = timeline(str(event["id"]))
    notes = [item for item in items if item["kind"] == "manual_note"]
    assert len(notes) == 1
    assert notes[0]["occurred_at"] == occurred


@pytest.mark.parametrize(
    ("current", "articles", "first_days", "last_days", "new_article", "expected"),
    [
        ("candidate", 1, 1.0, 0.5, True, "candidate"),
        ("candidate", 2, 1.0, 0.5, True, "active"),
        ("active", 3, 5.0, 0.5, True, "evolving"),
        ("active", 3, 5.0, 16.0, True, "dormant"),
        ("active", 3, 5.0, 20.0, False, "dormant"),
        ("evolving", 3, 5.0, 16.0, True, "dormant"),
        ("evolving", 3, 5.0, 4.0, False, "active"),
        ("dormant", 3, 5.0, 2.0, True, "active"),
        ("dormant", 3, 5.0, 20.0, False, "dormant"),
        ("closed", 3, 5.0, 0.1, True, "closed"),
        ("merged", 3, 5.0, 0.1, True, "merged"),
        ("archived", 3, 5.0, 0.1, True, "archived"),
    ],
)
def test_lifecycle_transition_table(
    current: str, articles: int, first_days: float, last_days: float,
    new_article: bool, expected: str
) -> None:
    now = datetime.now(timezone.utc)
    status = next_status(
        current,
        article_count=articles,
        first_seen_at=(now - timedelta(days=first_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        last_published_at=(now - timedelta(days=last_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        now=now,
        new_article=new_article,
    )
    assert status == expected
    if status != current:
        assert transition_reason(current, status)


def test_inactivity_only_marks_dormant_not_closed() -> None:
    now = datetime.now(timezone.utc)
    status = next_status(
        "active",
        article_count=2,
        first_seen_at="2026-01-01T00:00:00.000Z",
        last_published_at="2026-01-02T00:00:00.000Z",
        now=now,
        new_article=False,
    )
    assert status == "dormant"


def test_removing_article_cleans_timeline_and_keeps_last_member(ready) -> None:
    """Regression for P4-10: removed articles must not linger in the timeline,
    and an event can never be left with zero articles."""

    from services.errors import ServiceError

    source_id = create_source("移出测试来源")
    first = create_article(
        source_id=source_id,
        title="事件第一篇",
        published_at=stamp(0.2),
        summary="第一篇摘要",
    )
    second = create_article(
        source_id=source_id,
        title="事件第二篇",
        published_at=stamp(0.1),
        summary="第二篇摘要",
    )
    service = EventService()
    event = service.create_event(
        title="移出文章事件", category="科技", summary="摘要", article_ids=[first, second]
    )
    nodes = [item for item in timeline(event.id) if item["article_id"]]
    assert nodes
    target_article = str(nodes[0]["article_id"])
    other_article = second if target_article == first else first

    service.remove_article(event.id, target_article)
    remaining = timeline(event.id)
    assert all(item["article_id"] != target_article for item in remaining)

    with pytest.raises(ServiceError) as excinfo:
        service.remove_article(event.id, other_article)
    assert excinfo.value.code == "event_last_article"
    assert int(event_row(event.id)["article_count"]) == 1
