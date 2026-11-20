import Foundation

/// 信息源与分类的界面状态。所有数据来自真实 `/api/v1`，无本地假数据。
@MainActor
final class SourcesStore: ObservableObject {
    @Published private(set) var sources: [SourceDTO] = []
    @Published private(set) var categories: [SourceCategoryDTO] = []
    @Published private(set) var total = 0
    @Published private(set) var isLoading = false
    @Published private(set) var isSaving = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?
    @Published private(set) var errorRequestID: String?
    @Published private(set) var fieldErrors: [String: String] = [:]
    @Published private(set) var collectingSourceIDs: Set<String> = []
    @Published private(set) var collectNotice: String?

    @Published var searchText = ""
    @Published var typeFilter: SourceTypeFilter = .all
    @Published var enabledFilter: EnabledFilter = .all
    @Published var languageFilter: String?
    @Published var categoryFilter: String?
    @Published var onlyUncategorized = false

    private weak var client: APIClient?
    private let pageSize = 50

    var canLoadMore: Bool {
        hasLoaded && sources.count < total
    }

    func bind(_ client: APIClient?) {
        if client === self.client {
            return
        }
        self.client = client
        if client == nil {
            sources = []
            categories = []
            total = 0
            hasLoaded = false
            collectingSourceIDs = []
            collectNotice = nil
            clearError()
        } else {
            Task { await reload() }
        }
    }

    func reload() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            async let categoryList = client.fetchAllCategories()
            async let page = client.fetchSources(query: buildQuery(offset: 0))
            let (loadedCategories, loadedPage) = try await (categoryList, page)
            categories = loadedCategories
            sources = loadedPage.items
            total = loadedPage.total
            hasLoaded = true
            clearError()
        } catch {
            handle(error)
        }
    }

    func loadMore() async {
        guard let client, !isLoading, sources.count < total else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let page = try await client.fetchSources(query: buildQuery(offset: sources.count))
            sources.append(contentsOf: page.items)
            total = page.total
            clearError()
        } catch {
            handle(error)
        }
    }

    func save(_ draft: SourceDraft) async -> Bool {
        guard let client else { return false }
        let name = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty {
            fieldErrors = ["name": "不能为空"]
            return false
        }
        if draft.url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            fieldErrors = ["url": "不能为空"]
            return false
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let body = try draft.payload()
            if let sourceID = draft.sourceID {
                _ = try await client.updateSource(id: sourceID, body: body)
            } else {
                _ = try await client.createSource(body: body)
            }
            clearError()
            await reload()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func setEnabled(_ source: SourceDTO, _ enabled: Bool) async {
        guard let client else { return }
        do {
            let body = try JSONSerialization.data(withJSONObject: ["enabled": enabled])
            _ = try await client.updateSource(id: source.id, body: body)
            clearError()
            await reload()
        } catch {
            handle(error)
            await reload()
        }
    }

    func delete(_ source: SourceDTO) async {
        guard let client else { return }
        do {
            try await client.deleteSource(id: source.id)
            clearError()
            await reload()
        } catch {
            handle(error)
        }
    }

    /// 单来源采集：后端 202 返回真实 Job。409/422 的 message 原样展示。
    func collect(_ source: SourceDTO) async {
        guard let client, !collectingSourceIDs.contains(source.id) else { return }
        collectingSourceIDs.insert(source.id)
        defer { collectingSourceIDs.remove(source.id) }
        do {
            let response = try await client.collectSource(id: source.id)
            collectNotice = "已触发「\(source.name)」采集任务 \(response.job.id)，"
                + "状态：\(CollectionJobStatus.label(for: response.job.status))。"
            clearError()
        } catch {
            collectNotice = nil
            handle(error)
        }
    }

    func dismissCollectNotice() {
        collectNotice = nil
    }

    func saveCategory(_ draft: CategoryDraft) async -> Bool {
        guard let client else { return false }
        let name = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty {
            fieldErrors = ["name": "不能为空"]
            return false
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let body = try draft.payload()
            if let categoryID = draft.categoryID {
                _ = try await client.updateCategory(id: categoryID, body: body)
            } else {
                _ = try await client.createCategory(body: body)
            }
            clearError()
            await reload()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func deleteCategory(_ category: SourceCategoryDTO) async {
        guard let client else { return }
        do {
            try await client.deleteCategory(id: category.id)
            clearError()
            await reload()
        } catch {
            handle(error)
        }
    }

    func clearError() {
        errorMessage = nil
        errorCode = nil
        errorRequestID = nil
        fieldErrors = [:]
    }

    // MARK: - Helpers

    private func buildQuery(offset: Int) -> [URLQueryItem] {
        var items = [
            URLQueryItem(name: "limit", value: String(pageSize)),
            URLQueryItem(name: "offset", value: String(offset)),
            URLQueryItem(name: "order", value: "priority"),
            URLQueryItem(name: "direction", value: "desc"),
        ]
        let keyword = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !keyword.isEmpty {
            items.append(URLQueryItem(name: "q", value: keyword))
        }
        if typeFilter != .all {
            items.append(URLQueryItem(name: "source_type", value: typeFilter.rawValue))
        }
        if onlyUncategorized {
            items.append(URLQueryItem(name: "uncategorized", value: "true"))
        } else if let categoryFilter {
            items.append(URLQueryItem(name: "category_id", value: categoryFilter))
        }
        if let languageFilter {
            items.append(URLQueryItem(name: "language", value: languageFilter))
        }
        switch enabledFilter {
        case .all: break
        case .enabled: items.append(URLQueryItem(name: "enabled", value: "true"))
        case .disabled: items.append(URLQueryItem(name: "enabled", value: "false"))
        }
        return items
    }

    private func handle(_ error: Error) {
        if let api = error as? APIRequestError {
            errorMessage = api.message
            errorCode = api.code
            errorRequestID = api.requestID
            var map: [String: String] = [:]
            for item in api.fields {
                map[item.field] = item.message
            }
            fieldErrors = map
        } else {
            errorMessage = error.localizedDescription
            errorCode = nil
            errorRequestID = nil
            fieldErrors = [:]
        }
    }
}
