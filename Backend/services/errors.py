"""Domain errors and their HTTP projection for Phase 1 services.

`api/errors.py` registers a handler for `ServiceError`; routers therefore only
raise domain errors and never build HTTP responses themselves.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    field: str
    reason: str
    message: str


class ServiceError(Exception):
    """A stable business error with an HTTP status and optional field details."""

    def __init__(
        self,
        code: str,
        status_code: int,
        message: str,
        details: tuple[ErrorDetail, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.details = details


def not_found(code: str, message: str) -> ServiceError:
    return ServiceError(code, 404, message)


def conflict(
    code: str, message: str, *, details: tuple[ErrorDetail, ...] = ()
) -> ServiceError:
    return ServiceError(code, 409, message, details)


def validation(
    field: str, reason: str, message: str
) -> ServiceError:
    return ServiceError(
        "invalid_request",
        422,
        "请求参数无效",
        (ErrorDetail(field=field, reason=reason, message=message),),
    )


def validation_many(details: list[ErrorDetail]) -> ServiceError:
    return ServiceError("invalid_request", 422, "请求参数无效", tuple(details))


def insufficient_storage() -> ServiceError:
    return ServiceError("insufficient_storage", 507, "存储空间不足，已拒绝写入")


def unsupported(code: str, message: str) -> ServiceError:
    return ServiceError(code, 422, message)
