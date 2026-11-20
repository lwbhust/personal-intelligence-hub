"""Unified error model and exception handlers.

Contract: `Docs/API_CONTRACT.md` §7. Every failure is converted into
`{"error": {"code": ..., "message": ...}}`; stacks, SQL and paths never leave
the process. `X-Request-ID` is attached by `RequestMiddleware`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from core.logging import log_event
from services.errors import ServiceError

ERROR_MESSAGES: dict[str, str] = {
    "unauthorized": "未授权：访问令牌缺失或无效",
    "not_found": "请求的资源不存在",
    "method_not_allowed": "请求方法不被允许",
    "invalid_request": "请求参数无效",
    "internal_error": "服务内部错误",
    "source_not_found": "信息源不存在",
    "source_category_not_found": "分类不存在",
    "source_url_conflict": "该 URL 的信息源已存在",
    "source_category_name_conflict": "分类名称已存在",
    "source_category_in_use": "该分类仍被信息源引用",
    "payload_too_large": "请求体过大",
    "insufficient_storage": "存储空间不足，已拒绝写入",
    "article_not_found": "文章不存在",
    "source_not_collectable": "信息源已停用或不可采集",
    "source_already_collecting": "该信息源正在采集",
    "adapter_not_supported": "该类型的信息源暂不支持采集",
    "no_enabled_sources": "没有可采集的信息源",
    "collection_batch_too_large": "单次最多采集 50 个信息源",
    "job_not_found": "采集任务不存在",
    "job_not_cancellable": "当前任务状态不可取消",
    "job_not_retryable": "当前任务状态不可重试",
    "collection_failed": "采集任务执行失败",
    "ai_disabled": "本地 AI 分析已禁用",
    "ai_model_not_configured": "没有启用的本地模型",
    "no_analyzable_articles": "没有需要分析的文章",
    "ai_run_in_progress": "已有 AI 运行在进行中",
    "ai_run_not_found": "AI 运行不存在",
    "run_not_pausable": "当前状态不可暂停",
    "run_not_resumable": "当前状态不可恢复",
    "run_not_cancellable": "当前状态不可取消",
    "run_not_retryable": "当前状态不可重试",
    "article_already_analyzed": "该文章已有分析结果",
    "article_not_analyzable": "文章没有可用于分析的文本",
    "ai_run_batch_too_large": "单次最多分析 100 篇文章",
    # Phase 4 — events
    "event_not_found": "事件不存在",
    "event_merge_conflict": "事件当前状态不允许合并",
    "event_not_merged": "该事件未被合并，无法撤销",
    "event_merge_history_missing": "缺少可撤销的合并记录",
    "event_unmerge_conflict": "合并记录中的文章已不在目标事件中，无法撤销",
    "event_article_not_found": "文章不在该事件中",
    "event_article_conflict": "文章已属于其他事件或事件不可修改",
    "event_not_splittable": "事件当前状态不允许拆分",
    "event_last_article": "事件必须至少保留一篇文章",
    "event_relation_conflict": "该关系已存在",
    "event_batch_too_large": "单次最多重算 200 个事件",
    "score_scope_invalid": "重算范围不在允许范围",
    "relation_evidence_invalid": "关系证据无效",
    # Phase 4 — entities
    "entity_not_found": "实体不存在",
    "entity_merge_conflict": "实体当前状态或类型不允许合并",
    "entity_not_merged": "该实体没有可撤销的合并记录",
    "entity_alias_conflict": "该别名已属于同类型的其他实体",
    "entity_alias_protected": "规范名别名不可删除",
    "entity_alias_not_found": "别名不存在",
    # Phase 4 — clustering
    "clustering_run_not_found": "聚类任务不存在",
    "clustering_run_in_progress": "已有聚类任务在排队或运行中",
    "clustering_run_not_cancellable": "该聚类任务当前不可取消",
    "clustering_run_not_retryable": "该聚类任务当前不可重试",
    "no_clusterable_articles": "没有可聚类的文章",
    "clustering_disabled": "事件聚类已被配置关闭",
}

_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "不能为空",
    "string_too_long": "长度超出限制",
    "string_too_short": "长度不足",
    "string_type": "必须是字符串",
    "int_parsing": "必须是整数",
    "int_type": "必须是整数",
    "bool_parsing": "必须是布尔值",
    "bool_type": "必须是布尔值",
    "literal_error": "取值不在允许范围",
    "enum": "取值不在允许范围",
    "extra_forbidden": "不允许的字段",
    "uuid_parsing": "必须是合法的 UUID",
}


def error_body(
    code: str,
    details: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "code": code,
        "message": ERROR_MESSAGES.get(code, "服务内部错误"),
    }
    if details:
        error["details"] = details[:10]
    return {"error": error}


def code_for_status(status_code: int) -> str:
    if status_code == 401:
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    if status_code == 405:
        return "method_not_allowed"
    if status_code == 413:
        return "payload_too_large"
    if status_code == 507:
        return "insufficient_storage"
    if status_code == 500:
        return "internal_error"
    if status_code >= 500:
        return "internal_error"
    return "invalid_request"


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    status_code = int(exc.status_code)
    error_code = code_for_status(status_code)
    log_event(
        "request_error",
        level="error" if status_code >= 500 else "warn",
        request_id=request_id_of(request),
        error_code=error_code,
        status_code=status_code,
    )
    return JSONResponse(status_code=status_code, content=error_body(error_code))


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in exc.errors():
        location = [str(part) for part in item.get("loc", ())]
        field = location[-1] if location else "request"
        if field in ("body", "query", "path"):
            field = location[0] if location else "request"
        if field in seen:
            continue
        seen.add(field)
        reason = str(item.get("type", "invalid"))
        details.append(
            {
                "field": field,
                "reason": "invalid" if reason == "value_error" else reason,
                "message": _VALIDATION_MESSAGES.get(reason, "参数无效"),
            }
        )
        if len(details) >= 10:
            break

    log_event(
        "request_error",
        level="warn",
        request_id=request_id_of(request),
        error_code="invalid_request",
        status_code=422,
        exc_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=422, content=error_body("invalid_request", details)
    )


async def service_exception_handler(
    request: Request, exc: ServiceError
) -> JSONResponse:
    log_event(
        "request_error",
        level="error" if exc.status_code >= 500 else "warn",
        request_id=request_id_of(request),
        error_code=exc.code,
        status_code=exc.status_code,
    )
    details = [
        {"field": item.field, "reason": item.reason, "message": item.message}
        for item in exc.details
    ]
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, details),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log_event(
        "request_error",
        level="error",
        request_id=request_id_of(request),
        error_code="internal_error",
        status_code=500,
        exc_type=type(exc).__name__,
    )
    return JSONResponse(status_code=500, content=error_body("internal_error"))


def register_exception_handlers(app: Any) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ServiceError, service_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
