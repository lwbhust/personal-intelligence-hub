import Foundation

// Phase 7.1 情报中心 DTO。字段与 `/api/v1/intelligence/*` 一致。
// 统计字段全部来自 SQLite；只有 `content` 下的章节由本地模型生成。

struct IntelligenceLastReportDTO: Decodable, Sendable {
    let id: String
    let reportType: String
    let status: String
    let aiStatus: String
    let periodStart: String
    let createdAt: String
}

struct IntelligenceStatusDTO: Decodable, Sendable {
    let ollamaAvailable: Bool
    let ollamaVersion: String?
    let modelName: String?
    let modelInstalled: Bool
    let queueDepth: Int
    let runningReportId: String?
    let lastReport: IntelligenceLastReportDTO?
    let promptVersion: String
    let statsVersion: String
    let checkedAt: String
}

struct IntelligenceKeyEventContentDTO: Decodable, Identifiable, Sendable {
    let eventId: String
    let title: String?
    let development: String
    let background: String
    let impact: String
    let importance: String
    let entities: [String]
    let articleIds: [String]

    var id: String { eventId }
}

struct IntelligenceTopicDTO: Decodable, Identifiable, Sendable {
    let name: String
    let direction: String
    let evidenceEventIds: [String]

    var id: String { name + direction }
}

struct IntelligenceContentDTO: Decodable, Sendable {
    let keyEvents: [IntelligenceKeyEventContentDTO]?
    let topics: [IntelligenceTopicDTO]?
    let uncertainties: [String]?
    let warnings: [String]?

    var resolvedKeyEvents: [IntelligenceKeyEventContentDTO] { keyEvents ?? [] }
    var resolvedTopics: [IntelligenceTopicDTO] { topics ?? [] }
    var resolvedUncertainties: [String] { uncertainties ?? [] }
}

struct IntelligenceScoresDTO: Decodable, Sendable {
    let importance: Double
    let heat: Double
    let freshness: Double
    let coverage: Double
    let confidence: Double
    let total: Double
    let algorithmVersion: String?
}

struct IntelligenceEventEntityDTO: Decodable, Identifiable, Sendable {
    let name: String
    let type: String
    let role: String
    let articleCount: Int

    var id: String { name + type + role }
}

struct IntelligenceEvidenceArticleDTO: Decodable, Identifiable, Sendable {
    let articleId: String
    let title: String
    let sourceName: String
    let url: String?
    let summary: String
    let publishedAt: String?

    var id: String { articleId }
}

struct IntelligenceStatEventDTO: Decodable, Identifiable, Sendable {
    let eventId: String
    let title: String
    let summary: String
    let category: String
    let status: String
    let articleCount: Int
    let sourceCount: Int
    let firstSeenAt: String?
    let lastSeenAt: String?
    let scores: IntelligenceScoresDTO?
    let entities: [IntelligenceEventEntityDTO]
    let evidence: [IntelligenceEvidenceArticleDTO]

    var id: String { eventId }
}

struct IntelligenceCategoryStatDTO: Decodable, Identifiable, Sendable {
    let name: String
    let articles: Int
    let previous: Int
    let delta: Int

    var id: String { name }
}

struct IntelligenceKeywordStatDTO: Decodable, Identifiable, Sendable {
    let keyword: String
    let count: Int
    let previous: Int
    let delta: Int
    let sources: [String]

    var id: String { keyword }
}

struct IntelligenceCrossSourceTopicDTO: Decodable, Identifiable, Sendable {
    let keyword: String
    let count: Int
    let sources: [String]
    let articleIds: [String]
    let sourceCount: Int

    var id: String { keyword }
}

struct IntelligenceEntityStatDTO: Decodable, Identifiable, Sendable {
    let id: String
    let canonicalName: String
    let entityType: String
    let firstSeenAt: String?
    let mentions: Int?
}

struct IntelligenceTopEntityDTO: Decodable, Identifiable, Sendable {
    let name: String
    let entityType: String
    let mentions: Int

    var id: String { name }
}

struct IntelligenceUnclusteredDTO: Decodable, Identifiable, Sendable {
    let id: String
    let title: String
    let sourceName: String
    let at: String
}

struct IntelligenceTotalsDTO: Decodable, Sendable {
    let articles: Int
    let sources: Int
    let previousArticles: Int
    let events: Int
    let newEvents: Int
    let unclusteredArticles: Int
}

struct IntelligencePeriodDTO: Decodable, Sendable {
    let reportType: String
    let start: String
    let end: String
    let fromAt: String
    let toAt: String
    let previousStart: String
    let previousEnd: String
}

struct IntelligenceStatsDTO: Decodable, Sendable {
    let period: IntelligencePeriodDTO?
    let totals: IntelligenceTotalsDTO?
    let categories: [IntelligenceCategoryStatDTO]?
    let keyEvents: [IntelligenceStatEventDTO]?
    let risingKeywords: [IntelligenceKeywordStatDTO]?
    let crossSourceTopics: [IntelligenceCrossSourceTopicDTO]?
    let newEntities: [IntelligenceEntityStatDTO]?
    let topEntities: [IntelligenceTopEntityDTO]?
    let unclusteredSamples: [IntelligenceUnclusteredDTO]?
    let notes: [String]?

    var resolvedKeyEvents: [IntelligenceStatEventDTO] { keyEvents ?? [] }
    var resolvedCategories: [IntelligenceCategoryStatDTO] { categories ?? [] }
    var resolvedRising: [IntelligenceKeywordStatDTO] { risingKeywords ?? [] }
    var resolvedCrossSource: [IntelligenceCrossSourceTopicDTO] { crossSourceTopics ?? [] }
    var resolvedNewEntities: [IntelligenceEntityStatDTO] { newEntities ?? [] }
    var resolvedTopEntities: [IntelligenceTopEntityDTO] { topEntities ?? [] }
    var resolvedUnclustered: [IntelligenceUnclusteredDTO] { unclusteredSamples ?? [] }
    var resolvedNotes: [String] { notes ?? [] }
}

struct IntelligenceReportDTO: Decodable, Identifiable, Sendable {
    let id: String
    let reportType: String
    let periodKey: String
    let periodStart: String
    let periodEnd: String
    let dataFromAt: String?
    let dataToAt: String?
    let status: String
    let aiStatus: String
    let headline: String?
    let overview: String?
    let content: IntelligenceContentDTO
    let stats: IntelligenceStatsDTO
    let modelName: String?
    let modelDigest: String?
    let promptVersion: String
    let statsVersion: String
    let articleCount: Int
    let eventCount: Int
    let entityCount: Int
    let citationCount: Int
    let triggerType: String
    let errorCode: String?
    let errorMessage: String?
    let startedAt: String?
    let finishedAt: String?
    let durationMs: Int?
    let createdAt: String
    let updatedAt: String

    var isTerminal: Bool {
        ["succeeded", "degraded", "failed", "cancelled", "superseded"].contains(status)
    }
}

struct IntelligenceReportPageDTO: Decodable, Sendable {
    let items: [IntelligenceReportDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct IntelligenceCitationDTO: Decodable, Identifiable, Sendable {
    let id: String
    let citationType: String
    let refId: String
    let sectionKey: String
    let rank: Int
    let title: String?
    let sourceName: String?
    let url: String?
    let evidence: String?
    let createdAt: String
}

struct IntelligenceReportDetailDTO: Decodable, Sendable {
    let report: IntelligenceReportDTO
    let citations: [IntelligenceCitationDTO]
}

struct IntelligenceGenerateResponseDTO: Decodable, Sendable {
    let reused: Bool
    let report: IntelligenceReportDTO
}

struct IntelligenceEmergingDTO: Decodable, Sendable {
    let generatedAt: String
    let windowDays: Int
    let period: IntelligencePeriodDTO?
    let totals: IntelligenceTotalsDTO?
    let categories: [IntelligenceCategoryStatDTO]?
    let risingKeywords: [IntelligenceKeywordStatDTO]?
    let crossSourceTopics: [IntelligenceCrossSourceTopicDTO]?
    let newEntities: [IntelligenceEntityStatDTO]?
    let topEntities: [IntelligenceTopEntityDTO]?
    let unclusteredSamples: [IntelligenceUnclusteredDTO]?
    let notes: [String]?

    var resolvedCategories: [IntelligenceCategoryStatDTO] { categories ?? [] }
    var resolvedRising: [IntelligenceKeywordStatDTO] { risingKeywords ?? [] }
    var resolvedCrossSource: [IntelligenceCrossSourceTopicDTO] { crossSourceTopics ?? [] }
    var resolvedNewEntities: [IntelligenceEntityStatDTO] { newEntities ?? [] }
    var resolvedTopEntities: [IntelligenceTopEntityDTO] { topEntities ?? [] }
    var resolvedUnclustered: [IntelligenceUnclusteredDTO] { unclusteredSamples ?? [] }
    var resolvedNotes: [String] { notes ?? [] }
}

struct IntelligenceRankingScoresDTO: Decodable, Sendable {
    let importanceScore: Double
    let heatScore: Double
    let freshnessScore: Double
    let coverageScore: Double
    let confidenceScore: Double
    let totalScore: Double
}

struct IntelligenceRankingEventDTO: Decodable, Identifiable, Sendable {
    let id: String
    let title: String
    let summary: String?
    let category: String
    let status: String
    let articleCount: Int
    let sourceCount: Int
    let firstSeenAt: String
    let lastSeenAt: String
    let currentScores: IntelligenceRankingScoresDTO?
}

struct IntelligenceRankingItemDTO: Decodable, Identifiable, Sendable {
    let rank: Int
    let score: Double
    let previousTotalScore: Double?
    let scoreChange: Double?
    let event: IntelligenceRankingEventDTO

    var id: String { event.id }
}

struct IntelligenceRankingPageDTO: Decodable, Sendable {
    let kind: String
    let window: String
    let algorithmVersion: String
    let generatedAt: String
    let total: Int
    let items: [IntelligenceRankingItemDTO]
}
