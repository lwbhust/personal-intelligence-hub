import Foundation

/// Phase 3 本地 AI 访问：全部走真实 Sidecar HTTP，无本地假数据。
extension APIClient {
    private struct AIRunCreateBody: Encodable {
        let scope: String
        let articleIds: [String]?
        let limit: Int
    }

    private func aiBody(scope: String, articleIds: [String]?, limit: Int) throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(
            AIRunCreateBody(scope: scope, articleIds: articleIds, limit: limit)
        )
    }

    func fetchAIStatus() async throws -> AIStatusDTO {
        try await perform("GET", path: "/api/v1/ai/status", as: AIStatusDTO.self)
    }

    func fetchAIModels() async throws -> AIModelPage {
        try await perform("GET", path: "/api/v1/ai/models", as: AIModelPage.self)
    }

    func fetchAIRuns(limit: Int = 30, offset: Int = 0) async throws -> AIRunPage {
        try await perform(
            "GET",
            path: "/api/v1/ai/runs",
            query: [
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: String(offset)),
            ],
            as: AIRunPage.self
        )
    }

    func fetchAIRun(id: String) async throws -> AIRunDTO {
        try await perform("GET", path: "/api/v1/ai/runs/\(id)", as: AIRunDTO.self)
    }

    func createUnanalyzedAIRun(limit: Int) async throws -> AIRunDTO {
        let body = try aiBody(scope: "unanalyzed", articleIds: nil, limit: limit)
        return try await perform("POST", path: "/api/v1/ai/runs", body: body, as: AIRunDTO.self)
    }

    func analyzeArticle(id: String) async throws -> AIRunDTO {
        try await perform(
            "POST",
            path: "/api/v1/articles/\(id)/analyze",
            as: AIRunDTO.self
        )
    }

    func pauseAIRun(id: String) async throws -> AIRunDTO {
        try await perform("POST", path: "/api/v1/ai/runs/\(id)/pause", as: AIRunDTO.self)
    }

    func resumeAIRun(id: String) async throws -> AIRunDTO {
        try await perform("POST", path: "/api/v1/ai/runs/\(id)/resume", as: AIRunDTO.self)
    }

    func cancelAIRun(id: String) async throws -> AIRunDTO {
        try await perform("POST", path: "/api/v1/ai/runs/\(id)/cancel", as: AIRunDTO.self)
    }

    func retryAIRun(id: String) async throws -> AIRunDTO {
        try await perform("POST", path: "/api/v1/ai/runs/\(id)/retry", as: AIRunDTO.self)
    }

    func fetchArticleAnalysis(id: String) async throws -> ArticleAnalysisDTO {
        try await perform(
            "GET",
            path: "/api/v1/articles/\(id)/analysis",
            as: ArticleAnalysisDTO.self
        )
    }
}
