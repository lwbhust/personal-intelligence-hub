"""Unified taxonomy: resolution, event-domain voting and scoring bases."""

from __future__ import annotations

import pytest

from event_intelligence.scoring import SCORING_FALLBACK_BASE, compute_scores, ScoreInputs
from event_intelligence.taxonomy import (
    derive_event_domain,
    resolve_category,
    scoring_base_for,
    source_category_route,
    taxonomy_document,
)


@pytest.mark.parametrize(
    ("value", "domain"),
    [
        ("科技", "technology"),
        ("technology", "technology"),
        ("人工智能", "technology"),
        ("财经", "finance"),
        ("能源", "finance"),
        ("国际", "international"),
        ("军事", "international"),
        ("社会", "society"),
        ("环境", "society"),
        ("安全", "society"),
        ("其他", "other"),
    ],
)
def test_category_resolves_to_stored_domain(value: str, domain: str) -> None:
    resolution = resolve_category(value)
    assert resolution.known is True
    assert resolution.domain_key == domain


def test_unknown_category_stays_unresolved() -> None:
    resolution = resolve_category("外星文明")
    assert resolution.known is False
    assert resolution.domain_key is None
    assert "待确认" in resolution.detail


def test_source_category_is_only_a_routing_hint() -> None:
    route = source_category_route("tech")
    assert route.authoritative is False
    assert route.hint_topic_key == "technology"
    assert "路由提示" in route.note
    unknown = source_category_route("mystery")
    assert unknown.hint_domain_key is None
    assert unknown.authoritative is False


def test_primary_article_wins_a_tie() -> None:
    decision = derive_event_domain([("科技", True), ("国际", False)])
    assert decision.domain_name == "科技"
    assert decision.resolved is True
    assert decision.confidence == pytest.approx(2 / 3, rel=1e-3)


def test_follow_up_reports_can_change_the_domain() -> None:
    decision = derive_event_domain(
        [("科技", True), ("国际", False), ("国际", False), ("国际", False)]
    )
    assert decision.domain_name == "国际"
    assert decision.confidence == pytest.approx(3 / 5, rel=1e-3)


def test_event_without_analysis_is_unresolved_not_other() -> None:
    decision = derive_event_domain([(None, True), (None, False)])
    assert decision.resolved is False
    assert decision.domain_key == "other"
    assert decision.unknown_members == 2
    assert "待确认" in decision.reason


def test_scoring_uses_dictionary_bases_and_neutral_fallback() -> None:
    assert scoring_base_for("政治") == 60.0
    assert scoring_base_for("politics") == 60.0
    assert scoring_base_for("能源") == 55.0
    assert scoring_base_for("完全未知") == SCORING_FALLBACK_BASE == 40.0

    known = compute_scores(ScoreInputs(category="科技"))
    unknown = compute_scores(ScoreInputs(category="完全未知"))
    other = compute_scores(ScoreInputs(category="其他"))
    assert unknown.importance > other.importance
    assert known.importance > other.importance


def test_taxonomy_document_is_complete_and_serialisable() -> None:
    document = taxonomy_document()
    assert document["version"] == "taxonomy-v1"
    assert len(document["domains"]) == 10
    assert any(item["key"] == "ai" for item in document["topics"])
    assert all(item["authoritative"] is False for item in document["source_routes"])
