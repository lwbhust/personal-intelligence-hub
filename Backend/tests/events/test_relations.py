"""Stage 4.4 — evidence-backed event relations."""

from __future__ import annotations

import json

import pytest

import database
from services.errors import ServiceError
from services.event_service import EventService

from event_support import (
    audit_actions,
    event_article_ids,
    event_row,
    list_events,
    relations,
    run_clustering,
    seed_article,
    stamp,
    timeline,
)

AUTO_TYPES = {"related_to", "follows", "same_topic"}
FORBIDDEN_AUTO = {"caused_by", "part_of", "contradicts"}


def _seed_two_events() -> tuple[str, str, str, str]:
    first = seed_article(
        title="银河控股宣布年度分红方案",
        category="财经",
        summary="银河控股宣布年度分红方案。",
        keywords=["控股", "分红"],
        entities=[("银河控股", "organization"), ("年度分红方案", "event")],
        source_name="财经日报",
        published_at=stamp(4.0),
    )
    second = seed_article(
        title="银河控股发布新款折叠屏手机",
        category="财经",
        summary="银河控股发布新款折叠屏手机。",
        keywords=["控股", "手机"],
        entities=[("银河控股", "organization"), ("折叠屏手机发布", "event")],
        source_name="科技观察",
        published_at=stamp(1.0),
    )
    run_clustering(scope="incremental")
    events = list_events()
    assert len(events) == 2
    return str(events[0]["id"]), str(events[1]["id"]), first.article_id, second.article_id


def test_automatic_relations_are_candidate_only(ready) -> None:
    _seed_two_events()
    rows = relations()
    assert rows
    assert {str(row["relation_type"]) for row in rows} <= AUTO_TYPES
    assert not ({str(row["relation_type"]) for row in rows} & FORBIDDEN_AUTO)
    for row in rows:
        assert str(row["status"]) == "candidate"
        assert str(row["actor"]) == "algorithm"
        assert str(row["algorithm_version"]) == "event-relation-v1"
        assert 0.0 <= float(row["confidence"]) <= 1.0
        assert row["rationale"]


def test_relations_carry_evidence_articles_from_both_events(ready) -> None:
    left, right, left_article, right_article = _seed_two_events()
    allowed = {left_article, right_article}
    rows = relations()
    same_topic = [row for row in rows if row["relation_type"] == "same_topic"]
    assert same_topic
    import json

    for row in rows:
        evidence = set(json.loads(row["evidence_article_ids_json"]))
        assert evidence
        assert evidence <= allowed


def test_follows_is_directed_from_earlier_to_later(ready) -> None:
    _seed_two_events()
    rows = [row for row in relations() if row["relation_type"] == "follows"]
    assert rows
    events = {str(item["id"]): item for item in list_events()}
    for row in rows:
        source = events[str(row["source_event_id"])]
        target = events[str(row["target_event_id"])]
        assert str(source["first_published_at"]) < str(target["first_published_at"])


def test_manual_cause_requires_evidence(ready) -> None:
    left, right, left_article, right_article = _seed_two_events()
    service = EventService()

    with pytest.raises(ServiceError) as excinfo:
        service.add_relation(
            left,
            target_event_id=right,
            relation_type="caused_by",
            rationale="无证据",
            evidence_article_ids=["00000000-0000-4000-8000-000000000000"],
        )
    assert excinfo.value.code == "relation_evidence_invalid"

    relation = service.add_relation(
        left,
        target_event_id=right,
        relation_type="caused_by",
        rationale="分红方案导致手机业务调整",
        evidence_article_ids=[left_article, right_article],
    )
    assert relation.status == "confirmed"
    assert relation.actor == "manual"
    assert set(relation.evidence_article_ids) == {left_article, right_article}


def test_manual_relation_cannot_duplicate_or_self_link(ready) -> None:
    left, right, left_article, right_article = _seed_two_events()
    service = EventService()
    service.add_relation(
        left,
        target_event_id=right,
        relation_type="contradicts",
        rationale="事实冲突",
        evidence_article_ids=[left_article, right_article],
    )
    with pytest.raises(ServiceError) as excinfo:
        service.add_relation(
            left,
            target_event_id=right,
            relation_type="contradicts",
            rationale="重复",
            evidence_article_ids=[left_article],
        )
    assert excinfo.value.code == "event_relation_conflict"

    with pytest.raises(ServiceError) as self_exc:
        service.add_relation(
            left,
            target_event_id=left,
            relation_type="related_to",
            rationale=None,
            evidence_article_ids=[],
        )
    assert self_exc.value.code == "invalid_request"


def test_relation_status_can_be_confirmed_or_rejected(ready) -> None:
    _seed_two_events()
    rows = relations()
    algorithm_row = rows[0]
    service = EventService()
    updated = service.update_relation(
        str(algorithm_row["source_event_id"]),
        str(algorithm_row["id"]),
        status="confirmed",
    )
    assert updated.status == "confirmed"

    other = rows[1]
    rejected = service.update_relation(
        str(other["target_event_id"]),
        str(other["id"]),
        status="rejected",
    )
    assert rejected.status == "rejected"

    with database.read_session() as conn:
        actions = [row[0] for row in conn.execute(
            "SELECT action FROM event_audit_log WHERE action = 'update_relation'"
        )]
    assert len(actions) == 2


def test_merge_keeps_relation_records_valid(ready) -> None:
    left, right, _, _ = _seed_two_events()
    service = EventService()
    service.add_relation(
        left,
        target_event_id=right,
        relation_type="part_of",
        rationale="属于更大事件",
        evidence_article_ids=[],
    )
    third = seed_article(
        title="银河控股年度总结",
        category="财经",
        summary="银河控股年度总结。",
        keywords=["年度", "总结"],
        entities=[("银河控股", "organization"), ("年度总结", "event")],
        source_name="财经日报",
        published_at=stamp(5.0),
    )
    service.create_event(
        title="临时事件",
        category="财经",
        summary="临时事件",
        article_ids=[third.article_id],
    )
    events = list_events()
    target = next(item for item in events if str(item["id"]) == left)
    source = next(item for item in events if str(item["id"]) not in {left, right})

    service.merge(str(source["id"]), str(target["id"]), "测试合并")
    with database.read_session() as conn:
        rows = conn.execute("SELECT source_event_id, target_event_id FROM event_relations").fetchall()
        dangling = conn.execute(
            "SELECT COUNT(*) FROM event_relations r "
            "LEFT JOIN events s ON s.id = r.source_event_id "
            "LEFT JOIN events t ON t.id = r.target_event_id "
            "WHERE s.id IS NULL OR t.id IS NULL"
        ).fetchone()[0]
    assert int(dangling) == 0
    assert rows


def test_merge_can_be_undone_with_restored_membership(ready) -> None:
    left, right, left_article, right_article = _seed_two_events()
    source_before = set(event_article_ids(left))
    target_before = set(event_article_ids(right))
    timeline_before = {item["id"] for item in timeline(left)}
    status_before = str(event_row(left)["status"])

    service = EventService()
    service.merge(left, right, "测试合并")
    assert event_row(left)["status"] == "merged"
    assert set(event_article_ids(right)) == source_before | target_before
    for item in timeline(left):
        assert item["event_id"] == right

    restored = service.unmerge(left)
    assert restored.id == left
    assert event_row(left)["status"] == status_before
    assert event_row(left)["merged_into_event_id"] is None
    assert set(event_article_ids(left)) == source_before
    assert set(event_article_ids(right)) == target_before
    assert {item["id"] for item in timeline(left)} >= timeline_before
    assert "unmerge_events" in audit_actions(left)
    assert "merge_events" in audit_actions(right)

    with pytest.raises(ServiceError) as excinfo:
        service.unmerge(left)
    assert excinfo.value.code == "event_not_merged"


def test_relation_evidence_is_bounded(ready) -> None:
    """Regression for P4-17: oversized evidence lists are rejected before the
    DB CHECK constraint can raise an internal error."""

    left, right, *_ = _seed_two_events()
    service = EventService()
    with pytest.raises(ServiceError) as excinfo:
        service.add_relation(
            left,
            target_event_id=right,
            relation_type="related_to",
            rationale="证据过多",
            evidence_article_ids=[f"article-{index}" for index in range(51)],
        )
    assert excinfo.value.code == "relation_evidence_invalid"


def test_large_merge_can_be_undone_after_audit_chunking(ready) -> None:
    """Regression for P4-03: merge audits must stay valid JSON for merges whose
    ID lists exceed the audit row size, otherwise unmerge fails."""

    from event_support import create_article, create_source

    source_id = create_source("大事件来源")
    articles = [
        create_article(
            source_id=source_id,
            title=f"大事件报道 {index}",
            published_at=stamp(0.01 * index),
            summary=f"大事件报道摘要 {index}",
        )
        for index in range(300)
    ]
    service = EventService()
    event_a = service.create_event(
        title="事件A", category="科技", summary="A", article_ids=articles[:100]
    )
    event_b = service.create_event(
        title="事件B", category="科技", summary="B", article_ids=articles[100:200]
    )
    event_c = service.create_event(
        title="事件C", category="科技", summary="C", article_ids=articles[200:300]
    )
    service.merge(event_b.id, event_a.id, "合并B到A")
    service.merge(event_a.id, event_c.id, "合并A到C")

    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT detail_json FROM event_audit_log "
            "WHERE event_id = ? AND action = 'merge_events'",
            (event_c.id,),
        ).fetchall()
    for row in rows:
        assert isinstance(json.loads(str(row[0])), dict)

    restored = service.unmerge(event_a.id)
    assert restored.id == event_a.id
    assert int(event_row(event_a.id)["article_count"]) == 200
    assert set(event_article_ids(event_a.id)) == set(articles[:200])
    assert int(event_row(event_c.id)["article_count"]) == 100
    assert "unmerge_events" in audit_actions(event_a.id)
