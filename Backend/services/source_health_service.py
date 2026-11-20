"""Source health history reads and failure classification (Phase 8.0).

Phase 8.0 adds a small, dependency-free policy layer on top of the raw
collector error codes. It answers three questions the collector and the UI
need:

* what kind of failure was this (temporary network hiccup, dead URL, broken
  feed, security block, ...);
* how many consecutive failures should move a source from ``degraded`` to
  ``failing``;
* how long a failing source should cool down before the scheduler retries it.

The classification never changes what is stored per fetch: the raw
``error_code`` and message are preserved in ``source_health_logs`` and
``collection_job_items`` for auditing.
"""

from __future__ import annotations

from dataclasses import dataclass

import database
from database.repositories import source_health_repository as health_repo
from database.repositories import source_repository as source_repo
from database.repositories.models import SourceHealthRecord

from .errors import not_found

# Failure kinds -------------------------------------------------------------

TRANSIENT_NETWORK = "transient_network"
HTTP_GONE = "http_gone"
HTTP_CLIENT = "http_client"
FEED_INVALID = "feed_invalid"
ADAPTER_INVALID = "adapter_invalid"
SECURITY_BLOCKED = "security_blocked"
CONTENT_FORMAT = "content_format"
SYSTEM_INTERNAL = "system_internal"
UNKNOWN = "unknown"

_TRANSIENT_CODES = {
    "dns_failure",
    "network_timeout",
    "network_unreachable",
    "http_server_error",
    "interrupted",
}
_FEED_CODES = {"xml_parse_error", "feed_empty", "unsupported_content_type"}
_SECURITY_CODES = {"blocked_target", "redirect_rejected"}
_INTERNAL_CODES = {"internal_error", "collection_failed"}

# Codes that are caused by the local machine/network rather than the source.
SYSTEMIC_CODES = {"dns_failure", "network_unreachable"}


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    kind: str
    label: str
    # Consecutive failures needed before the source is marked ``failing``.
    escalate_after: int
    # Minimum minutes between scheduled retries once the source is failing.
    cooldown_minutes: int
    # True when the same problem is likely to hit every source at once.
    systemic: bool = False


def classify_failure(error_code: str | None, http_status: int | None = None) -> FailurePolicy:
    """Map a raw collector error code onto a retry/health policy."""

    code = (error_code or "").strip()
    if code in _TRANSIENT_CODES:
        return FailurePolicy(
            kind=TRANSIENT_NETWORK,
            label="网络或域名临时异常",
            escalate_after=3,
            cooldown_minutes=120,
            systemic=code in SYSTEMIC_CODES,
        )
    if code == "tls_error":
        return FailurePolicy(
            kind=TRANSIENT_NETWORK,
            label="TLS 握手或证书异常",
            escalate_after=3,
            cooldown_minutes=360,
        )
    if code == "http_client_error":
        if http_status in (404, 410):
            return FailurePolicy(
                kind=HTTP_GONE,
                label="链接已失效（HTTP 404/410）",
                escalate_after=2,
                cooldown_minutes=1440,
            )
        return FailurePolicy(
            kind=HTTP_CLIENT,
            label="目标站点拒绝访问（4xx）",
            escalate_after=3,
            cooldown_minutes=360,
        )
    if code in _FEED_CODES:
        return FailurePolicy(
            kind=FEED_INVALID,
            label="Feed 内容无法解析",
            escalate_after=3,
            cooldown_minutes=720,
        )
    if code.startswith("adapter_"):
        return FailurePolicy(
            kind=ADAPTER_INVALID,
            label="网页适配器未取到有效条目",
            escalate_after=3,
            cooldown_minutes=360,
        )
    if code in _SECURITY_CODES:
        return FailurePolicy(
            kind=SECURITY_BLOCKED,
            label="被安全策略拦截（域名或重定向不合规）",
            escalate_after=1,
            cooldown_minutes=1440,
        )
    if code == "partial_entry_errors":
        return FailurePolicy(
            kind=CONTENT_FORMAT,
            label="部分条目格式异常",
            escalate_after=5,
            cooldown_minutes=120,
        )
    if code in _INTERNAL_CODES:
        return FailurePolicy(
            kind=SYSTEM_INTERNAL,
            label="采集器内部异常",
            escalate_after=5,
            cooldown_minutes=60,
        )
    return FailurePolicy(
        kind=UNKNOWN,
        label="未知错误",
        escalate_after=3,
        cooldown_minutes=120,
    )


def describe_failure(error_code: str | None, message: str | None) -> str:
    """Human-readable failure line that is safe to show in the source list."""

    policy = classify_failure(error_code)
    base = (message or "").strip() or "采集失败"
    if policy.label and policy.label not in base:
        return f"{base}（{policy.label}）"[:500]
    return base[:500]


def effective_interval_minutes(
    *,
    base_interval: int,
    health_status: str,
    consecutive_failures: int,
    error_code: str | None,
) -> int:
    """Retry pacing for the scheduler.

    Healthy sources keep their configured interval. Failing sources back off
    to the policy cooldown so a dead URL is not hammered every few minutes —
    but they are never disabled or deleted automatically.
    """

    if health_status != "failing" and consecutive_failures < 3:
        return base_interval
    policy = classify_failure(error_code)
    return max(base_interval, policy.cooldown_minutes)


class SourceHealthService:
    def list(
        self, source_id: str, *, limit: int
    ) -> tuple[list[SourceHealthRecord], int]:
        with database.read_session() as conn:
            if source_repo.get_active(conn, source_id) is None:
                raise not_found("source_not_found", "信息源不存在")
            return health_repo.list_recent(conn, source_id, limit=limit)
