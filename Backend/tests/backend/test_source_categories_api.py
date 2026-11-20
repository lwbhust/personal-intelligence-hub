"""Real-process integration tests for `/api/v1/source-categories`."""

from __future__ import annotations

import uuid

import pytest

from support import Sidecar, assert_json_headers, http


def _auth(sidecar: Sidecar, path: str, **kwargs):
    return http(sidecar, path, token=sidecar.token, **kwargs)


def _create(sidecar: Sidecar, name: str = "Tech", **extra):
    payload = {"name": name, **extra}
    return _auth(sidecar, "/api/v1/source-categories", method="POST", json_body=payload)


def test_create_list_get_update_delete(sidecar: Sidecar) -> None:
    created = _create(sidecar, "AI 与科技", description="模型动态", sort_order=5)
    assert created.status_code == 201, created.text
    assert_json_headers(created)
    body = created.json()
    category_id = body["id"]
    assert body["name"] == "AI 与科技"
    assert body["source_count"] == 0

    listed = _auth(sidecar, "/api/v1/source-categories")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == category_id

    detailed = _auth(sidecar, f"/api/v1/source-categories/{category_id}")
    assert detailed.status_code == 200

    patched = _auth(
        sidecar,
        f"/api/v1/source-categories/{category_id}",
        method="PATCH",
        json_body={"name": "AI", "description": None},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "AI"
    assert patched.json()["description"] is None

    deleted = _auth(
        sidecar, f"/api/v1/source-categories/{category_id}", method="DELETE"
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert deleted.headers.get("x-request-id")
    assert deleted.headers.get("cache-control") == "no-store"

    missing = _auth(sidecar, f"/api/v1/source-categories/{category_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "source_category_not_found"


def test_duplicate_name_returns_409(sidecar: Sidecar) -> None:
    assert _create(sidecar, "News").status_code == 201
    duplicate = _create(sidecar, " News ")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "source_category_name_conflict"


def test_delete_category_in_use_returns_409(sidecar: Sidecar) -> None:
    category_id = _create(sidecar, "Tech").json()["id"]
    source = _auth(
        sidecar,
        "/api/v1/sources",
        method="POST",
        json_body={
            "name": "Example",
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
            "category_id": category_id,
        },
    )
    assert source.status_code == 201, source.text

    blocked = _auth(
        sidecar, f"/api/v1/source-categories/{category_id}", method="DELETE"
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "source_category_in_use"


def test_validation_details_and_unknown_fields(sidecar: Sidecar) -> None:
    missing = _auth(
        sidecar, "/api/v1/source-categories", method="POST", json_body={}
    )
    assert missing.status_code == 422
    error = missing.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"][0]["field"] == "name"
    assert "input" not in error["details"][0]

    unknown = _create(sidecar, "Tech", unexpected="x")
    assert unknown.status_code == 422
    assert unknown.json()["error"]["details"][0]["field"] == "unexpected"

    empty_patch = _auth(
        sidecar,
        f"/api/v1/source-categories/{uuid.uuid4()}",
        method="PATCH",
        json_body={},
    )
    assert empty_patch.status_code == 422
    assert empty_patch.json()["error"]["details"][0]["reason"] == "empty"


def test_invalid_uuid_and_unauthenticated(sidecar: Sidecar) -> None:
    invalid = _auth(sidecar, "/api/v1/source-categories/not-a-uuid")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["details"][0]["field"] == "category_id"

    unauth = http(sidecar, "/api/v1/source-categories")
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "unauthorized"


def test_all_endpoint_reports_active_source_count(sidecar: Sidecar) -> None:
    category_id = _create(sidecar, "Tech").json()["id"]
    created = _auth(
        sidecar,
        "/api/v1/sources",
        method="POST",
        json_body={
            "name": "Example",
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
            "category_id": category_id,
        },
    )
    assert created.status_code == 201, created.text

    all_categories = _auth(sidecar, "/api/v1/source-categories/all")
    assert all_categories.status_code == 200
    assert all_categories.json()[0]["source_count"] == 1

    deleted = _auth(sidecar, "/api/v1/sources/" + created.json()["id"], method="DELETE")
    assert deleted.status_code == 204
    after = _auth(sidecar, "/api/v1/source-categories/all")
    assert after.json()[0]["source_count"] == 0


def test_list_pagination_and_order_validation(sidecar: Sidecar) -> None:
    for name in ("A", "B", "C"):
        assert _create(sidecar, name).status_code == 201

    page = _auth(
        sidecar,
        "/api/v1/source-categories",
        params={"limit": "2", "offset": "1", "order": "name", "direction": "asc"},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 2

    bad_limit = _auth(sidecar, "/api/v1/source-categories", params={"limit": "101"})
    assert bad_limit.status_code == 422

    bad_order = _auth(
        sidecar, "/api/v1/source-categories", params={"order": "created_at"}
    )
    assert bad_order.status_code == 422
