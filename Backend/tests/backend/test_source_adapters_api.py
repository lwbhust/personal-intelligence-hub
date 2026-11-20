"""Integration tests for `/api/v1/sources/{id}/adapter`."""

from __future__ import annotations

from support import Sidecar, assert_json_headers, http


def _auth(sidecar: Sidecar, path: str, **kwargs):
    return http(sidecar, path, token=sidecar.token, **kwargs)


def _create_web_source(sidecar: Sidecar) -> str:
    response = _auth(
        sidecar,
        "/api/v1/sources",
        method="POST",
        json_body={
            "name": "Official Web",
            "source_type": "official_announcement",
            "url": "https://example.com/news/",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _config(**overrides):
    payload = {
        "adapter_type": "html_list",
        "list_urls": ["https://example.com/news/"],
        "link_pattern": r"/article/\d+$",
        "max_pages": 1,
        "rate_limit_seconds": 5,
        "max_entries_per_run": 10,
        "fetch_full_text": False,
    }
    payload.update(overrides)
    return payload


def test_adapter_config_crud_and_validation(sidecar: Sidecar) -> None:
    source_id = _create_web_source(sidecar)
    missing = _auth(sidecar, f"/api/v1/sources/{source_id}/adapter")
    assert missing.status_code == 404

    created = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}/adapter",
        method="PUT",
        json_body=_config(),
    )
    assert created.status_code == 200, created.text
    assert_json_headers(created)
    body = created.json()
    assert body["adapter_type"] == "html_list"
    assert body["list_urls"] == ["https://example.com/news/"]
    assert body["last_verification"] == "unknown"

    loaded = _auth(sidecar, f"/api/v1/sources/{source_id}/adapter")
    assert loaded.status_code == 200
    assert loaded.json()["source_id"] == source_id

    invalid = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}/adapter",
        method="PUT",
        json_body=_config(link_pattern="("),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["details"][0]["field"] == "link_pattern"

    removed = _auth(
        sidecar, f"/api/v1/sources/{source_id}/adapter", method="DELETE"
    )
    assert removed.status_code == 204
    assert (
        _auth(sidecar, f"/api/v1/sources/{source_id}/adapter").status_code == 404
    )


def test_adapter_rejects_rss_source(sidecar: Sidecar) -> None:
    created = _auth(
        sidecar,
        "/api/v1/sources",
        method="POST",
        json_body={
            "name": "RSS Source",
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
        },
    )
    source_id = created.json()["id"]
    response = _auth(
        sidecar,
        f"/api/v1/sources/{source_id}/adapter",
        method="PUT",
        json_body=_config(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "adapter_not_applicable"
