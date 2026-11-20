"""Pure algorithm tests for `personal-reco-v1` (no database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from event_intelligence import personalization as algo

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _signal(**overrides) -> algo.InterestSignal:
    payload = {
        "id": "i1",
        "name": "人工智能",
        "interest_type": "domain",
        "level": "core",
        "weight": 1.0,
        "domain_key": "technology",
    }
    payload.update(overrides)
    return algo.InterestSignal(**payload)


def _input(**overrides) -> algo.MatchInput:
    payload = {
        "title": "AI Agent 平台发布新版本",
        "summary": "面向企业的智能体平台",
        "category": "科技",
        "source_id": "s1",
        "source_name": "测试源",
        "entity_ids": (),
        "entity_names": (),
    }
    payload.update(overrides)
    return algo.MatchInput(**payload)


def test_core_domain_match_beats_general_keyword_match() -> None:
    core = algo.match_interests([_signal()], _input())
    general = algo.match_interests(
        [
            _signal(
                id="i2",
                name="机器人",
                interest_type="keyword",
                level="general",
                weight=0.3,
                domain_key=None,
                keywords=("机器人",),
            )
        ],
        _input(title="机器人公司发布新品", category="其他"),
    )
    assert core.score > general.score
    assert "CORE_INTEREST_MATCH" in core.reason_codes


def test_exclusion_keyword_blocks_interest() -> None:
    result = algo.match_interests(
        [_signal(exclusion_keywords=("融资",))],
        _input(summary="该公司完成新一轮融资"),
    )
    assert result.matched_interests == ()
    assert "EXCLUDED_KEYWORD" in result.warnings
    assert result.score == algo.DEFAULT_CONFIG["unmatched_interest_score"]


def test_keyword_only_match_is_flagged() -> None:
    result = algo.match_interests(
        [
            _signal(
                id="i3",
                name="大模型",
                interest_type="keyword",
                level="core",
                weight=1.0,
                domain_key=None,
                keywords=("大模型",),
            )
        ],
        _input(title="大模型创业公司观察", category="财经"),
    )
    assert "KEYWORD_ONLY_MATCH" in result.warnings


def test_no_interests_is_neutral_not_zero() -> None:
    result = algo.match_interests([], _input())
    assert result.score == 50.0
    assert "NO_INTERESTS_CONFIGURED" in result.warnings


def test_unknown_source_quality_is_neutral_with_warning() -> None:
    score, warnings = algo.source_quality_score(None)
    assert score == 50.0
    assert warnings == ("SOURCE_QUALITY_UNKNOWN",)


def test_recency_decays_with_time() -> None:
    fresh = algo.recency_score(
        (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z"), now=NOW
    )
    old = algo.recency_score(
        (NOW - timedelta(days=20)).isoformat().replace("+00:00", "Z"), now=NOW
    )
    assert fresh == 100.0
    assert old < 50.0


def test_major_event_fallback_raises_score_and_flags() -> None:
    match = algo.MatchResult(
        score=15.0,
        matched_interests=(),
        matched_entity_names=(),
        reason_codes=(),
        warnings=(),
    )
    scored = algo.score_item(
        match=match,
        importance=62.0,
        novelty=80.0,
        credibility=None,
        published_at=(NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        now=NOW,
        weights=algo.merge_weights(None),
        thresholds=algo.merge_thresholds(None),
        feedback=None,
        is_event=True,
    )
    assert scored.is_fallback is True
    assert scored.score >= 70.0
    assert "MAJOR_EVENT_FALLBACK" in scored.reason_codes


def test_threshold_ladder_is_monotonic() -> None:
    thresholds = algo.merge_thresholds({"must_read": 60, "recommended": 90, "watch": 80, "low": 70})
    assert thresholds["must_read"] > thresholds["recommended"] > thresholds["watch"] > thresholds["low"]
    assert algo.level_for(95, thresholds) == "must_read"
    assert algo.level_for(10, thresholds) == "not_recommended"


def test_dimension_weights_are_normalised() -> None:
    weights = algo.merge_weights({"interest": 2, "importance": 1})
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_negative_feedback_lowers_score() -> None:
    match = algo.MatchResult(
        score=80.0,
        matched_interests=("人工智能",),
        matched_entity_names=(),
        reason_codes=("CORE_INTEREST_MATCH",),
        warnings=(),
    )
    base = algo.score_item(
        match=match,
        importance=50.0,
        novelty=80.0,
        credibility=0.8,
        published_at=(NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        now=NOW,
        weights=algo.merge_weights(None),
        thresholds=algo.merge_thresholds(None),
        feedback="interested",
        is_event=False,
    )
    lowered = algo.score_item(
        match=match,
        importance=50.0,
        novelty=80.0,
        credibility=0.8,
        published_at=(NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        now=NOW,
        weights=algo.merge_weights(None),
        thresholds=algo.merge_thresholds(None),
        feedback="not_interested",
        is_event=False,
    )
    assert lowered.score < base.score


def test_keyword_hit_respects_latin_word_boundary() -> None:
    assert algo.keyword_hit("AI Agent platform", "AI")
    assert not algo.keyword_hit("said the company", "AI")
    assert algo.keyword_hit("机器学习平台", "机器学习")


def test_keyword_hit_treats_cjk_as_boundary_for_latin_keywords() -> None:
    assert algo.keyword_hit("大厂AI对照系", "AI")
    assert algo.keyword_hit("英伟达GPU新品", "GPU")
    assert not algo.keyword_hit("maintain the system", "AI")
