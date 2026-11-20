"""Entity name cleaning, type mapping, normalisation and alias variants."""

from __future__ import annotations

import re
import unicodedata

from .text import normalize_text

ENTITY_TYPES = (
    "person",
    "organization",
    "location",
    "company",
    "product",
    "event",
    "other",
)
TYPE_GROUPS = ("person", "organization", "location", "product", "event", "other")

_TYPE_ALIASES = {
    "person": "person",
    "people": "person",
    "人物": "person",
    "人名": "person",
    "organization": "organization",
    "organisation": "organization",
    "org": "organization",
    "组织": "organization",
    "机构": "organization",
    "company": "company",
    "corp": "company",
    "enterprise": "company",
    "企业": "company",
    "公司": "company",
    "location": "location",
    "place": "location",
    "gpe": "location",
    "地点": "location",
    "地区": "location",
    "城市": "location",
    "product": "product",
    "产品": "product",
    "event": "event",
    "事件": "event",
    "other": "other",
    "其他": "other",
}

_COMPANY_RE = re.compile(
    r"(公司|集团|控股|银行|保险|证券|基金|"
    r"\binc\.?|\bltd\.?|\bllc\b|\bcorp\.?|\bgmbh\b|\bplc\b|\bco\.)",
    re.IGNORECASE,
)

# Longest first so 股份有限公司 wins over 有限公司.
_LEGAL_SUFFIXES = (
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "有限公司",
    "incorporated",
    "corporation",
    "company",
    "limited",
    "gmbh",
    "ltd",
    "llc",
    "inc",
    "corp",
    "plc",
    "ag",
    "sa",
    "bv",
    "nv",
    "co",
)

_PAREN_RE = re.compile(r"[（(]([^（）()]{1,120})[）)]")
_ALIAS_SPLIT_RE = re.compile(r"[/｜|、,，;；]")
_LEAD_STRIP = "\"'“”‘’《》<>【】[]（）(){}「」"
_TRAIL_STRIP = "\"'“”‘’.,;:。，、；："
_CLOSERS = {")": "(", "）": "（", "]": "[", "】": "【", "}": "{", "》": "《", "」": "「"}

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _trim_edges(text: str) -> str:
    """Trim wrapping quotes/brackets and trailing punctuation only.

    A closing bracket that is balanced by an opening bracket earlier in the
    name is part of the name (``星河科技(Galaxy Tech)``), so it must survive:
    removing it would break parenthesised alias extraction.
    """

    text = text.lstrip(_LEAD_STRIP + " .。，,;；:：")
    text = text.rstrip(_TRAIL_STRIP)
    while text and text[-1] in _CLOSERS:
        opener = _CLOSERS[text[-1]]
        if text.count(opener) >= text.count(text[-1]):
            break
        text = text[:-1].rstrip(_TRAIL_STRIP + _LEAD_STRIP)
    return text


def clean_entity_name(value: str | None) -> str:
    text = normalize_text(value)
    text = _trim_edges(text)
    text = re.sub(r"\s+", " ", text)
    return text[:200].strip()


def _key_chars(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    chars: list[str] = []
    for ch in text:
        if ch.isalnum() or _CJK_RE.match(ch):
            chars.append(ch)
    return "".join(chars)


def _strip_legal_suffix(key: str) -> str:
    for suffix in _LEGAL_SUFFIXES:
        if key.endswith(suffix) and len(key) - len(suffix) >= 2:
            return key[: -len(suffix)]
    return key


def normalized_key(value: str | None, type_group: str = "other") -> str:
    key = _key_chars(value or "")
    if type_group == "organization":
        key = _strip_legal_suffix(key)
        if key.startswith("the") and len(key) > 5:
            key = key[3:]
    if not key:
        key = _key_chars(clean_entity_name(value)) or "unknown"
    return key[:200]


def entity_type_of(raw_type: str | None, name: str | None) -> tuple[str, str]:
    raw = (raw_type or "other").strip().lower()
    mapped = _TYPE_ALIASES.get(raw, "other")
    if mapped == "organization" and name and _COMPANY_RE.search(name):
        mapped = "company"
    if mapped == "company":
        group = "organization"
    elif mapped in TYPE_GROUPS:
        group = mapped
    else:
        mapped = "other"
        group = "other"
    return mapped, group


def guess_language(value: str | None) -> str:
    text = value or ""
    has_cjk = bool(_CJK_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def alias_variants(name: str | None, entity_type: str) -> list[tuple[str, str]]:
    """Return de-duplicated ``(alias, language)`` variants for a name."""

    cleaned = clean_entity_name(name)
    if not cleaned:
        return []

    raw_candidates: list[str] = [cleaned]

    base = _PAREN_RE.sub(" ", cleaned)
    base = re.sub(r"\s+", " ", base).strip()
    if base and base != cleaned:
        raw_candidates.append(base)
    for group in _PAREN_RE.findall(cleaned):
        raw_candidates.extend(_ALIAS_SPLIT_RE.split(group))

    if _PAREN_RE.search(cleaned) is None:
        parts = [part.strip() for part in _ALIAS_SPLIT_RE.split(cleaned)]
        if len(parts) > 1:
            raw_candidates.extend(part for part in parts if len(part) >= 2)

    group = entity_type_of(entity_type, cleaned)[1]
    if group == "organization":
        key = _key_chars(cleaned)
        stripped = _strip_legal_suffix(key)
        if stripped and stripped != key:
            raw_candidates.append(stripped)

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        alias = clean_entity_name(candidate)
        if not alias or len(alias) > 200:
            continue
        dedupe = alias.casefold()
        if dedupe in seen:
            continue
        seen.add(dedupe)
        result.append((alias, guess_language(alias)))
    return result


def mention_confidence(analysis_confidence: float | None, method: str) -> float:
    base = max(0.0, min(1.0, float(analysis_confidence or 0.6)))
    if method == "manual":
        return 1.0
    factor = {"canonical": 0.95, "alias": 0.85, "ambiguous": 0.4}.get(method, 0.7)
    return round(max(0.3, min(1.0, base * factor)), 2)


def compatible_groups(left: str, right: str) -> bool:
    return left == right
