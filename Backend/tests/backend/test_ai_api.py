"""Phase 3 AI API tests against a real Sidecar process.

`PIH_AI_ENABLED=0` keeps these tests deterministic: no article is actually sent
to Ollama. Provider behaviour is covered by `tests/ai/test_provider_security.py`
and live verification.
"""

from __future__ import annotations

import uuid

from support import Sidecar, assert_json_headers, http


def test_ai_status_shape(sidecar: Sidecar) -> None:
    response = http(sidecar, "/api/v1/ai/status", token=sidecar.token)
    assert response.status_code == 200
    assert_json_headers(response)
    body = response.json()
    assert body["enabled"] is False
    assert body["provider_kind"] == "ollama-local"
    assert body["base_url"] == "http://127.0.0.1:11434"
    assert body["concurrency"] == 1
    assert body["embedding"] == {
        "enabled": False,
        "reason": "embedding_model_not_configured",
    }
    assert body["default_model"] == "qwen3.5:4b-mlx"
    assert body["enabled_models"] == ["qwen3.5:4b-mlx"]
    assert isinstance(body["available"], bool)
    assert isinstance(body["cloud_models_blocked"], int)


def test_ai_models_lists_registry(sidecar: Sidecar) -> None:
    response = http(sidecar, "/api/v1/ai/models", token=sidecar.token)
    assert response.status_code == 200
    body = response.json()
    names = {item["model_name"] for item in body["items"]}
    assert {"qwen3.5:4b-mlx", "qwen3:1.7b", "gemma3:4b"} <= names
    assert body["total"] == len(body["items"])
    enabled = [item for item in body["items"] if item["enabled"]]
    assert [item["model_name"] for item in enabled] == ["qwen3.5:4b-mlx"]
    assert all(item["num_ctx"] == 4096 for item in body["items"])
    assert all(item["remote"] is False for item in body["items"])


def test_create_run_rejected_when_disabled(sidecar: Sidecar) -> None:
    response = http(
        sidecar,
        "/api/v1/ai/runs",
        method="POST",
        token=sidecar.token,
        json_body={"scope": "unanalyzed"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ai_disabled"


def test_create_run_validates_body(sidecar: Sidecar) -> None:
    response = http(
        sidecar,
        "/api/v1/ai/runs",
        method="POST",
        token=sidecar.token,
        json_body={"scope": "everything"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"

    response = http(
        sidecar,
        "/api/v1/ai/runs",
        method="POST",
        token=sidecar.token,
        json_body={"scope": "selected"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ai_disabled"


def test_run_listing_and_missing_run(sidecar: Sidecar) -> None:
    listing = http(sidecar, "/api/v1/ai/runs?limit=10", token=sidecar.token)
    assert listing.status_code == 200
    assert listing.json() == {"items": [], "total": 0, "limit": 10, "offset": 0}

    missing = http(
        sidecar, f"/api/v1/ai/runs/{uuid.uuid4()}", token=sidecar.token
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ai_run_not_found"

    paused = http(
        sidecar,
        f"/api/v1/ai/runs/{uuid.uuid4()}/pause",
        method="POST",
        token=sidecar.token,
    )
    assert paused.status_code == 404


def test_article_analysis_missing_article(sidecar: Sidecar) -> None:
    missing_id = uuid.uuid4()
    response = http(
        sidecar, f"/api/v1/articles/{missing_id}/analysis", token=sidecar.token
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "article_not_found"


def test_authentication_is_required_for_ai_routes(sidecar: Sidecar) -> None:
    response = http(sidecar, "/api/v1/ai/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
