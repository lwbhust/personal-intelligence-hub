"""Collection job API tests (deterministic; no public network)."""

from __future__ import annotations

import sqlite3
import time
import uuid

from core.timeutil import utc_timestamp
from support import Sidecar, assert_json_headers, http


def _create_source(
    sidecar: Sidecar,
    *,
    name: str = "Example",
    url: str = "https://example.invalid/feed",
    source_type: str = "rss",
    enabled: bool = True,
) -> str:
    response = http(
        sidecar,
        "/api/v1/sources",
        method="POST",
        token=sidecar.token,
        json_body={
            "name": name,
            "source_type": source_type,
            "url": url,
            "enabled": enabled,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_job(sidecar: Sidecar, source_id: str, *, status: str = "failed") -> str:
    job_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    now = utc_timestamp()
    conn = sqlite3.connect(str(sidecar.data_dir / "pih.sqlite3"))
    try:
        conn.execute(
            """
            INSERT INTO collection_jobs (
                id, trigger_type, scope, status, requested_source_count,
                processed_source_count, succeeded_source_count, failed_source_count,
                discovered_count, inserted_count, updated_count, duplicate_count,
                error_count, error_message, cancel_requested, started_at,
                finished_at, duration_ms, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                "manual",
                "single_source",
                status,
                1,
                1,
                0 if status == "failed" else 1,
                1 if status == "failed" else 0,
                3,
                0,
                0,
                0,
                1 if status == "failed" else 0,
                "目标资源返回 404" if status == "failed" else None,
                0,
                now,
                now,
                5,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO collection_job_items (
                id, job_id, source_id, status, http_status, discovered_count,
                inserted_count, updated_count, duplicate_count, error_count,
                error_code, error_message, started_at, finished_at, duration_ms,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item_id,
                job_id,
                source_id,
                "failed" if status == "failed" else "succeeded",
                404 if status == "failed" else 200,
                3,
                0,
                0,
                0,
                1 if status == "failed" else 0,
                "http_client_error" if status == "failed" else None,
                "目标资源返回 404" if status == "failed" else None,
                now,
                now,
                5,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def test_collection_status_and_empty_error(sidecar: Sidecar) -> None:
    status = http(sidecar, "/api/v1/collection/status", token=sidecar.token)
    assert status.status_code == 200
    assert_json_headers(status)
    body = status.json()
    assert body["scheduler_enabled"] is False
    assert body["max_concurrency"] == 3
    assert body["running_job_id"] is None

    empty = http(
        sidecar,
        "/api/v1/collection-jobs",
        method="POST",
        token=sidecar.token,
        json_body={"trigger_type": "manual", "source_ids": None},
    )
    assert empty.status_code == 409
    assert empty.json()["error"]["code"] == "no_enabled_sources"


def test_collect_disabled_and_unsupported_sources(sidecar: Sidecar) -> None:
    disabled = _create_source(sidecar, name="Disabled", enabled=False)
    response = http(
        sidecar,
        f"/api/v1/sources/{disabled}/collect",
        method="POST",
        token=sidecar.token,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_not_collectable"

    website = _create_source(
        sidecar,
        name="Website",
        url="https://example.com/blog",
        source_type="website",
    )
    unsupported = http(
        sidecar,
        f"/api/v1/sources/{website}/collect",
        method="POST",
        token=sidecar.token,
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "adapter_not_supported"

    missing = http(
        sidecar,
        f"/api/v1/sources/{uuid.uuid4()}/collect",
        method="POST",
        token=sidecar.token,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "source_not_found"


def test_job_list_detail_cancel_and_retry(sidecar: Sidecar) -> None:
    source_id = _create_source(sidecar)
    job_id = _seed_job(sidecar, source_id, status="failed")

    listing = http(sidecar, "/api/v1/collection-jobs", token=sidecar.token)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == job_id
    assert body["items"][0]["items"] == []

    filtered = http(
        sidecar,
        "/api/v1/collection-jobs",
        token=sidecar.token,
        params={"status": "failed"},
    ).json()
    assert filtered["total"] == 1

    detail = http(sidecar, f"/api/v1/collection-jobs/{job_id}", token=sidecar.token)
    assert detail.status_code == 200
    assert detail.json()["items"][0]["error_code"] == "http_client_error"

    missing = http(
        sidecar, f"/api/v1/collection-jobs/{uuid.uuid4()}", token=sidecar.token
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"

    cancelled = http(
        sidecar,
        f"/api/v1/collection-jobs/{job_id}/cancel",
        method="POST",
        token=sidecar.token,
    )
    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["code"] == "job_not_cancellable"

    retry = http(
        sidecar,
        f"/api/v1/collection-jobs/{job_id}/retry",
        method="POST",
        token=sidecar.token,
    )
    assert retry.status_code == 202, retry.text
    retried = retry.json()
    assert retried["status"] == "pending"
    assert retried["requested_source_count"] == 1

    # The worker may already have claimed the job; cancellation is still
    # accepted and must be reflected in cancel_requested.
    pending_id = retried["id"]
    cancel_pending = http(
        sidecar,
        f"/api/v1/collection-jobs/{pending_id}/cancel",
        method="POST",
        token=sidecar.token,
    )
    assert cancel_pending.status_code == 200
    cancelled_body = cancel_pending.json()
    assert cancelled_body["cancel_requested"] is True
    assert cancelled_body["status"] in {"pending", "running", "cancelled"}

    # Wait for the job to reach a terminal state so no work leaks into other tests.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = http(
            sidecar, f"/api/v1/collection-jobs/{pending_id}", token=sidecar.token
        ).json()
        if current["status"] in {
            "succeeded",
            "partially_succeeded",
            "failed",
            "cancelled",
        }:
            break
        time.sleep(0.05)
    assert current["status"] == "cancelled"

    unsupported_status = http(
        sidecar,
        "/api/v1/collection-jobs",
        token=sidecar.token,
        params={"status": "unknown"},
    )
    assert unsupported_status.status_code == 422


def test_job_endpoints_require_authentication(sidecar: Sidecar) -> None:
    for method, path in (
        ("GET", "/api/v1/collection-jobs"),
        ("POST", "/api/v1/collection-jobs"),
        ("GET", "/api/v1/collection/status"),
    ):
        response = http(sidecar, path, method=method)
        assert response.status_code == 401, (method, path)
