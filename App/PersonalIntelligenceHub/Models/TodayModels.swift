import Foundation

/// 「今日」首页聚合模型。所有字段来自 `/api/v1/today/overview`。
struct TodayMetricsDTO: Decodable, Sendable {
    let todayArticles: Int
    let recommendedTotal: Int
    let mustRead: Int
    let eventCount: Int
    let multiReportEvents: Int
    let unreadPicks: Int
}

struct TodayAutomationDTO: Decodable, Sendable {
    let enabled: Bool
    let paused: Bool
    let aiEnabled: Bool
    let eventEnabled: Bool
    let pending: Int
    let running: Int
    let failed: Int
    let todaySucceeded: Int
    let todayFailed: Int
    let todaySkipped: Int
    let lastCompletedAt: String?
    let lastSucceededAt: String?
}

struct TodayRecentReadDTO: Decodable, Identifiable, Sendable {
    let id: String
    let title: String
    let sourceName: String?
    let lastReadAt: String?
    let publishedAt: String?
}

struct TodayOverviewDTO: Decodable, Sendable {
    let generatedAt: String
    let metrics: TodayMetricsDTO
    let picks: [FeedItemDTO]
    let events: [FeedItemDTO]
    let todo: [FeedItemDTO]
    let recentReads: [TodayRecentReadDTO]
    let automation: TodayAutomationDTO
    let hasInterests: Bool
    let hasCoreInterest: Bool
    let onboardingDone: Bool
}
