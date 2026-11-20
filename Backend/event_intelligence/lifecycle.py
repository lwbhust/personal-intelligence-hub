"""Deterministic event lifecycle transitions (`event-lifecycle-v1`).

`closed` and `archived` are never produced automatically: inactivity only makes
an event dormant, it does not prove the event ended.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .text import parse_timestamp

AUTO_TERMINAL = {"merged", "closed", "archived"}


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _days_since(value: str | None, now: datetime) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _hours_since(value: str | None, now: datetime) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def next_status(
    current: str,
    *,
    article_count: int,
    first_seen_at: str | None,
    last_published_at: str | None,
    now: datetime | None = None,
    new_article: bool = False,
) -> str:
    moment = _now(now)
    if current in AUTO_TERMINAL:
        return current
    if current not in {"candidate", "active", "evolving", "dormant"}:
        return current

    age_days = _days_since(first_seen_at, moment) or 0.0
    last_days = _days_since(last_published_at, moment)
    last_hours = _hours_since(last_published_at, moment)

    if current == "dormant":
        if new_article and (last_days is None or last_days <= 7):
            return "active"
        return "dormant"

    if current == "candidate":
        return "active" if article_count >= 2 else "candidate"

    if current == "active":
        if age_days >= 3 and new_article and (last_hours is None or last_hours <= 72):
            return "evolving"
        if last_days is not None and last_days > 14:
            return "dormant"
        return "active"

    # evolving
    if last_days is not None and last_days > 14:
        return "dormant"
    if not new_article and last_hours is not None and last_hours > 72:
        return "active"
    return "evolving"


def transition_reason(previous: str, current: str) -> str:
    if previous == current:
        return ""
    reasons = {
        ("candidate", "active"): "事件已有至少两篇报道",
        ("active", "evolving"): "事件持续发展：近期仍在新增报道",
        ("evolving", "active"): "近期报道趋缓，事件仍活跃",
        ("active", "dormant"): "超过 14 天没有新增报道（仅表示暂无进展，不代表结束）",
        ("evolving", "dormant"): "超过 14 天没有新增报道（仅表示暂无进展，不代表结束）",
        ("dormant", "active"): "休眠事件出现新报道",
    }
    return reasons.get((previous, current), f"状态由 {previous} 变为 {current}")
