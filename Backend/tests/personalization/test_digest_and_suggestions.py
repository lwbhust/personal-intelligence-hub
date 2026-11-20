"""Daily digest and interest-suggestion tests on a real database."""

from __future__ import annotations

import database
from services import personalization_service as svc

from personalization_support import create_event, seed_article_with_analysis


def _interest(name: str, **overrides) -> dict:
    payload = {
        "name": name,
        "interest_type": "domain",
        "domain_key": "technology",
        "level": "general",
    }
    payload.update(overrides)
    return svc.create_interest(payload)


def test_digest_items_reference_real_rows(ready) -> None:
    article = seed_article_with_analysis(
        title="AI Agent 平台发布新版本", category="科技", published_hours_ago=0
    )
    event_id = create_event(
        title="AI Agent 平台发布新版本",
        category="科技",
        article_ids=[article["article_id"]],
        score=62.0,
    )
    _interest("人工智能", level="core", weight=1.0)

    digest = svc.digest_today()
    assert digest["status"] == "succeeded"
    assert digest["ai_status"] == "skipped"
    assert digest["items"]
    assert digest["stats"]["totals"]["articles_today"] >= 1

    targets = {(item["target_type"], item["target_id"]) for item in digest["items"]}
    assert ("event", event_id) in targets
    with database.read_session() as conn:
        for target_type, target_id in targets:
            if target_type == "event":
                row = conn.execute("SELECT 1 FROM events WHERE id = ?", (target_id,)).fetchone()
                assert row is not None
            elif target_type == "article":
                row = conn.execute("SELECT 1 FROM articles WHERE id = ?", (target_id,)).fetchone()
                assert row is not None


def test_digest_is_idempotent_and_force_supersedes(ready) -> None:
    seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest("人工智能", level="core", weight=1.0)
    first = svc.digest_today()
    second = svc.digest_today()
    assert second["id"] == first["id"]

    third = svc.digest_today(force=True)
    assert third["id"] != first["id"]
    with database.read_session() as conn:
        statuses = {
            str(row[0])
            for row in conn.execute(
                "SELECT status FROM daily_digests WHERE digest_date = ?",
                (first["digest_date"],),
            )
        }
    assert "succeeded" in statuses
    assert "superseded" in statuses

    history = svc.digest_history(limit=10, offset=0)
    assert history["total"] == 1


def test_digest_without_interests_degrades_but_still_generates(ready) -> None:
    seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    digest = svc.digest_today()
    assert digest["status"] == "succeeded"
    assert digest["headline"]


def test_digest_for_missing_date_requires_generate(ready) -> None:
    from services.errors import ServiceError

    try:
        svc.digest_for_date("2020-01-01", generate=False)
    except ServiceError as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected digest_not_found")


def test_suggestions_require_three_feedback(ready) -> None:
    first = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    second = seed_article_with_analysis(title="AI Agent 框架升级", category="科技")
    third = seed_article_with_analysis(title="AI Agent 工具链发布", category="科技")
    interest = _interest("人工智能", level="general")
    svc.recompute()

    for seed in (first, second):
        svc.submit_feedback(
            target_type="article", target_id=seed["article_id"], feedback="interested"
        )
    assert svc.suggestions()["total"] == 0

    svc.submit_feedback(
        target_type="article", target_id=third["article_id"], feedback="interested"
    )
    suggestions = svc.suggestions()
    assert suggestions["total"] == 1
    entry = suggestions["items"][0]
    assert entry["interest_id"] == interest["id"]
    assert entry["direction"] == "increase"
    assert entry["suggested_level"] in {"extended", "core"}
    assert entry["positive_feedback"] == 3
    assert suggestions["auto_adjust_enabled"] is True


def test_suggestions_from_negative_feedback(ready) -> None:
    seeds = [
        seed_article_with_analysis(title=f"AI Agent 观察 {index}", category="科技")
        for index in range(3)
    ]
    interest = _interest("人工智能", level="core", weight=1.0)
    svc.recompute()
    for seed in seeds:
        svc.submit_feedback(
            target_type="article", target_id=seed["article_id"], feedback="not_interested"
        )
    suggestions = svc.suggestions()
    assert suggestions["total"] == 1
    entry = suggestions["items"][0]
    assert entry["interest_id"] == interest["id"]
    assert entry["direction"] == "decrease"
    assert entry["suggested_level"] == "extended"


def test_feedback_history_preserved_after_replacement(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    first = svc.submit_feedback(
        target_type="article", target_id=article["article_id"], feedback="interested"
    )["feedback"]
    svc.submit_feedback(
        target_type="article", target_id=article["article_id"], feedback="duplicate"
    )
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT feedback, revoked_at FROM recommendation_feedback WHERE target_id = ? "
            "ORDER BY created_at",
            (article["article_id"],),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["feedback"] == "interested"
    assert rows[0]["revoked_at"] is not None
    assert rows[1]["revoked_at"] is None
    assert first["id"]


def test_feedback_on_event_member_article_has_no_article_recommendation(ready) -> None:
    """Phase 8.0: feedback must succeed even when the article is event evidence."""

    article = seed_article_with_analysis(
        title="储能电站项目并网投运", category="科技"
    )
    create_event(
        title="储能电站项目并网投运",
        category="科技",
        article_ids=[article["article_id"]],
        score=60.0,
    )
    _interest("电力行业与能源技术", level="core", weight=1.0)
    svc.recompute()

    result = svc.submit_feedback(
        target_type="article",
        target_id=article["article_id"],
        feedback="not_interested",
    )
    assert result["feedback"]["feedback"] == "not_interested"
    assert result["recommendation"] is None
    with database.read_session() as conn:
        row = conn.execute(
            "SELECT feedback FROM recommendation_feedback WHERE target_id = ? "
            "AND revoked_at IS NULL",
            (article["article_id"],),
        ).fetchone()
    assert row is not None and row["feedback"] == "not_interested"
