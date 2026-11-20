import Foundation

/// Phase 4 事件情报访问：全部走真实 Sidecar HTTP。
extension APIClient {
    private struct RenameBody: Encodable { let title: String }
    private struct StatusBody: Encodable {
        let status: String
        let statusReason: String
    }
    private struct MergeBody: Encodable {
        let targetEventId: String
        let reason: String?
    }
    private struct SplitBody: Encodable {
        let articleIds: [String]
        let title: String?
    }
    private struct ArticleBody: Encodable {
        let articleId: String
        let role: String
    }
    private struct RelationStatusBody: Encodable { let status: String }
    private struct ClusterRunBody: Encodable {
        let scope: String
        let limit: Int
        let useLlm: Bool
    }
    private struct ScoreRecomputeBody: Encodable { let scope: String }
    private struct ScoreRecomputeResult: Decodable {
        let scoredEvents: Int
        let createdSnapshots: Int
    }

    private func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(value)
    }

    // MARK: - Events

    func fetchEvents(query: [URLQueryItem]) async throws -> EventPageDTO {
        try await perform("GET", path: "/api/v1/events", query: query, as: EventPageDTO.self)
    }

    func fetchEvent(id: String) async throws -> EventDetailDTO {
        try await perform("GET", path: "/api/v1/events/\(id)", as: EventDetailDTO.self)
    }

    func fetchEventArticles(
        id: String, limit: Int = 50, offset: Int = 0
    ) async throws -> EventArticlePageDTO {
        try await perform(
            "GET",
            path: "/api/v1/events/\(id)/articles",
            query: [
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: String(offset)),
            ],
            as: EventArticlePageDTO.self
        )
    }

    func fetchEventTimeline(
        id: String, limit: Int = 50, offset: Int = 0, keyOnly: Bool = false
    ) async throws -> EventTimelinePageDTO {
        try await perform(
            "GET",
            path: "/api/v1/events/\(id)/timeline",
            query: [
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: String(offset)),
                URLQueryItem(name: "key_only", value: keyOnly ? "true" : "false"),
            ],
            as: EventTimelinePageDTO.self
        )
    }

    func fetchEventEntities(id: String) async throws -> [EventEntityDTO] {
        struct Page: Decodable { let items: [EventEntityDTO]; let total: Int }
        let page: Page = try await perform(
            "GET", path: "/api/v1/events/\(id)/entities", as: Page.self
        )
        return page.items
    }

    func fetchEventRelations(id: String) async throws -> [EventRelationDTO] {
        struct Page: Decodable { let items: [EventRelationDTO]; let total: Int }
        let page: Page = try await perform(
            "GET", path: "/api/v1/events/\(id)/relations", as: Page.self
        )
        return page.items
    }

    func fetchEventScores(id: String, limit: Int = 10) async throws -> EventScorePageDTO {
        try await perform(
            "GET",
            path: "/api/v1/events/\(id)/scores",
            query: [
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: "0"),
            ],
            as: EventScorePageDTO.self
        )
    }

    func fetchRankings(
        kind: String, window: String, category: String?, limit: Int = 20
    ) async throws -> RankingPageDTO {
        var query = [
            URLQueryItem(name: "kind", value: kind),
            URLQueryItem(name: "window", value: window),
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: "0"),
        ]
        if let category, !category.isEmpty {
            query.append(URLQueryItem(name: "category", value: category))
        }
        return try await perform("GET", path: "/api/v1/rankings", query: query, as: RankingPageDTO.self)
    }

    // MARK: - Manual corrections

    func renameEvent(id: String, title: String) async throws -> EventDetailDTO {
        try await perform(
            "PATCH",
            path: "/api/v1/events/\(id)",
            body: try encode(RenameBody(title: title)),
            as: EventDetailDTO.self
        )
    }

    func setEventStatus(id: String, status: String, reason: String) async throws -> EventDetailDTO {
        try await perform(
            "PATCH",
            path: "/api/v1/events/\(id)",
            body: try encode(StatusBody(status: status, statusReason: reason)),
            as: EventDetailDTO.self
        )
    }

    func mergeEvents(
        id: String, targetEventId: String, reason: String?
    ) async throws -> EventDetailDTO {
        try await perform(
            "POST",
            path: "/api/v1/events/\(id)/merge",
            body: try encode(MergeBody(targetEventId: targetEventId, reason: reason)),
            as: EventDetailDTO.self
        )
    }

    func splitEvent(
        id: String, articleIds: [String], title: String?
    ) async throws -> EventDetailDTO {
        try await perform(
            "POST",
            path: "/api/v1/events/\(id)/split",
            body: try encode(SplitBody(articleIds: articleIds, title: title)),
            as: EventDetailDTO.self
        )
    }

    func unmergeEvent(id: String) async throws -> EventDetailDTO {
        try await perform(
            "POST", path: "/api/v1/events/\(id)/unmerge", as: EventDetailDTO.self
        )
    }

    func addEventArticle(
        id: String, articleId: String, role: String
    ) async throws {
        struct Response: Decodable {
            let eventId: String
            let articleId: String
            let role: String
            let movedFromEventId: String?
            let articleCount: Int
        }
        let _: Response = try await perform(
            "POST",
            path: "/api/v1/events/\(id)/articles",
            body: try encode(ArticleBody(articleId: articleId, role: role)),
            as: Response.self
        )
    }

    func removeEventArticle(id: String, articleId: String) async throws {
        try await performNoContent(
            "DELETE", path: "/api/v1/events/\(id)/articles/\(articleId)"
        )
    }

    func updateRelationStatus(
        eventId: String, relationId: String, status: String
    ) async throws -> EventRelationDTO {
        try await perform(
            "PATCH",
            path: "/api/v1/events/\(eventId)/relations/\(relationId)",
            body: try encode(RelationStatusBody(status: status)),
            as: EventRelationDTO.self
        )
    }

    // MARK: - Clustering

    func fetchClusterStatus() async throws -> ClusterStatusDTO {
        try await perform("GET", path: "/api/v1/event-clusters/status", as: ClusterStatusDTO.self)
    }

    func createClusterRun(scope: String, limit: Int, useLLM: Bool) async throws -> ClusterRunDTO {
        try await perform(
            "POST",
            path: "/api/v1/event-clusters/runs",
            body: try encode(ClusterRunBody(scope: scope, limit: limit, useLlm: useLLM)),
            as: ClusterRunDTO.self
        )
    }

    func fetchClusterRun(id: String) async throws -> ClusterRunDTO {
        try await perform(
            "GET", path: "/api/v1/event-clusters/runs/\(id)", as: ClusterRunDTO.self
        )
    }

    func recomputeScores(scope: String = "stale") async throws -> (scored: Int, created: Int) {
        let result = try await perform(
            "POST",
            path: "/api/v1/event-scores/recompute",
            body: try encode(ScoreRecomputeBody(scope: scope)),
            as: ScoreRecomputeResult.self
        )
        return (result.scoredEvents, result.createdSnapshots)
    }

    // MARK: - Entities

    func fetchEntities(query: [URLQueryItem]) async throws -> EntityPageDTO {
        try await perform("GET", path: "/api/v1/entities", query: query, as: EntityPageDTO.self)
    }

    func fetchEntity(id: String) async throws -> EntityDetailDTO {
        try await perform("GET", path: "/api/v1/entities/\(id)", as: EntityDetailDTO.self)
    }
}
