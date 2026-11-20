"""Stage 4.2 — event candidate detection and deterministic clustering quality."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

import database

from event_support import (
    article_event,
    event_article_ids,
    list_events,
    run_clustering,
    seed_article,
    stamp,
)

FIXTURE = Path(__file__).parent / "fixtures" / "clustering_cases.json"


def load_cases() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


CASES = load_cases()
CASE_IDS = [case["id"] for case in CASES]


def seed_case(case: dict[str, object]):
    seeded = []
    for item in case["articles"]:  # type: ignore[union-attr]
        seeded.append(
            seed_article(
                title=str(item["title"]),
                category=str(item["category"]),
                summary=str(item["summary"]),
                keywords=list(item["keywords"]),
                entities=[tuple(pair) for pair in item["entities"]],
                source_name=str(item["source"]),
                published_at=stamp(float(item.get("days_ago", 0.0))),
                content_hash=item.get("content_hash"),
            )
        )
    return seeded


def article_events(article_ids: list[str]) -> dict[str, str | None]:
    if not article_ids:
        return {}
    placeholders = ", ".join("?" for _ in article_ids)
    with database.read_session() as conn:
        rows = conn.execute(
            f"SELECT article_id, event_id FROM event_articles "
            f"WHERE article_id IN ({placeholders})",
            tuple(article_ids),
        ).fetchall()
    mapping = {str(row["article_id"]): str(row["event_id"]) for row in rows}
    return {article_id: mapping.get(article_id) for article_id in article_ids}


def partition(article_ids: list[str]) -> dict[str, str]:
    assigned = article_events(article_ids)
    return {
        article_id: (event_id or f"singleton:{index}")
        for index, (article_id, event_id) in enumerate(assigned.items())
    }


def pending_decisions() -> list[dict[str, object]]:
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT article_id, candidate_event_id, decision, status, reasons_json "
            "FROM event_candidate_decisions WHERE status = 'pending'"
        ).fetchall()
    return [dict(row) for row in rows]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_clustering_case(ready, case: dict[str, object]) -> None:
    seeded = seed_case(case)
    article_ids = [item.article_id for item in seeded]

    run = run_clustering(scope="incremental")
    assert run.status == "succeeded", run.error_message
    assert run.requested_count == len(article_ids)
    assert run.processed_count == len(article_ids)

    groups = list(case["groups"])  # type: ignore[arg-type]
    assignment = partition(article_ids)

    # Articles in the same gold group must never be split across two events
    # when the case requires a merge, and articles in different gold groups
    # must never share an event (no false merge) in every case.
    by_group: dict[int, set[str]] = defaultdict(set)
    for index, group in enumerate(groups):
        by_group[int(group)].add(assignment[article_ids[index]])

    if case["expect"] == "same_event":
        assert len(set(assignment.values())) == 1, assignment
        assert len(by_group) == 1
    else:
        event_ids = [next(iter(values)) for values in by_group.values()]
        assert len(set(event_ids)) == len(event_ids), assignment

    if case["expect"] == "review":
        assert pending_decisions(), "expected an ambiguous decision for human review"
    else:
        assert not pending_decisions(), "unexpected unresolved decision"


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["expect"] == "same_event"], ids=[
        c["id"] for c in CASES if c["expect"] == "same_event"
    ]
)
def test_same_event_case_aggregates(ready, case: dict[str, object]) -> None:
    seeded = seed_case(case)
    run_clustering(scope="incremental")

    events = list_events()
    assert len(events) == 1
    event = events[0]
    assert int(event["article_count"]) == len(seeded)
    assert int(event["source_count"]) == len(seeded)
    assert sorted(event_article_ids(str(event["id"]))) == sorted(
        [item.article_id for item in seeded]
    )


def test_different_events_case_produces_separate_events(ready) -> None:
    case = next(c for c in CASES if c["id"] == "same_organization_different_events")
    seeded = seed_case(case)
    run_clustering(scope="incremental")
    events = list_events()
    assert len(events) == 2
    assert all(item["article_count"] == 1 for item in events)


def test_repost_uses_content_hash_not_counts(ready) -> None:
    case = next(c for c in CASES if c["id"] == "repost_same_content")
    seeded = seed_case(case)
    run_clustering(scope="incremental")

    events = list_events()
    assert len(events) == 1
    assert int(events[0]["article_count"]) == 2
    # Two physical rows but one information source family for heat purposes is
    # handled by the scoring layer; clustering still records both members.
    assert len(event_article_ids(str(events[0]["id"]))) == 2


def test_second_incremental_run_does_not_duplicate(ready) -> None:
    from services.errors import ServiceError

    case = next(c for c in CASES if c["id"] == "multi_source_same_event")
    seed_case(case)
    first = run_clustering(scope="incremental")
    assert first.created_event_count == 1

    # All articles are already assigned, so the incremental scope is a no-op
    # and reports a stable domain conflict instead of re-clustering.
    with pytest.raises(ServiceError) as excinfo:
        run_clustering(scope="incremental")
    assert excinfo.value.code == "no_clusterable_articles"

    events = list_events()
    assert len(events) == 1
    assert int(events[0]["article_count"]) == 3
    with database.read_session() as conn:
        count = conn.execute("SELECT COUNT(*) FROM event_articles").fetchone()[0]
    assert count == 3


def test_candidate_ranking_survives_many_similar_events(ready) -> None:
    """Generic shared keywords must not crowd the correct event out of the
    candidate window (regression for the unsorted-truncation bug)."""

    templates = 12
    per_template = 3
    for template in range(templates):
        company = f"并发公司{template:02d}"
        event_entity = f"并发事件{template:02d}"
        for index in range(per_template):
            seed_article(
                title=f"{company}发布{event_entity}进展 第{index + 1}报",
                category="科技",
                summary=f"{company}{event_entity}进展摘要。",
                keywords=["财报", "进展"],
                entities=[(company, "organization"), (event_entity, "event")],
                source_name=f"来源{template}-{index}",
                published_at=stamp(0.2 * index),
            )

    run = run_clustering(scope="incremental")
    assert run.status == "succeeded"
    events = list_events()
    assert len(events) == templates
    assert all(int(event["article_count"]) == per_template for event in events)


def test_second_incremental_run_attaches_new_article(ready) -> None:
    """Regression for P4-01: a second incremental run must reuse existing
    automatic events without crashing in `_event_features`."""

    case = next(c for c in CASES if c["id"] == "multi_source_same_event")
    seed_case(case)
    first = run_clustering(scope="incremental")
    assert first.status == "succeeded"
    events = list_events()
    assert len(events) == 1

    extra = seed_article(
        title="星河科技 Q3 财报电话会：管理层上调全年指引",
        category="科技",
        summary="星河科技第三季度财报电话会。",
        keywords=["财报", "营收"],
        entities=[("星河科技", "organization"), ("第三季度财报", "event")],
        source_name="后续来源",
        published_at=stamp(0.0),
    )
    second = run_clustering(scope="incremental")
    assert second.status == "succeeded"

    events = list_events()
    assert len(events) == 1
    assert int(events[0]["article_count"]) == 4
    assert article_event(extra.article_id) == str(events[0]["id"])

    from event_support import current_scores

    snapshot = current_scores(str(events[0]["id"]))
    assert snapshot is not None
    assert json.loads(str(snapshot["inputs_json"]))["article_count"] == 4


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("星河科技发布第三季度财报", "星河科技发布第四季度财报"),
        ("星河科技宣布大规模裁员", "星河科技宣布大规模招聘"),
    ],
)
def test_contradictory_markers_do_not_merge_without_event_entity(
    ready, left: str, right: str
) -> None:
    """P4-02: same organization but contradictory period/antonym markers must
    stay separate when the AI did not extract an event-type entity."""

    for index, title in enumerate((left, right)):
        seed_article(
            title=title,
            category="科技",
            summary=f"{title}，公司发布公告。",
            keywords=["公司", "公告"],
            entities=[("星河科技", "organization")],
            source_name=f"来源{index}",
            published_at=stamp(0.2 * index),
        )
    run = run_clustering(scope="incremental")
    assert run.status == "succeeded"
    assert len(list_events()) == 2


def test_cluster_run_is_persisted_with_version(ready) -> None:
    case = next(c for c in CASES if c["id"] == "evolving_progress")
    seed_case(case)
    run = run_clustering(scope="incremental")
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT * FROM event_cluster_runs WHERE id = ?", (run.id,)
        ).fetchone()
        events = conn.execute("SELECT algorithm_version FROM events").fetchall()
    assert row is not None and str(row["status"]) == "succeeded"
    assert int(row["duration_ms"]) >= 0
    assert {str(item[0]) for item in events} == {"event-cluster-v1"}


def test_manual_event_is_never_auto_merged(ready) -> None:
    from services.event_service import EventService

    case = next(c for c in CASES if c["id"] == "multi_source_same_event")
    seeded = seed_case(case)
    service = EventService()
    manual = service.create_event(
        title="人工维护的事件",
        summary="人工事件摘要",
        category="科技",
        article_ids=[seeded[0].article_id],
    )
    assert manual.is_manual is True

    run_clustering(scope="incremental")
    remaining = [item.article_id for item in seeded[1:]]
    assignment = partition(remaining)
    assert manual.id not in set(assignment.values())
    with database.read_session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM event_articles WHERE event_id = ?", (manual.id,)
        ).fetchone()[0]
    assert int(count) == 1
