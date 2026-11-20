"""`/api/v1/today/overview` must return real, bounded home-page data."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid

from core.timeutil import utc_timestamp
from support import Sidecar, assert_json_headers, http


def _create_source(sidecar: Sidecar) -> str:
    response = http(
        sidecar,
        "/api/v1/sources",
        method="POST",
        token=sidecar.token,
        json_body={
            "name": "Today Source",
            "source_type": "rss",
            "url": "https://today.example.com/feed.xml",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_article(sidecar: Sidecar, source_id: str, index: int) -> str:
    article_id = str(uuid.uuid4())
    now = utc_timestamp()
    conn = sqlite3.connect(str(sidecar.data_dir / "pih.sqlite3"))
    try:
        conn.execute(
            """
            INSERT INTO articles (
                id, source_id, external_id, canonical_url, original_url, title,
                author, summary, content_text, content_state, published_at,
                source_updated_at, fetched_at, content_hash, status,
                created_at, updated_at, deleted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                article_id,
                source_id,
                f"today-{index}",
                f"https://today.example.com/{index}",
                f"https://today.example.com/{index}",
                f"今日文章 {index}",
                None,
                "今天值得关注的完整摘要内容，长度足够用于推荐与首页展示。",
                None,
                "summary_only",
                now,
                None,
                now,
                hashlib.sha256(f"today-{index}".encode()).hexdigest(),
                "active",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return article_id


def test_today_overview_shape_and_limits(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    ids = [_seed_article(sidecar, source_id, index) for index in range(1, 7)]

    response = http(
        sidecar,
        "/api/v1/today/overview",
        token=sidecar.token,
        params={"picks": "3", "todo": "4"},
    )
    assert response.status_code == 200, response.text
    assert_json_headers(response)
    body = response.json()

    assert body["metrics"]["today_articles"] >= len(ids)
    assert len(body["picks"]) <= 3
    assert len(body["todo"]) <= 4
    assert "automation" in body
    assert isinstance(body["automation"]["enabled"], bool)
    assert isinstance(body["recent_reads"], list)


def test_today_overview_rejects_out_of_range_limits(sidecar: Sidecar) -> None:
    assert (
        http(
            sidecar,
            "/api/v1/today/overview",
            token=sidecar.token,
            params={"picks": "50"},
        ).status_code
        == 422
    )
