import Foundation

/// Phase 7.3.1 个性化 API。全部为真实 Sidecar 端点，不缓存、不伪造。
extension APIClient {
    private struct FeedbackPayload: Encodable {
        let targetType: String
        let targetId: String
        let feedback: String
        let interestId: String?

        enum CodingKeys: String, CodingKey {
            case targetType = "target_type"
            case targetId = "target_id"
            case feedback
            case interestId = "interest_id"
        }
    }

    private struct InterestRelationPayload: Encodable {
        let id: String

        enum CodingKeys: String, CodingKey {
            case id = "entity_id"
        }
    }

    private struct SourceRelationPayload: Encodable {
        let id: String

        enum CodingKeys: String, CodingKey {
            case id = "source_id"
        }
    }

    private struct BlockSourcePayload: Encodable {
        let sourceId: String
        let reason: String?

        enum CodingKeys: String, CodingKey {
            case sourceId = "source_id"
            case reason
        }
    }

    private struct KeywordsPayload: Encodable {
        let keywords: [String]
        let exclusionKeywords: [String]

        enum CodingKeys: String, CodingKey {
            case keywords
            case exclusionKeywords = "exclusion_keywords"
        }
    }

    private struct DigestGeneratePayload: Encodable {
        let date: String?
        let force: Bool
    }

    private struct EntityPageDTO: Decodable {
        struct Item: Decodable, Identifiable {
            let id: String
            let canonicalName: String
            let entityType: String
        }

        let items: [Item]
    }

    // MARK: - Profile & interests

    func fetchPersonalProfile() async throws -> PersonalProfileResponseDTO {
        try await perform("GET", path: "/api/v1/personalization/profile", as: PersonalProfileResponseDTO.self)
    }

    func updatePersonalProfile(_ payload: ProfileUpdatePayload) async throws -> PersonalProfileResponseDTO {
        let body = try JSONEncoder().encode(payload)
        return try await perform(
            "PATCH",
            path: "/api/v1/personalization/profile",
            body: body,
            as: PersonalProfileResponseDTO.self
        )
    }

    func fetchInterests() async throws -> InterestListDTO {
        try await perform("GET", path: "/api/v1/personalization/interests", as: InterestListDTO.self)
    }

    func createInterest(_ payload: InterestCreatePayload) async throws -> InterestDTO {
        let body = try JSONEncoder().encode(payload)
        return try await perform(
            "POST", path: "/api/v1/personalization/interests", body: body, as: InterestDTO.self
        )
    }

    func updateInterest(id: String, payload: InterestUpdatePayload) async throws -> InterestDTO {
        let body = try JSONEncoder().encode(payload)
        return try await perform(
            "PATCH",
            path: "/api/v1/personalization/interests/\(id)",
            body: body,
            as: InterestDTO.self
        )
    }

    func deleteInterest(id: String) async throws {
        try await performNoContent("DELETE", path: "/api/v1/personalization/interests/\(id)")
    }

    func updateInterestKeywords(
        id: String, keywords: [String], exclusions: [String]
    ) async throws -> InterestDTO {
        let body = try JSONEncoder().encode(
            KeywordsPayload(keywords: keywords, exclusionKeywords: exclusions)
        )
        return try await perform(
            "PUT",
            path: "/api/v1/personalization/interests/\(id)/keywords",
            body: body,
            as: InterestDTO.self
        )
    }

    func linkInterestEntity(interestId: String, entityId: String) async throws -> InterestDTO {
        let body = try JSONEncoder().encode(InterestRelationPayload(id: entityId))
        return try await perform(
            "POST",
            path: "/api/v1/personalization/interests/\(interestId)/entities",
            body: body,
            as: InterestDTO.self
        )
    }

    func unlinkInterestEntity(interestId: String, entityId: String) async throws -> InterestDTO {
        try await perform(
            "DELETE",
            path: "/api/v1/personalization/interests/\(interestId)/entities/\(entityId)",
            as: InterestDTO.self
        )
    }

    func linkInterestSource(interestId: String, sourceId: String) async throws -> InterestDTO {
        let body = try JSONEncoder().encode(SourceRelationPayload(id: sourceId))
        return try await perform(
            "POST",
            path: "/api/v1/personalization/interests/\(interestId)/sources",
            body: body,
            as: InterestDTO.self
        )
    }

    func unlinkInterestSource(interestId: String, sourceId: String) async throws -> InterestDTO {
        try await perform(
            "DELETE",
            path: "/api/v1/personalization/interests/\(interestId)/sources/\(sourceId)",
            as: InterestDTO.self
        )
    }

    func fetchBlockedSources() async throws -> BlockedSourceListDTO {
        try await perform(
            "GET", path: "/api/v1/personalization/blocked-sources", as: BlockedSourceListDTO.self
        )
    }

    func blockSource(sourceId: String, reason: String?) async throws -> BlockedSourceListDTO {
        let body = try JSONEncoder().encode(BlockSourcePayload(sourceId: sourceId, reason: reason))
        return try await perform(
            "POST",
            path: "/api/v1/personalization/blocked-sources",
            body: body,
            as: BlockedSourceListDTO.self
        )
    }

    func unblockSource(sourceId: String) async throws -> BlockedSourceListDTO {
        try await perform(
            "DELETE",
            path: "/api/v1/personalization/blocked-sources/\(sourceId)",
            as: BlockedSourceListDTO.self
        )
    }

    // MARK: - Feed & feedback

    func fetchPersonalFeed(
        limit: Int? = nil,
        includeLow: Bool = false,
        includeRead: Bool = false
    ) async throws -> PersonalFeedDTO {
        var query: [URLQueryItem] = [
            URLQueryItem(name: "include_low", value: includeLow ? "true" : "false"),
            URLQueryItem(name: "include_read", value: includeRead ? "true" : "false"),
        ]
        if let limit {
            query.append(URLQueryItem(name: "limit", value: String(limit)))
        }
        return try await perform(
            "GET", path: "/api/v1/personalization/feed", query: query, as: PersonalFeedDTO.self
        )
    }

    func fetchRecommendation(targetType: String, targetId: String) async throws -> RecommendationDetailDTO {
        try await perform(
            "GET",
            path: "/api/v1/personalization/recommendations/\(targetType)/\(targetId)",
            as: RecommendationDetailDTO.self
        )
    }

    func submitPersonalFeedback(
        targetType: String, targetId: String, feedback: String, interestId: String? = nil
    ) async throws -> FeedbackResponseDTO {
        let body = try JSONEncoder().encode(
            FeedbackPayload(
                targetType: targetType,
                targetId: targetId,
                feedback: feedback,
                interestId: interestId
            )
        )
        return try await perform(
            "POST", path: "/api/v1/personalization/feedback", body: body, as: FeedbackResponseDTO.self
        )
    }

    func revokePersonalFeedback(targetType: String, targetId: String) async throws {
        try await performNoContent(
            "DELETE", path: "/api/v1/personalization/feedback/target/\(targetType)/\(targetId)"
        )
    }

    func fetchSuggestions() async throws -> SuggestionsDTO {
        try await perform("GET", path: "/api/v1/personalization/suggestions", as: SuggestionsDTO.self)
    }

    func fetchPersonalStats() async throws -> PersonalStatsDTO {
        try await perform("GET", path: "/api/v1/personalization/stats", as: PersonalStatsDTO.self)
    }

    // MARK: - Digest

    func fetchTodayDigest(generate: Bool = true, force: Bool = false) async throws -> DailyDigestDTO {
        try await perform(
            "GET",
            path: "/api/v1/digest/today",
            query: [
                URLQueryItem(name: "generate", value: generate ? "true" : "false"),
                URLQueryItem(name: "force", value: force ? "true" : "false"),
            ],
            as: DailyDigestDTO.self
        )
    }

    func fetchDigest(date: String, generate: Bool = false) async throws -> DailyDigestDTO {
        try await perform(
            "GET",
            path: "/api/v1/digest/\(date)",
            query: [URLQueryItem(name: "generate", value: generate ? "true" : "false")],
            as: DailyDigestDTO.self
        )
    }

    func generateDigest(date: String? = nil, force: Bool = true) async throws -> DailyDigestDTO {
        let body = try JSONEncoder().encode(DigestGeneratePayload(date: date, force: force))
        return try await perform(
            "POST", path: "/api/v1/digest/generate", body: body, as: DailyDigestDTO.self
        )
    }

    func fetchDigestHistory(limit: Int = 20) async throws -> DigestHistoryDTO {
        try await perform(
            "GET",
            path: "/api/v1/digest/history",
            query: [URLQueryItem(name: "limit", value: String(limit))],
            as: DigestHistoryDTO.self
        )
    }

    private struct ResetPayload: Encodable {
        let clearInterests: Bool
        let clearFeedback: Bool
        let clearDigests: Bool

        enum CodingKeys: String, CodingKey {
            case clearInterests = "clear_interests"
            case clearFeedback = "clear_feedback"
            case clearDigests = "clear_digests"
        }
    }

    private struct ResetResponseDTO: Decodable {
        struct Removed: Decodable {
            let interests: Int?
            let feedback: Int?
            let digests: Int?
            let recommendations: Int?
        }

        let reset: Bool
        let removed: Removed
    }

    func resetPersonalization(
        clearInterests: Bool, clearFeedback: Bool, clearDigests: Bool
    ) async throws -> (interests: Int, feedback: Int, digests: Int, recommendations: Int) {
        let body = try JSONEncoder().encode(
            ResetPayload(
                clearInterests: clearInterests,
                clearFeedback: clearFeedback,
                clearDigests: clearDigests
            )
        )
        let response: ResetResponseDTO = try await perform(
            "POST", path: "/api/v1/personalization/reset", body: body, as: ResetResponseDTO.self
        )
        return (
            response.removed.interests ?? 0,
            response.removed.feedback ?? 0,
            response.removed.digests ?? 0,
            response.removed.recommendations ?? 0
        )
    }

    // MARK: - Entities (for interest links)

    func searchEntities(query: String, limit: Int = 20) async throws -> [(id: String, name: String, type: String)] {
        var items: [URLQueryItem] = [URLQueryItem(name: "limit", value: String(limit))]
        if !query.isEmpty {
            items.append(URLQueryItem(name: "q", value: query))
        }
        let page: EntityPageDTO = try await perform(
            "GET", path: "/api/v1/entities", query: items, as: EntityPageDTO.self
        )
        return page.items.map { ($0.id, $0.canonicalName, $0.entityType) }
    }
}
