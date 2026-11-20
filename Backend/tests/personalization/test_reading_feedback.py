"""Reading behaviour must feed back into explainable recommendations."""

from __future__ import annotations

import database
from database import session as write_session
from database.repositories import article_repository as article_repo
from services import personalization_service as svc

from personalization_support import seed_article_with_analysis


def _interest(name: str = "人工智能") -> dict:
    return svc.create_interest(
        {
            "name": name,
            "interest_type": "domain",
            "domain_key": "technology",
            "level": "core",
        }
    )


def test_favorite_boosts_article_and_records_reason(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest()
    svc.recompute()
    before = svc.recommendation_detail("article", article["article_id"])

    with write_session() as conn:
        article_repo.set_reading_state(
            conn, article["article_id"], is_favorite=True
        )

    svc.feed()
    after = svc.recommendation_detail("article", article["article_id"])
    assert after["score"] > before["score"]
    assert "FAVORITE_BOOST" in after["reason_codes"]


def test_read_article_is_demoted_and_excluded_from_feed(ready) -> None:
    read = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    other = seed_article_with_analysis(title="AI Agent 创业公司观察", category="科技")
    _interest()
    svc.recompute()
    baseline = svc.recommendation_detail("article", read["article_id"])

    with write_session() as conn:
        article_repo.mark_read(conn, read["article_id"])

    feed = svc.feed()
    ids = {
        item["target_id"]
        for section in feed["sections"].values()
        for item in section
        if isinstance(item, dict) and item.get("target_type") == "article"
    }
    assert read["article_id"] not in ids
    assert other["article_id"] in ids

    detail = svc.recommendation_detail("article", read["article_id"])
    assert detail["score"] < baseline["score"]
    assert "ALREADY_READ" in detail["reason_codes"]


def test_later_does_not_change_interest_score(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest()
    svc.recompute()
    before = svc.recommendation_detail("article", article["article_id"])

    with write_session() as conn:
        article_repo.mark_later(conn, article["article_id"])

    svc.feed()
    after = svc.recommendation_detail("article", article["article_id"])
    assert after["score"] == before["score"]
    assert "SAVED_FOR_LATER" in after["reason_codes"]


def test_reading_change_invalidates_recommendation_snapshot(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest()
    svc.feed()
    with database.read_session() as conn:
        version_before = conn.execute(
            "SELECT inputs_version FROM recommendation_results WHERE target_id = ?",
            (article["article_id"],),
        ).fetchone()[0]

    with write_session() as conn:
        article_repo.set_reading_state(conn, article["article_id"], is_favorite=True)

    svc.feed()
    with database.read_session() as conn:
        version_after = conn.execute(
            "SELECT inputs_version FROM recommendation_results WHERE target_id = ?",
            (article["article_id"],),
        ).fetchone()[0]
    assert version_after != version_before
