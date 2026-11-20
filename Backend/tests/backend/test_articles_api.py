"""Article browsing API tests against a real Sidecar and real SQLite."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid

import httpx

from core.timeutil import utc_timestamp
from support import Sidecar, assert_json_headers, http

STAMP = "2026-11-16T08:00:00.000Z"


def _create_source(sidecar: Sidecar, *, name: str = "Example", url: str = "https://example.com/feed") -> str:
    response = http(
        sidecar,
        "/api/v1/sources",
        method="POST",
        token=sidecar.token,
        json_body={"name": name, "source_type": "rss", "url": url},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_article(
    sidecar: Sidecar,
    source_id: str,
    index: int,
    *,
    status: str = "active",
    deleted: bool = False,
    published_at: str | None = None,
) -> str:
    article_id = str(uuid.uuid4())
    conn = sqlite3.connect(str(sidecar.data_dir / "pih.sqlite3"))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO articles (
                id, source_id, external_id, canonical_url, original_url, title,
                author, summary, content_text, content_state, published_at,
                source_updated_at, fetched_at, content_hash, status,
                created_at, updated_at, deleted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                article_id,
                source_id,
                f"guid-{index}",
                f"https://example.com/posts/{index}",
                f"https://example.com/posts/{index}",
                f"Article {index}",
                "Author",
                f"Summary {index}",
                f"Body {index}",
                "full",
                f"2026-11-16T{8 + index // 60:02d}:{index % 60:02d}:00.000Z",
                None,
                STAMP,
                hashlib.sha256(f"article-{index}".encode()).hexdigest(),
                status,
                STAMP,
                STAMP,
                STAMP if deleted else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return article_id


def test_articles_list_pagination_and_filters(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    for index in range(1, 26):
        _seed_article(sidecar, source_id, index)
    _seed_article(sidecar, source_id, 90, status="archived")
    _seed_article(sidecar, source_id, 91, deleted=True)

    response = http(sidecar, "/api/v1/articles", token=sidecar.token)
    assert response.status_code == 200
    assert_json_headers(response)
    body = response.json()
    assert body["total"] == 25
    assert len(body["items"]) == 20
    assert body["items"][0]["title"] == "Article 25"
    assert body["items"][0]["source_name"] == "Example"

    page = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"limit": "10", "offset": "20"},
    ).json()
    assert page["total"] == 25
    assert len(page["items"]) == 5

    filtered = http(
        sidecar, "/api/v1/articles", token=sidecar.token, params={"source_id": source_id}
    ).json()
    assert filtered["total"] == 25

    keyword = http(
        sidecar, "/api/v1/articles", token=sidecar.token, params={"q": "Article 7"}
    ).json()
    assert keyword["total"] == 1

    archived = http(
        sidecar, "/api/v1/articles", token=sidecar.token, params={"status": "archived"}
    ).json()
    assert archived["total"] == 1
    assert archived["items"][0]["title"] == "Article 90"

    ascending = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"order": "published_at", "direction": "asc", "limit": "1"},
    ).json()
    assert ascending["items"][0]["title"] == "Article 1"


def test_articles_filter_reading_status(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    later_id = _seed_article(sidecar, source_id, 1)
    read_id = _seed_article(sidecar, source_id, 2)
    _seed_article(sidecar, source_id, 3)

    assert (
        http(
            sidecar,
            f"/api/v1/articles/{later_id}/mark-later",
            method="POST",
            token=sidecar.token,
        ).status_code
        == 200
    )
    assert (
        http(
            sidecar,
            f"/api/v1/articles/{read_id}/mark-read",
            method="POST",
            token=sidecar.token,
        ).status_code
        == 200
    )

    later = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"reading_status": "later"},
    ).json()
    assert later["total"] == 1
    assert later["items"][0]["id"] == later_id

    read = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"reading_status": "read"},
    ).json()
    assert read["total"] == 1
    assert read["items"][0]["id"] == read_id

    invalid = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"reading_status": "unknown"},
    )
    assert invalid.status_code == 422


def test_articles_filter_favorites(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    favorite_id = _seed_article(sidecar, source_id, 1)
    _seed_article(sidecar, source_id, 2)

    response = http(
        sidecar,
        f"/api/v1/articles/{favorite_id}/favorite",
        method="PUT",
        token=sidecar.token,
        json_body={"is_favorite": True},
    )
    assert response.status_code == 200, response.text

    favorites = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"is_favorite": "true"},
    ).json()
    assert favorites["total"] == 1
    assert favorites["items"][0]["id"] == favorite_id

    others = http(
        sidecar,
        "/api/v1/articles",
        token=sidecar.token,
        params={"is_favorite": "false"},
    ).json()
    assert others["total"] == 1
    assert others["items"][0]["id"] != favorite_id


def test_article_detail_and_not_found(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    article_id = _seed_article(sidecar, source_id, 1)

    detail = http(sidecar, f"/api/v1/articles/{article_id}", token=sidecar.token)
    assert detail.status_code == 200
    assert_json_headers(detail)
    body = detail.json()
    assert body["content_text"] == "Body 1"
    assert body["content_state"] == "full"
    assert body["external_id"] == "guid-1"
    assert len(body["content_hash"]) == 64

    missing = http(
        sidecar, f"/api/v1/articles/{uuid.uuid4()}", token=sidecar.token
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "article_not_found"

    invalid = http(sidecar, "/api/v1/articles/not-a-uuid", token=sidecar.token)
    assert invalid.status_code == 422

    unauthenticated = http(sidecar, f"/api/v1/articles/{article_id}")
    assert unauthenticated.status_code == 401


def test_article_validation_rejects_bad_filters(sidecar: Sidecar) -> None:
    for params in (
        {"order": "content"},
        {"direction": "sideways"},
        {"status": "deleted"},
        {"limit": "101"},
    ):
        response = http(sidecar, "/api/v1/articles", token=sidecar.token, params=params)
        assert response.status_code == 422, params


def test_source_health_history(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    conn = sqlite3.connect(str(sidecar.data_dir / "pih.sqlite3"))
    try:
        for index in range(3):
            conn.execute(
                """
                INSERT INTO source_health_logs (
                    id, source_id, checked_at, status, http_status, latency_ms,
                    error_code, error_message, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    source_id,
                    f"2026-11-16T09:0{index}:00.000Z",
                    "healthy" if index == 2 else "degraded",
                    200 if index == 2 else 503,
                    120 + index,
                    None if index == 2 else "http_server_error",
                    None if index == 2 else "目标服务返回 503",
                    STAMP,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    response = http(
        sidecar, f"/api/v1/sources/{source_id}/health", token=sidecar.token
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["items"][0]["checked_at"] == "2026-11-16T09:02:00.000Z"
    assert body["items"][0]["status"] == "healthy"

    limited = http(
        sidecar,
        f"/api/v1/sources/{source_id}/health",
        token=sidecar.token,
        params={"limit": "1"},
    ).json()
    assert len(limited["items"]) == 1

    missing = http(
        sidecar, f"/api/v1/sources/{uuid.uuid4()}/health", token=sidecar.token
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "source_not_found"


def test_reading_state_and_favorite_endpoints(sidecar: Sidecar) -> None:
    """Phase 5 write endpoints must run against a real writable DB session."""

    source_id = _create_source(sidecar)
    article_id = _seed_article(sidecar, source_id, 1)

    read = http(
        sidecar,
        f"/api/v1/articles/{article_id}/mark-read",
        method="POST",
        token=sidecar.token,
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["reading_status"] == "read"
    assert body["read_count"] == 1

    later = http(
        sidecar,
        f"/api/v1/articles/{article_id}/mark-later",
        method="POST",
        token=sidecar.token,
    )
    assert later.status_code == 200, later.text
    assert later.json()["reading_status"] == "later"

    unread = http(
        sidecar,
        f"/api/v1/articles/{article_id}/mark-unread",
        method="POST",
        token=sidecar.token,
    )
    assert unread.status_code == 200, unread.text
    assert unread.json()["reading_status"] == "unread"

    favorite = http(
        sidecar,
        f"/api/v1/articles/{article_id}/favorite",
        method="PUT",
        token=sidecar.token,
        json_body={"is_favorite": True},
    )
    assert favorite.status_code == 200, favorite.text
    assert favorite.json()["is_favorite"] is True

    patched = http(
        sidecar,
        f"/api/v1/articles/{article_id}/reading-state",
        method="PATCH",
        token=sidecar.token,
        json_body={"reading_status": "read", "is_favorite": False},
    )
    assert patched.status_code == 200, patched.text
    final = patched.json()
    assert final["reading_status"] == "read"
    assert final["is_favorite"] is False
