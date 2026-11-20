"""`/api/v1/personalization` contract tests against a real temporary SQLite."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

from personalization_support import seed_article_with_analysis

TOKEN = "test-personalization-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _client() -> TestClient:
    return TestClient(create_app(TOKEN))


def test_requires_bearer_token(ready) -> None:
    with _client() as client:
        assert client.get("/api/v1/personalization/profile").status_code == 401
        assert client.get("/api/v1/digest/today").status_code == 401


def test_profile_defaults_and_update(ready) -> None:
    with _client() as client:
        profile = client.get("/api/v1/personalization/profile", headers=HEADERS)
        assert profile.status_code == 200
        body = profile.json()
        assert body["profile"]["timezone"] == "Asia/Shanghai"
        assert body["profile"]["exploration_ratio"] == 0.1
        assert body["interest_count"] == 0

        updated = client.patch(
            "/api/v1/personalization/profile",
            headers=HEADERS,
            json={
                "display_name": "技术情报",
                "daily_item_limit": 10,
                "daily_minutes": 20,
                "exploration_ratio": 0.2,
                "digest_time": "07:30",
            },
        )
        assert updated.status_code == 200
        payload = updated.json()["profile"]
        assert payload["display_name"] == "技术情报"
        assert payload["daily_item_limit"] == 10
        assert payload["daily_minutes"] == 20
        assert payload["exploration_ratio"] == 0.2
        assert payload["digest_time"] == "07:30"


def test_profile_rejects_invalid_values(ready) -> None:
    with _client() as client:
        assert (
            client.patch(
                "/api/v1/personalization/profile",
                headers=HEADERS,
                json={"digest_time": "25:00"},
            ).status_code
            == 422
        )
        assert (
            client.patch(
                "/api/v1/personalization/profile",
                headers=HEADERS,
                json={"timezone": "Mars/Olympus"},
            ).status_code
            == 422
        )
        assert (
            client.patch(
                "/api/v1/personalization/profile",
                headers=HEADERS,
                json={"exploration_ratio": 0.9},
            ).status_code
            == 422
        )
        assert (
            client.patch(
                "/api/v1/personalization/profile",
                headers=HEADERS,
                json={"unknown_field": True},
            ).status_code
            == 422
        )


def test_interest_crud_and_validation(ready) -> None:
    with _client() as client:
        created = client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={
                "name": "人工智能",
                "interest_type": "domain",
                "domain_key": "technology",
                "level": "core",
                "keywords": ["AI", "Agent"],
                "exclusion_keywords": ["融资"],
            },
        )
        assert created.status_code == 201
        interest = created.json()
        assert interest["weight"] == 1.0
        assert interest["keywords"] == ["AI", "Agent"]
        assert interest["exclusion_keywords"] == ["融资"]

        duplicate = client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={"name": "人工智能", "interest_type": "domain", "domain_key": "technology"},
        )
        assert duplicate.status_code == 409

        invalid_domain = client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={"name": "未知领域", "interest_type": "domain", "domain_key": "not-a-key"},
        )
        assert invalid_domain.status_code == 422

        listing = client.get("/api/v1/personalization/interests", headers=HEADERS)
        assert listing.json()["total"] == 1

        updated = client.patch(
            f"/api/v1/personalization/interests/{interest['id']}",
            headers=HEADERS,
            json={"level": "extended", "weight": 0.65, "keywords": ["大模型"]},
        )
        assert updated.status_code == 200
        assert updated.json()["level"] == "extended"
        assert updated.json()["weight"] == 0.65
        assert updated.json()["keywords"] == ["大模型"]

        keywords = client.put(
            f"/api/v1/personalization/interests/{interest['id']}/keywords",
            headers=HEADERS,
            json={"keywords": ["Agent"], "exclusion_keywords": ["招聘"]},
        )
        assert keywords.status_code == 200
        assert keywords.json()["exclusion_keywords"] == ["招聘"]

        deleted = client.delete(
            f"/api/v1/personalization/interests/{interest['id']}", headers=HEADERS
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.delete(
            f"/api/v1/personalization/interests/{interest['id']}", headers=HEADERS
        ).status_code == 404


def test_interest_entity_and_source_links(ready) -> None:
    from personalization_support import create_entity

    entity_id = create_entity("OpenAI")
    with _client() as client:
        interest = client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={"name": "大模型公司", "interest_type": "topic", "domain_key": "ai", "level": "core"},
        ).json()
        linked = client.post(
            f"/api/v1/personalization/interests/{interest['id']}/entities",
            headers=HEADERS,
            json={"entity_id": entity_id},
        )
        assert linked.status_code == 200
        assert linked.json()["entity_names"] == ["OpenAI"]
        duplicate = client.post(
            f"/api/v1/personalization/interests/{interest['id']}/entities",
            headers=HEADERS,
            json={"entity_id": entity_id},
        )
        assert duplicate.status_code == 409
        missing = client.post(
            f"/api/v1/personalization/interests/{interest['id']}/entities",
            headers=HEADERS,
            json={"entity_id": "missing"},
        )
        assert missing.status_code == 404
        unlinked = client.delete(
            f"/api/v1/personalization/interests/{interest['id']}/entities/{entity_id}",
            headers=HEADERS,
        )
        assert unlinked.status_code == 200
        assert unlinked.json()["entity_ids"] == []


def test_blocked_sources_roundtrip(ready) -> None:
    seed = seed_article_with_analysis(title="被屏蔽来源的文章")
    with _client() as client:
        blocked = client.post(
            "/api/v1/personalization/blocked-sources",
            headers=HEADERS,
            json={"source_id": seed["source_id"], "reason": "重复转载"},
        )
        assert blocked.status_code == 200
        assert blocked.json()["total"] == 1
        assert client.get(
            "/api/v1/personalization/blocked-sources", headers=HEADERS
        ).json()["items"][0]["reason"] == "重复转载"
        assert client.delete(
            f"/api/v1/personalization/blocked-sources/{seed['source_id']}", headers=HEADERS
        ).status_code == 200
        assert client.delete(
            f"/api/v1/personalization/blocked-sources/{seed['source_id']}", headers=HEADERS
        ).status_code == 404


def test_feed_and_stats_shape(ready) -> None:
    seed = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    with _client() as client:
        client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={
                "name": "人工智能",
                "interest_type": "domain",
                "domain_key": "technology",
                "level": "core",
                "keywords": ["AI", "Agent"],
            },
        )
        feed = client.get("/api/v1/personalization/feed", headers=HEADERS)
        assert feed.status_code == 200
        body = feed.json()
        assert body["algorithm_version"] == "personal-reco-v1"
        assert set(body["sections"]) == {
            "must_read",
            "event_highlights",
            "core_interest",
            "emerging",
            "leads",
            "watch",
            "others",
        }
        items = body["sections"]["core_interest"] + body["sections"]["leads"]
        assert any(item["target_id"] == seed["article_id"] for item in items)
        item = next(item for item in items if item["target_id"] == seed["article_id"])
        assert item["score"] > 0
        assert item["matched_interests"] == ["人工智能"]
        assert item["score_breakdown"]["interest"] > 0
        assert "CORE_INTEREST_MATCH" in item["reason_codes"]

        stats = client.get("/api/v1/personalization/stats", headers=HEADERS)
        assert stats.status_code == 200
        assert stats.json()["recommendations"]["total"] >= 1

        detail = client.get(
            f"/api/v1/personalization/recommendations/article/{seed['article_id']}",
            headers=HEADERS,
        )
        assert detail.status_code == 200
        assert detail.json()["explanation"]["algorithm_version"] == "personal-reco-v1"
        assert detail.json()["feedback"] is None

        missing = client.get(
            "/api/v1/personalization/recommendations/article/missing", headers=HEADERS
        )
        assert missing.status_code == 404


def _feed_target_ids(client: TestClient, *, include_read: bool = False) -> set[str]:
    suffix = "?include_read=true" if include_read else ""
    body = client.get(f"/api/v1/personalization/feed{suffix}", headers=HEADERS).json()
    ids: set[str] = set()
    for items in body["sections"].values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("target_id"):
                ids.add(str(item["target_id"]))
    return ids


def _create_core_ai_interest(client: TestClient) -> None:
    created = client.post(
        "/api/v1/personalization/interests",
        headers=HEADERS,
        json={
            "name": "人工智能",
            "interest_type": "domain",
            "domain_key": "technology",
            "level": "core",
            "keywords": ["AI", "Agent"],
        },
    )
    assert created.status_code == 201


def test_feed_excludes_read_article(ready) -> None:
    seed = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    with _client() as client:
        _create_core_ai_interest(client)
        assert seed["article_id"] in _feed_target_ids(client)

        marked = client.patch(
            f"/api/v1/articles/{seed['article_id']}/reading-state",
            headers=HEADERS,
            json={"reading_status": "read"},
        )
        assert marked.status_code == 200
        assert seed["article_id"] not in _feed_target_ids(client)
        assert seed["article_id"] in _feed_target_ids(client, include_read=True)


def test_feed_excludes_later_article(ready) -> None:
    seed = seed_article_with_analysis(title="AI Agent 平台路线图", category="科技")
    with _client() as client:
        _create_core_ai_interest(client)
        assert seed["article_id"] in _feed_target_ids(client)

        assert client.post(
            f"/api/v1/articles/{seed['article_id']}/mark-later", headers=HEADERS
        ).status_code == 200
        assert seed["article_id"] not in _feed_target_ids(client)
        assert seed["article_id"] in _feed_target_ids(client, include_read=True)


def test_feed_excludes_not_interested(ready) -> None:
    seed = seed_article_with_analysis(title="AI Agent 产品评测", category="科技")
    with _client() as client:
        _create_core_ai_interest(client)
        assert seed["article_id"] in _feed_target_ids(client)

        created = client.post(
            "/api/v1/personalization/feedback",
            headers=HEADERS,
            json={
                "target_type": "article",
                "target_id": seed["article_id"],
                "feedback": "not_interested",
            },
        )
        assert created.status_code == 201
        assert seed["article_id"] not in _feed_target_ids(client)
        assert seed["article_id"] not in _feed_target_ids(client, include_read=True)


def test_feedback_api_and_validation(ready) -> None:
    seed = seed_article_with_analysis(title="AI Agent 融资新闻", category="科技")
    with _client() as client:
        created = client.post(
            "/api/v1/personalization/feedback",
            headers=HEADERS,
            json={"target_type": "article", "target_id": seed["article_id"], "feedback": "interested"},
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["feedback"]["feedback"] == "interested"
        assert payload["recommendation"]["feedback"]["id"] == payload["feedback"]["id"]

        replaced = client.post(
            "/api/v1/personalization/feedback",
            headers=HEADERS,
            json={"target_type": "article", "target_id": seed["article_id"], "feedback": "later"},
        )
        assert replaced.status_code == 201
        assert replaced.json()["feedback"]["feedback"] == "later"

        history = client.get("/api/v1/personalization/feedback", headers=HEADERS)
        assert history.json()["total"] == 2
        assert history.json()["items"][1]["revoked_at"] is not None

        revoked = client.delete(
            f"/api/v1/personalization/feedback/{payload['feedback']['id']}", headers=HEADERS
        )
        assert revoked.status_code == 409

        revoked_target = client.delete(
            f"/api/v1/personalization/feedback/target/article/{seed['article_id']}",
            headers=HEADERS,
        )
        assert revoked_target.status_code == 200
        assert revoked_target.json()["revoked"] is True

        invalid = client.post(
            "/api/v1/personalization/feedback",
            headers=HEADERS,
            json={"target_type": "article", "target_id": seed["article_id"], "feedback": "meh"},
        )
        assert invalid.status_code == 422
        missing = client.post(
            "/api/v1/personalization/feedback",
            headers=HEADERS,
            json={"target_type": "event", "target_id": "missing", "feedback": "interested"},
        )
        assert missing.status_code == 404


def test_digest_endpoints(ready) -> None:
    seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    with _client() as client:
        client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={"name": "人工智能", "interest_type": "domain", "domain_key": "technology", "level": "core"},
        )
        today = client.get("/api/v1/digest/today", headers=HEADERS)
        assert today.status_code == 200
        digest = today.json()
        assert digest["status"] == "succeeded"
        assert digest["ai_status"] == "skipped"
        assert digest["items"]
        again = client.get("/api/v1/digest/today", headers=HEADERS)
        assert again.json()["id"] == digest["id"]

        force = client.post(
            "/api/v1/digest/generate", headers=HEADERS, json={"force": True}
        )
        assert force.status_code == 201
        assert force.json()["id"] != digest["id"]

        history = client.get("/api/v1/digest/history", headers=HEADERS)
        assert history.status_code == 200
        assert history.json()["total"] == 1

        missing = client.get("/api/v1/digest/2020-01-01", headers=HEADERS)
        assert missing.status_code == 404
        generated = client.get(
            "/api/v1/digest/2020-01-01?generate=true", headers=HEADERS
        )
        assert generated.status_code == 200


def test_reset_requires_a_selection_and_clears_only_personal_data(ready) -> None:
    from personalization_support import seed_article_with_analysis

    seed = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    with _client() as client:
        interest = client.post(
            "/api/v1/personalization/interests",
            headers=HEADERS,
            json={"name": "人工智能", "interest_type": "domain", "domain_key": "technology", "level": "core"},
        ).json()
        client.post(
            "/api/v1/personalization/feedback",
            headers=HEADERS,
            json={"target_type": "article", "target_id": seed["article_id"], "feedback": "interested"},
        )
        client.get("/api/v1/digest/today", headers=HEADERS)

        empty = client.post("/api/v1/personalization/reset", headers=HEADERS, json={})
        assert empty.status_code == 422

        reset = client.post(
            "/api/v1/personalization/reset",
            headers=HEADERS,
            json={"clear_interests": True, "clear_feedback": True, "clear_digests": True},
        )
        assert reset.status_code == 200
        removed = reset.json()["removed"]
        assert removed["interests"] == 1
        assert removed["feedback"] == 1
        assert removed["digests"] >= 1
        assert client.get("/api/v1/personalization/interests", headers=HEADERS).json()["total"] == 0
        assert client.get("/api/v1/personalization/feedback", headers=HEADERS).json()["total"] == 0
        assert client.get("/api/v1/digest/history", headers=HEADERS).json()["total"] == 0

    # Articles are untouched by a personal-data reset.
    import database

    with database.read_session() as conn:
        row = conn.execute("SELECT COUNT(*) FROM articles").fetchone()
    assert int(row[0]) == 1
    assert interest["id"]
