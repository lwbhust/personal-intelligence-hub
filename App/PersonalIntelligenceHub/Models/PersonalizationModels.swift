import Foundation

/// Phase 7.3.1 个人智能信息筛选模型。所有字段来自真实 API 响应；
/// 未返回的数值不做补零或推测。

struct PersonalProfileDTO: Decodable, Sendable {
    let displayName: String
    let digestTime: String
    let timezone: String
    let dailyItemLimit: Int?
    let dailyMinutes: Int?
    let explorationRatio: Double
    let autoAdjustEnabled: Bool
    let onboardingDone: Bool
    let updatedAt: String
}

struct PersonalProfileResponseDTO: Decodable, Sendable {
    let profile: PersonalProfileDTO
    let interestCount: Int
    let enabledInterestCount: Int
    let hasCoreInterest: Bool
    let blockedSourceCount: Int
}

struct InterestDTO: Decodable, Identifiable, Sendable, Hashable {
    let id: String
    let name: String
    let interestType: String
    let level: String
    let weight: Double
    let domainKey: String?
    let enabled: Bool
    let notes: String?
    let keywords: [String]
    let exclusionKeywords: [String]
    let entityIds: [String]
    let entityNames: [String]
    let sourceIds: [String]
    let sourceNames: [String]
    let createdAt: String
    let updatedAt: String
}

struct InterestListDTO: Decodable, Sendable {
    let items: [InterestDTO]
    let total: Int
}

struct InterestCreatePayload: Encodable, Sendable {
    var name: String
    var interestType: String
    var level: String
    var domainKey: String? = nil
    var keywords: [String] = []
    var exclusionKeywords: [String] = []
    var notes: String? = nil
    var enabled: Bool = true

    enum CodingKeys: String, CodingKey {
        case name
        case interestType = "interest_type"
        case level
        case domainKey = "domain_key"
        case keywords
        case exclusionKeywords = "exclusion_keywords"
        case notes
        case enabled
    }
}

struct InterestUpdatePayload: Encodable, Sendable {
    var name: String? = nil
    var level: String? = nil
    var weight: Double? = nil
    var domainKey: String? = nil
    var keywords: [String]? = nil
    var exclusionKeywords: [String]? = nil
    var notes: String? = nil
    var enabled: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case name
        case level
        case weight
        case domainKey = "domain_key"
        case keywords
        case exclusionKeywords = "exclusion_keywords"
        case notes
        case enabled
    }
}

struct ProfileUpdatePayload: Encodable, Sendable {
    var displayName: String? = nil
    var dailyItemLimit: Int? = nil
    var dailyMinutes: Int? = nil
    var explorationRatio: Double? = nil
    var autoAdjustEnabled: Bool? = nil
    var onboardingDone: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case dailyItemLimit = "daily_item_limit"
        case dailyMinutes = "daily_minutes"
        case explorationRatio = "exploration_ratio"
        case autoAdjustEnabled = "auto_adjust_enabled"
        case onboardingDone = "onboarding_done"
    }
}

struct ScoreBreakdownDTO: Decodable, Sendable, Hashable {
    let interest: Double
    let importance: Double
    let novelty: Double
    let sourceQuality: Double
    let recency: Double
}

struct FeedItemDTO: Decodable, Identifiable, Sendable, Hashable {
    let targetType: String
    let targetId: String
    let title: String?
    let summary: String?
    let sourceName: String?
    let category: String?
    let publishedAt: String?
    let eventId: String?
    let articleCount: Int
    let sourceCount: Int
    let isRead: Bool
    let isFavorite: Bool
    let score: Double
    let level: String
    let isFallback: Bool
    let matchedInterests: [String]
    let matchedEntities: [String]
    let reasonCodes: [String]
    let warnings: [String]
    let scoreBreakdown: ScoreBreakdownDTO
    let hasCoreInterest: Bool
    let computedAt: String

    var id: String { "\(targetType):\(targetId)" }
}

struct EmergingTopicDTO: Decodable, Identifiable, Sendable, Hashable {
    let targetType: String
    let targetId: String
    let title: String
    let count: Int
    let previous: Int
    let delta: Int
    let sources: [String]
    let reason: String

    var id: String { "topic:\(targetId)" }
}

struct FeedSectionsDTO: Decodable, Sendable {
    let mustRead: [FeedItemDTO]
    let eventHighlights: [FeedItemDTO]
    let coreInterest: [FeedItemDTO]
    let emerging: [EmergingTopicDTO]
    let leads: [FeedItemDTO]
    let watch: [FeedItemDTO]
    let others: [FeedItemDTO]
}

struct FeedBudgetDTO: Decodable, Sendable {
    let items: Int
    let dailyItemLimit: Int?
    let dailyMinutes: Int?
    let explorationRatio: Double
    let explorationCap: Int
}

struct FeedMetricsDTO: Decodable, Sendable {
    let todayArticles: Int
    let todayEvents: Int
    let recommendedTotal: Int
    let mustRead: Int
    let eventCount: Int
    let standaloneCount: Int
}

struct PersonalFeedDTO: Decodable, Sendable {
    let generatedAt: String
    let algorithmVersion: String
    let budget: FeedBudgetDTO
    let metrics: FeedMetricsDTO
    let sections: FeedSectionsDTO
    let hasInterests: Bool
    let hasCoreInterest: Bool
    let onboardingDone: Bool
}

struct FeedbackDTO: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let targetType: String
    let targetId: String
    let feedback: String
    let interestId: String?
    let note: String?
    let createdAt: String
    let revokedAt: String?
    let targetTitle: String?
}

struct FeedbackResponseDTO: Decodable, Sendable {
    let feedback: FeedbackDTO
    // Event-member articles are recommended as part of their event, so a valid
    // feedback on them has no article-level recommendation (Phase 8.0).
    let recommendation: RecommendationDetailDTO?
}

struct RecommendationDetailDTO: Decodable, Sendable {
    let targetType: String
    let targetId: String
    let title: String?
    let summary: String?
    let sourceName: String?
    let category: String?
    let score: Double
    let level: String
    let isFallback: Bool
    let matchedInterests: [String]
    let matchedEntities: [String]
    let reasonCodes: [String]
    let warnings: [String]
    let scoreBreakdown: ScoreBreakdownDTO
    let feedback: FeedbackDTO?
}

struct DigestItemDTO: Decodable, Identifiable, Sendable, Hashable {
    let id: String
    let section: String
    let rank: Int
    let targetType: String
    let targetId: String?
    let title: String
    let reason: String?
    let matchedInterests: [String]
    let score: Double?
    let eventDetail: DigestEventDetailDTO?
}

struct DigestEventArticleDTO: Decodable, Identifiable, Sendable, Hashable {
    let articleId: String
    let title: String
    let sourceId: String?
    let sourceName: String?
    let publishedAt: String?
    let url: String?
    var id: String { articleId }
}

struct DigestLatestProgressDTO: Decodable, Sendable, Hashable {
    let articleId: String
    let title: String
    let sourceId: String?
    let sourceName: String?
    let publishedAt: String?
    let url: String?
    let isRepresentative: Bool
}

struct DigestInfoIncrementDTO: Decodable, Sendable, Hashable {
    let followUpCount: Int
    let distinctSources: Int
    let hasMultipleSources: Bool
}

struct DigestEventDetailDTO: Decodable, Sendable, Hashable {
    let eventId: String
    let category: String
    let status: String
    let firstPublishedAt: String?
    let lastPublishedAt: String?
    let articleCount: Int
    let sourceCount: Int
    let sources: [String]
    let importance: Double?
    let representative: DigestEventArticleDTO?
    let otherReports: [DigestEventArticleDTO]
    let latestProgress: DigestLatestProgressDTO?
    let informationIncrement: DigestInfoIncrementDTO
}

struct DailyDigestDTO: Decodable, Identifiable, Sendable {
    let id: String
    let digestDate: String
    let timezone: String
    let status: String
    let aiStatus: String
    let headline: String?
    let overview: String?
    let digestVersion: String
    let generatedAt: String?
    let items: [DigestItemDTO]
}

struct DigestHistoryDTO: Decodable, Sendable {
    let items: [DailyDigestDTO]
    let total: Int
}

struct InterestSuggestionDTO: Decodable, Identifiable, Sendable {
    let interestId: String
    let interestName: String
    let currentLevel: String
    let currentWeight: Double
    let suggestedLevel: String
    let suggestedWeight: Double
    let direction: String
    let positiveFeedback: Int
    let negativeFeedback: Int
    let reason: String

    var id: String { interestId }
}

struct SuggestionsDTO: Decodable, Sendable {
    let items: [InterestSuggestionDTO]
    let total: Int
    let autoAdjustEnabled: Bool
}

struct PersonalStatsDTO: Decodable, Sendable {
    struct RecommendationStats: Decodable, Sendable {
        let total: Int
        let byLevel: [String: Int]
        let averageScore: Double?
    }

    struct InterestStats: Decodable, Sendable {
        let total: Int
        let enabled: Int
        let byLevel: [String: Int]
    }

    struct TodayStats: Decodable, Sendable {
        let articles: Int
        let events: Int
    }

    let recommendations: RecommendationStats
    let interests: InterestStats
    let today: TodayStats
}

struct BlockedSourceDTO: Decodable, Identifiable, Sendable {
    let sourceId: String
    let name: String
    let reason: String?
    let createdAt: String

    var id: String { sourceId }
}

struct BlockedSourceListDTO: Decodable, Sendable {
    let items: [BlockedSourceDTO]
    let total: Int
}

/// 兴趣等级展示文案。权重与等级来自后端，客户端不做二次推断。
enum InterestLevel: String, CaseIterable, Identifiable {
    case core
    case extended
    case general
    case muted

    var id: String { rawValue }

    var title: String {
        switch self {
        case .core: return "核心关注"
        case .extended: return "延伸关注"
        case .general: return "一般关注"
        case .muted: return "暂不关注"
        }
    }
}

/// 推荐等级展示。等级代表推荐优先级，不代表事实真实性。
enum RecommendationLevel: String {
    case mustRead = "must_read"
    case recommended
    case watch
    case low
    case notRecommended = "not_recommended"

    var title: String {
        switch self {
        case .mustRead: return "必读"
        case .recommended: return "推荐"
        case .watch: return "观察"
        case .low: return "低优先级"
        case .notRecommended: return "不推荐"
        }
    }

    var tint: String {
        switch self {
        case .mustRead: return "red"
        case .recommended: return "orange"
        case .watch: return "blue"
        case .low: return "gray"
        case .notRecommended: return "gray"
        }
    }

    init(raw: String) {
        self = RecommendationLevel(rawValue: raw) ?? .low
    }
}
