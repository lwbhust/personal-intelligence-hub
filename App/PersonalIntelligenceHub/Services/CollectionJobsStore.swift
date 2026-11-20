import Foundation

/// 采集任务列表、详情与操作状态。所有计数与状态都来自真实 API。
@MainActor
final class CollectionJobsStore: ObservableObject {
    @Published private(set) var jobs: [CollectionJobDTO] = []
    @Published private(set) var total = 0
    @Published private(set) var isLoading = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?
    @Published private(set) var errorRequestID: String?

    @Published private(set) var detail: CollectionJobDTO?
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var detailErrorMessage: String?
    @Published private(set) var detailErrorRequestID: String?

    @Published private(set) var isCreating = false
    @Published private(set) var isPerformingAction = false
    @Published private(set) var actionErrorMessage: String?
    @Published private(set) var actionErrorRequestID: String?

    @Published var statusFilter: CollectionJobStatusFilter = .all
    @Published var selectedJobID: String?

    private weak var client: APIClient?
    private let pageSize = 20

    var canLoadMore: Bool {
        hasLoaded && jobs.count < total
    }

    /// 有等待中/采集中任务时，列表需要轮询刷新真实进度。
    var hasActiveWork: Bool {
        if let detail, CollectionJobStatus.resolve(detail.status)?.isActive == true {
            return true
        }
        return jobs.contains { CollectionJobStatus.resolve($0.status)?.isActive == true }
    }

    func bind(_ client: APIClient?) {
        if client === self.client {
            return
        }
        self.client = client
        if client == nil {
            jobs = []
            total = 0
            hasLoaded = false
            detail = nil
            selectedJobID = nil
            clearListError()
            clearDetailError()
            clearActionError()
        } else {
            Task { await reload() }
        }
    }

    func reload(showSpinner: Bool = true) async {
        guard let client else { return }
        if showSpinner {
            isLoading = true
        }
        defer {
            if showSpinner {
                isLoading = false
            }
        }
        do {
            let page = try await client.fetchCollectionJobs(query: buildQuery(offset: 0))
            jobs = page.items
            total = page.total
            hasLoaded = true
            clearListError()
        } catch {
            handleListError(error)
        }
    }

    func loadMore() async {
        guard let client, !isLoading, jobs.count < total else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let page = try await client.fetchCollectionJobs(query: buildQuery(offset: jobs.count))
            jobs.append(contentsOf: page.items)
            total = page.total
            clearListError()
        } catch {
            handleListError(error)
        }
    }

    func loadDetail(force: Bool = false, showSpinner: Bool = true) async {
        guard let client, let id = selectedJobID else {
            detail = nil
            detailErrorMessage = nil
            detailErrorRequestID = nil
            isLoadingDetail = false
            return
        }
        if !force, detail?.id == id {
            return
        }
        if showSpinner {
            isLoadingDetail = true
        }
        detailErrorMessage = nil
        detailErrorRequestID = nil
        defer {
            if selectedJobID == id {
                isLoadingDetail = false
            }
        }
        do {
            let loaded = try await client.fetchCollectionJob(id: id)
            guard !Task.isCancelled, selectedJobID == id else { return }
            detail = loaded
        } catch {
            guard selectedJobID == id else { return }
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

    // MARK: - Commands

    /// “采集全部”：请求体固定 `source_ids=null`，由后端决定全部启用来源。
    func createJobForAllEnabledSources() async -> Bool {
        guard let client, !isCreating else { return false }
        isCreating = true
        defer { isCreating = false }
        do {
            let body = try CollectionJobRequest.allEnabledSources()
            let job = try await client.createCollectionJob(body: body)
            clearActionError()
            await reload(showSpinner: false)
            selectedJobID = job.id
            detail = nil
            await loadDetail(force: true)
            return true
        } catch {
            handleActionError(error)
            return false
        }
    }

    func cancel(_ job: CollectionJobDTO) async {
        guard let client, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let updated = try await client.cancelCollectionJob(id: job.id)
            clearActionError()
            replace(updated)
            if selectedJobID == updated.id {
                detail = updated
                await loadDetail(force: true, showSpinner: false)
            }
        } catch {
            handleActionError(error)
        }
    }

    func retry(_ job: CollectionJobDTO) async {
        guard let client, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let newJob = try await client.retryCollectionJob(id: job.id)
            clearActionError()
            await reload(showSpinner: false)
            selectedJobID = newJob.id
            detail = nil
            await loadDetail(force: true)
        } catch {
            handleActionError(error)
        }
    }

    func refreshQuietly() async {
        await reload(showSpinner: false)
        if selectedJobID != nil {
            await loadDetail(force: true, showSpinner: false)
        }
    }

    /// 仅在存在等待中/采集中任务时每 3 秒刷新一次真实进度。
    /// 视图消失时 `.task` 取消，循环随之退出。
    func pollWhileActive() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(3))
            if Task.isCancelled {
                return
            }
            guard client != nil, hasActiveWork else { continue }
            await refreshQuietly()
        }
    }

    func clearListError() {
        errorMessage = nil
        errorCode = nil
        errorRequestID = nil
    }

    func clearDetailError() {
        detailErrorMessage = nil
        detailErrorRequestID = nil
    }

    func clearActionError() {
        actionErrorMessage = nil
        actionErrorRequestID = nil
    }

    // MARK: - Helpers

    private func buildQuery(offset: Int) -> [URLQueryItem] {
        var items = [
            URLQueryItem(name: "limit", value: String(pageSize)),
            URLQueryItem(name: "offset", value: String(offset)),
        ]
        if let status = statusFilter.queryValue {
            items.append(URLQueryItem(name: "status", value: status))
        }
        return items
    }

    private func replace(_ job: CollectionJobDTO) {
        if let index = jobs.firstIndex(where: { $0.id == job.id }) {
            jobs[index] = job
        }
    }

    private func handleListError(_ error: Error) {
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

    private func handleActionError(_ error: Error) {
        if let api = error as? APIRequestError {
            actionErrorMessage = api.message
            actionErrorRequestID = api.requestID
        } else {
            actionErrorMessage = error.localizedDescription
            actionErrorRequestID = nil
        }
    }
}
