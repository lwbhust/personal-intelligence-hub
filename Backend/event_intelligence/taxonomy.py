"""Unified classification dictionary (`taxonomy-v1`).

PIH has three related but distinct classification concepts:

1. **source category** — how a feed is routed (`news`, `tech_zh`, …). It is a
   routing label only and must never decide an article's or an event's domain.
2. **article topic** — what the AI analysis says a single article is about.
3. **event domain** — the real-world field of an aggregated event.

`events.category` is constrained by the Phase 4 schema to ten Chinese names.
The dictionary therefore keeps a two-level model that is compatible with the
stored values: extended topics (人工智能 / 能源 / 环境 / 安全 / 军事 / 学术研究 …)
resolve to one of the ten stored domains.

Nothing in this module reads or writes the database; it is pure and cheap so it
can be reused by scoring, clustering, services and tests.
"""

from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "taxonomy-v1"

# Unknown categories are *not* mapped to `其他`: an unresolved classification is
# different from an article that is genuinely "other". Neutral base keeps an
# unmapped event from being systematically under-scored.
NEUTRAL_SCORING_BASE = 40.0


@dataclass(frozen=True, slots=True)
class DomainDef:
    """A first-level domain; `name` is the value persisted in `events.category`."""

    key: str
    name: str
    description: str
    scoring_base: float
    applies_to: tuple[str, ...] = ("event", "article_topic")
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class TopicDef:
    """An extended article topic that resolves to a stored domain."""

    key: str
    name: str
    domain_key: str
    description: str
    applies_to: tuple[str, ...] = ("article_topic", "source_route")
    enabled: bool = True


DOMAINS: tuple[DomainDef, ...] = (
    DomainDef("politics", "政治", "政府、政策、选举、立法与公共权力活动", 60.0),
    DomainDef("international", "国际", "跨国或他国事务、冲突、国际组织与全球治理", 58.0),
    DomainDef("finance", "财经", "宏观经济、金融市场、企业财务、能源与产业经济", 55.0),
    DomainDef("technology", "科技", "技术产品、平台、产业与科研工程进展", 50.0),
    DomainDef("health", "健康", "公共卫生、医疗、疾病与健康政策", 48.0),
    DomainDef("society", "社会", "民生、社会治理、环境、公共安全与事故灾害", 45.0),
    DomainDef("education", "教育", "学校、教育政策与人才培养", 35.0),
    DomainDef("culture", "文化", "文化、艺术、媒体与生活方式", 30.0),
    DomainDef("sports", "体育", "体育赛事与运动产业", 25.0),
    DomainDef("other", "其他", "无法可靠归入其他领域的待确认内容", 20.0),
)

DOMAIN_BY_KEY = {item.key: item for item in DOMAINS}
DOMAIN_BY_NAME = {item.name: item for item in DOMAINS}

# Extended second-level topics. They exist so that a later analysis version can
# emit a finer label without a schema change, and so source routing has a
# vocabulary. They always resolve down to one of the ten stored domains.
TOPICS: tuple[TopicDef, ...] = (
    TopicDef("ai", "人工智能", "technology", "模型、算力、算法与 AI 产业"),
    TopicDef("academic", "学术研究", "technology", "论文、科研机构与学术成果"),
    TopicDef("energy", "能源", "finance", "油气、电力、新能源与能源安全"),
    TopicDef("economy", "经济", "finance", "宏观经济运行与产业经济"),
    TopicDef("environment", "环境", "society", "气候、生态与污染治理"),
    TopicDef("security", "安全", "society", "公共安全、网络安全与事故灾害"),
    TopicDef("military", "军事", "international", "国防、军事行动与军备"),
    TopicDef("domestic", "国内", "society", "一国国内综合事务（来源路由提示）"),
)

TOPIC_BY_KEY = {item.key: item for item in TOPICS}

# Aliases are matched case-insensitively after trimming. Values may be the
# stored Chinese domain names, extended topic names, or common English keys.
_TOPIC_ALIASES: dict[str, str] = {}
for _domain in DOMAINS:
    _TOPIC_ALIASES[_domain.name] = _domain.key
    _TOPIC_ALIASES[_domain.key] = _domain.key
for _topic in TOPICS:
    _TOPIC_ALIASES[_topic.name] = _topic.key
    _TOPIC_ALIASES[_topic.key] = _topic.key

_TOPIC_ALIASES.update(
    {
        "politics": "politics",
        "political": "politics",
        "government": "politics",
        "gov": "politics",
        "政治": "politics",
        "国际关系": "international",
        "world": "international",
        "global": "international",
        "international": "international",
        "外交": "international",
        "finance": "finance",
        "financial": "finance",
        "business": "finance",
        "market": "finance",
        "money": "finance",
        "金融": "finance",
        "经济": "finance",
        "technology": "technology",
        "tech": "technology",
        "science": "technology",
        "科学": "technology",
        "技术": "technology",
        "ai": "ai",
        "artificial-intelligence": "ai",
        "人工智能": "ai",
        "health": "health",
        "medical": "health",
        "医疗": "health",
        "society": "society",
        "social": "society",
        "民生": "society",
        "education": "education",
        "教育": "education",
        "culture": "culture",
        "arts": "culture",
        "文化": "culture",
        "艺术": "culture",
        "sports": "sports",
        "sport": "sports",
        "体育": "sports",
        "运动": "sports",
        "other": "other",
        "others": "other",
        "misc": "other",
        "unknown": "other",
        "其他": "other",
        "其它": "other",
        "学术": "academic",
        "research": "academic",
        "学术研究": "academic",
    }
)

# Source categories are routing hints only. `authoritative` is always False:
# a source category can never decide an article topic or an event domain.
_SOURCE_ROUTES: dict[str, tuple[str, str]] = {
    # source category name -> (hint topic key, note)
    "news": ("international", "综合国际新闻频道，仅作为路由提示"),
    "news_zh": ("domestic", "中文综合新闻频道，仅作为路由提示"),
    "tech": ("technology", "英文科技频道，仅作为路由提示"),
    "tech_zh": ("technology", "中文科技频道，仅作为路由提示"),
    "research": ("academic", "学术/论文频道，仅作为路由提示"),
}


@dataclass(frozen=True, slots=True)
class CategoryResolution:
    """Result of resolving a free-form category label."""

    raw: str | None
    topic_key: str | None
    domain_key: str | None
    domain_name: str | None
    known: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw,
            "topic_key": self.topic_key,
            "domain_key": self.domain_key,
            "domain_name": self.domain_name,
            "known": self.known,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SourceRoute:
    source_category: str
    hint_topic_key: str | None
    hint_domain_key: str | None
    hint_domain_name: str | None
    authoritative: bool
    note: str


@dataclass(frozen=True, slots=True)
class EventDomainDecision:
    domain_key: str
    domain_name: str
    reason: str
    confidence: float
    resolved: bool
    unknown_members: int


def domain_name(key: str | None) -> str | None:
    item = DOMAIN_BY_KEY.get(key or "")
    return None if item is None else item.name


def domain_key_of(value: str | None) -> str | None:
    """Resolve a stored Chinese name or ASCII key to a domain key."""

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    direct = DOMAIN_BY_NAME.get(text)
    if direct is not None:
        return direct.key
    key = _TOPIC_ALIASES.get(text.lower())
    if key is None:
        return None
    if key in DOMAIN_BY_KEY:
        return key
    topic = TOPIC_BY_KEY.get(key)
    return None if topic is None else topic.domain_key


def resolve_category(value: str | None) -> CategoryResolution:
    """Resolve any label to a topic key and its stored domain."""

    if value is None or not str(value).strip():
        return CategoryResolution(None, None, None, None, False, "分类为空")

    text = str(value).strip()
    lookup = _TOPIC_ALIASES.get(text.lower()) or _TOPIC_ALIASES.get(text)
    if lookup is None:
        return CategoryResolution(text, None, None, None, False, "未知分类，保留待确认状态")

    if lookup in DOMAIN_BY_KEY:
        topic_key: str | None = lookup
        domain_key = lookup
        detail = "已匹配一级领域"
    else:
        topic = TOPIC_BY_KEY[lookup]
        topic_key = topic.key
        domain_key = topic.domain_key
        detail = f"二级主题映射到领域「{domain_name(domain_key)}」"
    return CategoryResolution(
        raw=text,
        topic_key=topic_key,
        domain_key=domain_key,
        domain_name=domain_name(domain_key),
        known=True,
        detail=detail,
    )


def event_domain_name(value: str | None) -> str:
    """Return the value safe to persist in `events.category`."""

    key = domain_key_of(value)
    return domain_name(key) or DOMAIN_BY_KEY["other"].name


def source_category_route(source_category: str | None) -> SourceRoute:
    """Return a non-authoritative routing hint for a source category."""

    text = (source_category or "").strip()
    hint = _SOURCE_ROUTES.get(text)
    if hint is None:
        return SourceRoute(
            source_category=text,
            hint_topic_key=None,
            hint_domain_key=None,
            hint_domain_name=None,
            authoritative=False,
            note="来源分类未知；不得据此推断文章主题或事件领域",
        )
    topic_key, note = hint
    topic = TOPIC_BY_KEY.get(topic_key)
    domain_key = topic.domain_key if topic is not None else topic_key
    return SourceRoute(
        source_category=text,
        hint_topic_key=topic_key,
        hint_domain_key=domain_key,
        hint_domain_name=domain_name(domain_key),
        authoritative=False,
        note=note,
    )


def derive_event_domain(
    members: tuple[tuple[str | None, bool], ...] | list[tuple[str | None, bool]]
) -> EventDomainDecision:
    """Pick an event's main domain from all of its member articles.

    Each member is `(ai_category, is_primary)`. The primary article (the first
    report) gets double weight, but a different category supported by several
    follow-up reports can still win — an event's domain follows its evidence,
    not only the first article. Ties fall back to the primary article's domain,
    then to the dictionary order.
    """

    weights: dict[str, float] = {}
    unknown = 0
    primary_domain: str | None = None
    total = 0.0
    for category, is_primary in members:
        resolution = resolve_category(category)
        if not resolution.known or resolution.domain_key is None:
            unknown += 1
            continue
        weight = 2.0 if is_primary else 1.0
        weights[resolution.domain_key] = weights.get(resolution.domain_key, 0.0) + weight
        total += weight
        if is_primary and primary_domain is None:
            primary_domain = resolution.domain_key

    if not weights:
        return EventDomainDecision(
            domain_key="other",
            domain_name=DOMAIN_BY_KEY["other"].name,
            reason="成员文章均无可用的 AI 分类，保留待确认",
            confidence=0.0,
            resolved=False,
            unknown_members=unknown,
        )

    order = {item.key: index for index, item in enumerate(DOMAINS)}
    best_key = max(
        weights,
        key=lambda key: (weights[key], 1 if key == primary_domain else 0, -order[key]),
    )
    if primary_domain is not None and weights.get(primary_domain) == weights[best_key]:
        best_key = primary_domain

    summary = "、".join(
        f"{domain_name(key)} {weights[key]:g}"
        for key in sorted(weights, key=lambda item: (-weights[item], order[item]))
    )
    return EventDomainDecision(
        domain_key=best_key,
        domain_name=domain_name(best_key) or DOMAIN_BY_KEY["other"].name,
        reason=f"成员文章分类加权投票（主文章权重 2）：{summary}",
        confidence=round(weights[best_key] / total, 4) if total else 0.0,
        resolved=True,
        unknown_members=unknown,
    )


def scoring_base_for(category: str | None) -> float:
    """Scoring base for a stored category; unknown labels get a neutral base."""

    resolution = resolve_category(category)
    if not resolution.known or resolution.domain_key is None:
        return NEUTRAL_SCORING_BASE
    domain = DOMAIN_BY_KEY.get(resolution.domain_key)
    return domain.scoring_base if domain is not None else NEUTRAL_SCORING_BASE


def taxonomy_document() -> dict[str, object]:
    """Serialisable dictionary for docs/API/UI introspection."""

    return {
        "version": TAXONOMY_VERSION,
        "neutral_scoring_base": NEUTRAL_SCORING_BASE,
        "domains": [
            {
                "key": item.key,
                "name": item.name,
                "description": item.description,
                "scoring_base": item.scoring_base,
                "level": "domain",
                "applies_to": list(item.applies_to),
                "enabled": item.enabled,
            }
            for item in DOMAINS
        ],
        "topics": [
            {
                "key": item.key,
                "name": item.name,
                "domain_key": item.domain_key,
                "domain_name": domain_name(item.domain_key),
                "description": item.description,
                "level": "topic",
                "applies_to": list(item.applies_to),
                "enabled": item.enabled,
            }
            for item in TOPICS
        ],
        "source_routes": [
            {
                "source_category": key,
                "hint_topic_key": topic,
                "authoritative": False,
                "note": note,
            }
            for key, (topic, note) in _SOURCE_ROUTES.items()
        ],
    }


__all__ = [
    "DOMAINS",
    "DOMAIN_BY_KEY",
    "NEUTRAL_SCORING_BASE",
    "TAXONOMY_VERSION",
    "TOPICS",
    "CategoryResolution",
    "EventDomainDecision",
    "SourceRoute",
    "derive_event_domain",
    "domain_key_of",
    "domain_name",
    "event_domain_name",
    "resolve_category",
    "scoring_base_for",
    "source_category_route",
    "taxonomy_document",
]
