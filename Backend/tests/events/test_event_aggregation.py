"""Phase 7.6 cross-source event aggregation tests (real SQLite, no mocks)."""

from __future__ import annotations

import json
import uuid

import database
from core.timeutil import utc_timestamp
from database.repositories import event_repository as event_repo
from event_intelligence.aggregation import (
    ArticleSignal,
    EventSignal,
    RepresentativeCandidate,
    choose_representative,
    headline_text,
    score_article_event,
)
from event_support import (
    create_analysis,
    create_article,
    create_source,
    seed_article,
    stamp,
    write_session,
)
from services.entity_service import sync_article
from services.event_aggregation_service import EventAggregationService


def _article(
    *,
    article_id: str,
    title: str,
    source_id: str,
    published_at: str,
    summary: str | None = None,
    category: str = "科技",
    keywords: tuple[str, ...] = ("模型",),
    entity_keys: tuple[str, ...] = ("星河科技",),
    event_entity_keys: tuple[str, ...] = (),
    content_hash: str | None = None,
) -> ArticleSignal:
    return ArticleSignal(
        id=article_id,
        title=title,
        summary=summary or title,
        published_at=published_at,
        source_id=source_id,
        source_name=source_id,
        category=category,
        keywords=frozenset(keywords),
        entity_keys=frozenset(entity_keys),
        event_entity_keys=frozenset(event_entity_keys),
        content_state="summary_only",
        content_hash=content_hash or uuid.uuid4().hex * 2,
        summary_length=len(summary or title),
    )


def _event(
    *,
    event_id: str,
    title: str,
    members: tuple[ArticleSignal, ...],
    category: str = "科技",
) -> EventSignal:
    return EventSignal(
        id=event_id,
        title=title,
        summary=title,
        category=category,
        status="candidate",
        is_manual=False,
        members=members,
        entity_ids=frozenset(),
        entity_keys=frozenset(key for member in members for key in member.entity_keys),
        event_entity_ids=frozenset(
            key for member in members for key in member.event_entity_ids
        ),
        event_entity_keys=frozenset(
            key for member in members for key in member.event_entity_keys
        ),
        keywords=frozenset(key for member in members for key in member.keywords),
        source_ids=frozenset(member.source_id for member in members),
        first_published_at=members[0].published_at,
        last_published_at=members[-1].published_at,
    )


def test_cross_source_same_story_merges() -> None:
    left = _article(
        article_id="a",
        title="OpenAI 发布 GPT-6.2 模型，推理能力提升",
        source_id="s1",
        published_at="2026-11-18T09:00:00.000Z",
        keywords=("openai", "gpt-6.2", "模型"),
        entity_keys=("openai", "gpt-6.2"),
    )
    right = _article(
        article_id="b",
        title="OpenAI 正式发布 GPT-6.2，推理能力全面提升",
        source_id="s2",
        published_at="2026-11-18T07:00:00.000Z",
        keywords=("openai", "gpt-6.2", "模型"),
        entity_keys=("openai", "gpt-6.2"),
    )
    score = score_article_event(left, _event(event_id="e", title=right.title, members=(right,)))
    assert score.decision == "merge", score.reasons
    assert score.guards == ()


def test_headline_prefix_is_ignored() -> None:
    assert headline_text("新华图讯丨习近平会见俄罗斯总统普京") == "习近平会见俄罗斯总统普京"
    assert headline_text("（深圳APEC）习近平会见韩国总统李在明") == "习近平会见韩国总统李在明"


def test_similar_titles_but_different_product_do_not_merge() -> None:
    left = _article(
        article_id="a",
        title="星河科技发布星河 X1 手机，售价 3999 元",
        source_id="s1",
        published_at="2026-11-18T09:00:00.000Z",
        keywords=("星河科技", "手机", "发布"),
        entity_keys=("星河科技",),
    )
    right = _article(
        article_id="b",
        title="星河科技发布星河 X2 手机，售价 4299 元",
        source_id="s2",
        published_at="2026-11-18T08:00:00.000Z",
        keywords=("星河科技", "手机", "发布"),
        entity_keys=("星河科技",),
    )
    score = score_article_event(left, _event(event_id="e", title=right.title, members=(right,)))
    assert score.decision == "separate", score.reasons
    assert "conflicting_version_marker" in score.guards


def test_quarter_markers_do_not_merge() -> None:
    left = _article(
        article_id="a",
        title="星河科技第三季度财报：营收同比增长两成",
        source_id="s1",
        published_at="2026-11-18T09:00:00.000Z",
        keywords=("财报", "营收"),
        entity_keys=("星河科技", "第三季度财报"),
    )
    right = _article(
        article_id="b",
        title="星河科技第四季度财报：营收同比下降",
        source_id="s2",
        published_at="2026-11-18T08:00:00.000Z",
        keywords=("财报", "营收"),
        entity_keys=("星河科技", "第四季度财报"),
    )
    score = score_article_event(left, _event(event_id="e", title=right.title, members=(right,)))
    assert score.decision == "separate"
    assert "conflicting_event_marker" in score.guards


def test_evolving_progress_merges() -> None:
    first = _article(
        article_id="a",
        title="蓝海数据宣布完成 A 轮融资",
        source_id="s1",
        published_at="2026-11-15T09:00:00.000Z",
        summary="蓝海数据宣布完成 A 轮融资。",
        category="财经",
        keywords=("融资", "A轮", "投资"),
        entity_keys=("蓝海数据",),
        event_entity_keys=("A轮融资",),
    )
    follow = _article(
        article_id="b",
        title="蓝海数据 A 轮融资落地，投资方为远景资本",
        source_id="s2",
        published_at="2026-11-16T08:00:00.000Z",
        summary="蓝海数据 A 轮融资落地。",
        category="财经",
        keywords=("融资", "A轮", "投资"),
        entity_keys=("蓝海数据",),
        event_entity_keys=("A轮融资",),
    )
    score = score_article_event(
        follow,
        _event(event_id="e", title=first.title, members=(first,), category="财经"),
    )
    assert score.decision == "merge", score.reasons


def test_cross_language_pair_needs_review() -> None:
    left = _article(
        article_id="a",
        title="OpenAI releases GPT-6.2 with stronger reasoning",
        source_id="s1",
        published_at="2026-11-18T09:00:00.000Z",
        keywords=("openai", "gpt-6.2"),
        entity_keys=("openai", "gpt-6.2"),
    )
    right = _article(
        article_id="b",
        title="OpenAI 发布 GPT-6.2，推理能力增强",
        source_id="s2",
        published_at="2026-11-18T08:00:00.000Z",
        keywords=("openai", "gpt-6.2"),
        entity_keys=("openai", "gpt-6.2"),
    )
    score = score_article_event(left, _event(event_id="e", title=right.title, members=(right,)))
    assert score.decision == "review"
    assert "cross_language_review" in score.guards


def test_representative_prefers_authority_and_completeness() -> None:
    choice = choose_representative(
        [
            RepresentativeCandidate(
                article_id="low",
                title="普通转载",
                source_id="s1",
                source_name="低可信源",
                published_at="2026-11-18T09:00:00.000Z",
                credibility=0.2,
                content_state="summary_only",
                has_ai_summary=False,
                summary_length=40,
            ),
            RepresentativeCandidate(
                article_id="high",
                title="权威完整报道",
                source_id="s2",
                source_name="高可信源",
                published_at="2026-11-18T10:00:00.000Z",
                credibility=0.9,
                content_state="full",
                has_ai_summary=True,
                summary_length=300,
            ),
        ]
    )
    assert choice is not None
    assert choice.article_id == "high"


def _insert_event(
    *, title: str, category: str, article_id: str, source_id: str, published_at: str
) -> str:
    event_id = str(uuid.uuid4())
    now = utc_timestamp()
    with write_session() as conn:
        event_repo.insert_event(
            conn,
            {
                "id": event_id,
                "title": title,
                "summary": title,
                "category": category,
                "status": "candidate",
                "status_reason": "test",
                "first_seen_at": now,
                "last_seen_at": now,
                "first_published_at": published_at,
                "last_published_at": published_at,
                "occurred_at": None,
                "article_count": 0,
                "source_count": 0,
                "is_manual": 0,
                "merged_into_event_id": None,
                "algorithm_version": "event-cluster-v1",
                "title_source": "auto",
                "summary_source": "auto",
                "created_at": now,
                "updated_at": now,
            },
        )
        event_repo.insert_event_article(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "article_id": article_id,
                "role": "report",
                "similarity": None,
                "match_reasons_json": "[]",
                "is_manual": 0,
                "added_at": now,
                "created_at": now,
            },
        )
        from services.event_aggregation import recompute_event_aggregates

        recompute_event_aggregates(conn, event_id, now)
    return event_id


def test_dry_run_groups_cross_source_duplicates(ready) -> None:
    left = seed_article(
        title="OpenAI 发布 GPT-6.2 模型，推理能力提升",
        category="科技",
        summary="OpenAI 发布 GPT-6.2 模型。",
        keywords=["openai", "gpt-6.2", "模型"],
        entities=[("OpenAI", "organization"), ("GPT-6.2", "product")],
        source_name="媒体甲",
        published_at=stamp(0.2),
    )
    right = seed_article(
        title="OpenAI 发布 GPT-6.2 模型，推理能力提升",
        category="科技",
        summary="OpenAI 发布 GPT-6.2 模型。",
        keywords=["openai", "gpt-6.2", "模型"],
        entities=[("OpenAI", "organization"), ("GPT-6.2", "product")],
        source_name="媒体乙",
        published_at=stamp(0.1),
    )
    result = EventAggregationService().dry_run(days=7, event_limit=10, article_limit=50)
    assert result["summary"]["article_groups"] >= 1
    group = next(
        group
        for group in result["article_groups"]
        if {left.article_id, right.article_id} <= set(group["article_ids"])
    )
    assert group["source_count"] == 2
    assert group["representative"] is not None


def test_apply_article_group_creates_one_event_without_deleting_articles(ready) -> None:
    left = seed_article(
        title="OpenAI 发布 GPT-6.2 模型，推理能力提升",
        category="科技",
        summary="OpenAI 发布 GPT-6.2 模型。",
        keywords=["openai", "gpt-6.2", "模型"],
        entities=[("OpenAI", "organization"), ("GPT-6.2", "product")],
        source_name="媒体甲",
        published_at=stamp(0.2),
    )
    right = seed_article(
        title="OpenAI 正式发布 GPT-6.2，推理能力全面提升",
        category="科技",
        summary="OpenAI 发布 GPT-6.2，推理全面提升。",
        keywords=["openai", "gpt-6.2", "模型"],
        entities=[("OpenAI", "organization"), ("GPT-6.2", "product")],
        source_name="媒体乙",
        published_at=stamp(0.1),
    )
    result = EventAggregationService().apply(
        [{"kind": "article_group", "article_ids": [left.article_id, right.article_id]}],
        confirm=True,
    )
    assert result["applied_count"] == 1, result
    event_id = result["applied"][0]["target_event_id"]

    with database.read_session() as conn:
        membership = conn.execute(
            "SELECT event_id, COUNT(*) FROM event_articles WHERE event_id = ? GROUP BY event_id",
            (event_id,),
        ).fetchone()
        assert membership is not None and int(membership[1]) == 2
        active = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE id IN (?, ?) AND status = 'active'",
            (left.article_id, right.article_id),
        ).fetchone()
        assert active is not None and int(active[0]) == 2
        audit = conn.execute(
            "SELECT COUNT(*) FROM event_audit_log WHERE event_id = ? AND action = 'create_event'",
            (event_id,),
        ).fetchone()
        assert audit is not None and int(audit[0]) == 1


def test_apply_article_group_keeps_same_source_duplicates_as_duplicates(ready) -> None:
    shared_source = create_source("媒体甲")
    first_id = create_article(
        source_id=shared_source,
        title="国家能源局发布新型储能发展指导意见",
        summary="国家能源局发布新型储能发展指导意见。",
        published_at=stamp(0.3),
    )
    duplicate_id = create_article(
        source_id=shared_source,
        title="国家能源局发布新型储能发展指导意见",
        summary="国家能源局发布新型储能发展指导意见。",
        published_at=stamp(0.2),
    )
    for article_id in (first_id, duplicate_id):
        create_analysis(
            article_id=article_id,
            category="科技",
            summary="国家能源局发布新型储能发展指导意见。",
            keywords=["储能", "能源", "政策"],
            entities=[("国家能源局", "organization")],
        )
        with write_session() as conn:
            sync_article(conn, article_id, now=utc_timestamp(), stats={})
    first = type("A", (), {"article_id": first_id})()
    duplicate = type("A", (), {"article_id": duplicate_id})()
    other = seed_article(
        title="国家能源局发布新型储能发展指导意见",
        category="科技",
        summary="国家能源局发布新型储能发展指导意见。",
        keywords=["储能", "能源", "政策"],
        entities=[("国家能源局", "organization")],
        source_name="媒体乙",
        published_at=stamp(0.1),
    )
    result = EventAggregationService().apply(
        [
            {
                "kind": "article_group",
                "article_ids": [first.article_id, duplicate.article_id, other.article_id],
            }
        ],
        confirm=True,
    )
    assert result["applied_count"] == 1, result
    event_id = result["applied"][0]["target_event_id"]
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT role, COUNT(*) FROM event_articles WHERE event_id = ? GROUP BY role",
            (event_id,),
        ).fetchall()
        roles = {str(row[0]): int(row[1]) for row in rows}
        assert sum(roles.values()) == 3
        assert roles.get("duplicate", 0) == 1


def test_apply_event_merge_moves_articles_and_is_audited(ready) -> None:
    left = seed_article(
        title="国家能源局发布新型储能发展指导意见",
        category="科技",
        summary="国家能源局发布新型储能发展指导意见。",
        keywords=["储能", "能源", "政策"],
        entities=[("国家能源局", "organization")],
        source_name="能源媒体甲",
        published_at=stamp(0.2),
    )
    right = seed_article(
        title="国家能源局发布新型储能发展指导意见",
        category="科技",
        summary="国家能源局发布新型储能发展指导意见。",
        keywords=["储能", "能源", "政策"],
        entities=[("国家能源局", "organization")],
        source_name="能源媒体乙",
        published_at=stamp(0.1),
    )
    source_event = _insert_event(
        title="国家能源局发布新型储能发展指导意见",
        category="科技",
        article_id=left.article_id,
        source_id=left.source_id,
        published_at=stamp(0.2),
    )
    target_event = _insert_event(
        title="国家能源局发布新型储能发展指导意见",
        category="科技",
        article_id=right.article_id,
        source_id=right.source_id,
        published_at=stamp(0.1),
    )
    result = EventAggregationService().apply(
        [
            {
                "kind": "event_merge",
                "source_event_id": source_event,
                "target_event_id": target_event,
            }
        ],
        confirm=True,
    )
    assert result["applied_count"] == 1, result
    with database.read_session() as conn:
        source = event_repo.get(conn, source_event)
        target = event_repo.get(conn, target_event)
        assert source is not None and source.status == "merged"
        assert source.merged_into_event_id == target_event
        assert target is not None and target.article_count == 2
        audit = conn.execute(
            "SELECT COUNT(*) FROM event_audit_log WHERE event_id = ? AND action = 'merge_events'",
            (target_event,),
        ).fetchone()
        assert audit is not None and int(audit[0]) == 1


def test_apply_requires_confirmation_and_never_touches_manual_events(ready) -> None:
    article = seed_article(
        title="某人工事件报道",
        category="科技",
        summary="摘要",
        keywords=["测试"],
        entities=[("某机构", "organization")],
        source_name="媒体甲",
        published_at=stamp(0.1),
    )
    event_id = _insert_event(
        title="某人工事件报道",
        category="科技",
        article_id=article.article_id,
        source_id=article.source_id,
        published_at=stamp(0.1),
    )
    service = EventAggregationService()
    try:
        service.apply([{"kind": "article_group", "article_ids": []}], confirm=False)
    except Exception as exc:  # noqa: BLE001 - validation error
        assert getattr(exc, "code", "") == "invalid_request"
        assert getattr(exc, "details", ())[0].field == "confirm"
    else:  # pragma: no cover
        raise AssertionError("confirm=False must be rejected")

    with write_session() as conn:
        conn.execute("UPDATE events SET is_manual = 1 WHERE id = ?", (event_id,))
    second = seed_article(
        title="某人工事件报道（另一来源）",
        category="科技",
        summary="摘要",
        keywords=["测试"],
        entities=[("某机构", "organization")],
        source_name="媒体乙",
        published_at=stamp(0.05),
    )
    result = service.apply(
        [
            {
                "kind": "article_attach",
                "article_id": second.article_id,
                "event_id": event_id,
            }
        ],
        confirm=True,
    )
    assert result["applied_count"] == 0
    assert result["rejected"][0]["code"] == "aggregation_manual_event"


def test_event_digest_detail_contains_representative_and_increment(ready) -> None:
    left = seed_article(
        title="OpenAI 发布 GPT-6.2 模型",
        category="科技",
        summary="OpenAI 发布 GPT-6.2 模型，推理提升。",
        keywords=["openai", "模型"],
        entities=[("OpenAI", "organization")],
        source_name="媒体甲",
        published_at=stamp(0.2),
    )
    right = seed_article(
        title="OpenAI 正式发布 GPT-6.2，能力全面提升",
        category="科技",
        summary="OpenAI 发布 GPT-6.2，能力提升。",
        keywords=["openai", "模型"],
        entities=[("OpenAI", "organization")],
        source_name="媒体乙",
        published_at=stamp(0.1),
    )
    event_id = _insert_event(
        title="OpenAI 发布 GPT-6.2 模型",
        category="科技",
        article_id=left.article_id,
        source_id=left.source_id,
        published_at=stamp(0.2),
    )
    now = utc_timestamp()
    with write_session() as conn:
        event_repo.insert_event_article(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "article_id": right.article_id,
                "role": "follow_up",
                "similarity": 0.9,
                "match_reasons_json": "[]",
                "is_manual": 0,
                "added_at": now,
                "created_at": now,
            },
        )
        from services.event_aggregation import recompute_event_aggregates

        recompute_event_aggregates(conn, event_id, now)

    from services import personalization_service

    with database.read_session() as conn:
        detail = personalization_service._event_digest_detail(conn, event_id)
    assert detail is not None
    assert detail["article_count"] == 2
    assert detail["source_count"] == 2
    assert detail["representative"] is not None
    assert detail["information_increment"]["follow_up_count"] == 1
    assert len(detail["other_reports"]) == 1
    assert detail["latest_progress"] is not None
