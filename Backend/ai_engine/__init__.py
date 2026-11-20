"""Local AI engine (Phase 3): provider, prompts and output validation."""

from __future__ import annotations

from .errors import AIError
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_messages, sanitize_text
from .provider import (
    BASE_URL,
    GenerationResult,
    OllamaLocalProvider,
    ProviderHealth,
    RemoteModel,
    is_remote_model_name,
)
from .schema import CATEGORIES, ENTITY_TYPES, AnalysisResult, extract_json, validate_analysis

__all__ = [
    "AIError",
    "AnalysisResult",
    "BASE_URL",
    "CATEGORIES",
    "ENTITY_TYPES",
    "GenerationResult",
    "OllamaLocalProvider",
    "PROMPT_VERSION",
    "ProviderHealth",
    "RemoteModel",
    "SYSTEM_PROMPT",
    "build_messages",
    "extract_json",
    "is_remote_model_name",
    "sanitize_text",
    "validate_analysis",
]
