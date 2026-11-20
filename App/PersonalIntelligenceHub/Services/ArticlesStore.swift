import Foundation

/// 文章列表与详情的界面状态。所有数据来自真实 `/api/v1`，无本地假数据。
@MainActor
final class ArticlesStore: ObservableObject {
    @Published private(set) var articles: [ArticleSummaryDTO] = []
    @Published private(set) var total = 0
    @Published private(set) var isLoading = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?
    @Published private(set) var errorRequestID: String?

    @Published private(set) var detail: ArticleDetailDTO?
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var detailErrorMessage: String?
    @Published private(set) var detailErrorRequestID: String?

    @Published private(set) var filterSources: [SourceDTO] = []
    @Published private(set) var filterCategories: [SourceCategoryDTO] = []
    @Published private(set) var filterOptionsError: String?

    // Phase 3: 当前文章的 AI 分析
    @Published private(set) var analysisItems: [AIAnalysisDTO] = []
    @Published private(set) var analysisArticleID: String?
    @Published private(set) var isLoadingAnalysis = false
    @Published private(set) var analysisErrorMessage: String?
    @Published private(set) var isAnalyzing = false
    @Published private(set) var analysisNotice: String?

    @Published var searchText = ""
    @Published var sourceFilter: String?
    @Published var categoryFilter: String?
    @Published var statusFilter: ArticleStatusFilter = .active
    @Published var readingFilter: ReadingStatus?
    @Published var favoriteFilter: Bool?
    @Published var order: ArticleOrder = .publishedAt
    @Published var direction: SortDirection = .desc
    @Published var selectedArticleID: String?

    @Published private(set) var isFetchingContent = false

    private weak var client: APIClient?
    private let pageSize = 30

    var canLoadMore: Bool {
        hasLoaded && articles.count < total
    }

    func bind(_ client: APIClient?) {
        if client === self.client {
            return
        }
        self.client = client
        if client == nil {
            articles = []
            total = 0
            hasLoaded = false
            detail = nil
            selectedArticleID = nil
            filterSources = []
            filterCategories = []
            filterOptionsError = nil
            analysisItems = []
            analysisArticleID = nil
            analysisNotice = nil
            clearListError()
            clearDetailError()
            clearAnalysisError()
        } else {
            Task { await reload() }
        }
    }

    func reload() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        if filterSources.isEmpty && filterCategories.isEmpty {
            await loadFilterOptionsIfNeeded()
        }
        do {
            let page = try await client.fetchArticles(query: buildQuery(offset: 0))
            articles = page.items
            total = page.total
            hasLoaded = true
            clearListError()
        } catch {
            handleListError(error)
        }
    }

    /// 筛选或搜索变化：回到第一页并清空详情，避免展示与筛选条件不符的旧文章。
    func applyFiltersAndReload() async {
        selectedArticleID = nil
        detail = nil
        analysisItems = []
        analysisArticleID = nil
        analysisNotice = nil
        clearDetailError()
        clearAnalysisError()
        await reload()
    }

    func loadMore() async {
        guard let client, !isLoading, articles.count < total else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let page = try await client.fetchArticles(query: buildQuery(offset: articles.count))
            articles.append(contentsOf: page.items)
            total = page.total
            clearListError()
        } catch {
            handleListError(error)
        }
    }

    func loadFilterOptionsIfNeeded() async {
        guard let client, filterSources.isEmpty && filterCategories.isEmpty else { return }
        do {
            async let sourcesTask = client.fetchSources(
                query: [
                    URLQueryItem(name: "limit", value: "100"),
                    URLQueryItem(name: "offset", value: "0"),
                    URLQueryItem(name: "order", value: "name"),
                    URLQueryItem(name: "direction", value: "asc"),
                ]
            )
            async let categoriesTask = client.fetchAllCategories()
            let (sourcePage, categories) = try await (sourcesTask, categoriesTask)
            filterSources = sourcePage.items
            filterCategories = categories
            filterOptionsError = nil
        } catch {
            if let api = error as? APIRequestError {
                filterOptionsError = api.message
            } else {
                filterOptionsError = error.localizedDescription
            }
        }
    }

    func loadDetail(force: Bool = false) async {
        guard let client, let id = selectedArticleID else {
            detail = nil
            detailErrorMessage = nil
            detailErrorRequestID = nil
            isLoadingDetail = false
            return
        }
        if !force, detail?.id == id {
            return
        }
        isLoadingDetail = true
        detailErrorMessage = nil
        detailErrorRequestID = nil
        defer {
            if selectedArticleID == id {
                isLoadingDetail = false
            }
        }
        do {
            let loaded = try await client.fetchArticle(id: id)
            guard !Task.isCancelled, selectedArticleID == id else { return }
            detail = loaded
        } catch {
            guard selectedArticleID == id else { return }
            if isCancellation(error) { return }
            detail = nil
            if let api = error as? APIRequestError {
                detailErrorMessage = api.message
                detailErrorRequestID = api.requestID
            } else {
                detailErrorMessage = error.localizedDescription
                detailErrorRequestID = nil
            }
        }
    }

    func clearListError() {
        errorMessage = nil
        errorCode = nil
        errorRequestID = nil
    }

    // MARK: - Phase 3: AI analysis

    func loadAnalysis(force: Bool = false) async {
        guard let client, let id = selectedArticleID else {
            analysisItems = []
            analysisArticleID = nil
            analysisErrorMessage = nil
            isLoadingAnalysis = false
            return
        }
        if !force, analysisArticleID == id {
            analysisErrorMessage = nil
            return
        }
        isLoadingAnalysis = true
        analysisErrorMessage = nil
        defer { isLoadingAnalysis = false }
        do {
            let result = try await client.fetchArticleAnalysis(id: id)
            guard !Task.isCancelled, selectedArticleID == id else { return }
            analysisItems = result.items
            analysisArticleID = id
        } catch {
            guard selectedArticleID == id else { return }
            if isCancellation(error) { return }
            analysisItems = []
            analysisArticleID = id
            if let api = error as? APIRequestError {
                analysisErrorMessage = api.message
            } else {
                analysisErrorMessage = error.localizedDescription
            }
        }
    }

    func analyzeSelectedArticle() async {
        guard let client, let id = selectedArticleID else { return }
        isAnalyzing = true
        analysisNotice = nil
        analysisErrorMessage = nil
        defer { isAnalyzing = false }
        do {
            let run = try await client.analyzeArticle(id: id)
            analysisNotice = "已创建分析任务：\(aiRunStatusLabel(run.status))"
            await pollRun(run.id, client: client, articleID: id)
        } catch {
            if isCancellation(error) { return }
            if let api = error as? APIRequestError {
                analysisErrorMessage = api.message
            } else {
                analysisErrorMessage = error.localizedDescription
            }
        }
    }

    private func pollRun(_ runID: String, client: APIClient, articleID: String) async {
        for _ in 0..<60 {
            try? await Task.sleep(for: .seconds(1.5))
            if Task.isCancelled || selectedArticleID != articleID { return }
            do {
                let run = try await client.fetchAIRun(id: runID)
                analysisNotice = "分析任务：\(aiRunStatusLabel(run.status)) · \(run.processedCount)/\(run.requestedCount)"
                if AIRunStatus(rawValue: run.status)?.isActive != true {
                    break
                }
            } catch {
                break
            }
        }
        guard selectedArticleID == articleID else { return }
        await loadAnalysis(force: true)
        if let first = analysisItems.first {
            analysisNotice = "已完成：\(first.category) · \(first.modelName)"
        }
    }

    func clearAnalysisError() {
        analysisErrorMessage = nil
    }

    func clearDetailError() {
        detailErrorMessage = nil
        detailErrorRequestID = nil
    }

    // MARK: - Helpers

    private func buildQuery(offset: Int) -> [URLQueryItem] {
        var items = [
            URLQueryItem(name: "limit", value: String(pageSize)),
            URLQueryItem(name: "offset", value: String(offset)),
            URLQueryItem(name: "status", value: statusFilter.rawValue),
            URLQueryItem(name: "order", value: order.rawValue),
            URLQueryItem(name: "direction", value: direction.rawValue),
        ]
        let keyword = String(
            searchText
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .prefix(100)
        )
        if !keyword.isEmpty {
            items.append(URLQueryItem(name: "q", value: keyword))
        }
        if let sourceFilter, !sourceFilter.isEmpty {
            items.append(URLQueryItem(name: "source_id", value: sourceFilter))
        }
        if let categoryFilter, !categoryFilter.isEmpty {
            items.append(URLQueryItem(name: "category_id", value: categoryFilter))
        }
        if let readingFilter {
            items.append(URLQueryItem(name: "reading_status", value: readingFilter.rawValue))
        }
        if let favoriteFilter {
            items.append(
                URLQueryItem(name: "is_favorite", value: favoriteFilter ? "true" : "false")
            )
        }
        return items
    }

    private func handleListError(_ error: Error) {
        // 页面切换会取消在途请求，这属于正常导航行为，不应显示为错误。
        if isCancellation(error) { return }
        if let api = error as? APIRequestError {
            errorMessage = api.message
            errorCode = api.code
            errorRequestID = api.requestID
        } else {
            errorMessage = error.localizedDescription
            errorCode = nil
            errorRequestID = nil
        }
    }

    private func isCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        let nsError = error as NSError
        return nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled
    }

    // MARK: - Phase 5: reading state & favorites

    func markSelectedRead() async {
        guard let client, let id = selectedArticleID else { return }
        do {
            let updated = try await client.markArticleRead(id: id)
            applyMutation(updated, success: "已标记为已读")
        } catch {
            reportActionFailure(error)
        }
    }

    func markSelectedLater() async {
        guard let client, let id = selectedArticleID else { return }
        do {
            let updated = try await client.markArticleLater(id: id)
            applyMutation(updated, success: "已加入稍后阅读")
        } catch {
            reportActionFailure(error)
        }
    }

    func markSelectedUnread() async {
        guard let client, let id = selectedArticleID else { return }
        do {
            let updated = try await client.markArticleUnread(id: id)
            applyMutation(updated, success: "已标记为未读")
        } catch {
            reportActionFailure(error)
        }
    }

    /// 阅读工具栏统一入口；只使用现有三个真实接口。
    func setSelectedReadingStatus(_ status: ReadingStatus) async {
        switch status {
        case .read:
            await markSelectedRead()
        case .later:
            await markSelectedLater()
        case .unread:
            await markSelectedUnread()
        case .reading:
            // 服务端没有「阅读中」的独立动作，避免伪造状态。
            break
        }
    }

    func toggleSelectedFavorite() async {
        guard let client, let id = selectedArticleID else { return }
        let new = !(detail?.isFavorite ?? false)
        do {
            let updated = try await client.setArticleFavorite(id: id, isFavorite: new)
            applyMutation(updated, success: new ? "已收藏" : "已取消收藏")
        } catch {
            reportActionFailure(error)
        }
    }

    /// 按需抓取正文。成功时更新详情与搜索索引；失败时保留摘要并提示原因。
    func fetchSelectedContent() async {
        guard let client, let id = selectedArticleID, !isFetchingContent else { return }
        isFetchingContent = true
        defer { isFetchingContent = false }
        do {
            let response = try await client.fetchArticleContent(id: id)
            guard selectedArticleID == id else { return }
            applyDetailUpdate(response.article)
            applyListUpdate(to: response.article)
            switch response.fetch.status {
            case "fetched":
                showActionFeedback("已抓取全文（\(response.fetch.chars) 字）", isError: false)
            case "cached":
                showActionFeedback("已使用本地缓存的正文", isError: false)
            default:
                let reason = response.fetch.errorMessage ?? "正文抓取失败"
                showActionFeedback(reason, isError: true)
            }
        } catch {
            reportActionFailure(error)
        }
    }

    // MARK: - Phase 7.3.1: article-level personal feedback
    func submitPersonalFeedback(_ feedback: String) async {
        guard let client, let id = selectedArticleID else { return }
        do {
            _ = try await client.submitPersonalFeedback(
                targetType: "article", targetId: id, feedback: feedback
            )
            showActionFeedback(
                "已记录反馈：\(PersonalizationStore.feedbackLabel(feedback))",
                isError: false
            )
        } catch {
            let message = (error as? APIRequestError)?.message ?? "反馈失败"
            showActionFeedback("反馈失败：\(message)", isError: true)
        }
    }

    // MARK: - Action feedback

    @Published private(set) var actionFeedback: String?
    @Published private(set) var actionFeedbackIsError = false
    private var feedbackToken = 0

    /// 操作结果轻提示：2.6 秒后自动消失，不占用正文空间。
    func showActionFeedback(_ message: String, isError: Bool) {
        actionFeedback = message
        actionFeedbackIsError = isError
        feedbackToken += 1
        let token = feedbackToken
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(2.6))
            guard let self, self.feedbackToken == token else { return }
            self.actionFeedback = nil
        }
    }

    private func applyMutation(_ updated: ArticleDetailDTO, success: String) {
        applyDetailUpdate(updated)
        applyListUpdate(to: updated)
        showActionFeedback(success, isError: false)
    }

    private func reportActionFailure(_ error: Error) {
        if isCancellation(error) { return }
        let message = (error as? APIRequestError)?.message ?? error.localizedDescription
        showActionFeedback("操作失败：\(message)", isError: true)
    }

    private func applyDetailUpdate(_ updated: ArticleDetailDTO) {
        guard detail?.id == updated.id else { return }
        detail = updated
    }

    private func applyListUpdate(to updated: ArticleDetailDTO) {
        guard let idx = articles.firstIndex(where: { $0.id == updated.id }) else { return }
        articles[idx] = ArticleSummaryDTO(from: updated)
    }
}
