"""The 今日 overview must be computed from real tables, not placeholders."""

from __future__ import annotations

from services import today_service

from personalization_support import create_event, seed_article_with_analysis


def _interest() -> dict:
    from services import personalization_service as svc

    return svc.create_interest(
        {
            "name": "人工智能",
            "interest_type": "domain",
            "domain_key": "technology",
            "level": "core",
        }
    )


def test_overview_returns_real_picks_and_automation(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest()

    payload = today_service.overview()

    assert payload["automation"]["enabled"] is True
    assert payload["automation"]["paused"] is False
    assert isinstance(payload["metrics"]["recommended_total"], int)
    ranked_ids = {
        item["target_id"]
        for item in payload["picks"] + payload["todo"]
        if item.get("target_type") == "article"
    }
    assert article["article_id"] in ranked_ids
    assert payload["recent_reads"] == []


def test_overview_limits_sections(ready) -> None:
    for index in range(8):
        seed_article_with_analysis(
            title=f"AI Agent 平台发布新版本 {index}", category="科技"
        )
    _interest()

    payload = today_service.overview(pick_limit=3, todo_limit=4)
    assert len(payload["picks"]) <= 3
    assert len(payload["todo"]) <= 4


def test_overview_lists_recent_reads(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest()

    from database import session as write_session
    from database.repositories import article_repository as article_repo

    with write_session() as conn:
        article_repo.mark_read(conn, article["article_id"])

    payload = today_service.overview()
    assert [item["id"] for item in payload["recent_reads"]] == [article["article_id"]]


def test_single_article_events_are_not_home_page_events(ready) -> None:
    first = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    second = seed_article_with_analysis(title="AI Agent 平台融资进展", category="科技")
    lonely = seed_article_with_analysis(title="AI Agent 行业观察", category="科技")
    single_id = create_event(
        title="单篇报道不足以成为重点事件",
        category="科技",
        article_ids=[lonely["article_id"]],
        score=80.0,
    )
    multi_id = create_event(
        title="多来源报道同一事件",
        category="科技",
        article_ids=[first["article_id"], second["article_id"]],
        score=80.0,
    )
    _interest()

    payload = today_service.overview()
    event_ids = {item["target_id"] for item in payload["events"]}
    pick_ids = {item["target_id"] for item in payload["picks"] if item["target_type"] == "event"}

    assert payload["metrics"]["multi_report_events"] >= 1
    assert multi_id in pick_ids | event_ids
    assert single_id not in event_ids
    assert single_id not in pick_ids
    assert not (event_ids & pick_ids)
