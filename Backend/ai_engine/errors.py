"""Stable AI engine errors shared by provider, schema and service layers."""

from __future__ import annotations


class AIError(Exception):
    """A failure with a stable code that is safe to persist and expose."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status


# Provider-level codes -------------------------------------------------------
PROVIDER_ENDPOINT_REJECTED = "provider_endpoint_rejected"
CLOUD_MODEL_BLOCKED = "cloud_model_blocked"
MODEL_NOT_ALLOWED = "model_not_allowed"
MODEL_UNAVAILABLE = "model_unavailable"
PROVIDER_TIMEOUT = "provider_timeout"
PROVIDER_UNREACHABLE = "provider_unreachable"
PROVIDER_HTTP_ERROR = "provider_http_error"
RESPONSE_TOO_LARGE = "response_too_large"
INVALID_RESPONSE = "invalid_response"
EMBEDDING_MODEL_UNAVAILABLE = "embedding_model_unavailable"

# Output-level codes ---------------------------------------------------------
INVALID_JSON = "invalid_json"
SCHEMA_INVALID = "schema_invalid"
ARTICLE_NOT_ANALYZABLE = "article_not_analyzable"
PROMPT_TOO_LONG = "prompt_too_long"
INTERRUPTED = "interrupted"
INTERNAL_ERROR = "internal_error"
