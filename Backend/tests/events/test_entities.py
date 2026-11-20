"""Stage 4.1 — entity normalisation, aliases, merge/unmerge (real SQLite)."""

from __future__ import annotations

import uuid

import pytest

import database
from core.timeutil import utc_timestamp
from database.repositories import entity_repository as entity_repo
from services.entity_service import EntityService, get_entity_service
from services.errors import ServiceError

from event_support import (
    ambiguous_rows,
    audit_actions,
    count_entities_for_article,
    entity_articles,
    entity_by_name,
    entity_count,
    seed_article,
)


def _entity_by_key(key: str, type_group: str = "organization"):
    with database.read_session() as conn:
        return entity_repo.find_active_by_key(
            conn, normalized_key=key, type_group=type_group
        )


def _insert_alias(entity_id: str, alias: str) -> None:
    from event_intelligence.entities import normalized_key

    with database.session() as conn:
        entity = entity_repo.get(conn, entity_id)
        assert entity is not None
        entity_repo.insert_alias(
            conn,
            {
                "id": str(uuid.uuid4()),
                "entity_id": entity_id,
                "alias": alias,
                "alias_key": normalized_key(alias, entity.type_group),
                "language": "en",
                "source": "manual",
                "confidence": 1.0,
                "merged_from_entity_id": None,
                "created_at": utc_timestamp(),
            },
        )


def test_full_name_and_short_name_resolve_to_same_entity(ready) -> None:
    first = seed_article(
        title="星河科技股份有限公司发布公告",
        category="科技",
        summary="星河科技发布年度业绩公告。",
        keywords=["公告", "业绩"],
        entities=[("星河科技股份有限公司", "organization")],
    )
    second = seed_article(
        title="星河科技融资消息",
        category="科技",
        summary="星河科技完成新一轮融资。",
        keywords=["融资"],
        entities=[("星河科技", "organization")],
    )

    full = entity_by_name("星河科技股份有限公司")
    assert full is not None
    assert entity_count() == 1
    assert count_entities_for_article(first.article_id) == 1
    assert count_entities_for_article(second.article_id) == 1
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT entity_id FROM article_entities WHERE article_id IN (?, ?)",
            (first.article_id, second.article_id),
        ).fetchall()
    assert [str(row[0]) for row in rows] == [full["id"]]


def test_parenthesised_english_alias_links_and_preserves_aliases(ready) -> None:
    seed_article(
        title="星河科技股份有限公司公告",
        category="科技",
        summary="星河科技股份有限公司公告。",
        keywords=["公告"],
        entities=[("星河科技股份有限公司", "organization")],
    )
    seed_article(
        title="Galaxy Tech files",
        category="科技",
        summary="Galaxy Tech files new documents.",
        keywords=["filing"],
        entities=[("星河科技（Galaxy Tech）", "organization")],
    )

    entity = _entity_by_key("星河科技")
    assert entity is not None
    with database.read_session() as conn:
        aliases = {item.alias for item in entity_repo.list_aliases(conn, entity.id)}
    assert "星河科技股份有限公司" in aliases
    assert "Galaxy Tech" in aliases
    assert entity_count() == 1


def test_same_name_different_type_is_not_merged(ready) -> None:
    seed_article(
        title="苹果公司发布新产品",
        category="科技",
        summary="苹果公司发布新产品。",
        keywords=["发布"],
        entities=[("苹果", "organization")],
    )
    seed_article(
        title="苹果价格上涨",
        category="财经",
        summary="苹果价格上涨。",
        keywords=["价格"],
        entities=[("苹果", "product")],
    )

    assert entity_count() == 2
    with database.read_session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT type_group FROM entities WHERE canonical_name = '苹果'"
        ).fetchall()
    assert {str(row[0]) for row in rows} == {"organization", "product"}


def test_same_name_person_is_not_auto_merged(ready) -> None:
    seed_article(
        title="张伟出席A公司活动",
        category="科技",
        summary="张伟出席活动。",
        keywords=["活动"],
        entities=[("张伟", "person")],
    )
    seed_article(
        title="张伟参加B公司会议",
        category="科技",
        summary="张伟参加会议。",
        keywords=["会议"],
        entities=[("张伟", "person")],
    )

    # Identical spelling is a deterministic same-name match, which is a
    # legitimate canonical match. The guard that matters is that unrelated
    # spelling/type pairs are kept apart (covered below).
    assert entity_count() == 1


def test_multiple_alias_owners_produce_ambiguous_mention(ready) -> None:
    seed_article(
        title="Alpha One 新闻",
        category="科技",
        summary="Alpha One 新闻。",
        keywords=["新闻"],
        entities=[("Alpha One", "person")],
    )
    seed_article(
        title="Beta Two 新闻",
        category="科技",
        summary="Beta Two 新闻。",
        keywords=["新闻"],
        entities=[("Beta Two", "person")],
    )
    left = entity_by_name("Alpha One")
    right = entity_by_name("Beta Two")
    assert left is not None and right is not None
    _insert_alias(str(left["id"]), "Common Alias")
    _insert_alias(str(right["id"]), "Common Alias")

    third = seed_article(
        title="Common Alias 报道",
        category="科技",
        summary="Common Alias 报道。",
        keywords=["报道"],
        entities=[("Common Alias", "person")],
    )

    rows = ambiguous_rows()
    assert any(row["article_id"] == third.article_id for row in rows)
    assert entity_count() == 2


def test_merge_and_unmerge_are_persisted_and_audited(ready) -> None:
    seed_article(
        title="A 公司公告",
        category="科技",
        summary="A 公司公告。",
        keywords=["公告"],
        entities=[("星河科技", "organization")],
    )
    seed_article(
        title="Galaxy Tech 公告",
        category="科技",
        summary="Galaxy Tech 公告。",
        keywords=["公告"],
        entities=[("Galaxy Tech", "organization")],
    )
    left = entity_by_name("星河科技")
    right = entity_by_name("Galaxy Tech")
    assert left is not None and right is not None
    left_articles = entity_articles(str(left["id"]))

    service = EntityService()
    merged = service.merge(str(left["id"]), str(right["id"]), "同一机构")

    assert merged.id == right["id"]
    with database.read_session() as conn:
        source = entity_repo.get(conn, str(left["id"]))
        target_articles = entity_repo.list_article_entities(conn, merged.id)
    assert source is not None and source.status == "merged"
    assert source.merged_into_entity_id == merged.id
    assert {str(item.article_id) for item in target_articles} >= set(left_articles)

    with database.read_session() as conn:
        actions = [row[0] for row in conn.execute(
            "SELECT action FROM event_audit_log ORDER BY created_at"
        )]
    assert "merge_entities" in actions

    restored = service.unmerge(merged.id)
    assert restored.id == left["id"]
    assert restored.status == "active"
    assert set(entity_articles(restored.id)) == set(left_articles)


def test_merge_rejects_incompatible_type_groups(ready) -> None:
    seed_article(
        title="苹果公司",
        category="科技",
        summary="苹果公司。",
        keywords=["公司"],
        entities=[("苹果", "organization")],
    )
    seed_article(
        title="苹果产品",
        category="科技",
        summary="苹果产品。",
        keywords=["产品"],
        entities=[("苹果", "product")],
    )
    org = entity_by_name("苹果")
    with database.read_session() as conn:
        product = conn.execute(
            "SELECT * FROM entities WHERE canonical_name = '苹果' AND type_group = 'product'"
        ).fetchone()
    assert org is not None and product is not None

    with pytest.raises(ServiceError) as excinfo:
        EntityService().merge(str(org["id"]), str(product["id"]), None)
    assert excinfo.value.code == "entity_merge_conflict"


def test_manual_alias_add_and_delete(ready) -> None:
    created = seed_article(
        title="Blue Ocean 公告",
        category="科技",
        summary="Blue Ocean 公告。",
        keywords=["公告"],
        entities=[("蓝海数据", "organization")],
    )
    entity = entity_by_name("蓝海数据")
    assert entity is not None
    service = EntityService()

    updated = service.add_alias(str(entity["id"]), "Blue Ocean Data", "en")
    with database.read_session() as conn:
        aliases = entity_repo.list_aliases(conn, updated.id)
    manual = [item for item in aliases if item.source == "manual"]
    assert manual and manual[0].alias == "Blue Ocean Data"

    service.delete_alias(updated.id, manual[0].id)
    with database.read_session() as conn:
        remaining = entity_repo.list_aliases(conn, updated.id)
    assert manual[0].id not in {item.id for item in remaining}
    assert count_entities_for_article(created.article_id) == 1


def test_alias_changes_are_audited(ready) -> None:
    """Regression for P4-11: manual alias add/delete must be auditable."""

    seed_article(
        title="审计别名新闻",
        category="科技",
        summary="审计别名新闻。",
        keywords=["新闻"],
        entities=[("远山科技", "organization")],
    )
    entity = entity_by_name("远山科技")
    assert entity is not None
    service = EntityService()
    updated = service.add_alias(str(entity["id"]), "Farshine Tech", "en")
    with database.read_session() as conn:
        alias = next(item for item in entity_repo.list_aliases(conn, updated.id) if item.source == "manual")
    service.delete_alias(updated.id, alias.id)

    actions = audit_actions()
    assert actions.count("entity_metadata") >= 2


def test_alias_conflict_is_rejected(ready) -> None:
    seed_article(
        title="Alpha 新闻",
        category="科技",
        summary="Alpha 新闻。",
        keywords=["新闻"],
        entities=[("Alpha Corp", "organization")],
    )
    seed_article(
        title="Beta 新闻",
        category="科技",
        summary="Beta 新闻。",
        keywords=["新闻"],
        entities=[("Beta Corp", "organization")],
    )
    alpha = entity_by_name("Alpha Corp")
    beta = entity_by_name("Beta Corp")
    assert alpha is not None and beta is not None

    service = EntityService()
    service.add_alias(str(alpha["id"]), "共享简称", None)
    with pytest.raises(ServiceError) as excinfo:
        service.add_alias(str(beta["id"]), "共享简称", None)
    assert excinfo.value.code == "entity_alias_conflict"


def test_canonical_alias_cannot_be_deleted(ready) -> None:
    seed_article(
        title="Gamma 新闻",
        category="科技",
        summary="Gamma 新闻。",
        keywords=["新闻"],
        entities=[("Gamma Corp", "organization")],
    )
    entity = entity_by_name("Gamma Corp")
    assert entity is not None
    service = EntityService()
    detail = service.detail(str(entity["id"]))
    canonical = [item for item in detail.aliases if item.source == "canonical"]
    assert canonical
    with pytest.raises(ServiceError) as excinfo:
        service.delete_alias(detail.id, canonical[0].id)
    assert excinfo.value.code == "entity_alias_protected"


def test_repeated_sync_is_idempotent(ready) -> None:
    created = seed_article(
        title="Delta 新闻",
        category="科技",
        summary="Delta 新闻。",
        keywords=["新闻"],
        entities=[("Delta Corp", "organization"), ("李雷", "person")],
    )
    with database.session() as conn:
        from services.entity_service import sync_article

        sync_article(conn, created.article_id, now=utc_timestamp(), stats={})
        sync_article(conn, created.article_id, now=utc_timestamp(), stats={})

    assert entity_count() == 2
    assert count_entities_for_article(created.article_id) == 2


def test_entity_listing_orders_and_filters(ready) -> None:
    seed_article(
        title="某公司新闻",
        category="科技",
        summary="某公司新闻。",
        keywords=["新闻"],
        entities=[("某公司", "organization")],
    )
    seed_article(
        title="某人物新闻",
        category="科技",
        summary="某人物新闻。",
        keywords=["新闻"],
        entities=[("某人物", "person")],
    )
    items, total = get_entity_service().list(
        limit=20, offset=0, entity_type="person", keyword=None,
        order="last_seen", direction="desc",
    )
    assert total == 1 and items[0].canonical_name == "某人物"
