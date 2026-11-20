"""Stage 4.6 — Phase 4 API contract tests against a real Sidecar process."""

from __future__ import annotations

import pytest

import database

from event_support import (
    list_events,
    run_clustering,
    seed_article,
    stamp,
)
from support import (
    Sidecar,
    assert_json_headers,
    http,
    start_sidecar,
    stop_sidecar,
)


def _seed() -> list[dict[str, object]]:
    for index, title in enumerate(
        [
            "星河科技第三季度财报：营收同比增长两成",
            "星河科技发布三季度财报 净利润超预期",
            "星河科技 Q3 财报显示营收增长 20%",
        ]
    ):
        seed_article(
            title=title,
            category="科技",
            summary="星河科技第三季度财报。",
            keywords=["财报", "营收"],
            entities=[("星河科技", "organization"), ("第三季度财报", "event")],
            source_name=f"来源{index}",
            published_at=stamp(0.3 - index * 0.1),
        )
    run_clustering(scope="incremental")
    return list_events()


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(data_dir))
    assert database.initialize().status == "ok"
    events = _seed()
    sidecar = start_sidecar(
        tmp_path,
        data_dir=data_dir,
        env_overrides={
            "PIH_AI_ENABLED": "0",
            "PIH_EVENT_CLUSTERING_ENABLED": "0",
        },
    )
    yield sidecar, events
    if sidecar.proc.poll() is None:
        stop_sidecar(sidecar)


def _auth(sidecar: Sidecar, path: str, **kwargs):
    return http(sidecar, path, token=sidecar.token, **kwargs)


def test_events_require_authentication(seeded) -> None:
    sidecar, _ = seeded
    response = http(sidecar, "/api/v1/events")
    assert response.status_code == 401
    assert_json_headers(response)


def test_list_events_returns_real_clustered_data(seeded) -> None:
    sidecar, events = seeded
    response = _auth(sidecar, "/api/v1/events")
    assert response.status_code == 200
    assert_json_headers(response)
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 20 and body["offset"] == 0
    item = body["items"][0]
    assert item["id"] == str(events[0]["id"])
    assert item["article_count"] == 3
    assert item["source_count"] == 3
    assert item["status"] == "active"
    assert item["current_scores"] is not None
    assert item["current_scores"]["algorithm_version"] == "event-score-v1"


def test_list_events_filters_and_validation(seeded) -> None:
    sidecar, _ = seeded
    assert _auth(sidecar, "/api/v1/events", params={"status": "active"}).json()["total"] == 1
    assert _auth(sidecar, "/api/v1/events", params={"status": "closed"}).json()["total"] == 0
    assert _auth(sidecar, "/api/v1/events", params={"category": "财经"}).json()["total"] == 0
    assert _auth(sidecar, "/api/v1/events", params={"q": "财报"}).json()["total"] == 1

    assert _auth(sidecar, "/api/v1/events", params={"limit": 0}).status_code == 422
    assert _auth(sidecar, "/api/v1/events", params={"status": "bogus"}).status_code == 422
    assert _auth(sidecar, "/api/v1/events", params={"order": "bogus"}).status_code == 422


def test_list_events_supports_article_count_order(seeded) -> None:
    """Regression for P4-04: the UI's 文章数 sort must be accepted."""

    sidecar, events = seeded
    response = _auth(sidecar, "/api/v1/events", params={"order": "articles"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(events[0]["id"])
    assert body["items"][0]["article_count"] == 3


def test_event_detail_and_not_found(seeded) -> None:
    sidecar, events = seeded
    event_id = str(events[0]["id"])
    response = _auth(sidecar, f"/api/v1/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == event_id
    assert body["entities"]
    assert body["title"]

    missing = _auth(sidecar, "/api/v1/events/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "event_not_found"
    assert _auth(sidecar, "/api/v1/events/not-a-uuid").status_code == 422


def test_event_articles_timeline_entities_scores(seeded) -> None:
    sidecar, events = seeded
    event_id = str(events[0]["id"])

    articles = _auth(sidecar, f"/api/v1/events/{event_id}/articles").json()
    assert articles["total"] == 3
    assert all(item["article_id"] for item in articles["items"])

    timeline = _auth(sidecar, f"/api/v1/events/{event_id}/timeline").json()
    assert timeline["total"] >= 3
    kinds = {item["kind"] for item in timeline["items"]}
    assert "first_report" in kinds
    for item in timeline["items"]:
        assert "occurred_at" in item and "published_at" in item and "recognized_at" in item

    entities = _auth(sidecar, f"/api/v1/events/{event_id}/entities").json()
    assert entities["total"] >= 2
    assert {"entity_id", "canonical_name", "role"} <= set(entities["items"][0])

    scores = _auth(sidecar, f"/api/v1/events/{event_id}/scores").json()
    assert scores["total"] >= 1
    snapshot = scores["items"][0]
    assert snapshot["algorithm_version"] == "event-score-v1"
    for key in (
        "importance_score",
        "heat_score",
        "freshness_score",
        "coverage_score",
        "confidence_score",
        "total_score",
    ):
        assert 0 <= snapshot[key] <= 100
    assert snapshot["explanation"]["formula"]
    assert snapshot["inputs"]["unique_source_count"] == 3


def test_rename_and_status_change_are_persisted(seeded) -> None:
    sidecar, events = seeded
    event_id = str(events[0]["id"])
    renamed = _auth(
        sidecar,
        f"/api/v1/events/{event_id}",
        method="PATCH",
        json_body={"title": "星河科技三季度财报（人工标题）"},
    )
    assert renamed.status_code == 200
    # Titles are NFKC-normalised on write (full-width parentheses become ASCII).
    assert renamed.json()["title"] == "星河科技三季度财报(人工标题)"

    closed = _auth(
        sidecar,
        f"/api/v1/events/{event_id}",
        method="PATCH",
        json_body={"status": "closed", "status_reason": "人工结束"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["is_manual"] is True

    assert _auth(
        sidecar, f"/api/v1/events/{event_id}", method="PATCH", json_body={"status": "merged"}
    ).status_code == 422
    assert _auth(
        sidecar, f"/api/v1/events/{event_id}", method="PATCH", json_body={}
    ).status_code == 422


def test_manual_merge_conflict_and_split_validation(seeded) -> None:
    sidecar, events = seeded
    event_id = str(events[0]["id"])

    same = _auth(
        sidecar,
        f"/api/v1/events/{event_id}/merge",
        method="POST",
        json_body={"target_event_id": event_id},
    )
    assert same.status_code == 409

    members = _auth(sidecar, f"/api/v1/events/{event_id}/articles").json()["items"]
    all_ids = [item["article_id"] for item in members]
    split_all = _auth(
        sidecar,
        f"/api/v1/events/{event_id}/split",
        method="POST",
        json_body={"article_ids": all_ids},
    )
    assert split_all.status_code == 409

    split_one = _auth(
        sidecar,
        f"/api/v1/events/{event_id}/split",
        method="POST",
        json_body={"article_ids": [all_ids[0]], "title": "拆分事件"},
    )
    assert split_one.status_code == 201
    assert split_one.json()["article_count"] == 1
    assert split_one.json()["is_manual"] is True


def test_remove_article_and_add_article(seeded) -> None:
    sidecar, events = seeded
    event_id = str(events[0]["id"])
    members = _auth(sidecar, f"/api/v1/events/{event_id}/articles").json()["items"]
    article_id = members[0]["article_id"]

    removed = _auth(
        sidecar, f"/api/v1/events/{event_id}/articles/{article_id}", method="DELETE"
    )
    assert removed.status_code == 204
    after = _auth(sidecar, f"/api/v1/events/{event_id}/articles").json()
    assert after["total"] == 2

    added = _auth(
        sidecar,
        f"/api/v1/events/{event_id}/articles",
        method="POST",
        json_body={"article_id": article_id, "role": "follow_up"},
    )
    assert added.status_code == 200
    assert added.json()["article_count"] == 3


def test_unmerge_restores_a_manual_merge(seeded) -> None:
    sidecar, events = seeded
    event_id = str(events[0]["id"])
    members = _auth(sidecar, f"/api/v1/events/{event_id}/articles").json()["items"]
    split = _auth(
        sidecar,
        f"/api/v1/events/{event_id}/split",
        method="POST",
        json_body={"article_ids": [members[0]["article_id"]], "title": "临时拆分"},
    )
    assert split.status_code == 201
    new_id = split.json()["id"]

    merged = _auth(
        sidecar,
        f"/api/v1/events/{new_id}/merge",
        method="POST",
        json_body={"target_event_id": event_id},
    )
    assert merged.status_code == 200
    assert merged.json()["source_event_id"] == new_id
    merged_detail = _auth(sidecar, f"/api/v1/events/{new_id}")
    assert merged_detail.json()["status"] == "merged"

    unmerged = _auth(sidecar, f"/api/v1/events/{new_id}/unmerge", method="POST")
    assert unmerged.status_code == 200
    assert unmerged.json()["status"] == "active"
    assert unmerged.json()["article_count"] == 1
    assert unmerged.json()["merged_into_event_id"] is None

    repeat = _auth(sidecar, f"/api/v1/events/{new_id}/unmerge", method="POST")
    assert repeat.status_code == 409


def test_rankings_and_recompute(seeded) -> None:
    sidecar, events = seeded
    response = _auth(sidecar, "/api/v1/rankings", params={"kind": "importance", "window": "all"})
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm_version"] == "event-score-v1"
    assert body["total"] == 1
    assert body["items"][0]["rank"] == 1
    assert body["items"][0]["event"]["id"] == str(events[0]["id"])

    for kind in ("recent", "heat", "emerging", "confidence"):
        assert _auth(
            sidecar, "/api/v1/rankings", params={"kind": kind, "window": "all"}
        ).status_code == 200
    assert _auth(sidecar, "/api/v1/rankings", params={"kind": "bogus"}).status_code == 422

    recompute = _auth(
        sidecar,
        "/api/v1/event-scores/recompute",
        method="POST",
        json_body={"scope": "all", "event_ids": [], "limit": 50},
    )
    assert recompute.status_code == 200
    assert recompute.json()["algorithm_version"] == "event-score-v1"
    assert recompute.json()["scored_events"] >= 1


def test_entities_list_detail_and_alias(seeded) -> None:
    sidecar, _ = seeded
    listing = _auth(sidecar, "/api/v1/entities").json()
    assert listing["total"] >= 2
    organization = next(
        item for item in listing["items"] if item["canonical_name"] == "星河科技"
    )
    detail_response = _auth(sidecar, f"/api/v1/entities/{organization['id']}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["aliases"]
    assert detail["article_count"] == 3

    added = _auth(
        sidecar,
        f"/api/v1/entities/{organization['id']}/aliases",
        method="POST",
        json_body={"alias": "Galaxy Tech", "language": "en"},
    )
    assert added.status_code == 200
    aliases = {item["alias"] for item in added.json()["aliases"]}
    assert "Galaxy Tech" in aliases

    assert _auth(sidecar, "/api/v1/entities/00000000-0000-4000-8000-000000000000").status_code == 404
    assert _auth(sidecar, "/api/v1/entities", params={"type": "bogus"}).status_code == 422


def test_cluster_status_and_run_validation(seeded) -> None:
    sidecar, _ = seeded
    status = _auth(sidecar, "/api/v1/event-clusters/status")
    assert status.status_code == 200
    body = status.json()
    assert body["algorithm_version"] == "event-cluster-v1"
    assert "llm_enabled" in body

    runs = _auth(sidecar, "/api/v1/event-clusters/runs").json()
    assert runs["total"] >= 1

    invalid = _auth(
        sidecar,
        "/api/v1/event-clusters/runs",
        method="POST",
        json_body={"scope": "bogus", "limit": 10},
    )
    assert invalid.status_code == 422


def test_decisions_and_candidates_endpoints(seeded) -> None:
    sidecar, _ = seeded
    decisions = _auth(sidecar, "/api/v1/events/clustering/decisions").json()
    assert decisions["total"] == 3
    assert {item["decision"] for item in decisions["items"]} == {"created", "attached"}

    candidates = _auth(sidecar, "/api/v1/events/candidates").json()
    assert candidates["total"] == 0
