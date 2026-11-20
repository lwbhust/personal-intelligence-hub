"""Event read models, manual corrections, merge/split and candidate review."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace

import database
from core.timeutil import utc_timestamp
from database.repositories import event_audit_repository as audit_repo
from database.repositories import event_cluster_run_repository as cluster_repo
from database.repositories import event_relation_repository as relation_repo
from database.repositories import event_repository as event_repo
from database.repositories import event_score_repository as score_repo
from database.repositories.models import (
    EventDecisionRecord,
    EventRecord,
    EventRelationRecord,
    EventScoreRecord,
    EventTimelineRecord,
)
from event_intelligence.text import normalize_text
from services.errors import ServiceError, conflict, not_found, validation
from services.event_aggregation import (
    rebuild_event_entities,
    recompute_event_aggregates,
    refresh_event_summary,
)
from services.event_scoring_service import score_event_in_conn

CATEGORIES = {"科技", "财经", "政治", "国际", "社会", "健康", "教育", "文化", "体育", "其他"}
RELATION_TYPES = {"related_to", "follows", "caused_by", "part_of", "same_topic", "contradicts"}
MANUAL_STATUSES = {"active", "dormant", "closed", "archived"}
TERMINAL = {"merged", "archived"}
MAX_RELATION_EVIDENCE = 50


def _clean_title(value: str | None) -> str:
    title = normalize_text(value)[:300]
    if not title:
        raise validation("title", "empty", "标题不能为空")
    return title


def _clean_category(value: str | None) -> str:
    if value is None:
        return "其他"
    if value not in CATEGORIES:
        raise validation("category", "invalid", "分类不在允许范围")
    return value


class EventService:
    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None,
        category: str | None,
        keyword: str | None,
        order: str,
        window: str,
    ) -> tuple[list[EventRecord], int]:
        from services.event_scoring_service import _cutoff  # shared window helper

        cutoff = _cutoff(window) if window != "all" else None
        with database.read_session() as conn:
            records, total = event_repo.list_events(
                conn,
                limit=limit,
                offset=offset,
                status=status,
                category=category,
                keyword=keyword,
                order=order,
                cutoff=cutoff,
                exclude_terminal=True,
            )
            enriched = [
                replace(
                    record,
                    top_entities=tuple(event_repo.list_event_entities(conn, record.id)[:3]),
                )
                for record in records
            ]
            return enriched, total

    def detail(self, event_id: str) -> EventRecord:
        with database.read_session() as conn:
            event = event_repo.get(conn, event_id)
            if event is None:
                raise not_found("event_not_found", "事件不存在")
            return self._decorate(conn, event)

    def articles(
        self, event_id: str, *, limit: int, offset: int
    ):
        with database.read_session() as conn:
            if event_repo.get(conn, event_id) is None:
                raise not_found("event_not_found", "事件不存在")
            return event_repo.list_event_articles(conn, event_id, limit=limit, offset=offset)

    def timeline(
        self, event_id: str, *, limit: int, offset: int, key_only: bool
    ) -> tuple[list[EventTimelineRecord], int]:
        with database.read_session() as conn:
            if event_repo.get(conn, event_id) is None:
                raise not_found("event_not_found", "事件不存在")
            return event_repo.list_timeline(
                conn, event_id, limit=limit, offset=offset, key_only=key_only
            )

    def entities(self, event_id: str):
        with database.read_session() as conn:
            if event_repo.get(conn, event_id) is None:
                raise not_found("event_not_found", "事件不存在")
            return event_repo.list_event_entities(conn, event_id)

    def relations(self, event_id: str) -> list[EventRelationRecord]:
        with database.read_session() as conn:
            if event_repo.get(conn, event_id) is None:
                raise not_found("event_not_found", "事件不存在")
            return self._decorate_relations(conn, relation_repo.list_for_event(conn, event_id))

    def scores(
        self, event_id: str, *, limit: int, offset: int
    ) -> tuple[list[EventScoreRecord], int]:
        with database.read_session() as conn:
            if event_repo.get(conn, event_id) is None:
                raise not_found("event_not_found", "事件不存在")
            return score_repo.list_snapshots(conn, event_id, limit=limit, offset=offset)

    def candidates(
        self, *, limit: int, offset: int
    ) -> tuple[list[tuple[EventRecord, EventDecisionRecord | None]], int]:
        with database.read_session() as conn:
            records, total = event_repo.list_events(
                conn,
                limit=limit,
                offset=offset,
                status="candidate",
                order="recent",
                exclude_terminal=False,
            )
            items = [
                (
                    replace(
                        record,
                        top_entities=tuple(
                            event_repo.list_event_entities(conn, record.id)[:3]
                        ),
                    ),
                    cluster_repo.latest_decision_for_event(conn, record.id),
                )
                for record in records
            ]
            return items, total

    def decisions(
        self,
        *,
        limit: int,
        offset: int,
        decision: str | None,
        status: str | None,
    ) -> tuple[list[EventDecisionRecord], int]:
        with database.read_session() as conn:
            return cluster_repo.list_decisions(
                conn, limit=limit, offset=offset, decision=decision, status=status
            )

    # ------------------------------------------------------------------
    # manual writes
    # ------------------------------------------------------------------

    def create_event(
        self,
        *,
        title: str,
        category: str | None,
        summary: str | None,
        article_ids: list[str] | None,
    ) -> EventRecord:
        clean_title = _clean_title(title)
        clean_category = _clean_category(category)
        ids = list(dict.fromkeys(article_ids or []))
        if len(ids) > 100:
            raise validation("article_ids", "too_many", "单次最多关联 100 篇文章")
        now = utc_timestamp()
        with database.session() as conn:
            for article_id in ids:
                if event_repo.article_feature_row(conn, article_id) is None:
                    raise validation("article_ids", "not_found", f"文章不存在：{article_id}")
                if event_repo.get_article_membership(conn, article_id) is not None:
                    raise conflict("event_article_conflict", "文章已属于其他事件")
            event_id = self._create_manual_event(
                conn,
                title=clean_title,
                category=clean_category,
                summary=(normalize_text(summary)[:2000] or None),
                article_ids=ids,
                now=now,
            )
            self._audit(
                conn,
                event_id=event_id,
                action="create_event",
                detail={"title": clean_title, "article_ids": ids, "is_manual": True},
                now=now,
            )
            event = event_repo.get(conn, event_id)
            if event is None:
                raise not_found("event_not_found", "事件不存在")
            return self._decorate(conn, event)

    def confirm(self, event_id: str) -> EventRecord:
        now = utc_timestamp()
        with database.session() as conn:
            event = event_repo.get(conn, event_id)
            if event is None:
                raise not_found("event_not_found", "事件不存在")
            if event.status != "candidate":
                raise conflict("event_not_confirmable", "只有候选事件可以确认")
            event_repo.update_event(
                conn,
                event_id,
                {
                    "status": "active",
                    "status_reason": "人工确认事件边界",
                    "is_manual": 1,
                    "updated_at": now,
                },
            )
            self._timeline(
                conn,
                event_id=event_id,
                kind="status_change",
                title="事件状态变化：candidate → active",
                description="人工确认事件边界",
                now=now,
                evidence={"previous": "candidate", "current": "active", "manual": True},
            )
            self._audit(
                conn,
                event_id=event_id,
                action="confirm_event",
                detail={"previous_status": "candidate"},
                now=now,
            )
            score_event_in_conn(conn, event_id, now=now)
            updated = event_repo.get(conn, event_id)
            assert updated is not None
            return self._decorate(conn, updated)

    def patch(
        self,
        event_id: str,
        *,
        title: str | None,
        summary: str | None,
        category: str | None,
        status: str | None,
        status_reason: str | None,
    ) -> EventRecord:
        now = utc_timestamp()
        with database.session() as conn:
            event = event_repo.get(conn, event_id)
            if event is None:
                raise not_found("event_not_found", "事件不存在")
            if event.status == "merged":
                raise conflict("invalid_event_status_transition", "已合并事件不可修改")
            fields: dict[str, object] = {"updated_at": now}
            action = "entity_metadata"
            detail: dict[str, object] = {}

            if title is not None:
                fields["title"] = _clean_title(title)
                fields["title_source"] = "manual"
                action = "rename_event"
                detail["previous_title"] = event.title
            if summary is not None:
                fields["summary"] = normalize_text(summary)[:2000] or None
                fields["summary_source"] = "manual"
                action = "entity_metadata"
                detail["summary_changed"] = True
            if category is not None:
                fields["category"] = _clean_category(category)
                fields["category_source"] = "manual"
                fields["category_reason"] = "人工修正事件分类"
                fields["category_updated_at"] = now
                action = "recategorize_event"
                detail["previous_category"] = event.category
            if status is not None:
                if status not in MANUAL_STATUSES:
                    raise validation("status", "invalid", "人工只能设置 active/dormant/closed/archived")
                if status != event.status:
                    fields["status"] = status
                    fields["status_reason"] = (
                        normalize_text(status_reason)[:500] or "人工调整事件状态"
                    )
                    fields["is_manual"] = 1
                    action = "change_status"
                    detail["previous_status"] = event.status
                    detail["current_status"] = status
            if len(fields) == 1:
                raise validation("body", "empty", "至少提供一个可修改字段")
            event_repo.update_event(conn, event_id, fields)
            if "status" in fields:
                self._timeline(
                    conn,
                    event_id=event_id,
                    kind="status_change",
                    title=f"事件状态变化：{event.status} → {fields['status']}",
                    description=str(fields.get("status_reason") or ""),
                    now=now,
                    evidence={
                        "previous": event.status,
                        "current": fields["status"],
                        "manual": True,
                    },
                )
            self._audit(conn, event_id=event_id, action=action, detail=detail, now=now)
            score_event_in_conn(conn, event_id, now=now)
            updated = event_repo.get(conn, event_id)
            assert updated is not None
            return self._decorate(conn, updated)

    def add_article(self, event_id: str, article_id: str, role: str) -> dict[str, object]:
        now = utc_timestamp()
        with database.session() as conn:
            event = event_repo.get(conn, event_id)
            if event is None:
                raise not_found("event_not_found", "事件不存在")
            if event.status in TERMINAL:
                raise conflict("event_article_conflict", "已归档事件不能添加文章")
            article = event_repo.article_feature_row(conn, article_id)
            if article is None:
                raise not_found("event_article_not_found", "文章不存在")
            membership = event_repo.get_article_membership(conn, article_id)
            moved_from = None
            if membership is not None:
                if str(membership["event_id"]) == event_id:
                    return {
                        "event_id": event_id,
                        "article_id": article_id,
                        "role": str(membership["role"]),
                        "moved_from_event_id": None,
                        "article_count": event.article_count,
                    }
                moved_from = str(membership["event_id"])
                event_repo.delete_event_article(conn, moved_from, article_id)
                event_repo.add_exclusion(
                    conn,
                    article_id=article_id,
                    event_id=moved_from,
                    reason=f"人工移动到 {event_id}",
                    created_at=now,
                )
                recompute_event_aggregates(conn, moved_from, now)
                rebuild_event_entities(conn, moved_from, now)
                self._audit(
                    conn,
                    event_id=moved_from,
                    action="detach_article",
                    detail={"article_id": article_id, "moved_to_event_id": event_id},
                    now=now,
                )

            event_repo.insert_event_article(
                conn,
                {
                    "id": str(uuid.uuid4()),
                    "event_id": event_id,
                    "article_id": article_id,
                    "role": role,
                    "similarity": None,
                    "match_reasons_json": json.dumps(["manual_add"]),
                    "is_manual": 1,
                    "added_at": now,
                    "created_at": now,
                },
            )
            event_repo.delete_exclusion(conn, article_id=article_id, event_id=event_id)
            event_repo.update_event(conn, event_id, {"is_manual": 1, "updated_at": now})
            stats = recompute_event_aggregates(conn, event_id, now)
            rebuild_event_entities(conn, event_id, now)
            if event_repo.timeline_is_empty(conn, event_id):
                self._timeline(
                    conn,
                    event_id=event_id,
                    kind="first_report",
                    title=str(article["title"]),
                    description=article["ai_summary"] or article["summary"],
                    now=now,
                    article_id=article_id,
                    published_at=article["published_at"],
                    evidence={"manual_add": True},
                )
            elif not event_repo.timeline_exists_for_article(conn, event_id, article_id):
                self._timeline(
                    conn,
                    event_id=event_id,
                    kind="follow_up",
                    title=str(article["title"]),
                    description=article["ai_summary"] or article["summary"],
                    now=now,
                    article_id=article_id,
                    published_at=article["published_at"],
                    is_key=True,
                    evidence={"manual_add": True},
                )
            refresh_event_summary(conn, event_id)
            status_change = None
            if event.status == "candidate":
                event_repo.update_event(
                    conn,
                    event_id,
                    {"status": "active", "status_reason": "人工加入文章", "updated_at": now},
                )
                status_change = {"previous": "candidate", "current": "active"}
                self._timeline(
                    conn,
                    event_id=event_id,
                    kind="status_change",
                    title="事件状态变化：candidate → active",
                    description="人工加入文章",
                    now=now,
                    is_key=True,
                    evidence=status_change,
                )
            self._audit(
                conn,
                event_id=event_id,
                action="attach_article",
                detail={
                    "article_id": article_id,
                    "role": role,
                    "moved_from_event_id": moved_from,
                    "status_change": status_change,
                },
                now=now,
            )
            score_event_in_conn(conn, event_id, now=now)
            return {
                "event_id": event_id,
                "article_id": article_id,
                "role": role,
                "moved_from_event_id": moved_from,
                "article_count": int(stats["article_count"]),
            }

    def remove_article(self, event_id: str, article_id: str) -> None:
        now = utc_timestamp()
        with database.session() as conn:
            event = event_repo.get(conn, event_id)
            if event is None:
                raise not_found("event_not_found", "事件不存在")
            if event_repo.get_event_article(conn, event_id, article_id) is None:
                raise not_found("event_article_not_found", "文章不在该事件中")
            if event_repo.count_event_articles(conn, event_id) <= 1:
                raise conflict(
                    "event_last_article", "事件必须至少保留一篇文章；如需结束请归档事件"
                )
            event_repo.delete_event_article(conn, event_id, article_id)
            removed_timeline = event_repo.delete_timeline_for_article(
                conn, event_id, article_id
            )
            event_repo.add_exclusion(
                conn,
                article_id=article_id,
                event_id=event_id,
                reason="人工移出事件",
                created_at=now,
            )
            event_repo.update_event(conn, event_id, {"is_manual": 1, "updated_at": now})
            recompute_event_aggregates(conn, event_id, now)
            rebuild_event_entities(conn, event_id, now)
            refresh_event_summary(conn, event_id)
            self._timeline(
                conn,
                event_id=event_id,
                kind="manual_note",
                title="文章被人工移出事件",
                description=f"article_id={article_id}",
                now=now,
                is_key=True,
                evidence={"article_id": article_id},
            )
            self._audit(
                conn,
                event_id=event_id,
                action="detach_article",
                detail={
                    "article_id": article_id,
                    "removed_timeline_items": removed_timeline,
                },
                now=now,
            )
            score_event_in_conn(conn, event_id, now=now)

    def add_note(
        self,
        event_id: str,
        *,
        title: str,
        description: str | None,
        occurred_at: str | None,
    ) -> str:
        now = utc_timestamp()
        with database.session() as conn:
            if event_repo.get(conn, event_id) is None:
                raise not_found("event_not_found", "事件不存在")
            item_id = str(uuid.uuid4())
            event_repo.insert_timeline_item(
                conn,
                {
                    "id": item_id,
                    "event_id": event_id,
                    "article_id": None,
                    "kind": "manual_note",
                    "title": _clean_title(title),
                    "description": (normalize_text(description)[:2000] or None),
                    "occurred_at": occurred_at,
                    "published_at": None,
                    "recognized_at": now,
                    "confidence": None,
                    "is_key": 1,
                    "evidence_json": json.dumps({"manual": True}, separators=(",", ":")),
                    "created_at": now,
                },
            )
            self._audit(
                conn,
                event_id=event_id,
                action="add_timeline_note",
                detail={"title": title, "occurred_at": occurred_at},
                now=now,
            )
            return item_id

    def merge(
        self, source_event_id: str, target_event_id: str, reason: str | None
    ) -> tuple[EventRecord, dict[str, int]]:
        if source_event_id == target_event_id:
            raise conflict("event_merge_conflict", "不能合并到自身")
        now = utc_timestamp()
        with database.session() as conn:
            source = event_repo.get(conn, source_event_id)
            target = event_repo.get(conn, target_event_id)
            if source is None or target is None:
                raise not_found("event_not_found", "事件不存在")
            if source.status == "merged" or target.status == "merged":
                raise conflict("event_merge_conflict", "已合并事件不能再合并")
            if target.status == "archived":
                raise conflict("event_merge_conflict", "不能合并到已归档事件")
            source_status = source.status
            moved_article_ids = event_repo.list_event_article_ids(conn, source_event_id)
            moved_timeline_ids = event_repo.list_timeline_ids(conn, source_event_id)
            moved, duplicates = event_repo.move_articles(
                conn, source_event_id=source_event_id, target_event_id=target_event_id
            )
            moved_timeline = event_repo.move_timeline_all(
                conn, source_event_id=source_event_id, target_event_id=target_event_id
            )
            relation_repo.merge_event_relations(
                conn,
                source_event_id=source_event_id,
                target_event_id=target_event_id,
                updated_at=now,
            )
            event_repo.delete_event_entities(conn, source_event_id)
            event_repo.update_event(
                conn,
                source_event_id,
                {
                    "status": "merged",
                    "merged_into_event_id": target_event_id,
                    "status_reason": (normalize_text(reason)[:500] or "人工合并到其他事件"),
                    "is_manual": 1,
                    "updated_at": now,
                },
            )
            event_repo.update_event(
                conn,
                target_event_id,
                {"is_manual": 1, "updated_at": now},
            )
            recompute_event_aggregates(conn, target_event_id, now)
            rebuild_event_entities(conn, target_event_id, now)
            refresh_event_summary(conn, target_event_id)
            self._timeline(
                conn,
                event_id=target_event_id,
                kind="merge",
                title=f"合并事件：{source.title}",
                description=f"来源事件 {source_event_id} 的 {moved} 篇文章与 {moved_timeline} 个时间线节点已并入",
                now=now,
                is_key=True,
                evidence={
                    "source_event_id": source_event_id,
                    "moved_articles": moved,
                    "duplicate_articles": duplicates,
                },
            )
            merge_audit_id = str(uuid.uuid4())
            audit_repo.insert(
                conn,
                audit_id=merge_audit_id,
                event_id=target_event_id,
                entity_id=None,
                action="merge_events",
                actor="user",
                detail={
                    "source_event_id": source_event_id,
                    "target_event_id": target_event_id,
                    "source_status": source_status,
                    "moved_articles": moved,
                    "duplicate_articles": duplicates,
                    "moved_timeline_items": moved_timeline,
                    "reason": (reason or "")[:500],
                },
                created_at=now,
            )
            # Full ID lists are stored as bounded JSON chunks so `unmerge` can
            # restore arbitrarily large merges without truncated/corrupt JSON.
            audit_repo.insert_merge_chunks(
                conn,
                audit_id=f"{merge_audit_id}:ids",
                target_event_id=target_event_id,
                source_event_id=source_event_id,
                source_status=source_status,
                article_ids=moved_article_ids,
                timeline_ids=moved_timeline_ids,
                reason=reason or "",
                created_at=now,
            )
            score_event_in_conn(conn, target_event_id, now=now)
            updated = event_repo.get(conn, target_event_id)
            assert updated is not None
            return self._decorate(conn, updated), {
                "moved_articles": moved,
                "duplicate_articles": duplicates,
                "moved_timeline_items": moved_timeline,
            }

    def unmerge(self, source_event_id: str) -> EventRecord:
        """撤销一次人工合并：把记录在审计中的文章与时间线节点搬回来源事件。

        Relations are not restored because the merge rewrites them in place;
        the audit detail records how many articles/timeline items were restored.
        """

        now = utc_timestamp()
        with database.session() as conn:
            source = event_repo.get(conn, source_event_id)
            if source is None:
                raise not_found("event_not_found", "事件不存在")
            if source.status != "merged" or not source.merged_into_event_id:
                raise conflict("event_not_merged", "该事件未被合并，无法撤销")
            target_event_id = source.merged_into_event_id
            target = event_repo.get(conn, target_event_id)
            if target is None:
                raise conflict("event_not_merged", "合并目标事件已不存在")
            detail = audit_repo.find_merge_detail(
                conn, target_event_id=target_event_id, source_event_id=source_event_id
            )
            if detail is None:
                raise conflict("event_merge_history_missing", "缺少可撤销的合并记录")

            raw_articles = detail.get("moved_article_ids")
            raw_timeline = detail.get("moved_timeline_ids")
            article_ids = (
                [str(item) for item in raw_articles if isinstance(item, str)]
                if isinstance(raw_articles, list)
                else []
            )
            timeline_ids = (
                [str(item) for item in raw_timeline if isinstance(item, str)]
                if isinstance(raw_timeline, list)
                else []
            )

            restored = 0
            for article_id in article_ids:
                membership = event_repo.get_article_membership(conn, article_id)
                if membership is None or str(membership["event_id"]) != target_event_id:
                    continue
                event_repo.move_articles(
                    conn,
                    source_event_id=target_event_id,
                    target_event_id=source_event_id,
                    article_ids=[article_id],
                )
                restored += 1
            if restored == 0:
                raise conflict(
                    "event_unmerge_conflict", "合并记录中的文章已不在目标事件中，无法撤销"
                )
            restored_timeline = event_repo.move_timeline_by_ids(
                conn,
                source_event_id=source_event_id,
                target_event_id=target_event_id,
                item_ids=timeline_ids,
            )

            previous = detail.get("source_status")
            status = (
                str(previous)
                if previous in {"candidate", "active", "evolving", "dormant", "closed", "archived"}
                else "active"
            )
            event_repo.update_event(
                conn,
                source_event_id,
                {
                    "status": status,
                    "merged_into_event_id": None,
                    "status_reason": "撤销合并",
                    "is_manual": 1,
                    "updated_at": now,
                },
            )
            recompute_event_aggregates(conn, source_event_id, now)
            recompute_event_aggregates(conn, target_event_id, now)
            rebuild_event_entities(conn, source_event_id, now)
            rebuild_event_entities(conn, target_event_id, now)
            refresh_event_summary(conn, source_event_id)
            refresh_event_summary(conn, target_event_id)
            self._timeline(
                conn,
                event_id=source_event_id,
                kind="split",
                title=f"撤销合并：从「{target.title}」恢复",
                description=(
                    f"恢复 {restored} 篇文章与 {restored_timeline} 个时间线节点；"
                    "事件关系不随撤销恢复"
                ),
                now=now,
                is_key=True,
                evidence={
                    "target_event_id": target_event_id,
                    "restored_articles": restored,
                    "restored_timeline_items": restored_timeline,
                },
            )
            self._audit(
                conn,
                event_id=source_event_id,
                action="unmerge_events",
                detail={
                    "source_event_id": source_event_id,
                    "target_event_id": target_event_id,
                    "restored_articles": restored,
                    "restored_timeline_items": restored_timeline,
                    "relations_restored": False,
                },
                now=now,
            )
            score_event_in_conn(conn, source_event_id, now=now)
            score_event_in_conn(conn, target_event_id, now=now)
            updated = event_repo.get(conn, source_event_id)
            assert updated is not None
            return self._decorate(conn, updated)

    def split(
        self,
        event_id: str,
        *,
        article_ids: list[str],
        title: str | None,
        category: str | None,
    ) -> EventRecord:
        ids = list(dict.fromkeys(article_ids))
        if not ids:
            raise validation("article_ids", "empty", "至少选择一篇文章")
        if len(ids) > 100:
            raise validation("article_ids", "too_many", "单次最多拆分 100 篇文章")
        now = utc_timestamp()
        with database.session() as conn:
            source = event_repo.get(conn, event_id)
            if source is None:
                raise not_found("event_not_found", "事件不存在")
            if source.status == "merged":
                raise conflict("event_not_splittable", "已合并事件不能拆分")
            members = set(event_repo.list_event_article_ids(conn, event_id))
            if not set(ids).issubset(members):
                raise conflict("event_not_splittable", "包含不属于该事件的文章")
            if not (members - set(ids)):
                raise conflict("event_not_splittable", "源事件必须至少保留一篇文章")

            new_category = _clean_category(category or source.category)
            new_title = _clean_title(title or f"{source.title}（拆分）")
            first, last = event_repo.article_publish_bounds(conn, ids)
            new_event_id = str(uuid.uuid4())
            event_repo.insert_event(
                conn,
                {
                    "id": new_event_id,
                    "title": new_title,
                    "summary": None,
                    "category": new_category,
                    "status": "active",
                    "status_reason": "人工拆分事件",
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "first_published_at": first,
                    "last_published_at": last,
                    "occurred_at": None,
                    "article_count": 0,
                    "source_count": 0,
                    "is_manual": 1,
                    "merged_into_event_id": None,
                    "algorithm_version": "event-cluster-v1",
                    "title_source": "manual",
                    "summary_source": "auto",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            moved, _ = event_repo.move_articles(
                conn,
                source_event_id=event_id,
                target_event_id=new_event_id,
                article_ids=ids,
            )
            for article_id in ids:
                event_repo.update_event_article(
                    conn, new_event_id, article_id, {"is_manual": 1}
                )
                event_repo.add_exclusion(
                    conn,
                    article_id=article_id,
                    event_id=event_id,
                    reason=f"人工拆分到 {new_event_id}",
                    created_at=now,
                )
            moved_timeline = event_repo.move_timeline_articles(
                conn,
                source_event_id=event_id,
                target_event_id=new_event_id,
                article_ids=ids,
            )
            event_repo.update_event(conn, event_id, {"is_manual": 1, "updated_at": now})
            recompute_event_aggregates(conn, new_event_id, now)
            rebuild_event_entities(conn, new_event_id, now)
            refresh_event_summary(conn, new_event_id)
            if event_repo.timeline_is_empty(conn, new_event_id):
                rows = event_repo.list_member_rows(conn, new_event_id)
                if rows:
                    first_row = rows[0]
                    self._timeline(
                        conn,
                        event_id=new_event_id,
                        kind="first_report",
                        title=str(first_row["title"]),
                        description=first_row["ai_summary"] or first_row["summary"],
                        now=now,
                        article_id=str(first_row["id"]),
                        published_at=first_row["published_at"],
                        evidence={"manual_split": True},
                    )
            recompute_event_aggregates(conn, event_id, now)
            rebuild_event_entities(conn, event_id, now)
            refresh_event_summary(conn, event_id)
            self._timeline(
                conn,
                event_id=event_id,
                kind="split",
                title=f"拆分出 {moved} 篇文章",
                description=f"新事件：{new_title}（{new_event_id}）",
                now=now,
                is_key=True,
                evidence={"new_event_id": new_event_id, "article_ids": ids},
            )
            self._audit(
                conn,
                event_id=event_id,
                action="split_event",
                detail={
                    "new_event_id": new_event_id,
                    "article_ids": ids,
                    "moved_articles": moved,
                    "moved_timeline_items": moved_timeline,
                },
                now=now,
            )
            score_event_in_conn(conn, event_id, now=now)
            score_event_in_conn(conn, new_event_id, now=now)
            created = event_repo.get(conn, new_event_id)
            assert created is not None
            return self._decorate(conn, created)

    def add_relation(
        self,
        event_id: str,
        *,
        target_event_id: str,
        relation_type: str,
        rationale: str | None,
        evidence_article_ids: list[str],
    ) -> EventRelationRecord:
        if relation_type not in RELATION_TYPES:
            raise validation("relation_type", "invalid", "关系类型不在允许范围")
        if event_id == target_event_id:
            raise validation("target_event_id", "invalid", "不能关联自身")
        now = utc_timestamp()
        evidence = list(dict.fromkeys(evidence_article_ids))
        if len(evidence) > MAX_RELATION_EVIDENCE:
            raise ServiceError(
                "relation_evidence_invalid",
                422,
                f"证据文章最多 {MAX_RELATION_EVIDENCE} 篇",
            )
        with database.session() as conn:
            source = event_repo.get(conn, event_id)
            target = event_repo.get(conn, target_event_id)
            if source is None or target is None:
                raise not_found("event_not_found", "事件不存在")
            if relation_repo.find(
                conn,
                source_event_id=event_id,
                target_event_id=target_event_id,
                relation_type=relation_type,
            ) is not None:
                raise conflict("event_relation_conflict", "该关系已存在")
            if evidence:
                valid = event_repo.article_ids_belonging_to_events(
                    conn, article_ids=evidence, event_ids=[event_id, target_event_id]
                )
                if set(evidence) - valid:
                    raise ServiceError(
                        "relation_evidence_invalid",
                        422,
                        "证据文章必须属于这两个事件",
                    )
            relation_id = str(uuid.uuid4())
            relation_repo.insert_manual(
                conn,
                {
                    "id": relation_id,
                    "source_event_id": event_id,
                    "target_event_id": target_event_id,
                    "relation_type": relation_type,
                    "confidence": 1.0,
                    "status": "confirmed",
                    "rationale": (normalize_text(rationale)[:1000] or None),
                    "evidence_article_ids_json": json.dumps(
                        evidence, ensure_ascii=False, separators=(",", ":")
                    ),
                    "actor": "manual",
                    "algorithm_version": "event-relation-v1",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            self._audit(
                conn,
                event_id=event_id,
                action="create_relation",
                detail={
                    "relation_id": relation_id,
                    "target_event_id": target_event_id,
                    "relation_type": relation_type,
                    "evidence_article_ids": evidence,
                },
                now=now,
            )
            relation = relation_repo.get(conn, relation_id)
            assert relation is not None
            return self._decorate_relations(conn, [relation])[0]

    def update_relation(
        self, event_id: str, relation_id: str, *, status: str
    ) -> EventRelationRecord:
        if status not in {"confirmed", "rejected"}:
            raise validation("status", "invalid", "关系状态只能是 confirmed 或 rejected")
        now = utc_timestamp()
        with database.session() as conn:
            relation = relation_repo.get(conn, relation_id)
            if relation is None or event_id not in {
                relation.source_event_id,
                relation.target_event_id,
            }:
                raise not_found("event_relation_not_found", "关系不存在")
            relation_repo.update_status(conn, relation_id, status=status, updated_at=now)
            self._audit(
                conn,
                event_id=event_id,
                action="update_relation",
                detail={"relation_id": relation_id, "status": status},
                now=now,
            )
            updated = relation_repo.get(conn, relation_id)
            assert updated is not None
            return self._decorate_relations(conn, [updated])[0]

    def resolve_decision(
        self, decision_id: str, *, action: str, event_id: str | None
    ) -> EventDecisionRecord:
        if action not in {"attach", "create_event", "ignore"}:
            raise validation("action", "invalid", "action 必须是 attach、create_event 或 ignore")
        now = utc_timestamp()
        with database.session() as conn:
            decision = cluster_repo.get_decision(conn, decision_id)
            if decision is None:
                raise not_found("clustering_run_not_found", "候选决策不存在")
            if decision.status != "pending":
                raise conflict("event_relation_conflict", "该候选决策已处理")
            if action == "ignore":
                cluster_repo.update_decision(
                    conn,
                    decision_id,
                    {
                        "decision": "manual_resolved",
                        "status": "ignored",
                        "resolved_at": now,
                        "method": "manual",
                    },
                )
            elif action == "attach":
                if not event_id:
                    raise validation("event_id", "required", "attach 必须提供事件 ID")
                event = event_repo.get(conn, event_id)
                if event is None or event.status in {"merged", "archived"}:
                    raise not_found("event_not_found", "事件不存在或不可用")
                if event_repo.get_article_membership(conn, decision.article_id) is not None:
                    raise conflict("event_article_conflict", "文章已属于其他事件")
                self._attach_single(
                    conn, event_id, decision.article_id, now, write_timeline=True
                )
                event_repo.update_event(
                    conn,
                    event_id,
                    {"is_manual": 1, "updated_at": now},
                )
                recompute_event_aggregates(conn, event_id, now)
                rebuild_event_entities(conn, event_id, now)
                refresh_event_summary(conn, event_id)
                score_event_in_conn(conn, event_id, now=now)
                cluster_repo.update_decision(
                    conn,
                    decision_id,
                    {
                        "candidate_event_id": event_id,
                        "decision": "manual_resolved",
                        "status": "resolved",
                        "resolved_at": now,
                        "method": "manual",
                    },
                )
            else:
                article = event_repo.article_feature_row(conn, decision.article_id)
                if article is None:
                    raise not_found("event_article_not_found", "文章不存在")
                category = article["ai_category"] or article["source_category"] or "其他"
                new_event_id = self._create_manual_event(
                    conn,
                    title=normalize_text(article["title"])[:300] or "未命名事件",
                    category=_clean_category(str(category)),
                    summary=article["ai_summary"] or article["summary"],
                    article_ids=[decision.article_id],
                    now=now,
                )
                cluster_repo.update_decision(
                    conn,
                    decision_id,
                    {
                        "candidate_event_id": new_event_id,
                        "decision": "manual_resolved",
                        "status": "resolved",
                        "resolved_at": now,
                        "method": "manual",
                    },
                )
                event_id = new_event_id
            self._audit(
                conn,
                event_id=event_id,
                action="resolve_candidate",
                detail={"decision_id": decision_id, "action": action},
                now=now,
            )
            updated = cluster_repo.get_decision(conn, decision_id)
            assert updated is not None
            return updated

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _decorate(self, conn: sqlite3.Connection, event: EventRecord) -> EventRecord:
        entities = tuple(event_repo.list_event_entities(conn, event.id))
        relations = tuple(
            self._decorate_relations(conn, relation_repo.list_for_event(conn, event.id))
        )
        return replace(
            event,
            entities=entities,
            top_entities=entities[:3],
            relations=relations,
        )

    def _decorate_relations(
        self, conn: sqlite3.Connection, relations: list[EventRelationRecord]
    ) -> list[EventRelationRecord]:
        return [
            replace(
                relation,
                evidence_articles=tuple(
                    relation_repo.article_titles(
                        conn, list(relation.evidence_article_ids)
                    )
                ),
            )
            for relation in relations
        ]

    def _create_manual_event(
        self,
        conn: sqlite3.Connection,
        *,
        title: str,
        category: str,
        summary: str | None,
        article_ids: list[str],
        now: str,
    ) -> str:
        first, last = event_repo.article_publish_bounds(conn, article_ids)
        event_id = str(uuid.uuid4())
        event_repo.insert_event(
            conn,
            {
                "id": event_id,
                "title": title,
                "summary": summary,
                "category": category,
                "status": "active",
                "status_reason": "人工创建事件",
                "first_seen_at": now,
                "last_seen_at": now,
                "first_published_at": first,
                "last_published_at": last,
                "occurred_at": None,
                "article_count": 0,
                "source_count": 0,
                "is_manual": 1,
                "merged_into_event_id": None,
                "algorithm_version": "event-cluster-v1",
                "title_source": "manual",
                "summary_source": "manual" if summary else "auto",
                "created_at": now,
                "updated_at": now,
            },
        )
        for article_id in article_ids:
            self._attach_single(
                conn,
                event_id,
                article_id,
                now,
                write_timeline=False,
            )
        event_repo.set_category_provenance(
            conn,
            event_id,
            source="manual",
            reason="人工创建事件并指定分类",
            updated_at=now,
        )
        recompute_event_aggregates(conn, event_id, now)
        rebuild_event_entities(conn, event_id, now)
        refresh_event_summary(conn, event_id)
        rows = event_repo.list_member_rows(conn, event_id)
        if rows:
            first_row = rows[0]
            self._timeline(
                conn,
                event_id=event_id,
                kind="first_report",
                title=str(first_row["title"]),
                description=first_row["ai_summary"] or first_row["summary"],
                now=now,
                article_id=str(first_row["id"]),
                published_at=first_row["published_at"],
                evidence={"manual_create": True},
            )
        score_event_in_conn(conn, event_id, now=now)
        return event_id

    def _attach_single(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        article_id: str,
        now: str,
        *,
        write_timeline: bool = False,
    ) -> None:
        if event_repo.get_event_article(conn, event_id, article_id) is not None:
            return
        event_repo.insert_event_article(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "article_id": article_id,
                "role": "report",
                "similarity": None,
                "match_reasons_json": json.dumps(["manual"]),
                "is_manual": 1,
                "added_at": now,
                "created_at": now,
            },
        )
        event_repo.delete_exclusion(conn, article_id=article_id, event_id=event_id)
        if write_timeline:
            article = event_repo.article_feature_row(conn, article_id)
            if article is not None:
                self._timeline(
                    conn,
                    event_id=event_id,
                    kind="follow_up",
                    title=str(article["title"]),
                    description=article["ai_summary"] or article["summary"],
                    now=now,
                    article_id=article_id,
                    published_at=article["published_at"],
                    is_key=True,
                    evidence={"manual_add": True},
                )

    def _timeline(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        kind: str,
        title: str,
        description: str | None,
        now: str,
        article_id: str | None = None,
        published_at: str | None = None,
        is_key: bool = True,
        evidence: dict[str, object] | None = None,
    ) -> None:
        event_repo.insert_timeline_item(
            conn,
            {
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "article_id": article_id,
                "kind": kind,
                "title": title[:300] or "时间线节点",
                "description": (normalize_text(description)[:2000] or None),
                "occurred_at": None,
                "published_at": published_at,
                "recognized_at": now,
                "confidence": None,
                "is_key": 1 if is_key else 0,
                "evidence_json": json.dumps(
                    evidence or {}, ensure_ascii=False, separators=(",", ":")
                )[:4000],
                "created_at": now,
            },
        )

    def _audit(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str | None,
        action: str,
        detail: dict[str, object],
        now: str,
    ) -> None:
        audit_repo.insert(
            conn,
            audit_id=str(uuid.uuid4()),
            event_id=event_id,
            entity_id=None,
            action=action,
            actor="user",
            detail=detail,
            created_at=now,
        )


_event_service: EventService | None = None


def get_event_service() -> EventService:
    global _event_service
    if _event_service is None:
        _event_service = EventService()
    return _event_service
