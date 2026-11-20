"""Phase 7.1 — deterministic statistics, generation, dedupe and degradation."""

from __future__ import annotations

import pytest

import database
from services.intelligence_service import IntelligenceService
from services.intelligence_stats import build_stats, period_for

from intelligence_support import StubProvider, default_seed, seed_graph, wait_for


def _daily_stats(stats):
    totals = stats["totals"]
    assert totals["articles"] >= 3
    assert totals["events"] >= 1
    assert totals["new_events"] >= 1


def test_daily_stats_are_real_database_numbers(ready):
    seeded = default_seed()
    start, end = period_for("daily")
    with database.read_session() as conn:
        stats = build_stats(conn, report_type="daily", period_start=start, period_end=end)

    _daily_stats(stats)
    keys = {item["keyword"] for item in stats["rising_keywords"]}
    assert "量子计算" in keys
    assert stats["key_events"][0]["event_id"] == seeded["events"][0]
    assert stats["key_events"][0]["scores"]["importance"] == 80.0
    evidence_ids = {
        item["article_id"] for item in stats["key_events"][0]["evidence"]
    }
    assert set(seeded["articles"]) <= evidence_ids
    category_names = {item["name"]: item["articles"] for item in stats["categories"]}
    assert category_names.get("科技", 0) >= 2


def test_generation_persists_validated_ai_sections(ready):
    seeded = default_seed()
    event_id = seeded["events"][0]
    article_id = seeded["articles"][0]
    brief = {
        "development": "量子计算芯片进入测试阶段。",
        "background": "近期多家企业公布量子计算路线图。",
        "impact": "可能推动相关芯片供应链变化。",
        "importance": "多来源共同报道，热度较高。",
        "entities": ["测试实体", "虚构实体"],
        "article_ids": [article_id, "hallucinated-article"],
    }
    overview = {
        "headline": "量子计算成为今日主线",
        "overview": "多家来源同时报道量子计算进展，形成当日最主要的事件。",
        "topics": [
            {
                "name": "量子计算",
                "direction": "报道密度明显上升",
                "evidence_event_ids": [event_id],
            },
            {
                "name": "无证据主题",
                "direction": "未提供证据",
                "evidence_event_ids": ["unknown"],
            },
        ],
        "uncertainties": ["样本仅覆盖最近一天。"],
    }
    service = IntelligenceService(provider=StubProvider(payloads=[brief, overview]))
    try:
        service.start()
        record, reused = service.create_report(report_type="daily")
        assert reused is False
        finished, citations = wait_for(service, record.id)
    finally:
        service.stop()

    assert finished.status == "succeeded"
    assert finished.ai_status == "used"
    assert finished.headline == "量子计算成为今日主线"
    assert finished.model_name == "qwen3.5:4b-mlx"
    assert finished.article_count >= 3
    # Unknown article id and entity are dropped; the brief stays traceable.
    assert [item["event_id"] for item in finished.content["key_events"]] == [event_id]
    assert finished.content["key_events"][0]["entities"] == ["测试实体"]
    assert finished.content["key_events"][0]["article_ids"] == [article_id]
    assert [item["name"] for item in finished.content["topics"]] == ["量子计算"]
    assert "topic_without_evidence_dropped" in finished.content["warnings"]

    event_citations = [
        item for item in citations
        if item.citation_type == "event" and item.section_key == "key_events"
    ]
    article_citations = [
        item for item in citations
        if item.citation_type == "article" and item.ref_id == article_id
    ]
    assert [item.ref_id for item in event_citations] == [event_id]
    assert article_citations and article_citations[0].title
    assert finished.citation_count == len(citations)


def test_invalid_brief_degrades_instead_of_fabricating(ready):
    seeded = default_seed()
    brief = {"development": "", "impact": "", "article_ids": ["unknown"]}
    overview = {"headline": "不应出现", "overview": "不应出现"}
    service = IntelligenceService(provider=StubProvider(payloads=[brief, overview]))
    try:
        service.start()
        record, _ = service.create_report(report_type="daily")
        finished, citations = wait_for(service, record.id)
    finally:
        service.stop()

    assert finished.status == "degraded"
    assert finished.ai_status == "invalid"
    assert finished.content["key_events"] == []
    assert {item.ref_id for item in citations if item.citation_type == "event"} == {
        seeded["events"][0]
    }


def test_ollama_unavailable_degrades_to_statistics_only(ready):
    seeded = default_seed()
    service = IntelligenceService(provider=StubProvider(available=False))
    try:
        service.start()
        record, _ = service.create_report(report_type="daily")
        finished, citations = wait_for(service, record.id)
    finally:
        service.stop()

    assert finished.status == "degraded"
    assert finished.ai_status == "unavailable"
    assert finished.content["key_events"] == []
    assert finished.content["uncertainties"]
    assert finished.stats["totals"]["articles"] >= 3
    assert {item.ref_id for item in citations if item.citation_type == "event"} == {
        seeded["events"][0]
    }
    assert all(item.section_key == "stats_events" for item in citations)


def test_duplicate_generation_is_reused_and_force_supersedes(ready):
    default_seed()
    service = IntelligenceService(provider=StubProvider(available=False))
    try:
        service.start()
        first, reused = service.create_report(report_type="daily")
        assert reused is False
        wait_for(service, first.id)

        second, reused_again = service.create_report(report_type="daily")
        assert reused_again is True
        assert second.id == first.id

        third, reused_force = service.create_report(report_type="daily", force=True)
        assert reused_force is False
        assert third.id != first.id
        wait_for(service, third.id)

        previous, _ = service.report_detail(first.id)
        assert previous.status == "superseded"
    finally:
        service.stop()


def test_pending_report_can_be_cancelled_before_worker_runs(ready):
    default_seed()
    service = IntelligenceService(provider=StubProvider(available=False))
    try:
        record, _ = service.create_report(report_type="weekly")
        cancelled = service.cancel_report(record.id)
        assert cancelled.status == "cancelled"
        detail, _ = service.report_detail(record.id)
        assert detail.status == "cancelled"
        assert detail.finished_at is not None
    finally:
        service.stop()


def test_recovery_marks_interrupted_reports_failed(ready):
    default_seed()
    service = IntelligenceService(provider=StubProvider(available=False))
    try:
        record, _ = service.create_report(report_type="daily")
    finally:
        service.stop()
    # Simulate a crash: the row stays pending, restart must not leave it stuck.
    changed = service.recover_interrupted()
    assert changed == 1
    detail, _ = service.report_detail(record.id)
    assert detail.status == "failed"
    assert detail.error_code == "interrupted"


def test_history_list_and_detail(ready):
    default_seed()
    service = IntelligenceService(provider=StubProvider(available=False))
    try:
        service.start()
        record, _ = service.create_report(report_type="daily")
        wait_for(service, record.id)
        records, total = service.list_reports(
            report_type="daily", status=None, limit=10, offset=0
        )
    finally:
        service.stop()
    assert total == 1
    assert records[0].id == record.id
    assert records[0].content["key_events"] == []


def test_weekly_window_covers_seven_days(ready):
    seed_graph([
        # Inside the 7-day window.
        _seed("近期新闻", "来源D", ["新能源", "电池"], "财经", 1.0),
        _seed("近期新闻二", "来源E", ["新能源", "储能"], "财经", 2.0),
        # Outside the window (previous week).
        _seed("旧新闻", "来源F", ["新能源"], "财经", 12.0),
    ])
    start, end = period_for("weekly")
    with database.read_session() as conn:
        stats = build_stats(conn, report_type="weekly", period_start=start, period_end=end)
    assert stats["totals"]["articles"] == 2
    assert stats["totals"]["previous_articles"] == 1
    rising = {item["keyword"]: item for item in stats["rising_keywords"]}
    assert rising["新能源"]["count"] == 2
    assert rising["新能源"]["previous"] == 1
    assert rising["新能源"]["delta"] == 1


def _seed(title, source, keywords, category, days):
    from intelligence_support import Seed

    return Seed(
        article_title=title, source_name=source, keywords=keywords,
        category=category, days_ago=days,
    )


def test_stats_endpoint_rejects_unknown_report_type(ready):
    from services.errors import ServiceError

    service = IntelligenceService(provider=StubProvider(available=False))
    with pytest.raises(ServiceError) as exc:
        service.create_report(report_type="hourly")
    assert exc.value.status_code == 422
