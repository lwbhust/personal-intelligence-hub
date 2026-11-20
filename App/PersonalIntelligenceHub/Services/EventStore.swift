import Foundation

/// 事件中心状态：列表、详情、时间线、实体、关系、评分与人工校正。
/// 所有数据来自真实 Sidecar API；无静态假数据。
@MainActor
final class EventStore: ObservableObject {
    @Published private(set) var events: [EventSummaryDTO] = []
    @Published private(set) var total = 0
    @Published private(set) var rankings: [RankingItemDTO] = []
    @Published private(set) var rankingTotal = 0
    @Published private(set) var clusterStatus: ClusterStatusDTO?

    @Published private(set) var selectedEvent: EventDetailDTO?
    @Published private(set) var timeline: [EventTimelineDTO] = []
    @Published private(set) var detailArticles: [EventArticleDTO] = []
    @Published private(set) var detailEntities: [EventEntityDTO] = []
    @Published private(set) var detailRelations: [EventRelationDTO] = []
    @Published private(set) var scores: [EventScoreSnapshotDTO] = []

    @Published private(set) var pickerArticles: [ArticleSummaryDTO] = []
    @Published private(set) var isLoading = false
    @Published private(set) var isLoadingMore = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?
    @Published private(set) var actionMessage: String?
    @Published private(set) var isBusy = false

    @Published var statusFilter: String?
    @Published var categoryFilter: String?
    @Published var order = "importance"
    @Published var window = "7d"
    @Published var keyword = ""
    @Published var rankingKind = "importance"
    @Published var selectedEventID: String?

    private weak var client: APIClient?
    private let pageSize = 20

    var hasMore: Bool { events.count < total }

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        if client == nil {
            events = []
            total = 0
            rankings = []
            rankingTotal = 0
            clusterStatus = nil
            selectedEvent = nil
            selectedEventID = nil
            resetDetail()
            hasLoaded = false
            clearError()
        } else {
            Task { await reload() }
        }
    }

    // MARK: - List

    func reload() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            async let pageTask = client.fetchEvents(query: listQuery(offset: 0))
            async let rankingTask = client.fetchRankings(
                kind: rankingKind, window: window, category: categoryFilter, limit: 10
            )
            async let statusTask = client.fetchClusterStatus()
            let (page, rankingPage, status) = try await (pageTask, rankingTask, statusTask)
            events = page.items
            total = page.total
            rankings = rankingPage.items
            rankingTotal = rankingPage.total
            clusterStatus = status
            hasLoaded = true
            clearError()
        } catch {
            handle(error)
        }
    }

    func loadMore() async {
        guard let client, !isLoading, !isLoadingMore, hasMore else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let page = try await client.fetchEvents(query: listQuery(offset: events.count))
            let existing = Set(events.map(\.id))
            events += page.items.filter { !existing.contains($0.id) }
            total = page.total
        } catch {
            handle(error)
        }
    }

    func loadMoreIfNeeded(current id: String) async {
        guard let index = events.firstIndex(where: { $0.id == id }) else { return }
        if index >= events.count - 3 {
            await loadMore()
        }
    }

    func refreshRankings() async {
        guard let client else { return }
        do {
            let page = try await client.fetchRankings(
                kind: rankingKind, window: window, category: categoryFilter, limit: 10
            )
            rankings = page.items
            rankingTotal = page.total
        } catch {
            handle(error)
        }
    }

    // MARK: - Detail

    func select(_ id: String?) async {
        selectedEventID = id
        selectedEvent = nil
        resetDetail()
        guard let id else { return }
        await loadDetail(id: id)
    }

    func loadDetail(id: String) async {
        guard let client else { return }
        isLoadingDetail = true
        defer { isLoadingDetail = false }
        do {
            async let detailTask = client.fetchEvent(id: id)
            async let timelineTask = client.fetchEventTimeline(id: id, limit: 50, offset: 0)
            async let articlesTask = client.fetchEventArticles(id: id, limit: 50, offset: 0)
            async let entitiesTask = client.fetchEventEntities(id: id)
            async let relationsTask = client.fetchEventRelations(id: id)
            async let scoresTask = client.fetchEventScores(id: id, limit: 10)
            let (detail, timelinePage, articlePage, entities, relations, scorePage) =
                try await (detailTask, timelineTask, articlesTask, entitiesTask,
                           relationsTask, scoresTask)
            guard selectedEventID == id else { return }
            selectedEvent = detail
            timeline = timelinePage.items
            detailArticles = articlePage.items
            detailEntities = entities
            detailRelations = relations
            scores = scorePage.items
            clearError()
        } catch {
            handle(error)
        }
    }

    // MARK: - Manual corrections

    func rename(_ title: String) async {
        guard let client, let id = selectedEventID else { return }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if await run({ try await client.renameEvent(id: id, title: trimmed) }) {
            actionMessage = "事件标题已更新"
        }
    }

    func changeStatus(_ status: String, reason: String) async {
        guard let client, let id = selectedEventID else { return }
        if await run({ try await client.setEventStatus(id: id, status: status, reason: reason) }) {
            actionMessage = "事件状态已更新为\(eventStatusLabel(status))"
        }
    }

    func merge(into targetID: String, reason: String?) async {
        guard let client, let id = selectedEventID else { return }
        do {
            isBusy = true
            defer { isBusy = false }
            let detail = try await client.mergeEvents(id: id, targetEventId: targetID, reason: reason)
            selectedEventID = detail.id
            await reload()
            await loadDetail(id: detail.id)
            actionMessage = "事件已合并"
        } catch {
            handle(error)
        }
    }

    func split(articleIDs: [String], title: String?) async {
        guard let client, let id = selectedEventID else { return }
        do {
            isBusy = true
            defer { isBusy = false }
            let created = try await client.splitEvent(id: id, articleIds: articleIDs, title: title)
            await reload()
            selectedEventID = created.id
            await loadDetail(id: created.id)
            actionMessage = "已拆分出新事件"
        } catch {
            handle(error)
        }
    }

    func unmerge() async {
        guard let client, let id = selectedEventID else { return }
        do {
            isBusy = true
            defer { isBusy = false }
            let detail = try await client.unmergeEvent(id: id)
            selectedEvent = detail
            await reload()
            await loadDetail(id: detail.id)
            actionMessage = "已撤销合并（事件关系不随撤销恢复）"
        } catch {
            handle(error)
        }
    }

    func addArticle(_ articleID: String, role: String) async {
        guard let client, let id = selectedEventID else { return }
        do {
            isBusy = true
            defer { isBusy = false }
            try await client.addEventArticle(id: id, articleId: articleID, role: role)
            await loadDetail(id: id)
            await reload()
            actionMessage = "文章已加入事件"
        } catch {
            handle(error)
        }
    }

    func removeArticle(_ articleID: String) async {
        guard let client, let id = selectedEventID else { return }
        do {
            isBusy = true
            defer { isBusy = false }
            try await client.removeEventArticle(id: id, articleId: articleID)
            await loadDetail(id: id)
            await reload()
            actionMessage = "文章已移出事件"
        } catch {
            handle(error)
        }
    }

    func setRelationStatus(_ relation: EventRelationDTO, status: String) async {
        guard let client, let id = selectedEventID else { return }
        do {
            isBusy = true
            defer { isBusy = false }
            _ = try await client.updateRelationStatus(
                eventId: id, relationId: relation.id, status: status
            )
            await loadDetail(id: id)
            actionMessage = status == "confirmed" ? "关系已确认" : "关系已忽略"
        } catch {
            handle(error)
        }
    }

    // MARK: - Clustering

    func runClustering(scope: String, limit: Int, useLLM: Bool) async {
        guard let client else { return }
        do {
            isBusy = true
            actionMessage = nil
            let run = try await client.createClusterRun(scope: scope, limit: limit, useLLM: useLLM)
            actionMessage = "已提交聚类任务（\(run.requestedCount) 篇文章）"
            let terminal = ["succeeded", "partially_succeeded", "failed", "cancelled"]
            var current = run
            var attempts = 0
            while !terminal.contains(current.status) && attempts < 300 {
                try await Task.sleep(for: .milliseconds(400))
                current = try await client.fetchClusterRun(id: run.id)
                attempts += 1
            }
            actionMessage = "聚类任务：\(clusterRunStatusLabel(current.status))"
            await reload()
            if let selectedEventID {
                await loadDetail(id: selectedEventID)
            }
        } catch {
            handle(error)
        }
        isBusy = false
    }

    // MARK: - Article picker

    func recomputeScores() async {
        guard let client else { return }
        do {
            isBusy = true
            let result = try await client.recomputeScores(scope: "stale")
            await reload()
            await refreshRankings()
            if let selectedEventID {
                await loadDetail(id: selectedEventID)
            }
            actionMessage = "已重算 \(result.scored) 个事件的过期评分"
        } catch {
            handle(error)
        }
        isBusy = false
    }

    func loadPickerArticles() async {
        guard let client else { return }
        do {
            let page = try await client.fetchArticles(query: [
                URLQueryItem(name: "limit", value: "50"),
                URLQueryItem(name: "offset", value: "0"),
                URLQueryItem(name: "order", value: "recent"),
            ])
            let memberIDs = Set(detailArticles.map(\.articleId))
            pickerArticles = page.items.filter { !memberIDs.contains($0.id) }
        } catch {
            handle(error)
        }
    }

    func refreshClusterStatus() async {
        guard let client else { return }
        do {
            clusterStatus = try await client.fetchClusterStatus()
        } catch {
            handle(error)
        }
    }

    func clearError() {
        errorMessage = nil
        errorCode = nil
    }

    func clearActionMessage() {
        actionMessage = nil
    }

    // MARK: - Helpers

    private func listQuery(offset: Int) -> [URLQueryItem] {
        var query = [
            URLQueryItem(name: "limit", value: String(pageSize)),
            URLQueryItem(name: "offset", value: String(offset)),
            URLQueryItem(name: "order", value: order),
            URLQueryItem(name: "window", value: window),
        ]
        if let statusFilter, !statusFilter.isEmpty {
            query.append(URLQueryItem(name: "status", value: statusFilter))
        }
        if let categoryFilter, !categoryFilter.isEmpty {
            query.append(URLQueryItem(name: "category", value: categoryFilter))
        }
        let trimmed = keyword.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            query.append(URLQueryItem(name: "q", value: trimmed))
        }
        return query
    }

    private func resetDetail() {
        timeline = []
        detailArticles = []
        detailEntities = []
        detailRelations = []
        scores = []
        pickerArticles = []
    }

    private func run(_ action: @escaping () async throws -> EventDetailDTO) async -> Bool {
        isBusy = true
        defer { isBusy = false }
        do {
            let detail = try await action()
            selectedEvent = detail
            await reload()
            await loadDetail(id: detail.id)
            return true
        } catch {
            handle(error)
            return false
        }
    }

    private func handle(_ error: Error) {
        if let api = error as? APIRequestError {
            errorMessage = api.message
            errorCode = api.code
        } else {
            errorMessage = error.localizedDescription
            errorCode = nil
        }
    }
}
