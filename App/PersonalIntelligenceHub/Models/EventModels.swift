import Foundation

/// Phase 4 事件情报读模型。字段与 `Docs/PHASE4_API.md` 一致。

struct EventScoreSummaryDTO: Decodable, Hashable, Sendable {
    let importanceScore: Double
    let heatScore: Double
    let freshnessScore: Double
    let coverageScore: Double
    let confidenceScore: Double
    let totalScore: Double
    let algorithmVersion: String
    let scoredAt: String
}

struct EventEntityDTO: Decodable, Identifiable, Hashable, Sendable {
    let entityId: String
    let canonicalName: String
    let entityType: String
    let role: String
    let articleCount: Int
    let confidence: Double
    let evidenceArticleId: String?
    let evidenceArticleTitle: String?

    var id: String { entityId }
}

struct EventRelationEvidenceDTO: Decodable, Identifiable, Hashable, Sendable {
    let articleId: String
    let title: String

    var id: String { articleId }
}

struct EventRelationDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let sourceEventId: String
    let targetEventId: String
    let sourceEventTitle: String?
    let targetEventTitle: String?
    let relationType: String
    let confidence: Double
    let status: String
    let rationale: String?
    let evidenceArticles: [EventRelationEvidenceDTO]
    let actor: String
    let algorithmVersion: String
    let createdAt: String
    let updatedAt: String
}

struct EventSummaryDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let summary: String?
    let category: String
    let status: String
    let firstSeenAt: String
    let lastSeenAt: String
    let firstPublishedAt: String?
    let lastPublishedAt: String?
    let articleCount: Int
    let sourceCount: Int
    let isManual: Bool
    let mergedIntoEventId: String?
    let algorithmVersion: String
    let currentScores: EventScoreSummaryDTO?
    let topEntities: [EventEntityDTO]
}

struct EventDetailDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let summary: String?
    let category: String
    let status: String
    let statusReason: String?
    let firstSeenAt: String
    let lastSeenAt: String
    let firstPublishedAt: String?
    let lastPublishedAt: String?
    let occurredAt: String?
    let articleCount: Int
    let sourceCount: Int
    let isManual: Bool
    let mergedIntoEventId: String?
    let algorithmVersion: String
    let createdAt: String
    let updatedAt: String
    let currentScores: EventScoreSummaryDTO?
    let topEntities: [EventEntityDTO]
    let entities: [EventEntityDTO]
    let relations: [EventRelationDTO]
}

struct EventPageDTO: Decodable, Sendable {
    let items: [EventSummaryDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct EventArticleDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let articleId: String
    let title: String
    let sourceId: String
    let sourceName: String?
    let publishedAt: String?
    let fetchedAt: String
    let summary: String?
    let aiSummary: String?
    let category: String?
    let canonicalUrl: String?
    let originalUrl: String?
    let role: String
    let similarity: Double?
    let matchReasons: [String]
    let isManual: Bool
    let addedAt: String
}

struct EventArticlePageDTO: Decodable, Sendable {
    let items: [EventArticleDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct EventTimelineDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let kind: String
    let title: String
    let description: String?
    let occurredAt: String?
    let publishedAt: String?
    let recognizedAt: String
    let articleId: String?
    let articleTitle: String?
    let confidence: Double?
    let isKey: Bool
    let evidence: [String: AIJSONValue]
    let createdAt: String
}

struct EventTimelinePageDTO: Decodable, Sendable {
    let items: [EventTimelineDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct EventScoreComponentDTO: Decodable, Hashable, Sendable {
    let name: String
    let weight: Double
    let value: Double
    let contribution: Double
    let reason: String
}

struct EventScoreExplanationDTO: Decodable, Hashable, Sendable {
    let formula: String
    let weights: [String: Double]?
    let components: [EventScoreComponentDTO]
}

struct EventScoreSnapshotDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let eventId: String
    let algorithmVersion: String
    let scoredAt: String
    let importanceScore: Double
    let heatScore: Double
    let freshnessScore: Double
    let coverageScore: Double
    let confidenceScore: Double
    let totalScore: Double
    let isCurrent: Bool
    let inputs: [String: AIJSONValue]
    let explanation: EventScoreExplanationDTO
}

struct EventScorePageDTO: Decodable, Sendable {
    let items: [EventScoreSnapshotDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct RankingItemDTO: Decodable, Identifiable, Hashable, Sendable {
    let rank: Int
    let event: EventSummaryDTO
    let score: Double
    let previousTotalScore: Double?
    let scoreChange: Double?

    var id: String { event.id }
}

struct RankingPageDTO: Decodable, Sendable {
    let kind: String
    let window: String
    let algorithmVersion: String
    let generatedAt: String
    let items: [RankingItemDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct EntityAliasDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let alias: String
    let language: String
    let source: String
    let confidence: Double
}

struct EntityArticleDTO: Decodable, Identifiable, Hashable, Sendable {
    let articleId: String
    let title: String?
    let sourceName: String?
    let publishedAt: String?
    let rawName: String
    let rawType: String
    let matchMethod: String
    let confidence: Double

    var id: String { articleId }
}

struct EntitySummaryDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let canonicalName: String
    let entityType: String
    let typeGroup: String
    let status: String
    let confidence: Double
    let articleCount: Int
    let aliasCount: Int
    let firstSeenAt: String?
    let lastSeenAt: String?
    let mergedIntoEntityId: String?
}

struct EntityDetailDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let canonicalName: String
    let entityType: String
    let typeGroup: String
    let status: String
    let confidence: Double
    let articleCount: Int
    let aliasCount: Int
    let firstSeenAt: String?
    let lastSeenAt: String?
    let mergedIntoEntityId: String?
    let normalizationBasis: String
    let aliases: [EntityAliasDTO]
    let articles: [EntityArticleDTO]
    let mergedFrom: [EntityMergeRefDTO]
}

struct EntityMergeRefDTO: Decodable, Hashable, Sendable {
    let id: String
    let canonicalName: String
}

struct EntityPageDTO: Decodable, Sendable {
    let items: [EntitySummaryDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct ClusterStatusDTO: Decodable, Sendable {
    let enabled: Bool
    let runningRunId: String?
    let queueDepth: Int
    let llmEnabled: Bool
    let lastRunId: String?
    let lastRunStatus: String?
    let lastRunAt: String?
    let algorithmVersion: String
}

struct ClusterRunDTO: Decodable, Identifiable, Sendable {
    let id: String
    let triggerType: String
    let scope: String
    let status: String
    let requestedCount: Int
    let processedCount: Int
    let attachedCount: Int
    let createdEventCount: Int
    let updatedEventCount: Int
    let candidatePairCount: Int
    let ambiguousCount: Int
    let llmCalledCount: Int
    let llmAcceptedCount: Int
    let skippedCount: Int
    let failedCount: Int
    let useLlm: Bool
    let modelName: String?
    let errorMessage: String?
    let cancelRequested: Bool
    let startedAt: String?
    let finishedAt: String?
    let durationMs: Int?
    let createdAt: String
    let updatedAt: String
}

// MARK: - Presentation helpers

func eventStatusLabel(_ raw: String) -> String {
    switch raw {
    case "candidate": return "候选"
    case "active": return "活跃"
    case "evolving": return "发展中"
    case "dormant": return "休眠"
    case "closed": return "已结束"
    case "merged": return "已合并"
    case "archived": return "已归档"
    default: return raw
    }
}

func eventRelationLabel(_ raw: String) -> String {
    switch raw {
    case "related_to": return "相关"
    case "follows": return "后续"
    case "caused_by": return "因果"
    case "part_of": return "隶属于"
    case "same_topic": return "同主题"
    case "contradicts": return "存在冲突"
    default: return raw
    }
}

func eventEntityRoleLabel(_ raw: String) -> String {
    switch raw {
    case "subject": return "主体"
    case "actor": return "参与者"
    case "organization": return "组织"
    case "location": return "地点"
    case "mentioned": return "提及"
    default: return raw
    }
}

func eventEntityTypeLabel(_ raw: String) -> String {
    switch raw {
    case "person": return "人物"
    case "organization": return "组织"
    case "company": return "企业"
    case "location": return "地点"
    case "product": return "产品"
    case "event": return "事件"
    case "other": return "其他"
    default: return raw
    }
}

func eventTimelineKindLabel(_ raw: String) -> String {
    switch raw {
    case "first_report": return "首次报道"
    case "follow_up": return "后续进展"
    case "key_development": return "关键进展"
    case "status_change": return "状态变化"
    case "merge": return "合并"
    case "split": return "拆分"
    case "manual_note": return "人工备注"
    default: return raw
    }
}

func eventArticleRoleLabel(_ raw: String) -> String {
    switch raw {
    case "report": return "报道"
    case "follow_up": return "后续"
    case "commentary": return "评论"
    case "duplicate": return "转载"
    case "primary": return "主报道"
    default: return raw
    }
}

func clusterRunStatusLabel(_ raw: String) -> String {
    switch raw {
    case "pending": return "排队中"
    case "running": return "聚类中"
    case "succeeded": return "已完成"
    case "partially_succeeded": return "部分完成"
    case "failed": return "失败"
    case "cancelled": return "已取消"
    default: return raw
    }
}

/// 后端时间均为 UTC ISO8601 毫秒字符串；本地展示统一转成当前时区。
func displayTimestamp(_ raw: String?, fallback: String = "—") -> String {
    guard let raw else { return fallback }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    guard let date = formatter.date(from: raw) else { return raw }
    let output = DateFormatter()
    output.locale = Locale(identifier: "zh_CN")
    output.dateFormat = "yyyy-MM-dd HH:mm"
    return output.string(from: date)
}
