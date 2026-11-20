"""`/api/v1/pipeline` integration tests against a real app + temporary SQLite."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

from pipeline_support import seed_article

TOKEN = "test-pipeline-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _client() -> TestClient:
    return TestClient(create_app(TOKEN))


def test_requires_bearer_token(ready) -> None:
    with _client() as client:
        response = client.get("/api/v1/pipeline/overview")
    assert response.status_code == 401


def test_overview_and_settings(ready) -> None:
    with _client() as client:
        overview = client.get("/api/v1/pipeline/overview", headers=HEADERS)
        assert overview.status_code == 200
        body = overview.json()
        # 0013：全新数据库默认开启自动化；已有文章的库保持原设置。
        assert body["automation"]["enabled"] is True
        assert body["counts"]["total"] == 0

        updated = client.patch(
            "/api/v1/pipeline/settings",
            headers=HEADERS,
            json={"automation_enabled": False, "batch_size": 2},
        )
        assert updated.status_code == 200
        assert updated.json()["automation_enabled"] is False
        assert updated.json()["batch_size"] == 2

        reenabled = client.patch(
            "/api/v1/pipeline/settings",
            headers=HEADERS,
            json={"automation_enabled": True},
        )
        assert reenabled.status_code == 200
        assert reenabled.json()["automation_enabled"] is True

        paused = client.post(
            "/api/v1/pipeline/control", headers=HEADERS, json={"action": "pause"}
        )
        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        resumed = client.post(
            "/api/v1/pipeline/control", headers=HEADERS, json={"action": "resume"}
        )
        assert resumed.json()["paused"] is False


def test_invalid_settings_are_rejected(ready) -> None:
    with _client() as client:
        response = client.patch(
            "/api/v1/pipeline/settings", headers=HEADERS, json={"batch_size": 999}
        )
    assert response.status_code == 422


def test_backfill_task_list_detail_and_logs(ready) -> None:
    seed_article(title="回填测试文章", with_analysis=False)

    with _client() as client:
        preview = client.get("/api/v1/pipeline/backfill/preview", headers=HEADERS)
        assert preview.status_code == 200
        assert preview.json()["pending_articles"] == 1

        created = client.post(
            "/api/v1/pipeline/backfill", headers=HEADERS, json={"limit": 1}
        )
        assert created.status_code == 202
        assert created.json()["created_tasks"] == 1

        listing = client.get("/api/v1/pipeline/tasks", headers=HEADERS)
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 1
        task_id = items[0]["id"]
        assert items[0]["trigger_type"] == "backfill"

        detail = client.get(f"/api/v1/pipeline/tasks/{task_id}", headers=HEADERS)
        assert detail.status_code == 200

        logs = client.get(f"/api/v1/pipeline/tasks/{task_id}/logs", headers=HEADERS)
        assert logs.status_code == 200

        cancelled = client.post(
            f"/api/v1/pipeline/tasks/{task_id}/cancel", headers=HEADERS
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["task"]["status"] == "cancelled"

        retried = client.post(
            f"/api/v1/pipeline/tasks/{task_id}/retry", headers=HEADERS
        )
        assert retried.status_code == 200
        assert retried.json()["task"]["status"] == "ready"

        runs = client.get("/api/v1/pipeline/runs", headers=HEADERS)
        assert runs.status_code == 200
        assert runs.json()["total"] == 1


def test_unknown_task_returns_404(ready) -> None:
    with _client() as client:
        response = client.get("/api/v1/pipeline/tasks/does-not-exist", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "pipeline_task_not_found"


def test_classification_endpoints_are_read_only_by_default(ready) -> None:
    with _client() as client:
        taxonomy = client.get("/api/v1/pipeline/classification/taxonomy", headers=HEADERS)
        assert taxonomy.status_code == 200
        assert taxonomy.json()["version"] == "taxonomy-v1"

        report = client.get("/api/v1/pipeline/classification/report", headers=HEADERS)
        assert report.status_code == 200
        assert "events" in report.json()

        apply = client.post(
            "/api/v1/pipeline/classification/apply",
            headers=HEADERS,
            json={"confirm": False},
        )
        assert apply.status_code == 200
        assert apply.json()["applied"] is False
