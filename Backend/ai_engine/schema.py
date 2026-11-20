"""JSON extraction and strict validation for article analysis output.

The model is untrusted: only a fully validated object is persisted. Unknown
fields, wrong types, invalid categories and empty summaries are rejected so a
retry (or a failed item) happens instead of writing a half-guessed result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import AIError, INVALID_JSON, SCHEMA_INVALID

CATEGORIES = (
    "科技",
    "财经",
    "政治",
    "国际",
    "社会",
    "健康",
    "教育",
    "文化",
    "体育",
    "其他",
)
ENTITY_TYPES = ("person", "organization", "product", "location", "event", "other")
SUMMARY_MAX_CHARS = 300
KEYWORDS_MIN = 3
KEYWORDS_MAX = 6
KEYWORD_MAX_CHARS = 30
ENTITIES_MAX = 10
ENTITY_NAME_MAX_CHARS = 60

_ENTITY_TYPE_SYNONYMS = {
    "company": "organization",
    "org": "organization",
    "organization": "organization",
    "organisation": "organization",
    "企业": "organization",
    "公司": "organization",
    "机构": "organization",
    "组织": "organization",
    "people": "person",
    "人物": "person",
    "人名": "person",
    "产品": "product",
    "地点": "location",
    "地区": "location",
    "place": "location",
    "事件": "event",
    "其他": "other",
}


class EntityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str


class AnalysisOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    summary: str
    keywords: list[str]
    entities: list[EntityOut] = []


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    category: str
    summary: str
    keywords: tuple[str, ...]
    entities: tuple[dict[str, str], ...]
    confidence: float
    warnings: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "category": self.category,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "entities": [dict(item) for item in self.entities],
        }


def extract_json(text: str) -> dict[str, Any]:
    """Return the first balanced JSON object found in a model response."""

    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    start = candidate.find("{")
    bracket = candidate.find("[")
    if start < 0 or (bracket >= 0 and bracket < start):
        raise AIError(INVALID_JSON, "模型输出中未找到 JSON 对象")
    try:
        value, _ = json.JSONDecoder().raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        raise AIError(INVALID_JSON, "模型输出的 JSON 无法解析") from exc
    if not isinstance(value, dict):
        raise AIError(INVALID_JSON, "模型输出不是 JSON 对象")
    return value


def _clean_keyword(value: str) -> str:
    return value.strip().strip("`\"'“”‘’。，、；;:：").strip()


def _normalized_entity_type(value: str) -> str:
    raw = value.strip().lower()
    if raw in ENTITY_TYPES:
        return raw
    return _ENTITY_TYPE_SYNONYMS.get(raw) or _ENTITY_TYPE_SYNONYMS.get(value.strip()) or "other"


def _confidence(
    *,
    keyword_count: int,
    entity_count: int,
    summary_length: int,
    truncated: bool,
) -> float:
    score = 0.6
    if keyword_count >= KEYWORDS_MIN:
        score += 0.1
    if entity_count > 0:
        score += 0.1
    if 20 <= summary_length <= SUMMARY_MAX_CHARS:
        score += 0.1
    if not truncated:
        score += 0.1
    return round(min(1.0, score), 2)


def validate_analysis(payload: dict[str, Any]) -> AnalysisResult:
    try:
        parsed = AnalysisOut.model_validate(payload)
    except ValidationError as exc:
        raise AIError(SCHEMA_INVALID, "模型输出未通过结构校验") from exc

    warnings: list[str] = []
    truncated = False

    category = parsed.category.strip()
    if category not in CATEGORIES:
        raise AIError(SCHEMA_INVALID, "模型输出的分类不在允许范围内")

    summary = parsed.summary.strip()
    if not summary:
        raise AIError(SCHEMA_INVALID, "模型输出的摘要为空")
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[:SUMMARY_MAX_CHARS]
        truncated = True
        warnings.append("summary_truncated")

    keywords: list[str] = []
    for item in parsed.keywords:
        text = _clean_keyword(item)
        if not text:
            continue
        if len(text) > KEYWORD_MAX_CHARS:
            text = text[:KEYWORD_MAX_CHARS]
            truncated = True
            warnings.append("keyword_truncated")
        if text not in keywords:
            keywords.append(text)
    if len(keywords) < KEYWORDS_MIN:
        raise AIError(SCHEMA_INVALID, "模型输出的关键词少于 3 个")
    if len(keywords) > KEYWORDS_MAX:
        keywords = keywords[:KEYWORDS_MAX]
        warnings.append("keywords_trimmed")

    entities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entity in parsed.entities:
        name = entity.name.strip()
        if not name:
            continue
        if len(name) > ENTITY_NAME_MAX_CHARS:
            name = name[:ENTITY_NAME_MAX_CHARS]
            truncated = True
            warnings.append("entity_name_truncated")
        entity_type = _normalized_entity_type(entity.type)
        if entity_type != entity.type.strip().lower():
            warnings.append("entity_type_normalized")
        key = (name, entity_type)
        if key in seen:
            continue
        seen.add(key)
        entities.append({"name": name, "type": entity_type})
    if len(entities) > ENTITIES_MAX:
        entities = entities[:ENTITIES_MAX]
        warnings.append("entities_trimmed")

    confidence = _confidence(
        keyword_count=len(keywords),
        entity_count=len(entities),
        summary_length=len(summary),
        truncated=truncated,
    )
    return AnalysisResult(
        category=category,
        summary=summary,
        keywords=tuple(keywords),
        entities=tuple(entities),
        confidence=confidence,
        warnings=tuple(dict.fromkeys(warnings)),
    )
