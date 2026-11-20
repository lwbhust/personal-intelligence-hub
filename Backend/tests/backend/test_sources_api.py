"""Real-process integration tests for `/api/v1/sources`."""

from __future__ import annotations

import uuid

from support import Sidecar, assert_json_headers, http


def _auth(sidecar: Sidecar, path: str, **kwargs):
    return http(sidecar, path, token=sidecar.token, **kwargs)


def _category(sidecar: Sidecar, name: str) -> str:
    response = _auth(
        sidecar,
        "/api/v1/source-categories",
        method="POST",
        json_body={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_source(sidecar: Sidecar, **overrides):
    payload = {
        "name": "Example",
        "source_type": "rss",
        "url": "https://example.com/feed.xml",
    }
    payload.update(overrides)
    return _auth(sidecar, "/api/v1/sources", method="POST", json_body=payload)


def test_create_get_and_url_normalisation(sidecar: Sidecar) -> None:
    category_id = _category(sidecar, "Tech")
    created = _create_source(
        sidecar,
        name="Example Feed",
        homepage_url="https://Example.COM:443/home#fragment",
        category_id=category_id,
        priority=50,
        fetch_interval_minutes=30,
    )
    assert created.status_code == 201, created.text
    assert_json_headers(created)
    body = created.json()
    assert body["url"] == "https://example.com/feed.xml"
    assert body["homepage_url"] == "https://example.com/home"
    assert body["health_status"] == "unknown"
    assert body["last_success_at"] is None
    assert body["category"]["name"] == "Tech"

    detailed = _auth(sidecar, f"/api/v1/sources/{body['id']}")
    assert detailed.status_code == 200
    assert detailed.json()["id"] == body["id"]


def test_duplicate_url_and_private_targets(sidecar: Sidecar) -> None:
    assert _create_source(sidecar).status_code == 201

    duplicate = _create_source(sidecar, name="Other")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "source_url_conflict"

    trailing = _create_source(sidecar, name="Trailing", url="https://example.com/feed.xml/")
    assert trailing.status_code == 409

    homepage = _create_source(
        sidecar,
        name="Non-standard homepage",
        url="https://example.com/feed-port.xml",
        homepage_url="https://example.com:8080/home",
    )
    assert homepage.status_code == 201, homepage.text

    for url in (
        "http://127.0.0.1/feed",
        "http://127.1/",
        "http://0177.0.0.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://[::ffff:127.0.0.1]/",
        "http://100.64.0.1/feed",
        "http://100.100.100.200/latest/meta-data/",
        "http://example.com:22/feed",
        "http://localhost/feed",
        "http://user:pass@example.com/feed",
        "ftp://example.com/feed",
    ):
        rejected = _create_source(sidecar, url=url)
        assert rejected.status_code == 422, url
        detail = rejected.json()["error"]["details"][0]
        assert detail["field"] == "url"
        assert detail["reason"] in {
            "url_host",
            "url_userinfo",
            "url_scheme",
            "url_port",
        }


def test_list_filters_pagination_and_ordering(sidecar: Sidecar) -> None:
    tech = _category(sidecar, "Tech")
    news = _category(sidecar, "News")
    first = _create_source(
        sidecar, name="Alpha", url="https://alpha.example/feed", category_id=tech
    )
    assert first.status_code == 201
    assert _create_source(
        sidecar, name="Beta", url="https://beta.example/feed", category_id=news
    ).status_code == 201
    assert _create_source(
        sidecar,
        name="Gamma",
        source_type="website",
        url="https://gamma.example/",
        enabled=False,
    ).status_code == 201

    all_items = _auth(sidecar, "/api/v1/sources")
    assert all_items.status_code == 200
    assert all_items.json()["total"] == 3

    enabled_only = _auth(sidecar, "/api/v1/sources", params={"enabled": "true"})
    assert enabled_only.json()["total"] == 2

    by_type = _auth(sidecar, "/api/v1/sources", params={"source_type": "website"})
    assert by_type.json()["total"] == 1

    by_category = _auth(
        sidecar, "/api/v1/sources", params={"category_id": tech}
    )
    assert by_category.json()["total"] == 1
    assert by_category.json()["items"][0]["name"] == "Alpha"

    uncategorised = _auth(
        sidecar, "/api/v1/sources", params={"uncategorized": "true"}
    )
    assert uncategorised.json()["total"] == 1

    keyword = _auth(sidecar, "/api/v1/sources", params={"q": "Bet"})
    assert keyword.json()["total"] == 1

    page = _auth(sidecar, "/api/v1/sources", params={"limit": "1", "offset": "1"})
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1

    conflict = _auth(
        sidecar,
        "/api/v1/sources",
        params={"uncategorized": "true", "category_id": tech},
    )
    assert conflict.status_code == 422

    bad_order = _auth(sidecar, "/api/v1/sources", params={"order": "url"})
    assert bad_order.status_code == 422


def test_patch_semantics_and_toggle(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar, description="hello").json()["id"]

    keep_name = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}",
        method="PATCH",
        json_body={"priority": 90},
    )
    assert keep_name.status_code == 200
    assert keep_name.json()["name"] == "Example"
    assert keep_name.json()["priority"] == 90

    cleared = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}",
        method="PATCH",
        json_body={"description": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None

    null_name = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}",
        method="PATCH",
        json_body={"name": None},
    )
    assert null_name.status_code == 422
    assert null_name.json()["error"]["details"][0]["field"] == "name"

    disabled = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}",
        method="PATCH",
        json_body={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    reenabled = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}",
        method="PATCH",
        json_body={"enabled": True},
    )
    assert reenabled.json()["enabled"] is True

    assert _create_source(
        sidecar, name="Second", url="https://second.example/feed"
    ).status_code == 201
    duplicate = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}",
        method="PATCH",
        json_body={"url": "https://second.example/feed"},
    )
    assert duplicate.status_code == 409


def test_delete_is_soft_and_isolated(sidecar: Sidecar) -> None:
    first = _create_source(sidecar).json()["id"]
    second = _create_source(
        sidecar, name="Second", url="https://second.example/feed"
    ).json()["id"]

    deleted = _auth(sidecar, f"/api/v1/sources/{first}", method="DELETE")
    assert deleted.status_code == 204
    assert deleted.headers.get("x-request-id")
    assert deleted.headers.get("cache-control") == "no-store"

    assert _auth(sidecar, f"/api/v1/sources/{first}").status_code == 404
    remaining = _auth(sidecar, "/api/v1/sources")
    assert remaining.json()["total"] == 1
    assert remaining.json()["items"][0]["id"] == second

    again = _auth(sidecar, f"/api/v1/sources/{first}", method="DELETE")
    assert again.status_code == 404


def test_payload_limit_and_auth_precedence(sidecar: Sidecar) -> None:
    oversized = b"{" + b" " * (70 * 1024) + b"}"
    with_token = _auth(
        sidecar,
        "/api/v1/sources",
        method="POST",
        content=oversized,
        headers={"Content-Type": "application/json"},
    )
    assert with_token.status_code == 413
    assert with_token.json()["error"]["code"] == "payload_too_large"
    assert with_token.headers.get("x-request-id")

    without_token = http(
        sidecar,
        "/api/v1/sources",
        method="POST",
        content=oversized,
        headers={"Content-Type": "application/json"},
    )
    assert without_token.status_code == 401

    unknown = _auth(sidecar, "/openapi.json")
    assert unknown.status_code == 404
    unauth_unknown = http(sidecar, "/api/v1/unknown")
    assert unauth_unknown.status_code == 401
    assert _auth(sidecar, "/api/v1/unknown").status_code == 404


def test_invalid_category_reference(sidecar: Sidecar) -> None:
    response = _create_source(sidecar, category_id=str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "category_id"
