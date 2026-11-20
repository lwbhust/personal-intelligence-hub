"""Recommendation service behaviour on a real temporary database."""

from __future__ import annotations

import database
from database.repositories import personalization_repository as repo
from services import personalization_service as svc

from personalization_support import (
    create_event,
    create_entity,
    link_article_entity,
    seed_article_with_analysis,
    set_source_credibility,
)


def _interest(name: str, **overrides) -> dict:
    payload = {
        "name": name,
        "interest_type": "domain",
        "domain_key": "technology",
        "level": "core",
    }
    payload.update(overrides)
    return svc.create_interest(payload)


def test_event_recommendation_uses_event_score_and_interest(ready) -> None:
    first = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    second = seed_article_with_analysis(title="国际会议开幕", category="国际")
    set_source_credibility(first["source_id"], 0.8)
    event_id = create_event(
        title="AI Agent 平台发布新版本",
        category="科技",
        article_ids=[first["article_id"], second["article_id"]],
        score=62.0,
    )
    _interest("人工智能")

    result = svc.recompute()
    assert result["events_scored"] >= 1

    detail = svc.recommendation_detail("event", event_id)
    assert detail["target_type"] == "event"
    assert detail["score"] >= 70
    assert detail["score_breakdown"]["importance"] == 62.0
    assert "人工智能" in detail["matched_interests"]
    assert detail["event_id"] == event_id
    assert detail["summary"] == "事件摘要"

    with database.read_session() as conn:
        article_result = repo.get_current_result(
            conn, target_type="article", target_id=first["article_id"]
        )
    assert article_result is None or article_result.event_id is not None


def test_standalone_article_recommendation_and_low_priority(ready) -> None:
    matched = seed_article_with_analysis(title="AI Agent 产品更新", category="科技")
    unmatched = seed_article_with_analysis(title="本地文化活动", category="文化")
    _interest("人工智能")
    svc.recompute()

    high = svc.recommendation_detail("article", matched["article_id"])
    low = svc.recommendation_detail("article", unmatched["article_id"])
    assert high["score"] > low["score"]
    assert high["level"] in {"recommended", "must_read", "watch"}
    assert high["warnings"]
    assert high["summary"] == "测试摘要"


def test_negative_feedback_lowers_event_score(ready) -> None:
    first = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    event_id = create_event(
        title="AI Agent 平台发布新版本",
        category="科技",
        article_ids=[first["article_id"]],
        score=55.0,
    )
    _interest("人工智能")
    svc.recompute()
    before = svc.recommendation_detail("event", event_id)

    updated = svc.submit_feedback(
        target_type="event",
        target_id=event_id,
        feedback="not_interested",
    )
    after = updated["recommendation"]
    assert after["score"] < before["score"]
    assert "FEEDBACK_NOT_INTERESTED" in after["reason_codes"]
    assert after["feedback"]["feedback"] == "not_interested"

    svc.revoke_feedback_for_target("event", event_id)
    restored = svc.recommendation_detail("event", event_id)
    assert restored["feedback"] is None
    assert restored["score"] == before["score"]


def test_important_feedback_lifts_score(ready) -> None:
    article = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest("人工智能")
    svc.recompute()
    before = svc.recommendation_detail("article", article["article_id"])
    svc.submit_feedback(
        target_type="article", target_id=article["article_id"], feedback="important"
    )
    after = svc.recommendation_detail("article", article["article_id"])
    assert after["score"] > before["score"]
    assert "FEEDBACK_IMPORTANT" in after["reason_codes"]


def test_event_interest_change_triggers_recompute(ready) -> None:
    first = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    event_id = create_event(
        title="AI Agent 平台发布新版本",
        category="科技",
        article_ids=[first["article_id"]],
        score=60.0,
    )
    interest = _interest("人工智能")
    svc.feed()
    before = svc.recommendation_detail("event", event_id)

    svc.update_interest(interest["id"], {"level": "muted", "weight": 0.0})
    feed = svc.feed()
    after = svc.recommendation_detail("event", event_id)
    assert after["score"] < before["score"]
    assert after["matched_interests"] == []
    assert feed["has_core_interest"] is False


def test_blocked_source_disappears_from_feed(ready) -> None:
    blocked = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    visible = seed_article_with_analysis(title="AI Agent 创业公司观察", category="科技")
    _interest("人工智能")
    svc.feed()
    svc.block_source(blocked["source_id"], "重复转载")
    feed = svc.feed()
    ids = {
        item["target_id"]
        for section in feed["sections"].values()
        for item in section
        if isinstance(item, dict) and item.get("target_type") == "article"
    }
    assert blocked["article_id"] not in ids
    assert visible["article_id"] in ids


def test_entity_interest_matches_article_entities(ready) -> None:
    entity_id = create_entity("OpenAI")
    article = seed_article_with_analysis(title="OpenAI 发布新模型", category="财经")
    link_article_entity(article["article_id"], entity_id)
    interest = _interest("OpenAI", interest_type="entity", domain_key=None, level="extended")
    svc.link_interest_entity(interest["id"], entity_id)
    svc.recompute()

    detail = svc.recommendation_detail("article", article["article_id"])
    assert detail["matched_entities"] == ["OpenAI"]
    assert "TRACKED_ENTITY" in detail["reason_codes"]


def test_exclusion_keyword_reduces_match(ready) -> None:
    article = seed_article_with_analysis(
        title="AI Agent 平台完成融资", category="科技"
    )
    interest = _interest("人工智能")
    svc.update_interest(interest["id"], {"exclusion_keywords": ["融资"]})
    svc.recompute()

    detail = svc.recommendation_detail("article", article["article_id"])
    assert detail["matched_interests"] == []
    assert "EXCLUDED_KEYWORD" in detail["warnings"]


def test_ensure_fresh_is_idempotent_without_changes(ready) -> None:
    seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    _interest("人工智能")
    first = svc.ensure_fresh()
    second = svc.ensure_fresh()
    assert first["recomputed"] is True
    assert second["recomputed"] is False


def test_pipeline_refresh_hook_updates_one_event(ready) -> None:
    first = seed_article_with_analysis(title="AI Agent 平台发布新版本", category="科技")
    event_id = create_event(
        title="AI Agent 平台发布新版本",
        category="科技",
        article_ids=[first["article_id"]],
        score=58.0,
    )
    _interest("人工智能")
    svc.refresh_event(event_id)
    detail = svc.recommendation_detail("event", event_id)
    assert detail["target_type"] == "event"
    assert detail["score"] > 0

    # A missing/blocked event must never break the pipeline hook.
    svc.refresh_event("00000000-0000-4000-8000-000000000000")
