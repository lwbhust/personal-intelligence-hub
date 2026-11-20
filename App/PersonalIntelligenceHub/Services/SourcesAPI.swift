import Foundation

/// Phase 1 数据访问。所有方法都走真实 Sidecar HTTP，不做本地假数据。
extension APIClient {
    func fetchSources(query: [URLQueryItem]) async throws -> SourcePage {
        try await perform("GET", path: "/api/v1/sources", query: query, as: SourcePage.self)
    }

    func createSource(body: Data) async throws -> SourceDTO {
        try await perform("POST", path: "/api/v1/sources", body: body, as: SourceDTO.self)
    }

    func updateSource(id: String, body: Data) async throws -> SourceDTO {
        try await perform("PATCH", path: "/api/v1/sources/\(id)", body: body, as: SourceDTO.self)
    }

    func deleteSource(id: String) async throws {
        try await performNoContent("DELETE", path: "/api/v1/sources/\(id)")
    }

    func fetchAdapter(sourceID: String) async throws -> SourceAdapterDTO {
        try await perform(
            "GET",
            path: "/api/v1/sources/\(sourceID)/adapter",
            as: SourceAdapterDTO.self
        )
    }

    func saveAdapter(sourceID: String, body: Data) async throws -> SourceAdapterDTO {
        try await perform(
            "PUT",
            path: "/api/v1/sources/\(sourceID)/adapter",
            body: body,
            as: SourceAdapterDTO.self
        )
    }

    func deleteAdapter(sourceID: String) async throws {
        try await performNoContent(
            "DELETE", path: "/api/v1/sources/\(sourceID)/adapter"
        )
    }

    func dryRunAdapter(sourceID: String, limit: Int = 3) async throws -> AdapterDryRunDTO {
        try await perform(
            "POST",
            path: "/api/v1/sources/\(sourceID)/adapter/dry-run",
            query: [URLQueryItem(name: "limit", value: String(limit))],
            as: AdapterDryRunDTO.self
        )
    }

    func fetchAllCategories() async throws -> [SourceCategoryDTO] {
        try await perform(
            "GET",
            path: "/api/v1/source-categories/all",
            as: [SourceCategoryDTO].self
        )
    }

    func createCategory(body: Data) async throws -> SourceCategoryDTO {
        try await perform(
            "POST",
            path: "/api/v1/source-categories",
            body: body,
            as: SourceCategoryDTO.self
        )
    }

    func updateCategory(id: String, body: Data) async throws -> SourceCategoryDTO {
        try await perform(
            "PATCH",
            path: "/api/v1/source-categories/\(id)",
            body: body,
            as: SourceCategoryDTO.self
        )
    }

    func deleteCategory(id: String) async throws {
        try await performNoContent("DELETE", path: "/api/v1/source-categories/\(id)")
    }
}
