"""Parameterised SQL for `event_audit_log`."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

MAX_DETAIL_BYTES = 12000
MAX_STRING = 2000
MAX_LIST = 80


def _shrink(value: object) -> object:
    """Bound audit detail while keeping the payload valid JSON.

    Large ID lists are chunked by the merge writer, so this only guards
    accidental oversized strings/lists. It never slices serialized JSON.
    """

    if isinstance(value, str):
        return value if len(value) <= MAX_STRING else value[:MAX_STRING] + "…"
    if isinstance(value, list):
        items = [_shrink(item) for item in value[:MAX_LIST]]
        if len(value) > MAX_LIST:
            items.append(f"__truncated__:{len(value) - MAX_LIST}")
        return items
    if isinstance(value, dict):
        return {str(key): _shrink(item) for key, item in value.items()}
    return value


def insert(
    conn: sqlite3.Connection,
    *,
    audit_id: str,
    event_id: str | None,
    entity_id: str | None,
    action: str,
    actor: str,
    detail: Mapping[str, object],
    created_at: str,
) -> None:
    payload = json.dumps(
        _shrink(dict(detail)), ensure_ascii=False, separators=(",", ":")
    )
    if len(payload.encode("utf-8")) > MAX_DETAIL_BYTES:
        # Last resort: keep a valid, minimal JSON object instead of a broken
        # truncated string (unmerge would otherwise lose the audit record).
        payload = json.dumps(
            {"truncated": True, "keys": sorted(str(key) for key in detail)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    conn.execute(
        "INSERT INTO event_audit_log "
        "(id, event_id, entity_id, action, actor, detail_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (audit_id, event_id, entity_id, action, actor, payload, created_at),
    )


def insert_merge_chunks(
    conn: sqlite3.Connection,
    *,
    audit_id: str,
    target_event_id: str,
    source_event_id: str,
    source_status: str,
    article_ids: list[str],
    timeline_ids: list[str],
    reason: str,
    created_at: str,
    chunk_size: int = 80,
) -> int:
    """Store a merge audit as bounded, valid-JSON chunks.

    Returns the number of rows written. `unmerge` concatenates the chunks to
    restore every moved article/timeline item regardless of merge size.
    """

    written = 0
    for kind, values in (("articles", article_ids), ("timeline", timeline_ids)):
        chunks = [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]
        if not chunks:
            chunks = [[]]
        for index, chunk in enumerate(chunks):
            insert(
                conn,
                audit_id=audit_id if written == 0 else f"{audit_id}:{written}",
                event_id=target_event_id,
                entity_id=None,
                action="merge_events",
                actor="user",
                detail={
                    "source_event_id": source_event_id,
                    "target_event_id": target_event_id,
                    "source_status": source_status,
                    "kind": kind,
                    "chunk": index,
                    "chunks": len(chunks),
                    "ids": chunk,
                    "reason": reason[:500],
                },
                created_at=created_at,
            )
            written += 1
    return written


def list_for_event(
    conn: sqlite3.Connection, event_id: str, *, limit: int = 50
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM event_audit_log WHERE event_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (event_id, limit),
    ).fetchall()


def list_for_entity(
    conn: sqlite3.Connection, entity_id: str, *, limit: int = 50
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM event_audit_log WHERE entity_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (entity_id, limit),
    ).fetchall()


def find_merge_detail(
    conn: sqlite3.Connection, *, target_event_id: str, source_event_id: str
) -> dict[str, object] | None:
    """Return the merged audit record for `source` folded into `target`.

    Merge audits may span multiple chunk rows; they are reassembled here so
    `unmerge` can restore large merges without truncation.
    """

    rows = conn.execute(
        "SELECT detail_json, created_at FROM event_audit_log "
        "WHERE event_id = ? AND action = 'merge_events' "
        "ORDER BY created_at DESC, id DESC LIMIT 2000",
        (target_event_id,),
    ).fetchall()
    article_ids: list[str] = []
    timeline_ids: list[str] = []
    source_status: str | None = None
    reason = ""
    batch_created_at: str | None = None
    matched = 0
    for row in rows:
        try:
            detail = json.loads(str(row[0]))
        except (TypeError, ValueError):
            continue
        if not isinstance(detail, dict) or detail.get("source_event_id") != source_event_id:
            continue
        created_at = str(row[1])
        # Chunks of one merge share `created_at`; ignore older merge batches so
        # a merge → unmerge → merge sequence never double-restores rows.
        if batch_created_at is None:
            batch_created_at = created_at
        elif created_at != batch_created_at:
            continue
        matched += 1
        kind = detail.get("kind")
        ids = detail.get("ids")
        if isinstance(ids, list):
            bucket = article_ids if kind == "articles" else timeline_ids if kind == "timeline" else None
            if bucket is not None:
                bucket.extend(str(item) for item in ids if isinstance(item, str))
        if source_status is None and isinstance(detail.get("source_status"), str):
            source_status = str(detail["source_status"])
        if not reason and isinstance(detail.get("reason"), str):
            reason = str(detail["reason"])
    if matched == 0:
        return None
    return {
        "source_event_id": source_event_id,
        "target_event_id": target_event_id,
        "source_status": source_status,
        "moved_article_ids": article_ids,
        "moved_timeline_ids": timeline_ids,
        "reason": reason,
    }
