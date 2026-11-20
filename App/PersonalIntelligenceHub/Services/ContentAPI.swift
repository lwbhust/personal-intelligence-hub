import Foundation

/// Phase 2 数据访问：文章、采集任务与来源健康。全部走真实 Sidecar HTTP。
extension APIClient {
    // MARK: - Articles

    func fetchArticles(query: [URLQueryItem]) async throws -> ArticlePage {
        try await perform("GET", path: "/api/v1/articles", query: query, as: ArticlePage.self)
    }

    func fetchArticle(id: String) async throws -> ArticleDetailDTO {
        try await perform("GET", path: "/api/v1/articles/\(id)", as: ArticleDetailDTO.self)
    }

    // MARK: - Phase 5: reading state & favorites

    func markArticleRead(id: String) async throws -> ArticleDetailDTO {
        try await perform(
            "POST", path: "/api/v1/articles/\(id)/mark-read",
            as: ArticleDetailDTO.self
        )
    }

    func markArticleLater(id: String) async throws -> ArticleDetailDTO {
        try await perform(
            "POST", path: "/api/v1/articles/\(id)/mark-later",
            as: ArticleDetailDTO.self
        )
    }

    func markArticleUnread(id: String) async throws -> ArticleDetailDTO {
        try await perform(
            "POST", path: "/api/v1/articles/\(id)/mark-unread",
            as: ArticleDetailDTO.self
        )
    }

    func setArticleFavorite(id: String, isFavorite: Bool) async throws -> ArticleDetailDTO {
        let body = try JSONSerialization.data(
            withJSONObject: ["is_favorite": isFavorite]
        )
        return try await perform(
            "PUT", path: "/api/v1/articles/\(id)/favorite",
            body: body,
            as: ArticleDetailDTO.self
        )
    }

    /// 按需抓取正文：只在用户打开「仅摘要」文章并点击时调用。
    func fetchArticleContent(id: String) async throws -> ArticleContentFetchResponseDTO {
        try await perform(
            "POST",
            path: "/api/v1/articles/\(id)/fetch-content",
            as: ArticleContentFetchResponseDTO.self
        )
    }

    // MARK: - Phase 5: full-text search

    func searchArticles(query: [URLQueryItem]) async throws -> FtsSearchResponse {
        try await perform(
            "GET", path: "/api/v1/search", query: query,
            as: FtsSearchResponse.self
        )
    }

    // MARK: - Collection jobs

    func fetchCollectionJobs(query: [URLQueryItem]) async throws -> CollectionJobPage {
        try await perform(
            "GET",
            path: "/api/v1/collection-jobs",
            query: query,
            as: CollectionJobPage.self
        )
    }

    func fetchCollectionJob(id: String) async throws -> CollectionJobDTO {
        try await perform("GET", path: "/api/v1/collection-jobs/\(id)", as: CollectionJobDTO.self)
    }

    func fetchCollectionStatus() async throws -> CollectionStatusDTO {
        try await perform("GET", path: "/api/v1/collection/status", as: CollectionStatusDTO.self)
    }

    func createCollectionJob(body: Data) async throws -> CollectionJobDTO {
        try await perform(
            "POST",
            path: "/api/v1/collection-jobs",
            body: body,
            as: CollectionJobDTO.self
        )
    }

    func cancelCollectionJob(id: String) async throws -> CollectionJobDTO {
        try await perform(
            "POST",
            path: "/api/v1/collection-jobs/\(id)/cancel",
            as: CollectionJobDTO.self
        )
    }

    func retryCollectionJob(id: String) async throws -> CollectionJobDTO {
        try await perform(
            "POST",
            path: "/api/v1/collection-jobs/\(id)/retry",
            as: CollectionJobDTO.self
        )
    }

    // MARK: - Single source collection & health

    func collectSource(id: String) async throws -> CollectResponseDTO {
        try await perform(
            "POST",
            path: "/api/v1/sources/\(id)/collect",
            as: CollectResponseDTO.self
        )
    }

    func fetchSourceHealth(id: String, limit: Int = 20) async throws -> SourceHealthLogPage {
        try await perform(
            "GET",
            path: "/api/v1/sources/\(id)/health",
            query: [URLQueryItem(name: "limit", value: String(limit))],
            as: SourceHealthLogPage.self
        )
    }
}
