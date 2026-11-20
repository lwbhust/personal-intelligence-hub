"""Optional local-LLM judge for ambiguous article/event pairs (Phase 4).

Only used when the caller explicitly enables it. It can never override the
deterministic `separate` guards, never calls a cloud model, and any failure
degrades to the deterministic `ambiguous` result.
"""

from __future__ import annotations

import time

import database
from ai_engine.errors import AIError
from ai_engine.prompts import build_event_judge_messages
from ai_engine.provider import OllamaLocalProvider, ProviderHealth
from ai_engine.schema import extract_json
from core.logging import log_event
from database.repositories import ai_model_repository as model_repo
from database.repositories.models import AIModelRecord
from event_intelligence.clustering import ArticleFeatures, EventFeatures
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_LLM_PAIRS = 20
LLM_TIMEOUT_SECONDS = 60.0
LLM_NUM_PREDICT = 256
LLM_MIN_ACCEPT_CONFIDENCE = 0.8


class JudgeOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    same_event: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_article_ids: list[str] = Field(default_factory=list, max_length=10)
    reason: str = Field(default="", max_length=200)


class AmbiguousJudge:
    def __init__(self, provider: OllamaLocalProvider | None = None) -> None:
        self.provider = provider or OllamaLocalProvider()
        self.model_name: str | None = None

    def health(self) -> ProviderHealth:
        return self.provider.health_check()

    def _resolve_model(self) -> tuple[AIModelRecord, tuple[str, ...]] | None:
        with database.read_session() as conn:
            model = model_repo.default_model(conn, role="summary")
            allowed = model_repo.enabled_model_names(conn)
        if model is None:
            return None
        return model, allowed

    def judge(
        self,
        *,
        article: ArticleFeatures,
        event: EventFeatures,
        member_rows: list[tuple[str, str, str | None]],
    ) -> JudgeOutcome | None:
        resolved = self._resolve_model()
        if resolved is None:
            return None
        model, allowed = resolved
        self.model_name = model.model_name

        messages, _ = build_event_judge_messages(
            article_id=article.id,
            title=article.title,
            summary=article.summary,
            category=article.category,
            keywords=sorted(article.keywords),
            candidate_event_id=event.id,
            candidate_title=event.title,
            candidate_summary=event.summary,
            members=member_rows,
        )
        started = time.monotonic()
        try:
            result = self.provider.generate_structured(
                model=model.model_name,
                messages=messages,
                num_ctx=model.num_ctx,
                temperature=0.0,
                num_predict=LLM_NUM_PREDICT,
                allowed_models=allowed,
                timeout=LLM_TIMEOUT_SECONDS,
            )
            payload = extract_json(result.text)
            outcome = JudgeOutcome.model_validate(payload)
        except (AIError, ValidationError, ValueError) as exc:
            log_event(
                "event_judge_failed",
                level="warn",
                error_code=getattr(exc, "code", "invalid_judge_output"),
                exc_type=type(exc).__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - never break clustering
            log_event(
                "event_judge_failed",
                level="error",
                error_code="internal_error",
                exc_type=type(exc).__name__,
            )
            return None

        allowed_ids = {article.id} | set(event.member_article_ids)
        if any(item not in allowed_ids for item in outcome.evidence_article_ids):
            log_event(
                "event_judge_evidence_rejected",
                level="warn",
                article_id=article.id,
                event_id=event.id,
            )
            return None
        log_event(
            "event_judge_finished",
            article_id=article.id,
            event_id=event.id,
            same_event=outcome.same_event,
            confidence=outcome.confidence,
            duration_ms=int((time.monotonic() - started) * 1000),
            model=model.model_name,
        )
        return outcome

    @staticmethod
    def accepts(outcome: JudgeOutcome) -> bool:
        return (
            outcome.same_event
            and outcome.confidence >= LLM_MIN_ACCEPT_CONFIDENCE
            and bool(outcome.evidence_article_ids)
            and bool(outcome.reason.strip())
        )
